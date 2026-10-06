"""Pins for the managed-install engine, the manifest, the pins reader, and
the managed run-mode (turn 2).

Hermetic: subprocess and network boundaries are fakes; no test downloads a
byte or launches uv. RED statements are argued against the attached tree,
not executed.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_apply.application.services.install.bootstrap_pins import (
    load_pins,
    uv_checksum,
    uv_download_url,
    uv_target,
)
from auto_apply.application.services.install.engine import (
    InstallEngine,
    InstallEnvironment,
    InstallError,
    extra_support,
)
from auto_apply.application.services.install.manifest import (
    load_manifest,
    write_manifest,
)
from auto_apply.application.services.uninstall.engine import (
    UninstallEngine,
    UninstallEnvironment,
)
from auto_apply.application.services.uninstall.model import (
    GROUP_INSTALL,
    UninstallDecision,
)


# ── fakes ───────────────────────────────────────────────────────────────────


class FakeRunner:
    """Programmable subprocess boundary."""

    def __init__(self, version_stdout: str = "uv 0.9.16 (fake)") -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.version_stdout = version_stdout

    def __call__(self, cmd: list[str], **kwargs):
        self.calls.append((list(cmd), dict(kwargs)))
        if cmd and cmd[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout=self.version_stdout, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class FakeDownloader:
    """Serves canned bytes; records URLs; never touches a network."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def __call__(self, url: str, dest: Path) -> None:
        self.urls.append(url)
        dest.write_bytes(self.payload)


def _record_launch(launched: list, staging: Path):
    """A launch_detached double that records its payload (mypy-safe, D10)."""

    def _launch(paths, roots):
        launched.append((list(paths), tuple(roots)))
        return staging

    return _launch


def _uv_archive_bytes(name: str = "uv") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"#!/bin/sh\necho uv 0.9.16\n"
        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _pins_for(payload: bytes) -> dict[str, str]:
    return {
        "UV_VERSION": "0.9.16",
        "PYTHON_VERSION": "3.12.11",
        "AA_RELEASE_REPO": "Liebmann5/AA",
        "AA_ARCHIVE_ASSET": "AA-src.tar.gz",
        "SIZE_UV_MB": "20",
        "SIZE_PYTHON_MB": "45",
        "UV_SHA256_X86_64_UNKNOWN_LINUX_GNU": hashlib.sha256(payload).hexdigest(),
        # Darwin fixtures verify against the same fake payload (D8).
        "UV_SHA256_X86_64_APPLE_DARWIN": hashlib.sha256(payload).hexdigest(),
    }


def _make_env(tmp_path: Path, payload: bytes, **overrides) -> InstallEnvironment:
    source = tmp_path / "root" / "app"
    (source / "packages").mkdir(parents=True, exist_ok=True)
    (source / "pyproject.toml").write_text("[project]\nname='auto_apply'\n", encoding="utf-8")
    (source / "uv.lock").write_text("lock", encoding="utf-8")
    kwargs = {
        "root": tmp_path / "root",
        "pins": _pins_for(payload),
        "system": "linux",
        "machine": "x86_64",
        "home": tmp_path / "home",
        "assume_yes": True,
        "downloader": FakeDownloader(payload),
        "runner": FakeRunner(),
    }
    kwargs.update(overrides)
    return InstallEnvironment(**kwargs)


# ── the required pins ───────────────────────────────────────────────────────


def test_uv_is_downloaded_verified_and_installed(tmp_path: Path) -> None:
    """TEETH: end-to-end happy path — uv verified, python+sync via uv,
    launcher and manifest written, ledger roots recorded as managed. RED
    before this change: no installer existed."""
    payload = _uv_archive_bytes()
    env = _make_env(tmp_path, payload)
    report = InstallEngine(env).execute(InstallEngine(env).build_plan())
    assert (env.root / "uv" / "uv").exists()
    assert any("uv 0.9.16" in line for line in report.downloaded)
    cmds = [c for c, _ in env.runner.calls]
    assert any(c[-3:] == ["python", "install", "3.12.11"] for c in cmds)
    assert any("sync" in c and "--frozen" in c for c in cmds)
    manifest = load_manifest(env.root)
    assert manifest is not None and manifest.project_origin == "aa"
    assert (env.root / "data" / "footprint_ledger.jsonl").exists()
    assert report.launcher is not None and report.launcher.exists()


def test_verification_failure_stops_the_install(tmp_path: Path) -> None:
    """TEETH: a checksum mismatch deletes the download and stops BEFORE any
    other side effect — no binary, no launcher, no manifest."""
    payload = _uv_archive_bytes()
    env = _make_env(tmp_path, payload)
    env.pins["UV_SHA256_X86_64_UNKNOWN_LINUX_GNU"] = "0" * 64
    with pytest.raises(InstallError, match="checksum mismatch"):
        InstallEngine(env).execute(InstallEngine(env).build_plan())
    assert not (env.root / "uv" / "uv").exists()
    assert not (env.root / "bin" / "auto-apply").exists()
    assert not (env.root / "install.json").exists()
    assert not list((env.root / "tmp").iterdir())


def test_idempotent_reinstall_repairs_without_redownloading(tmp_path: Path) -> None:
    """TEETH: a second execute() reuses what exists — the downloader runs
    exactly once across two installs."""
    payload = _uv_archive_bytes()
    env = _make_env(tmp_path, payload)
    engine = InstallEngine(env)
    engine.execute(engine.build_plan())
    report2 = engine.execute(engine.build_plan())
    assert len(env.downloader.urls) == 1
    assert any("uv" in line for line in report2.existing)


def test_launcher_sets_every_containment_variable(tmp_path: Path) -> None:
    """TEETH: the launcher is the containment contract — every variable the
    design names is set, on both the sh and the bat launcher."""
    payload = _uv_archive_bytes()
    env = _make_env(tmp_path, payload)
    InstallEngine(env).execute(InstallEngine(env).build_plan())
    sh = (env.root / "bin" / "auto-apply").read_text(encoding="utf-8")
    bat = (env.root / "bin" / "auto-apply.bat").read_bytes().decode("utf-8")
    for var in (
        "AA_DATA_DIR",
        "AA_MANAGED_ROOT",
        "UV_PYTHON_INSTALL_DIR",
        "UV_CACHE_DIR",
        "SE_CACHE_PATH",
        "SE_AVOID_STATS",
        "PLAYWRIGHT_BROWSERS_PATH",
        "HF_HOME",
    ):
        assert f"export {var}=" in sh, var
        assert f'set "{var}=' in bat, var
    assert "--frozen" in sh  # uv.lock exists in the fixture


def test_offline_install_from_a_prepopulated_root(tmp_path: Path) -> None:
    """TEETH: no network at all — uv present, python present, source present;
    sync runs with --offline and the downloader is never called."""
    payload = _uv_archive_bytes()
    env = _make_env(tmp_path, payload, offline=True)
    uv_bin = env.root / "uv" / "uv"
    uv_bin.parent.mkdir(parents=True)
    uv_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    (env.root / "python" / "3.12.11").mkdir(parents=True)
    env.downloader = FakeDownloader(b"")
    engine = InstallEngine(env)
    plan = engine.build_plan()
    assert not plan.needs_download
    report = engine.execute(plan)
    assert env.downloader.urls == []
    sync_cmds = [c for c, _ in env.runner.calls if "sync" in c]
    assert sync_cmds and all("--offline" in c for c in sync_cmds)
    assert any("--frozen" in c for c in sync_cmds)
    assert report.existing


def test_preexisting_components_are_recorded_and_survive_uninstall(
    tmp_path: Path, monkeypatch
) -> None:
    """TEETH (origin recording): a --source checkout and the interpreter that
    ran the installer are recorded pre-existing; a simulated managed
    uninstall leaves both standing. RED before this change: nothing recorded
    origins, so an uninstaller could not have known the difference."""
    payload = _uv_archive_bytes()
    checkout = tmp_path / "my-checkout"
    (checkout / "packages").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text("[project]\nname='auto_apply'\n", encoding="utf-8")
    fake_python = tmp_path / "system" / "bin" / "python3"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("not AA's", encoding="utf-8")
    env = _make_env(
        tmp_path,
        payload,
        source=checkout,
        project_origin="preexisting",
        runner_python=fake_python,
    )
    InstallEngine(env).execute(InstallEngine(env).build_plan())
    manifest = load_manifest(env.root)
    assert manifest is not None
    assert manifest.project_origin == "preexisting"
    assert manifest.runner_python_origin == "preexisting"

    launched: list[tuple] = []
    monkeypatch.setattr(
        "auto_apply.application.services.uninstall.engine.launch_detached",
        _record_launch(launched, tmp_path / "staging"),
    )
    uninstall_env = _uninstall_env(env.root, tmp_path)
    report = UninstallEngine(uninstall_env).execute(
        UninstallEngine(uninstall_env).build_plan(), UninstallDecision(confirm=True)
    )
    assert checkout.exists() and (checkout / "pyproject.toml").exists()
    assert fake_python.read_text() == "not AA's"
    assert launched, "the install root should have been handed to the finisher"
    assert not (env.root / "data").exists()
    assert report is not None


def test_managed_research_is_kept_out_of_the_finisher_targets(
    tmp_path: Path, monkeypatch
) -> None:
    """TEETH (the turn-1 defect): in an umbrella install the data home lives
    inside the install root — research kept in place must NOT be in the
    finisher's payload. RED against turn 1's payload, which was the root."""
    root = tmp_path / "root"
    data = root / "data"
    (data / "research").mkdir(parents=True)
    (data / "research" / "research_signals.db").write_text("rows", encoding="utf-8")
    (data / "profiles").mkdir()
    (root / "uv").mkdir(parents=True)
    (root / "bin").mkdir()
    launched: list[tuple] = []
    monkeypatch.setattr(
        "auto_apply.application.services.uninstall.engine.launch_detached",
        _record_launch(launched, tmp_path / "staging"),
    )
    uninstall_env = _uninstall_env(root, tmp_path)
    engine = UninstallEngine(uninstall_env)
    plan = engine.build_plan()
    assert any(i.group == GROUP_INSTALL for i in plan.items)
    report = engine.execute(plan, UninstallDecision(confirm=True))
    assert report.research_action == "keep-in-place"
    assert (data / "research" / "research_signals.db").exists()
    assert launched
    targets = launched[0][0]
    assert data not in targets
    assert any(t == root / "uv" for t in targets)


def test_extras_table_matches_the_measured_lock_facts() -> None:
    """GUARD (advisory table): semantic blocked on Intel Macs and pre-14
    Apple Silicon; captcha blocked on macOS; stealth fine everywhere."""
    intel_mac = extra_support("darwin", "x86_64", (14, 0))
    assert intel_mac["semantic"][0] is False
    assert "PyTorch" in intel_mac["semantic"][1]
    old_arm = extra_support("darwin", "arm64", (13, 5))
    assert old_arm["semantic"][0] is False
    new_arm = extra_support("darwin", "arm64", (14, 0))
    assert new_arm["semantic"][0] is True
    assert new_arm["captcha"][0] is False
    linux = extra_support("linux", "x86_64", None)
    assert linux["captcha"][0] is True
    assert linux["stealth"][0] is True


def test_blocked_extras_are_never_synced_and_are_explained(tmp_path: Path) -> None:
    """TEETH: the installer never offers an extra that cannot install on
    this machine, and says why in plain words."""
    payload = _uv_archive_bytes()
    env = _make_env(
        tmp_path, payload, system="darwin", machine="x86_64", extras=("semantic", "nlp")
    )
    engine = InstallEngine(env)
    plan = engine.build_plan()
    assert plan.extras_supported == ["nlp"]
    assert plan.extras_skipped and plan.extras_skipped[0][0] == "semantic"
    engine.execute(plan)
    sync_args = [arg for c, _ in env.runner.calls for arg in c if arg == "--extra"]
    assert sync_args == ["--extra"]  # only nlp's


def test_shortcut_is_recorded_in_the_ledger_and_removed_by_uninstall(
    tmp_path: Path, monkeypatch
) -> None:
    """TEETH: an opt-in shortcut is an outside item with origin=aa — the
    uninstaller may delete exactly it, and does."""
    payload = _uv_archive_bytes()
    env = _make_env(tmp_path, payload, shortcut=True)
    report = InstallEngine(env).execute(InstallEngine(env).build_plan())
    assert report.shortcut is not None and report.shortcut.exists()
    from auto_apply.application.services.footprint_ledger import FootprintLedger

    snap = FootprintLedger(env.root / "data" / "footprint_ledger.jsonl").load()
    assert any(i.path == report.shortcut and i.origin == "aa" for i in snap.outside)
    monkeypatch.setattr(
        "auto_apply.application.services.uninstall.engine.launch_detached",
        lambda paths, roots: tmp_path / "staging",
    )
    uninstall_env = _uninstall_env(env.root, tmp_path)
    UninstallEngine(uninstall_env).execute(
        UninstallEngine(uninstall_env).build_plan(), UninstallDecision(confirm=True)
    )
    assert not report.shortcut.exists()


def test_downloads_require_consent(tmp_path: Path) -> None:
    """TEETH (consent is structural): no --yes and a declined prompt both
    stop the install before the downloader is called."""
    payload = _uv_archive_bytes()
    env = _make_env(tmp_path, payload, assume_yes=False, confirm=lambda text: False)
    with pytest.raises(InstallError, match="declined"):
        InstallEngine(env).execute(InstallEngine(env).build_plan())
    assert env.downloader.urls == []
    env2 = _make_env(tmp_path / "second", payload, assume_yes=False, confirm=None)
    with pytest.raises(InstallError, match="--yes"):
        InstallEngine(env2).execute(InstallEngine(env2).build_plan())


def test_exec_probe_failure_names_noexec(tmp_path: Path) -> None:
    """TEETH: a noexec mount is a plain-words refusal, not a traceback."""
    payload = _uv_archive_bytes()
    env = _make_env(tmp_path, payload)

    def probe_failing_runner(cmd, **kwargs):
        if cmd and ".exec_probe" in str(cmd[0]):
            raise OSError(13, "Permission denied")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    env.runner = probe_failing_runner
    with pytest.raises(InstallError, match="noexec"):
        InstallEngine(env).execute(InstallEngine(env).build_plan())


def test_manifest_round_trip(tmp_path: Path) -> None:
    """GUARD: the manifest survives write/load with its origins intact."""
    write_manifest(
        tmp_path,
        uv_version="0.9.16",
        python_version="3.12.11",
        project_dir=tmp_path / "app",
        project_origin="aa",
        components={"uv": "aa"},
        runner_python=Path("/usr/bin/python3"),
        runner_python_origin="preexisting",
    )
    manifest = load_manifest(tmp_path)
    assert manifest is not None
    assert manifest.uv_version == "0.9.16"
    assert manifest.runner_python_origin == "preexisting"
    assert load_manifest(tmp_path / "nothing") is None


def test_managed_run_mode_in_config(tmp_path: Path, monkeypatch) -> None:
    """GUARD: the fifth run mode resolves through the one authority."""
    import auto_apply.domain.config as cfg

    root = tmp_path / "R"
    monkeypatch.setenv("AA_MANAGED_ROOT", str(root))
    assert cfg.get_run_mode() == "managed"
    assert cfg.get_install_root() == root
    assert cfg._determine_user_data_dir() == root / "data"


# ── helpers ─────────────────────────────────────────────────────────────────


def _uninstall_env(root: Path, tmp_path: Path) -> UninstallEnvironment:
    data = root / "data"
    return UninstallEnvironment(
        run_mode="managed",
        data_root=data,
        install_root=root,
        ledger_path=data / "footprint_ledger.jsonl",
        instances_dir=data / "instances",
        research_dir=data / "research",
        research_db=data / "research" / "research_signals.db",
        consent_db=data / "research_consent.db",
        provenance_key=data / "provenance_key.pem",
        research_salt=data / "research_salt.txt",
        page_copies_dir=data / "research" / "page_copies",
        hold_path=data / "research_retention.json",
        browser_profile_dir=data / "cache" / "chromium_profile",
        home=tmp_path / "nowhere",
    )

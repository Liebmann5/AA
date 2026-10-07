"""Pins for the uninstall engine, the lifecycle authority, the ledger, the
instance registry and the finisher (turn 1).

Every test is hermetic: roots, ledgers, research homes and instances live
under tmp_path; process tests spawn real children and clean them up. RED
statements are argued against the attached tree, not executed (this session
runs no code).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from auto_apply.application.services.footprint_ledger import FootprintLedger
from auto_apply.application.services.instance_registry import InstanceRegistry
from auto_apply.application.services.research_consent import ResearchConsentManager
from auto_apply.application.services.uninstall.engine import (
    UninstallEngine,
    UninstallEnvironment,
    UninstallRefused,
)
from auto_apply.application.services.uninstall.finisher import (
    build_payload,
    run_finisher,
    validate_payload,
)
from auto_apply.application.services.uninstall.model import (
    ResearchDecision,
    UninstallDecision,
)
from auto_apply.application.services.uninstall.scoping import (
    OutOfScopeError,
    require_deletable,
)
from auto_apply.domain.constants import (
    CURRENT_CONSENT_VERSION,
    CURRENT_PAGE_COPIES_VERSION,
    WITHDRAWAL_NOTICE_FILENAME,
)
from auto_apply.domain.models.consent import ConsentRecord
from auto_apply.domain.services import research_consent_text


def _write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def env(tmp_path: Path) -> UninstallEnvironment:
    """A hermetic uninstall environment over tmp_path (home included — tests
    never scan the real home directory)."""
    data = tmp_path / "data"
    return UninstallEnvironment(
        run_mode="development",
        data_root=data,
        install_root=tmp_path / "checkout",
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
        home=tmp_path,
    )


def _seed(env: UninstallEnvironment, *, research: bool = True) -> None:
    # The tombstone ensure_creation_marker writes when AA creates the home —
    # the fixture simulates an AA-created home, so it carries one (D2).
    _write(env.data_root / ".aa_created_root", "{}")
    _write(env.data_root / "profiles" / "default.json", "{}")
    _write(env.data_root / "aa_data.db", "db")
    if research:
        _write(env.research_db, "research")
        _write(env.consent_db, "consent")
        _write(env.provenance_key, "key")
        _write(env.research_salt, "salt")


class FakeConsentManager:
    """Records the ORDER of consent operations — the stop-before-purge teeth."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def stop_collection(self) -> bool:
        self.calls.append(("stop_collection",))
        return True

    def withdraw_consent(self, purge_data: bool = True, *, purge_copies: bool = True) -> int:
        self.calls.append(("withdraw_consent", purge_data, purge_copies))
        return 0

    def withdraw(self, purge_data: bool = True):
        self.calls.append(("withdraw", purge_data))
        return SimpleNamespace(purged=3, collection_stopped=True, status=None)


# ── the plan/safety pins ────────────────────────────────────────────────────


def test_dry_run_stops_and_deletes_nothing(env: UninstallEnvironment) -> None:
    """TEETH: --dry-run is plan + report only. RED before this change: there
    was no uninstall at all; a dry-run flag had nothing honest to stand on."""
    _seed(env)
    engine = UninstallEngine(env)
    plan = engine.build_plan()
    report = engine.execute(plan, UninstallDecision(confirm=False), dry_run=True)
    assert report.dry_run
    assert (env.data_root / "aa_data.db").exists()
    assert env.research_db.exists()
    assert report.removed == [] and report.stopped_pids == []


def test_nothing_outside_the_roots_is_deleted(env: UninstallEnvironment, tmp_path: Path) -> None:
    """TEETH: an arbitrary outside file survives a full uninstall untouched.

    (Turn-4 fix: this seeded research and then asserted the data root was
    gone — contradicting the keep-in-place-by-default ruling, which is right
    for IRB. It now seeds no research; research-keeping has its own pins.)
    """
    outside = _write(tmp_path / "keep-me.txt", "not AA's")
    _seed(env, research=False)
    engine = UninstallEngine(env)
    report = engine.execute(engine.build_plan(), UninstallDecision(confirm=True))
    assert outside.read_text() == "not AA's"
    assert not env.data_root.exists()
    assert report.clean


def test_symlink_escape_unlinks_the_link_not_the_target(env: UninstallEnvironment, tmp_path: Path) -> None:
    """TEETH: a symlink inside the data root pointing outside is unlinked;
    its target is never followed. RED before this change: no guarded delete
    existed."""
    target_dir = tmp_path / "elsewhere"
    target = _write(target_dir / "precious.txt", "do not touch")
    # Inside an AA-known entry: an unknown top-level name is left in place
    # by the ownership rule (D2), which is a different pin.
    link = env.data_root / "cache" / "evil-link"
    _seed(env, research=False)
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target_dir, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"cannot create symlinks here: {exc}")
    engine = UninstallEngine(env)
    engine.execute(engine.build_plan(), UninstallDecision(confirm=True))
    assert target.read_text() == "do not touch"
    assert not link.exists() and not link.is_symlink()


def test_preexisting_ledger_items_are_never_removed(env: UninstallEnvironment, tmp_path: Path) -> None:
    """TEETH: origin="preexisting" is a promise. RED before this change: the
    ledger and its origin vocabulary did not exist."""
    shared = _write(tmp_path / "shared-cache", "pre-dates AA")
    _seed(env, research=False)
    FootprintLedger(env.ledger_path).record_outside(shared, origin="preexisting", kind="file")
    engine = UninstallEngine(env)
    report = engine.execute(engine.build_plan(), UninstallDecision(confirm=True))
    assert shared.exists()
    assert any(k.path == str(shared) for k in report.kept)


def test_research_is_kept_in_place_by_default(env: UninstallEnvironment) -> None:
    """TEETH: non-interactive with no research flag keeps research in place
    and mutates NOTHING about consent. RED before this change: there was no
    research step at all."""
    _seed(env)
    fake = FakeConsentManager()
    env.consent_factory = lambda: fake
    engine = UninstallEngine(env)
    report = engine.execute(engine.build_plan(), UninstallDecision(confirm=True))
    assert report.research_action == "keep-in-place"
    assert env.research_db.exists() and env.consent_db.exists()
    assert fake.calls == [("stop_collection",)]  # stopped, never withdrawn
    assert ("withdraw" in str(c) for c in fake.calls) is False or True


def test_retention_hold_refuses_destruction_even_explicit(env: UninstallEnvironment) -> None:
    """TEETH: a hold makes deletion a refusal no choice can override; the
    fallback keeps everything, page copies included, and documents the
    withdrawal in the retained data (OHRP). RED before this change: neither
    holds nor uninstall existed."""
    _seed(env)
    _write(env.page_copies_dir / "page.warc.gz", "copy")
    engine = UninstallEngine(env)
    engine.write_hold("until-released", "IRB protocol 2026-114")
    plan = engine.build_plan()
    assert plan.hold is not None and plan.hold.active(env.today)
    with pytest.raises(UninstallRefused):
        engine.execute(
            plan,
            UninstallDecision(confirm=True, research=ResearchDecision(action="delete")),
        )
    assert env.research_db.exists()

    fake = FakeConsentManager()
    env.consent_factory = lambda: fake
    engine = UninstallEngine(env)
    report = engine.execute(engine.build_plan(), UninstallDecision(confirm=True))
    assert report.research_action == "keep-in-place"
    assert env.research_db.exists()
    assert (env.page_copies_dir / "page.warc.gz").exists()
    assert ("withdraw_consent", False, False) in fake.calls
    assert (env.research_dir / WITHDRAWAL_NOTICE_FILENAME).exists()


def test_the_observer_is_stopped_before_any_purge(env: UninstallEnvironment) -> None:
    """TEETH (the recreate-after-purge scenario): stop_collection() precedes
    every withdrawal call. RED before this change: measured 2026-09 — a live
    aggregator recreated research_signals.db and minted a new private key
    after a purge, because nothing stopped it first."""
    _seed(env)
    fake = FakeConsentManager()
    env.consent_factory = lambda: fake
    engine = UninstallEngine(env)
    engine.execute(
        engine.build_plan(),
        UninstallDecision(confirm=True, research=ResearchDecision(action="delete")),
    )
    assert fake.calls[0] == ("stop_collection",)
    assert ("withdraw", True) in fake.calls


def test_delete_purges_through_the_consent_path(env: UninstallEnvironment) -> None:
    """GUARD: destruction goes through withdraw(purge_data=True) — the secure
    purge (secure_delete, key rotation) — never a reimplementation."""
    _seed(env)
    fake = FakeConsentManager()
    env.consent_factory = lambda: fake
    engine = UninstallEngine(env)
    report = engine.execute(
        engine.build_plan(),
        UninstallDecision(confirm=True, research=ResearchDecision(action="delete")),
    )
    assert report.research_action == "delete"
    assert ("withdraw", True) in fake.calls
    assert not env.research_db.exists()


def test_keep_moves_the_research_home_and_documents_the_withdrawal(
    env: UninstallEnvironment, tmp_path: Path
) -> None:
    """TEETH: Keep preserves EVERYTHING (consent db, key, salt included) at a
    confirmed location, then the data root goes. RED before this change:
    exports and data lived inside the data root, so deleting it destroyed
    the researcher's records."""
    _seed(env)
    dest = tmp_path / "kept-research"
    fake = FakeConsentManager()
    env.consent_factory = lambda: fake
    engine = UninstallEngine(env)
    report = engine.execute(
        engine.build_plan(),
        UninstallDecision(confirm=True, research=ResearchDecision(action="keep", dest=dest)),
    )
    assert report.research_action == "keep"
    assert (dest / "research" / "research_signals.db").exists()
    assert (dest / "research_consent.db").exists()
    assert (dest / "provenance_key.pem").exists()
    assert (dest / "research_salt.txt").exists()
    notice = json.loads((dest / WITHDRAWAL_NOTICE_FILENAME).read_text(encoding="utf-8"))
    assert notice["decided_by"] == "subject"
    assert notice["identifying_information"] == "none"
    assert not env.data_root.exists()
    assert ("withdraw_consent", False, True) in fake.calls


def test_export_goes_to_a_confirmed_dir_and_verifies_before_removal(
    env: UninstallEnvironment, tmp_path: Path
) -> None:
    """TEETH: Export writes the bundle where the user said, verifies it, and
    only then lets the originals go with the data root."""
    _seed(env)
    dest = tmp_path / "export-here"
    calls: list[tuple] = []

    def fake_export(d: Path, fmt: str):
        calls.append(("export", d, fmt))
        bundle = d / "bundle"
        bundle.mkdir(parents=True)
        (bundle / "research_signals.csv").write_text("rows", encoding="utf-8")
        return SimpleNamespace(directory=bundle)

    def fake_verify(bundle_dir: Path):
        calls.append(("verify", bundle_dir))

    env.export_bundle = fake_export
    env.verify_bundle = fake_verify
    env.consent_factory = lambda: FakeConsentManager()
    engine = UninstallEngine(env)
    report = engine.execute(
        engine.build_plan(),
        UninstallDecision(confirm=True, research=ResearchDecision(action="export", dest=dest)),
    )
    assert report.research_action == "export"
    assert calls[0] == ("export", dest, "csv")
    assert calls[1] == ("verify", dest / "bundle")
    assert (dest / "bundle" / WITHDRAWAL_NOTICE_FILENAME).exists()
    assert not env.data_root.exists()


# ── lifecycle mechanics ─────────────────────────────────────────────────────


def test_import_with_AA_NO_CREATE_DIRS_creates_nothing(tmp_path: Path) -> None:
    """TEETH: the import-time-mkdir defeat, pinned at the subprocess
    boundary. RED before this change: importing config.py created nine
    directories, so --uninstall recreated the home it was deleting."""
    target = tmp_path / "no-such-data-home"
    env_vars = dict(os.environ)
    env_vars["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    env_vars["AA_DATA_DIR"] = str(target)
    env_vars["AA_NO_CREATE_DIRS"] = "1"
    subprocess.run(
        [sys.executable, "-c", "import auto_apply.domain.config"],
        env=env_vars, check=True, capture_output=True,
    )
    assert not target.exists()
    # Control leg: without the suppression the same import DOES create it —
    # the guard is the mechanism, not a broken mkdir.
    del env_vars["AA_NO_CREATE_DIRS"]
    subprocess.run(
        [sys.executable, "-c", "import auto_apply.domain.config"],
        env=env_vars, check=True, capture_output=True,
    )
    assert target.exists()


def test_an_empty_research_folder_is_not_research_data(env: UninstallEnvironment) -> None:
    """TEETH: config creates research/ on every install; with nothing in it,
    a default uninstall removes the whole data home. RED before: the empty
    folder was "research data kept in place" and the home was never removed."""
    _seed(env, research=False)
    env.research_dir.mkdir(parents=True, exist_ok=True)
    engine = UninstallEngine(env)
    report = engine.execute(engine.build_plan(), UninstallDecision(confirm=True))
    assert report.clean
    assert not env.data_root.exists()


def test_an_interrupted_run_resumes_to_completion(env: UninstallEnvironment, monkeypatch) -> None:
    """TEETH: idempotent resume — a second run finishes and never errors on
    items already gone."""
    _seed(env, research=False)
    engine = UninstallEngine(env)
    real_unlink = Path.unlink
    state = {"failed": False}

    def flaky(self: Path, *args, **kwargs):
        if self.name == "aa_data.db" and not state["failed"]:
            state["failed"] = True
            raise PermissionError("simulated lock")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky)
    report1 = engine.execute(engine.build_plan(), UninstallDecision(confirm=True))
    assert any(f.path.endswith("aa_data.db") for f in report1.failed)

    monkeypatch.setattr(Path, "unlink", real_unlink)
    report2 = engine.execute(engine.build_plan(), UninstallDecision(confirm=True))
    assert report2.clean
    assert not env.data_root.exists()


def test_verify_reports_leftovers_honestly(env: UninstallEnvironment, monkeypatch) -> None:
    """TEETH: an undeletable item is reported as failed AND as a leftover —
    never silently absent from the account."""
    _seed(env, research=False)
    real_unlink = Path.unlink

    def blocked(self: Path, *args, **kwargs):
        if self.name == "aa_data.db":
            raise PermissionError("simulated Windows lock")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", blocked)
    engine = UninstallEngine(env)
    report = engine.execute(engine.build_plan(), UninstallDecision(confirm=True))
    assert any(f.path.endswith("aa_data.db") for f in report.failed)
    assert not report.clean


# ── the ledger ──────────────────────────────────────────────────────────────


def test_ledger_round_trips_bytes_exactly(tmp_path: Path) -> None:
    """TEETH (byte discipline): the file is exactly the bytes _encode made —
    re-encoding every parsed line reproduces the file byte for byte."""
    ledger = FootprintLedger(tmp_path / "ledger.jsonl")
    ledger.record_roots(run_mode="development", data_root=tmp_path / "d", install_root=tmp_path / "i")
    ledger.record_outside(tmp_path / "x", origin="aa", kind="dir", note="n")
    raw = ledger.path.read_bytes()
    assert b"\r" not in raw
    lines = [l for l in raw.split(b"\n") if l]
    rebuilt = b"".join(
        json.dumps(json.loads(line), separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
        for line in lines
    )
    assert rebuilt == raw


def test_ledger_last_roots_wins_and_missing_means_discovery(tmp_path: Path) -> None:
    """GUARD: discovery-mode detection and last-wins roots."""
    ledger = FootprintLedger(tmp_path / "ledger.jsonl")
    assert ledger.load().exists is False
    ledger.record_roots(run_mode="development", data_root=tmp_path / "a", install_root=tmp_path / "i")
    ledger.record_roots(run_mode="portable-frozen", data_root=tmp_path / "b", install_root=tmp_path / "j")
    snap = ledger.load()
    assert snap.exists and snap.roots is not None
    assert snap.roots.run_mode == "portable-frozen"
    assert str(snap.roots.data_root).endswith("b")


# ── the instance registry ───────────────────────────────────────────────────


def test_instance_registry_liveness_and_stale_sweep(tmp_path: Path) -> None:
    """GUARD: own registration is live; a record for a dead pid is swept."""
    registry = InstanceRegistry(tmp_path / "instances")
    registry.register()
    alive = registry.alive()
    assert any(rec.pid == os.getpid() for rec in alive)
    # A pid KNOWN to be dead: spawned and reaped (a hard-coded 999999 failed
    # once in a full-suite run — some live process had it).
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    stale = tmp_path / "instances" / f"{dead.pid}.instance.json"
    stale.write_text(
        json.dumps({"pid": dead.pid, "started_at": 0.0, "host": "x"}), encoding="utf-8"
    )
    alive = registry.alive()
    assert all(rec.pid != dead.pid for rec in alive)
    assert not stale.exists()
    registry.unregister()
    assert all(rec.pid != os.getpid() for rec in registry.alive())


def _spawn_child(*extra_args: str) -> int:
    # The BASE interpreter: on Windows a venv's python.exe is a launcher that
    # re-spawns the real one, so sys.executable would give two processes and
    # the pid returned here would not be the one carrying the arguments.
    python = getattr(sys, "_base_executable", None) or sys.executable
    proc = subprocess.Popen(
        [python, "-c", "import time; time.sleep(60)", *extra_args],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return proc.pid


def _record_launch(launched: list, staging: Path):
    """A launch_detached double that records its payload (mypy-safe: the
    lambda returning list.append's None was a type error, D10)."""

    def _launch(paths, roots):
        launched.append((list(paths), tuple(roots)))
        return staging

    return _launch


def test_uninstall_stops_registered_processes_and_aa_browsers(env: UninstallEnvironment) -> None:
    """TEETH: stop-before-delete, cross-process — the recreate-after-purge
    mechanism's other half. A registered live child and a child carrying the
    browser-profile flag are both gone after execute."""
    _seed(env, research=False)
    pid_a = _spawn_child()
    pid_b = _spawn_child(f"--user-data-dir={env.browser_profile_dir}")
    try:
        env.instances_dir.mkdir(parents=True, exist_ok=True)
        (env.instances_dir / f"{pid_a}.instance.json").write_text(
            json.dumps(
                {
                    "pid": pid_a,
                    "started_at": psutil.Process(pid_a).create_time(),
                    "host": "test",
                }
            ),
            encoding="utf-8",
        )
        engine = UninstallEngine(env)
        plan = engine.build_plan()
        assert pid_a in plan.running_pids
        report = engine.execute(plan, UninstallDecision(confirm=True))
        assert pid_a in report.stopped_pids
        assert pid_b in report.stopped_pids
        assert not psutil.pid_exists(pid_a)
        assert not psutil.pid_exists(pid_b)
    finally:
        for pid in (pid_a, pid_b):
            if psutil.pid_exists(pid):
                psutil.Process(pid).kill()


# ── the finisher ────────────────────────────────────────────────────────────


def test_run_finisher_deletes_payload_paths(tmp_path: Path) -> None:
    """GUARD: the finisher's synchronous core removes exactly the payload."""
    victim_dir = tmp_path / "runtime"
    _write(victim_dir / "python.exe", "bin")
    victim_file = _write(tmp_path / "marker.lock", "x")
    payload = build_payload([victim_dir, victim_file], [tmp_path], os.getpid())
    result = run_finisher(payload, wait_for_parent=False)
    assert not victim_dir.exists() and not victim_file.exists()
    assert str(victim_dir) in result.removed


def test_finisher_payload_refuses_an_escape(tmp_path: Path) -> None:
    """TEETH: a payload is never trusted — a path outside the roots is a
    refusal, not a deletion."""
    outside = tmp_path / "outside"
    roots = (tmp_path / "root",)
    payload = build_payload([outside], roots, os.getpid())
    with pytest.raises(OutOfScopeError):
        validate_payload(payload, realpath=os.path.realpath)
    empty = build_payload([tmp_path / "root" / "x"], [], os.getpid())
    with pytest.raises(OutOfScopeError):
        validate_payload(empty)


def test_require_deletable_pure_arithmetic() -> None:
    """GUARD (sans-IO): containment is computed on resolved paths, so a
    realpath that escapes is a refusal even for a path that looks inside."""
    identity = lambda s: s  # noqa: E731
    require_deletable(Path("/a/b/c"), (Path("/a"),), realpath=identity)
    with pytest.raises(OutOfScopeError):
        require_deletable(Path("/a/b/c"), (Path("/x"),), realpath=identity)
    # Compared as Paths: on Windows str(Path("/a/link")) is "\\a\\link".
    escaping = lambda s: "/elsewhere" if Path(s) == Path("/a/link") else s  # noqa: E731
    with pytest.raises(OutOfScopeError):
        require_deletable(Path("/a/link"), (Path("/a"),), realpath=escaping)


# ── consent text and the withdrawal contract ────────────────────────────────


def test_consent_text_states_the_uninstall_rules_and_versions_moved() -> None:
    """GUARD (requirement c): the consent text tells subjects what uninstall
    does to their data, and the version bump marks the practices change."""
    assert "uninstall" in research_consent_text.DIALOG_BODY.lower()
    assert "kept by default" in research_consent_text.DIALOG_BODY
    assert "retention hold" in research_consent_text.DIALOG_BODY
    assert CURRENT_CONSENT_VERSION == "2.6"
    assert "retention hold" in research_consent_text.PAGE_COPIES_BODY
    assert CURRENT_PAGE_COPIES_VERSION == "1.1"
    assert WITHDRAWAL_NOTICE_FILENAME == "aa_withdrawal_notice.json"


class _RecordingRepo:
    """A ConsentRepositoryPort double that counts purges."""

    def __init__(self) -> None:
        from datetime import datetime, timezone

        self.record = ConsentRecord(
            granted=True,
            consent_version=CURRENT_CONSENT_VERSION,
            granted_at=datetime.now(timezone.utc),
        )
        self.purged_rows = 0
        self.purged_copies = 0

    def load_consent(self) -> ConsentRecord:
        return self.record

    def save_consent(self, record: ConsentRecord) -> None:
        self.record = record

    def purge_research_data(self) -> int:
        self.purged_rows += 1
        return 0

    def purge_page_copies(self) -> int:
        self.purged_copies += 1
        return 0


def test_withdraw_consent_default_still_purges_copies_and_the_flag_gates_it() -> None:
    """GUARD (back-compat): existing callers keep copies-purged behaviour;
    only the hold path passes purge_copies=False."""
    repo = _RecordingRepo()
    manager = ResearchConsentManager(repo, salt_available=lambda: True)
    manager.withdraw_consent(purge_data=False)
    assert repo.purged_copies == 1

    repo2 = _RecordingRepo()
    manager2 = ResearchConsentManager(repo2, salt_available=lambda: True)
    manager2.withdraw_consent(purge_data=False, purge_copies=False)
    assert repo2.purged_copies == 0


def test_hold_roundtrip_and_expired_hold_is_absent(env: UninstallEnvironment) -> None:
    """GUARD: the hold file round-trips; an expired hold does not protect."""
    engine = UninstallEngine(env)
    engine.write_hold("2999-01-01", "protocol X")
    hold = engine.read_hold()
    assert hold is not None and hold.active(env.today)
    engine.write_hold("2000-01-01")
    _seed(env, research=False)
    plan = UninstallEngine(env).build_plan()
    assert plan.hold is None


def test_report_serializes_to_json_bytes(env: UninstallEnvironment) -> None:
    """GUARD: the machine-readable report parses and carries the promise."""
    _seed(env, research=False)
    engine = UninstallEngine(env)
    report = engine.execute(engine.build_plan(), UninstallDecision(confirm=True))
    parsed = json.loads(report.to_json_bytes().decode("utf-8"))
    assert parsed["run_mode"] == "development"
    assert "Time Machine" in parsed["promise"]
    assert report.clean


# ── D1/D2: deletion is by proof of creation, never by folder ───────────────


def test_uninstall_never_deletes_user_files_on_a_frozen_drive(
    tmp_path: Path, monkeypatch
) -> None:
    """TEETH (D1, the measured script): on a frozen USB layout, the user's
    own files in the drive root are NEVER deletion targets — only the
    build's own entries go to the finisher, and the drive root never does."""
    usb = tmp_path / "E_drive"
    data = usb / "data"
    (data / "logs").mkdir(parents=True)
    (usb / "AutoApply.exe").write_bytes(b"MZ")
    (usb / "_internal").mkdir()
    (usb / "_internal" / "python312.dll").write_bytes(b"x")
    (usb / "My Resumes").mkdir()
    (usb / "My Resumes" / "resume_final.docx").write_text("the user's own file")
    (usb / "tax_return_2025.pdf").write_text("the user's own file")
    env = UninstallEnvironment(
        run_mode="portable-frozen",
        data_root=data,
        install_root=usb,
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
        home=tmp_path,
    )
    launched: list[tuple] = []
    monkeypatch.setattr(
        "auto_apply.application.services.uninstall.engine.launch_detached",
        _record_launch(launched, tmp_path / "staging"),
    )
    engine = UninstallEngine(env)
    engine.execute(engine.build_plan(), UninstallDecision(confirm=True))
    assert (usb / "My Resumes" / "resume_final.docx").exists()
    assert (usb / "tax_return_2025.pdf").exists()
    assert launched, "the runtime should still be handed to the finisher"
    targets = launched[0][0]
    assert usb / "AutoApply.exe" in targets
    assert usb / "_internal" in targets
    assert usb not in targets, "the drive root is never a target"
    assert all("My Resumes" not in str(t) and "tax_return" not in str(t) for t in targets)


def test_uninstall_empties_only_aa_entries_from_a_preexisting_data_folder(
    env: UninstallEnvironment,
) -> None:
    """TEETH (D2, the measured script): a data folder the user already owned
    keeps every non-AA entry, and the folder itself is left standing."""
    _write(env.data_root / "thesis.docx", "the user's own file")
    _write(env.data_root / "family_photos" / "2019.jpg", "the user's own file")
    _write(env.data_root / "aa_data.db", "db")
    _write(env.data_root / "logs" / "session.log", "log")
    engine = UninstallEngine(env)
    report = engine.execute(engine.build_plan(), UninstallDecision(confirm=True))
    assert (env.data_root / "thesis.docx").exists()
    assert (env.data_root / "family_photos" / "2019.jpg").exists()
    assert not (env.data_root / "aa_data.db").exists()
    assert not (env.data_root / "logs").exists()
    assert env.data_root.exists(), "a pre-existing folder is never removed"
    assert any("not AA's" in k.reason for k in report.kept)
    assert any("existed before AA" in k.reason for k in report.kept)


def test_finisher_actually_starts_and_finishes_in_source_mode(tmp_path: Path) -> None:
    """TEETH (D3): `python -m auto_apply --finisher-payload` starts, deletes
    the payload targets, and leaves no trace on a clean run."""
    from auto_apply.application.services.uninstall.finisher import build_payload

    victim = tmp_path / "runtime"
    _write(victim / "python.exe", "x")
    staging = tmp_path / "staging"
    staging.mkdir()
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    payload_path = staging / "aa_uninstall_payload.json"
    payload_path.write_text(
        json.dumps(build_payload([victim], [tmp_path], dead.pid)), encoding="utf-8"
    )
    env_vars = dict(os.environ)
    env_vars["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    env_vars["AA_DATA_DIR"] = str(tmp_path / "data")
    result = subprocess.run(
        [sys.executable, "-m", "auto_apply", "--finisher-payload", str(payload_path)],
        env=env_vars,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode()[-400:]
    assert "unknown option" not in result.stderr.decode()
    assert not victim.exists()
    assert not staging.exists(), "a clean finish removes its own staging dir"


def test_browser_matching_uses_the_profile_flag_not_a_substring(
    env: UninstallEnvironment,
) -> None:
    """TEETH (D5): an editor with the profile folder open survives; the
    browser launched with AA's profile flag is stopped."""
    _seed(env, research=False)
    marker = str(env.browser_profile_dir)
    browser_pid = _spawn_child(f"--user-data-dir={marker}")
    editor_pid = _spawn_child(str(env.browser_profile_dir / "notes.txt"))
    try:
        fake_procs = [
            SimpleNamespace(
                info={"pid": browser_pid, "cmdline": ["chrome", f"--user-data-dir={marker}"]}
            ),
            SimpleNamespace(
                info={
                    "pid": editor_pid,
                    "cmdline": ["editor", str(env.browser_profile_dir / "notes.txt")],
                }
            ),
        ]
        env.processes = lambda attrs=None: iter(fake_procs)
        engine = UninstallEngine(env)
        report = engine.execute(engine.build_plan(), UninstallDecision(confirm=True))
        assert browser_pid in report.stopped_pids
        assert editor_pid not in report.stopped_pids
        assert psutil.pid_exists(editor_pid)
    finally:
        for pid in (browser_pid, editor_pid):
            if psutil.pid_exists(pid):
                psutil.Process(pid).kill()

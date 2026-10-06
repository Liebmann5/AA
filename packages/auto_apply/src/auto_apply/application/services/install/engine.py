"""The --install engine: create or repair a managed AA install.

One root, everything inside it (the turn-1 ruling): uv, the uv-managed
Python, the source tree, the environment uv maintains, the launchers, and
AA's data home. A component that predates AA — the interpreter running this
installer, a checkout passed via --source — is recorded as pre-existing and
is never touched by uninstall.

Three structural properties, not conventions:

  CONSENT      execute() refuses to download anything unless the caller
               opted in (assume_yes) or answered a confirmation prompt.
  VERIFICATION a downloaded uv archive whose sha256 does not match the pin
               is deleted and the install stops before any other side
               effect. A placeholder pin is a refusal, not a verification.
  IDEMPOTENCY  every step checks before acting, so re-running --install is
               repair, not duplication.

Network and subprocess boundaries are injected (downloader, runner) so the
pins run hermetically — no test downloads a byte.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from auto_apply.application.services.footprint_ledger import FootprintLedger
from auto_apply.application.services.install.bootstrap_pins import (
    sha256_file,
    uv_checksum,
    uv_download_url,
    uv_target,
)
from auto_apply.application.services.install.manifest import (
    MANAGED_RECEIPT_ENTRIES,
    RECEIPT_NAME,
    write_manifest,
)
from auto_apply.domain.config import ensure_creation_marker
from auto_apply.application.services.uninstall.scoping import is_within


class InstallError(RuntimeError):
    """The install cannot proceed — said in plain words, before side effects
    whenever possible."""


#: Optional extras and whether they can install on a given machine.
#: Measured 2026-10 against uv.lock (the prompt's census): torch's only
#: macOS wheels are arm64/macOS 14+; vosk has no macOS wheel;
#: undetected-chromedriver and srt are pure-Python sdists (no compiler
#: needed). Windows/Linux coverage of the rest is assumed from the lock but
#: UNVERIFIED — a failed extra sync is reported and never fatal, so this
#: table is advisory, not load-bearing.
EXTRA_ORDER: tuple[str, ...] = (
    "nlp",
    "semantic",
    "browser",
    "ai",
    "captcha",
    "stealth",
    "research",
)


def extra_support(
    system: str, machine: str, macos_version: tuple[int, int] | None
) -> dict[str, tuple[bool, str]]:
    """(installable, plain-words reason) per extra for this machine.

    system: "darwin" | "linux" | "win32". macos_version: (14, 0) etc, or
    None on non-Macs.
    """
    table = {name: (True, "") for name in EXTRA_ORDER}
    if system == "darwin":
        arm = machine.lower() in ("arm64", "aarch64")
        recent = macos_version is not None and macos_version >= (14, 0)
        if not (arm and recent):
            table["semantic"] = (
                False,
                "PyTorch publishes macOS wheels only for Apple Silicon on "
                "macOS 14 or newer; this Mac has no wheel to install",
            )
        table["captcha"] = (False, "vosk publishes no macOS wheel")
    return table


@dataclass(frozen=True)
class DownloadItem:
    what: str
    url: str
    size_text: str
    dest: Path


@dataclass
class InstallPlan:
    root: Path
    downloads: list[DownloadItem]
    creations: list[str]
    extras_supported: list[str]
    extras_skipped: list[tuple[str, str]]
    needs_download: bool


@dataclass
class InstallReport:
    downloaded: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    extras_installed: list[str] = field(default_factory=list)
    extras_skipped: list[tuple[str, str]] = field(default_factory=list)
    shortcut: Path | None = None
    launcher: Path | None = None
    notes: list[str] = field(default_factory=list)


def _default_runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("timeout", 900)
    return subprocess.run(cmd, **kwargs)


def _url_download(url: str, dest: Path) -> None:
    """The production downloader. Small and honest: HTTPS, 60s timeout."""
    import urllib.request  # noqa: PLC0415

    with urllib.request.urlopen(url, timeout=60) as response, open(dest, "wb") as fh:
        shutil.copyfileobj(response, fh)


@dataclass
class InstallEnvironment:
    """Everything the engine needs, injectable so the pins stay hermetic."""

    root: Path
    pins: dict[str, str]
    source: Path | None = None  # default <root>/app
    project_origin: str = "aa"  # "preexisting" when --source names a checkout
    offline: bool = False
    shortcut: bool = False
    extras: tuple[str, ...] = ()
    assume_yes: bool = False
    confirm: Callable[[str], bool] | None = None
    downloader: Callable[[str, Path], None] = _url_download
    runner: Callable[..., Any] = _default_runner
    system: str = sys.platform
    machine: str = platform.machine()
    home: Path = field(default_factory=Path.home)
    data_root: Path | None = None  # default <root>/data
    runner_python: Path = field(default_factory=lambda: Path(sys.executable))
    progress: Callable[[str], None] | None = None

    @classmethod
    def default_root(cls) -> Path:
        override = os.environ.get("AA_INSTALL_ROOT")
        return Path(override) if override else Path.home() / ".auto_apply"

    @property
    def resolved_data_root(self) -> Path:
        return self.data_root or (self.root / "data")

    @property
    def resolved_source(self) -> Path:
        return self.source or (self.root / "app")


class InstallEngine:
    """Plan, execute, record. See the module docstring for the invariants."""

    def __init__(self, env: InstallEnvironment) -> None:
        self.env = env

    # ── plan ─────────────────────────────────────────────────────────────

    def build_plan(self) -> InstallPlan:
        """What execute() will do — read-only (this is the consent text's data)."""
        env = self.env
        pins = env.pins
        downloads: list[DownloadItem] = []
        if not self._uv_ok():
            target = uv_target(env.system, env.machine)
            downloads.append(
                DownloadItem(
                    what=f"uv {pins['UV_VERSION']} (the installer/runtime)",
                    url=uv_download_url(pins, target),
                    size_text=f"~{pins.get('SIZE_UV_MB', '?')} MB",
                    dest=env.root / "uv",
                )
            )
        python_dir = env.root / "python"
        python_present = python_dir.exists() and any(python_dir.iterdir())
        if not python_present:
            downloads.append(
                DownloadItem(
                    what=f"Python {pins['PYTHON_VERSION']} (via uv, into the root)",
                    url="resolved by uv (python-build-standalone, checksum-verified by uv)",
                    size_text=f"~{pins.get('SIZE_PYTHON_MB', '?')} MB",
                    dest=python_dir,
                )
            )
        creations = [
            str(env.root),
            str(env.resolved_data_root),
            f"{env.root / 'bin'} launcher",
            f"{env.root / 'install.json'} manifest",
        ]
        supported, skipped = self._resolve_extras()
        return InstallPlan(
            root=env.root,
            downloads=downloads,
            creations=creations,
            extras_supported=supported,
            extras_skipped=skipped,
            needs_download=bool(downloads) and not env.offline,
        )

    def _resolve_extras(self) -> tuple[list[str], list[tuple[str, str]]]:
        requested = list(self.env.extras)
        if "all" in requested:
            requested = [n for n in EXTRA_ORDER]
        table = extra_support(self.env.system, self.env.machine, self._macos_version())
        supported: list[str] = []
        skipped: list[tuple[str, str]] = []
        for name in requested:
            if name not in table:
                skipped.append((name, f"unknown extra {name!r} — choices: {', '.join(EXTRA_ORDER)}"))
                continue
            ok, reason = table[name]
            (supported if ok else skipped).append((name) if ok else (name, reason))  # type: ignore[arg-type]
        return supported, skipped

    @staticmethod
    def _macos_version() -> tuple[int, int] | None:
        if sys.platform != "darwin" and platform.system() != "Darwin":
            return None
        raw = platform.mac_ver()[0]
        try:
            major, minor, *_ = (int(p) for p in raw.split("."))
            return (major, minor)
        except ValueError:
            return None

    # ── execute ──────────────────────────────────────────────────────────

    def execute(self, plan: InstallPlan) -> InstallReport:
        env = self.env
        if plan.needs_download and not env.assume_yes:
            if env.confirm is None:
                raise InstallError(
                    "downloads are required but there is no way to ask — "
                    "pass --yes for scripted use (the plan is printed first)"
                )
            if not env.confirm(self._consent_text(plan)):
                raise InstallError("declined — nothing was downloaded or changed")
        report = InstallReport(extras_skipped=list(plan.extras_skipped))
        self._preflight()
        self._note("checking uv")
        self._ensure_uv(plan, report)
        self._note("installing Python")
        self._ensure_python(report)
        source = self._source()
        self._note("resolving dependencies")
        self._sync(source, [], report)  # core environment — must succeed
        self._sync_extras(source, plan, report)
        self._note("writing the launcher")
        launcher = self._write_launchers(source, report)
        self._note("recording the install")
        self._record(source, report)
        if env.shortcut:
            self._create_shortcut(report)
        return report

    def _note(self, message: str) -> None:
        """Progress for the surfaces — injected, never printed here."""
        if self.env.progress is not None:
            self.env.progress(message)

    @staticmethod
    def _consent_text(plan: InstallPlan) -> str:
        lines = ["AutoApply will download:"]
        for item in plan.downloads:
            lines.append(f"  {item.what} ({item.size_text}) -> {item.dest}")
        lines.append("Nothing is installed system-wide; no administrator rights are used.")
        return "\n".join(lines)

    # ── preflight ────────────────────────────────────────────────────────

    def _preflight(self) -> None:
        root = self.env.root
        root.mkdir(parents=True, exist_ok=True)
        (root / "tmp").mkdir(exist_ok=True)
        probe = root / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        if self._windows:
            return
        exec_probe = root / ".exec_probe.sh"
        exec_probe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        try:
            exec_probe.chmod(0o755)
            result = self.env.runner([str(exec_probe)])
            failed = getattr(result, "returncode", 1) != 0
        except OSError:
            failed = True
        finally:
            exec_probe.unlink(missing_ok=True)
        if failed:
            raise InstallError(
                f"cannot execute programs under {root} — the filesystem is "
                "likely mounted noexec (common on USB drives and some "
                "managed machines). Choose another root: --root /path/on/a/normal/fs"
            )

    # ── uv ───────────────────────────────────────────────────────────────

    @property
    def _windows(self) -> bool:
        """The ONE platform answer for this install: env.system, the same
        value that picks the uv download. Asking os.name as well split the
        engine in two: a linux-targeted install on a Windows host downloaded
        uv/uv, then looked for uv/uv.exe and never found it."""
        return self.env.system.startswith("win")

    def _uv_binary(self) -> Path:
        name = "uv.exe" if self._windows else "uv"
        return self.env.root / "uv" / name

    def _uv_ok(self) -> bool:
        binary = self._uv_binary()
        if not binary.exists():
            return False
        try:
            result = self.env.runner([str(binary), "--version"])
        except (OSError, subprocess.SubprocessError):
            return False
        return (
            getattr(result, "returncode", 1) == 0
            and self.env.pins["UV_VERSION"] in str(getattr(result, "stdout", ""))
        )

    def _ensure_uv(self, plan: InstallPlan, report: InstallReport) -> None:
        env = self.env
        if self._uv_ok():
            report.existing.append(f"uv {env.pins['UV_VERSION']}")
            return
        if env.offline:
            raise InstallError(
                f"offline mode but no usable uv at {self._uv_binary()} — "
                "pre-populate the root (run the same installer online once) "
                "or re-run without --offline"
            )
        target = uv_target(env.system, env.machine)
        checksum = uv_checksum(env.pins, target)
        if checksum is None:
            raise InstallError(
                "uv's SHA-256 is not pinned in install_pins.txt "
                f"({target}) — the release process fills it from the "
                "published uv release. Refusing to run an unverifiable binary."
            )
        url = uv_download_url(env.pins, target)
        archive = env.root / "tmp" / url.rsplit("/", 1)[1]
        env.downloader(url, archive)
        actual = sha256_file(archive)
        if actual != checksum:
            archive.unlink(missing_ok=True)
            raise InstallError(
                f"checksum mismatch for {url}:\n  expected {checksum}\n"
                f"  got      {actual}\nThe download was deleted; nothing was "
                "installed. This is the safety property working — do not bypass it."
            )
        self._extract_uv(archive)
        archive.unlink(missing_ok=True)
        report.downloaded.append(f"uv {env.pins['UV_VERSION']}")

    def _extract_uv(self, archive: Path) -> None:
        dest = self.env.root / "uv"
        dest.mkdir(parents=True, exist_ok=True)
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(dest)
        else:
            with tarfile.open(archive) as tf:
                tf.extractall(dest)
        binary = self._uv_binary()
        if not binary.exists():
            for child in sorted(dest.iterdir()):
                nested = child / binary.name
                if child.is_dir() and nested.exists():
                    for item in child.iterdir():
                        shutil.move(str(item), dest / item.name)
                    child.rmdir()
                    break
        if not self._windows and binary.exists():
            binary.chmod(0o755)

    # ── python and the environment ───────────────────────────────────────

    def _uv_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["UV_PYTHON_INSTALL_DIR"] = str(self.env.root / "python")
        env["UV_CACHE_DIR"] = str(self.env.root / "uv-cache")
        env["UV_NO_MODIFY_PATH"] = "1"
        return env

    def _run_uv(self, args: list[str], *, cwd: Path | None = None) -> Any:
        result = self.env.runner(
            [str(self._uv_binary()), *args],
            cwd=str(cwd) if cwd else None,
            env=self._uv_env(),
        )
        return result

    @staticmethod
    def _tail(result: Any) -> str:
        out = f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}".strip()
        return out[-400:] if out else "(no output)"

    def _ensure_python(self, report: InstallReport) -> None:
        version = self.env.pins["PYTHON_VERSION"]
        args = ["python", "install", version]
        if self.env.offline:
            args.append("--offline")
        result = self._run_uv(args)
        if getattr(result, "returncode", 1) != 0:
            raise InstallError(f"could not install Python {version} via uv:\n{self._tail(result)}")
        report.created.append(f"Python {version} (uv-managed, inside the root)")

    def _source(self) -> Path:
        source = self.env.resolved_source
        if not (source / "pyproject.toml").exists():
            raise InstallError(
                f"no AA source tree at {source} — re-run the bootstrap "
                "(install.sh / install.ps1), or pass --source <path to a checkout>"
            )
        return source

    def _sync(
        self, source: Path, extra_args: list[str], report: InstallReport
    ) -> None:
        lock = (source / "uv.lock").exists()
        args = ["sync"]
        if lock:
            args.append("--frozen")  # verify against uv.lock's hashes
        if self.env.offline:
            args.append("--offline")
        args.extend(extra_args)
        result = self._run_uv(args, cwd=source)
        if getattr(result, "returncode", 1) != 0:
            raise InstallError(f"uv {' '.join(args)} failed:\n{self._tail(result)}")
        report.created.append(f"environment (uv {' '.join(a for a in args if a.startswith('--')) or 'sync'})")

    def _sync_extras(
        self, source: Path, plan: InstallPlan, report: InstallReport
    ) -> None:
        """Each extra is its own attempt; a failure is reported, never fatal —
        the core environment already succeeded."""
        for name in plan.extras_supported:
            lock = (source / "uv.lock").exists()
            args = ["sync"] + (["--frozen"] if lock else [])
            if self.env.offline:
                args.append("--offline")
            args.extend(["--extra", name])
            result = self._run_uv(args, cwd=source)
            if getattr(result, "returncode", 1) != 0:
                report.extras_skipped.append(
                    (name, f"uv sync --extra {name} failed: {self._tail(result)[:120]}")
                )
            else:
                report.extras_installed.append(name)

    # ── launcher, manifest, ledger, shortcut ─────────────────────────────

    def _write_launchers(self, source: Path, report: InstallReport) -> Path:
        bin_dir = self.env.root / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        frozen = "--frozen " if (source / "uv.lock").exists() else ""
        sh = bin_dir / "auto-apply"
        sh.write_text(
            "#!/bin/sh\n"
            "# Generated by auto_apply --install. Sets AA's containment\n"
            "# environment, then runs AA. Everything lives inside the root.\n"
            'AA_ROOT="$(cd "$(dirname "$0")/.." && pwd)"\n'
            'export AA_DATA_DIR="$AA_ROOT/data"\n'
            'export AA_MANAGED_ROOT="$AA_ROOT"\n'
            'export UV_PYTHON_INSTALL_DIR="$AA_ROOT/python"\n'
            'export UV_CACHE_DIR="$AA_ROOT/uv-cache"\n'
            "export UV_NO_MODIFY_PATH=1\n"
            'export UV_UNMANAGED_INSTALL="$AA_ROOT/uv"\n'
            'export SE_CACHE_PATH="$AA_ROOT/data/cache/selenium"\n'
            "export SE_AVOID_STATS=1\n"
            'export PLAYWRIGHT_BROWSERS_PATH="$AA_ROOT/data/cache/pw-browsers"\n'
            'export HF_HOME="$AA_ROOT/data/cache/huggingface"\n'
            f'exec "$AA_ROOT/uv/uv" run {frozen}--project "$AA_ROOT/app" '
            '--package auto_apply python -m auto_apply "$@"\n',
            encoding="utf-8",
            newline="\n",
        )
        if not self._windows:
            sh.chmod(0o755)
        bat = bin_dir / "auto-apply.bat"
        bat.write_bytes(
            b"@echo off\r\nrem Generated by auto_apply --install.\r\n"
            b"set \"AA_ROOT=%~dp0..\"\r\n"
            b"set \"AA_DATA_DIR=%AA_ROOT%\\data\"\r\n"
            b"set \"AA_MANAGED_ROOT=%AA_ROOT%\"\r\n"
            b"set \"UV_PYTHON_INSTALL_DIR=%AA_ROOT%\\python\"\r\n"
            b"set \"UV_CACHE_DIR=%AA_ROOT%\\uv-cache\"\r\n"
            b"set \"UV_NO_MODIFY_PATH=1\"\r\n"
            b"set \"UV_UNMANAGED_INSTALL=%AA_ROOT%\\uv\"\r\n"
            b"set \"SE_CACHE_PATH=%AA_ROOT%\\data\\cache\\selenium\"\r\n"
            b"set \"SE_AVOID_STATS=1\"\r\n"
            b"set \"PLAYWRIGHT_BROWSERS_PATH=%AA_ROOT%\\data\\cache\\pw-browsers\"\r\n"
            b"set \"HF_HOME=%AA_ROOT%\\data\\cache\\huggingface\"\r\n"
            + f"\"%AA_ROOT%\\uv\\uv.exe\" run {frozen}--project \"%AA_ROOT%\\app\" --package auto_apply python -m auto_apply %*\r\n".encode()
        )
        report.launcher = sh
        report.created.append("launcher (bin/auto-apply + .bat)")
        return sh

    def _record(self, source: Path, report: InstallReport) -> None:
        env = self.env
        root = env.root
        # The two proofs the uninstaller's "delete only what AA created"
        # rule reads (D1/D2): the data home's creation tombstone (AA creates
        # it here on a fresh install) and the root's receipt of AA-created
        # top-level entries.
        ensure_creation_marker(env.resolved_data_root)
        receipt_tmp = root / (RECEIPT_NAME + ".tmp")
        receipt_tmp.write_bytes(
            (
                json.dumps(
                    {"version": 1, "entries": list(MANAGED_RECEIPT_ENTRIES)},
                    indent=2,
                )
                + "\n"
            ).encode("utf-8")
        )
        os.replace(receipt_tmp, root / RECEIPT_NAME)
        runner_origin = (
            "aa" if is_within(env.runner_python, root) else "preexisting"
        )
        write_manifest(
            root,
            uv_version=env.pins["UV_VERSION"],
            python_version=env.pins["PYTHON_VERSION"],
            project_dir=source,
            project_origin=env.project_origin,
            components={
                "uv": "aa",
                "python": "aa",
                "environment": "aa",
                "launcher": "aa",
                "source": env.project_origin,
            },
            runner_python=env.runner_python,
            runner_python_origin=runner_origin,
        )
        FootprintLedger(env.resolved_data_root / "footprint_ledger.jsonl").record_roots(
            run_mode="managed",
            data_root=env.resolved_data_root,
            install_root=env.root,
        )
        report.created.append("install manifest + footprint ledger roots (managed)")

    def _create_shortcut(self, report: InstallReport) -> None:
        env = self.env
        launcher = report.launcher or (env.root / "bin" / "auto-apply")
        if env.system == "darwin":
            target = env.home / "Desktop" / "AutoApply.command"
            content = f"#!/bin/sh\nexec \"{launcher}\"\n"
        elif env.system == "win32":
            target = (
                env.home
                / "AppData" / "Roaming" / "Microsoft" / "Windows"
                / "Start Menu" / "Programs" / "AutoApply.bat"
            )
            content = f"@echo off\r\ncall \"{env.root / 'bin' / 'auto-apply.bat'}\" %*\r\n"
        else:
            target = env.home / ".local" / "share" / "applications" / "auto_apply.desktop"
            content = (
                "[Desktop Entry]\nType=Application\nName=AutoApply\n"
                f"Exec={launcher}\nTerminal=true\nCategories=Office;\n"
            )
        if target.exists() and "AutoApply" not in target.read_text(
            encoding="utf-8", errors="replace"
        ):
            report.notes.append(
                f"shortcut NOT written: {target} exists and is not AutoApply's"
            )
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
        if env.system == "darwin":
            target.chmod(0o755)  # locally created: no quarantine attribute
        FootprintLedger(env.resolved_data_root / "footprint_ledger.jsonl").record_outside(
            target, origin="aa", kind="file", note=f"{env.system} shortcut"
        )
        report.shortcut = target

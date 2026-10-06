"""The lifecycle parity pin: install and uninstall are first-class on BOTH
surfaces, with one wording source and one engine (ruling C).

Mirrors the research-consent parity pin:

  1. ONE CONTRACT. Both surfaces import lifecycle_wording and the engines;
     neither carries a literal line of the wording.
  2. ONE VOCABULARY. The research choices, their labels, their order, the
     defaults and the confirmation tokens are identical — the CLI is probed
     with scripted input; the GUI is checked through its pure helper and
     its source.
  3. STREAM DISCIPLINE. The CLI conversation goes to stderr; only the final
     report reaches stdout; input() is never handed a prompt; the CLI
     lifecycle path never imports tkinter.

RED statements are argued against the attached tree, not executed.
"""
from __future__ import annotations

import ast
import hashlib
import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_apply.adapters.primary.cli import lifecycle_screen as cli_screen
from auto_apply.adapters.primary.gui import lifecycle_window as gui_window
from auto_apply.application.services import lifecycle_wording as _w
from auto_apply.application.services.install.engine import (
    InstallEngine,
    InstallEnvironment,
)
from auto_apply.application.services.uninstall.engine import (
    UninstallEngine,
    UninstallEnvironment,
)
from auto_apply.application.services.uninstall.model import (
    GROUP_AA,
    GROUP_INSTALL,
    GROUP_PREEXISTING,
    PlanItem,
    UninstallPlan,
    UninstallReport,
)

_SURFACES = {
    "cli": Path(cli_screen.__file__),
    "gui": Path(gui_window.__file__),
}


# ── fixtures and fakes ──────────────────────────────────────────────────────


def _write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _env(tmp_path: Path) -> UninstallEnvironment:
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


def _seed(env: UninstallEnvironment, *, research: bool = False) -> None:
    # An AA-created home carries the creation marker (D2), as in
    # test_uninstall_engine's fixture.
    _write(env.data_root / ".aa_created_root", "{}")
    _write(env.data_root / "profiles" / "default.json", "{}")
    _write(env.data_root / "aa_data.db", "db")
    if research:
        _write(env.research_db, "research")
        _write(env.consent_db, "consent")
        _write(env.provenance_key, "key")
        _write(env.research_salt, "salt")


class _Script:
    """Scripted stdin (the research parity precedent's pattern)."""

    def __init__(self, answers: list[str]) -> None:
        self._answers = iter(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        try:
            return next(self._answers)
        except StopIteration:
            raise EOFError from None


def _interactive(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> _Script:
    script = _Script(answers)
    monkeypatch.setattr("builtins.input", script)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    return script


# ── claim 1: one contract ────────────────────────────────────────────────────


def test_both_surfaces_reach_the_engines_through_the_composition_root() -> None:
    """GUARD (parity + the reach pin, D11): both surfaces take the engines
    and the wording from infrastructure.composition_root — the
    research-consent precedent — never from application.services directly."""
    for name, path in _SURFACES.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        modules |= {
            f"{node.module}.{alias.name}"
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
            for alias in node.names
        }
        assert "auto_apply.infrastructure.composition_root" in modules, name
        offenders = sorted(
            m for m in modules if m.startswith("auto_apply.application.services")
        )
        assert offenders == [], f"{name} reaches past the composition root: {offenders}"
        source = path.read_text(encoding="utf-8")
        assert "_w." in source, f"{name} does not use the single wording source"


def test_no_surface_repeats_a_line_of_the_wording() -> None:
    """TEETH (parity): no string literal in either surface repeats the
    canonical wording — a paraphrase that drifts is what the module exists
    to prevent."""
    canonical = list(_w.GROUP_TITLES.values()) + list(_w.CHOICE_LABELS.values())
    canonical += [line for line in _w.PROMISE_TEXT.split(". ") if len(line) >= 40]
    canonical = [c for c in canonical if len(c) >= 20]
    assert canonical, "the pin would pass vacuously"
    for name, path in _SURFACES.items():
        source = path.read_text(encoding="utf-8")
        for line in canonical:
            assert line not in source, f"{name} repeats a wording line: {line[:60]}…"


# ── claim 2: one vocabulary ──────────────────────────────────────────────────


def test_research_choices_are_single_source_on_both_surfaces() -> None:
    """GUARD (parity): the GUI helper returns exactly the wording labels for
    exactly the wording's choices, in the wording's order, default first."""
    for hold in (False, True):
        choices = _w.research_choices(hold)
        assert choices[0] is _w.ResearchChoice.KEEP_IN_PLACE
        assert gui_window.research_choice_labels(choices) == [
            _w.CHOICE_LABELS[c] for c in choices
        ]
        menu = _w.format_choice_menu_lines(choices)
        assert len(menu) == len(choices)
        assert all(_w.CHOICE_LABELS[c] in line for c, line in zip(choices, menu))


def test_hold_reduces_choices_identically_on_both_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """TEETH (parity, probed): under a hold the CLI menu offers KEEP and
    EXPORT only — the same set research_choices() hands the GUI."""
    env = _env(tmp_path)
    _seed(env, research=True)
    UninstallEngine(env).write_hold("until-released", "IRB protocol")
    _interactive(monkeypatch, ["UNINSTALL", "k"])
    code = cli_screen.run_uninstall(env)
    captured = capsys.readouterr()
    assert code == 0
    assert _w.CHOICE_LABELS[_w.ResearchChoice.KEEP_IN_PLACE] in captured.err
    assert _w.CHOICE_LABELS[_w.ResearchChoice.EXPORT] in captured.err
    assert _w.CHOICE_LABELS[_w.ResearchChoice.MOVE] not in captured.err
    assert _w.CHOICE_LABELS[_w.ResearchChoice.DELETE] not in captured.err
    assert env.research_db.exists()


def test_confirmation_tokens_are_single_source() -> None:
    """GUARD (parity): both surfaces reference the wording's tokens, never
    literals of their own."""
    for name, path in _SURFACES.items():
        source = path.read_text(encoding="utf-8")
        assert "_w.CONFIRM_UNINSTALL" in source, name
        assert "_w.CONFIRM_DELETE" in source, name


def test_cli_wrong_token_cancels_and_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEETH: the typed gate works — a wrong token exits 2 with the data
    root untouched. RED before this feature: no gate existed."""
    env = _env(tmp_path)
    _seed(env)
    _interactive(monkeypatch, ["not-the-token"])
    code = cli_screen.run_uninstall(env)
    assert code == 2
    assert (env.data_root / "aa_data.db").exists()


def test_cli_research_menu_offers_all_choices_and_typed_delete_is_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """TEETH (parity, probed): all four choices render; choosing Delete and
    failing the second token keeps everything. Default (blank) keeps."""
    env = _env(tmp_path)
    _seed(env, research=True)
    _interactive(monkeypatch, ["UNINSTALL", "d", "NOPE"])
    code = cli_screen.run_uninstall(env)
    captured = capsys.readouterr()
    assert code == 0
    for choice in _w.research_choices(False):
        assert _w.CHOICE_LABELS[choice] in captured.err
    assert env.research_db.exists(), "a failed DELETE token must keep the data"


def test_plan_group_order_is_fixed_and_single_source(tmp_path: Path) -> None:
    """GUARD: the groups render in GROUP_ORDER regardless of item order."""
    plan = UninstallPlan(
        run_mode="development",
        data_root=tmp_path / "data",
        install_root=None,
        items=[
            PlanItem(tmp_path / "z-pre", GROUP_PREEXISTING, 1),
            PlanItem(tmp_path / "a-aa", GROUP_AA, 1),
            PlanItem(tmp_path / "m-rt", GROUP_INSTALL, 1),
        ],
        research_items=[],
        running_pids=[],
        hold=None,
        discovery_mode=False,
    )
    lines = _w.format_plan_lines(plan)
    positions = [next(i for i, l in enumerate(lines) if _w.GROUP_TITLES[g] in l) for g in _w.GROUP_ORDER]
    assert positions == sorted(positions)


def test_report_contains_the_scoped_promise_verbatim(tmp_path: Path) -> None:
    """TEETH: the scoped promise reaches the user word-for-word in both
    surfaces (both render format_report_lines)."""
    report = UninstallReport(run_mode="development", dry_run=False)
    lines = _w.format_report_lines(report)
    assert _w.PROMISE_TEXT in lines
    assert lines[0] == "Uninstall report"


# ── claim 3: stream discipline and the no-tk rule ────────────────────────────


def test_cli_conversation_goes_to_stderr_and_the_report_to_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """TEETH (the measured defect): the question appears on stderr, never
    stdout; the final report appears on stdout. RED against turn 1's
    handler, which asked on stdout."""
    env = _env(tmp_path)
    _seed(env)
    _interactive(monkeypatch, ["UNINSTALL"])
    code = cli_screen.run_uninstall(env)
    captured = capsys.readouterr()
    assert code == 0
    assert f"Type {_w.CONFIRM_UNINSTALL} to proceed:" in captured.err
    assert _w.CONFIRM_UNINSTALL not in captured.out.replace("Uninstall report", "")
    assert "Uninstall report" in captured.out
    assert not env.data_root.exists()


def test_cli_dry_run_writes_no_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """TEETH: --dry-run is a conversation, not an artifact — zero stdout
    bytes, so redirection can never hide it."""
    env = _env(tmp_path)
    _seed(env)
    code = cli_screen.run_uninstall(env, dry_run=True)
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    assert "plan" in captured.err


def test_no_input_call_writes_its_prompt_to_stdout() -> None:
    """GUARD: input(prompt) writes the prompt to stdout — so this file must
    never call input with an argument."""
    tree = ast.parse(Path(cli_screen.__file__).read_text(encoding="utf-8"))
    offenders = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in ("input", "input_fn")
        and node.args
    ]
    assert offenders == []


def test_no_tkinter_on_the_cli_lifecycle_path() -> None:
    """TEETH: a no-tk machine can install and uninstall. Two legs: the
    screen's source never mentions tkinter, and importing it plus main.py
    in a fresh interpreter leaves tkinter unimported."""
    assert "tkinter" not in Path(cli_screen.__file__).read_text(encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    code = (
        "import auto_apply.adapters.primary.cli.lifecycle_screen; "
        "import auto_apply.main; "
        "import sys; "
        "raise SystemExit(1 if 'tkinter' in sys.modules else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True
    )
    assert result.returncode == 0, result.stderr.decode()[-400:]


def test_gui_window_source_is_keyboard_navigable() -> None:
    """GUARD (source-level): the window takes focus, focuses the typed
    entries, binds Escape, and gates the destructive button on typed text.
    What this CANNOT check headless: real Tab traversal and screen-reader
    output — those are manual testing, said plainly in the module docstring."""
    source = Path(gui_window.__file__).read_text(encoding="utf-8")
    assert "takefocus=True" in source
    assert "focus_set()" in source
    assert '"<Escape>"' in source
    assert "_w.CONFIRM_UNINSTALL" in source


def test_install_flow_routes_through_the_same_engine_and_wording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """TEETH: the CLI install surface drives InstallEngine with the
    wording's plan/report renderers — plan on stderr, report on stdout."""
    payload = _uv_archive()
    pins = {
        "UV_VERSION": "0.9.16",
        "PYTHON_VERSION": "3.12.11",
        "AA_RELEASE_REPO": "Liebmann5/AA",
        "AA_ARCHIVE_ASSET": "AA-src.tar.gz",
        "UV_SHA256_X86_64_UNKNOWN_LINUX_GNU": hashlib.sha256(payload).hexdigest(),
    }
    source = tmp_path / "root" / "app"
    _write(source / "pyproject.toml", "[project]\nname='auto_apply'\n")
    _write(source / "uv.lock", "lock")
    env = InstallEnvironment(
        root=tmp_path / "root",
        pins=pins,
        system="linux",
        machine="x86_64",
        home=tmp_path / "home",
        downloader=_Downloader(payload),
        runner=_Runner(),
    )
    _interactive(monkeypatch, ["y"])
    code = cli_screen.run_install(lambda: env)
    captured = capsys.readouterr()
    assert code == 0
    assert "download:" in captured.err
    assert "Install complete" in captured.out
    assert "download:" not in captured.out


def _uv_archive() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"#!/bin/sh\necho uv\n"
        info = tarfile.TarInfo("uv")
        info.size = len(data)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class _Downloader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __call__(self, url: str, dest: Path) -> None:
        dest.write_bytes(self.payload)


class _Runner:
    def __call__(self, cmd, **kwargs):
        if cmd and cmd[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout="uv 0.9.16 (fake)", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

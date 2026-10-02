"""The parity pin: both consent surfaces are first-class (ruling C).

Three claims, mechanically checked:

  1. ONE CONTRACT. Both surfaces import the shared wording module and the
     ResearchConsentPort, and neither carries a literal line of the consent
     text — the canonical copy lives in domain/services/
     research_consent_text.py and reaches users only through the port.

  2. ONE VOCABULARY. The actions available for every ResearchConsentState
     (and every INACTIVE reason) are identical on both surfaces: the GUI
     computes them with research_window.actions_for; the CLI implements the
     same rules as guards in its flows, probed here with scripted input.
     Both cover page copies, withdraw with and without delete, and the
     page-copies keep choice.

  3. IT CATCHES A THIRD SURFACE. The expectation table below iterates the
     ResearchConsentState ENUM, not a hardcoded list, and the CLI probe and
     the GUI function must both answer for every member. A future surface
     (a mobile client) would register its own probe here; if it skips a
     state, the parametrized case for that state fails — totality is
     structural, not remembered.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from auto_apply.adapters.primary.cli import research_consent_screen as cli_screen
from auto_apply.adapters.primary.gui import research_window as gui_window
from auto_apply.adapters.secondary.research.sqlite_consent_repository import (
    SqliteConsentRepository,
)
from auto_apply.application.services.research_consent import ResearchConsentManager
from auto_apply.domain.constants import CURRENT_CONSENT_VERSION
from auto_apply.domain.models.consent import ConsentRecord
from auto_apply.domain.ports.research_consent_port import (
    ResearchConsentReason,
    ResearchConsentState,
    ResearchConsentStatus,
)
from auto_apply.domain.services import research_consent_text, research_consent_wording
from datetime import datetime, timezone

_SURFACES = {
    "cli": Path(cli_screen.__file__),
    "gui": Path(gui_window.__file__),
}


# ── claim 1: one contract ────────────────────────────────────────────────────


def test_both_surfaces_import_the_single_copy() -> None:
    """GUARD (parity): both surfaces read their words from the shared
    wording module and drive the ResearchConsentPort — no surface carries
    its own consent logic or its own wording."""
    for name, path in _SURFACES.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        # `from package import module` names the module through its alias.
        modules |= {
            f"{node.module}.{alias.name}"
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
            for alias in node.names
        }
        names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "auto_apply.domain.ports.research_consent_port"
            for alias in node.names
        }
        assert (
            "auto_apply.domain.services.research_consent_wording" in modules
        ), f"{name} does not import the shared wording module"
        assert "ResearchConsentPort" in names, (
            f"{name} does not type against ResearchConsentPort"
        )


def test_no_surface_repeats_a_line_of_the_consent_text() -> None:
    """TEETH (parity): no string literal in either surface repeats a line
    of the consent text — a paraphrase that drifts from the canonical copy
    is exactly what the canonical module and its doc pin exist to prevent."""
    canonical_lines = [
        line.strip()
        for text in (
            research_consent_text.DIALOG_BODY,
            research_consent_text.PAGE_COPIES_BODY,
        )
        for line in text.splitlines()
        if len(line.strip()) >= 40
    ]
    assert canonical_lines, "the pin would pass vacuously"
    for name, path in _SURFACES.items():
        source = path.read_text(encoding="utf-8")
        for line in canonical_lines:
            assert line not in source, (
                f"{name} repeats a consent-text line verbatim: {line[:60]}…"
            )


# ── claim 2: one vocabulary ──────────────────────────────────────────────────

Action = gui_window.ResearchAction

_EXPECTED_ACTIONS: dict[ResearchConsentState, frozenset] = {
    ResearchConsentState.OFF: frozenset({Action.AGREE, Action.EXPORT}),
    ResearchConsentState.WITHDRAWN: frozenset({Action.AGREE, Action.EXPORT}),
    ResearchConsentState.NEEDS_RECONSENT: frozenset(
        {Action.AGREE, Action.WITHDRAW, Action.EXPORT}
    ),
    # No AGREE: already agreed to the current text (see actions_for).
    ResearchConsentState.INACTIVE: frozenset(
        {Action.WITHDRAW, Action.PAGE_COPIES, Action.EXPORT}
    ),
    ResearchConsentState.ACTIVE: frozenset(
        {Action.WITHDRAW, Action.PAGE_COPIES, Action.EXPORT}
    ),
}


class _Script:
    """Scripted stdin (duplicated from test_cli_research_screen.py rather
    than imported across test modules — 15 lines, and the modules stay
    independent)."""

    def __init__(self, answers: list[str]) -> None:
        self._answers = iter(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        try:
            return next(self._answers)
        except StopIteration:
            raise EOFError from None


def _install_input(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> _Script:
    script = _Script(answers)
    monkeypatch.setattr("builtins.input", script)
    return script


def _service_in_state(
    state: ResearchConsentState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ResearchConsentManager:
    monkeypatch.setenv(
        "AA_RESEARCH_SALT", "parity-salt" if state is not ResearchConsentState.INACTIVE else ""
    )
    if state is ResearchConsentState.INACTIVE:
        monkeypatch.delenv("AA_RESEARCH_SALT", raising=False)  # INACTIVE/NO_SALT
    repo = SqliteConsentRepository(
        consent_db_path=tmp_path / "research_consent.db",
        research_db_path=tmp_path / "research" / "research_signals.db",
        provenance_key_path=tmp_path / "provenance_key.pem",
        page_copies_dir=tmp_path / "research" / "page_copies",
    )
    mgr = ResearchConsentManager(repo)
    if state is ResearchConsentState.OFF:
        return mgr
    if state is ResearchConsentState.NEEDS_RECONSENT:
        repo.save_consent(
            ConsentRecord(
                granted=True,
                consent_version="2.3",
                granted_at=datetime.now(timezone.utc),
            )
        )
        return mgr
    mgr.grant_consent()
    if state is ResearchConsentState.WITHDRAWN:
        mgr.withdraw_consent(purge_data=False)
    return mgr


def _status(state: ResearchConsentState, reason: ResearchConsentReason) -> ResearchConsentStatus:
    return ResearchConsentStatus(
        state=state,
        reason=reason,
        offered=True,
        collecting_now=False,
        consent_version=None,
        current_version=CURRENT_CONSENT_VERSION,
    )


def _cli_actions(service: ResearchConsentManager, monkeypatch: pytest.MonkeyPatch) -> frozenset:
    """The actions the CLI offers, probed through its own flows: an action
    counts as offered iff the flow reaches its question rather than its
    refusal sentence. Every probe declines, so no probe changes state."""
    actions = {Action.EXPORT}  # the export menu entry is unconditional
    script = _install_input(monkeypatch, ["2", "n"])
    cli_screen.run(service)
    if any(p == "\nDo you agree? [y/N]: " for p in script.prompts):
        actions.add(Action.AGREE)
    script = _install_input(monkeypatch, ["3", "n"])
    cli_screen.run(service)
    if any(p == "Withdraw? [y/N]: " for p in script.prompts):
        actions.add(Action.WITHDRAW)
    script = _install_input(monkeypatch, ["4", "n"])
    cli_screen.run(service)
    if any(
        "Page Copies on This Device? [y/N]: " in p
        or p == "Turn page copies off? [y/N]: "
        for p in script.prompts
    ):
        actions.add(Action.PAGE_COPIES)
    return frozenset(actions)


@pytest.mark.parametrize("state", list(ResearchConsentState))
def test_actions_match_on_both_surfaces_for_every_state(
    state: ResearchConsentState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEETH (parity, the core claim): for EVERY state — the table iterates
    the enum, so a state cannot be skipped — the GUI's actions_for and the
    CLI's probed behaviour offer the identical action set."""
    expected = _EXPECTED_ACTIONS[state]
    reasons = (
        (
            ResearchConsentReason.NO_SALT,
            ResearchConsentReason.ADMIN_PROHIBITED,
            ResearchConsentReason.NOT_OFFERED,
        )
        if state is ResearchConsentState.INACTIVE
        else (ResearchConsentReason.NONE,)
    )
    for reason in reasons:
        assert gui_window.actions_for(_status(state, reason)) == expected, (
            f"GUI actions drifted for {state.name}/{reason.name}"
        )
    service = _service_in_state(state, tmp_path, monkeypatch)
    assert _cli_actions(service, monkeypatch) == expected, (
        f"CLI actions drifted for {state.name}"
    )


@pytest.mark.parametrize(
    "state",
    [
        ResearchConsentState.OFF,
        ResearchConsentState.WITHDRAWN,
        ResearchConsentState.NEEDS_RECONSENT,
    ],
)
def test_neither_surface_offers_agree_when_research_is_not_offered(
    state: ResearchConsentState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEETH (parity + the documented admin lock): when an administrator
    policy or the installation turns research off, "the opt-in toggle is
    locked" (docs/research_module/index.md). Both surfaces withhold AGREE,
    and both describe the lock with the same words."""
    from dataclasses import replace

    locked = replace(_status(state, ResearchConsentReason.NONE), offered=False)
    assert Action.AGREE not in gui_window.actions_for(locked)
    service = _service_in_state(state, tmp_path, monkeypatch)
    service._admin_prohibited = True  # what composition passes for a policy
    assert Action.AGREE not in _cli_actions(service, monkeypatch)
    words = research_consent_wording.status_detail(locked)
    assert "cannot be turned on here" in words
    assert words == research_consent_wording.status_detail(service.status())


def test_both_surfaces_show_the_same_consent_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """GUARD (parity of text): the CLI prints the canonical body; the GUI's
    render helper carries it verbatim. Same words, one copy."""
    service = _service_in_state(ResearchConsentState.OFF, tmp_path, monkeypatch)
    _install_input(monkeypatch, ["1"])
    cli_screen.run(service)
    out = capsys.readouterr().out
    first_line = next(
        line for line in research_consent_text.DIALOG_BODY.splitlines() if line.strip()
    )
    assert first_line in out
    rendered = gui_window.dialog_render_text(service.consent_dialog())
    assert research_consent_text.DIALOG_BODY in rendered


def test_both_surfaces_offer_withdraw_with_and_without_delete() -> None:
    """GUARD (parity of the irreversible choice): both surfaces ask the
    delete question with deletion as the recommended default and give the
    final, cannot-be-undone confirmation no default."""
    cli_source = Path(cli_screen.__file__).read_text(encoding="utf-8")
    gui_source = Path(gui_window.__file__).read_text(encoding="utf-8")
    assert "Also delete ALL research data collected so far? [Y/n]" in cli_source
    assert "Also delete ALL research data collected so far?" in gui_source
    assert "Type DELETE to confirm" in cli_source
    assert "default=messagebox.NO" in gui_source


def test_both_surfaces_offer_page_copies_with_the_keep_choice() -> None:
    """GUARD (parity of the page-copies choice): both surfaces ask the same
    delete-or-keep question when page copies are turned off, delete being
    the default and keep the explicit alternative."""
    cli_source = Path(cli_screen.__file__).read_text(encoding="utf-8")
    gui_source = Path(gui_window.__file__).read_text(encoding="utf-8")
    assert "Delete every kept page copy? [Y/n]" in cli_source
    assert "Delete every kept page copy?" in gui_source

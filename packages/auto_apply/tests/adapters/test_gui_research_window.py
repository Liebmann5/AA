"""Pins for the GUI research-consent window — widget-free.

Every pin exercises the pure helpers or the source text of
gui/research_window.py; none constructs Tk (the
test_results_surface.py:435 / TestGUISurface precedent). tkinter is
importable on the Windows baseline, so importing the module is safe.

Labels are honest: pins in this new file fail against the pre-change tree
by import error (the window did not exist); each docstring states the
BEHAVIOUR it locks.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from auto_apply.adapters.primary.gui import research_window as gw
from auto_apply.domain.constants import (
    CURRENT_CONSENT_VERSION,
    CURRENT_PAGE_COPIES_VERSION,
)
from auto_apply.domain.ports.research_consent_port import (
    PageCopiesState,
    ResearchConsentReason,
    ResearchConsentState,
    ResearchConsentStatus,
    WithdrawalResult,
)
from auto_apply.domain.services import (
    research_consent_text,
    research_consent_wording as wording,
)

_SRC = Path(gw.__file__).read_text(encoding="utf-8")


def _status(
    state: ResearchConsentState,
    reason: ResearchConsentReason = ResearchConsentReason.NONE,
    **kw: Any,
) -> ResearchConsentStatus:
    return ResearchConsentStatus(
        state=state,
        reason=reason,
        offered=True,
        collecting_now=False,
        consent_version=None,
        current_version=CURRENT_CONSENT_VERSION,
        **kw,
    )


def test_every_state_and_reason_renders_non_empty_distinct_text() -> None:
    """TEETH: the window's status block renders non-empty text for every
    state and every INACTIVE reason, distinct per reason, and the page-
    copies line is always present."""
    for state in ResearchConsentState:
        lines = gw.status_lines(_status(state))
        assert len(lines) == 3
        assert all(lines)
        assert lines[0] == wording.status_headline(_status(state))
    details = {
        gw.status_lines(_status(ResearchConsentState.INACTIVE, reason))[1]
        for reason in (
            ResearchConsentReason.NO_SALT,
            ResearchConsentReason.ADMIN_PROHIBITED,
            ResearchConsentReason.NOT_OFFERED,
        )
    }
    assert len(details) == 3
    for pcs in PageCopiesState:
        assert gw.status_lines(
            _status(ResearchConsentState.ACTIVE, page_copies=pcs)
        )[2]


def test_actions_for_covers_every_state() -> None:
    """TEETH: the action set is defined for every state (totality), matches
    the parity table the CLI's guards implement, and does not depend on the
    INACTIVE reason."""
    expected = {
        ResearchConsentState.OFF: {gw.ResearchAction.AGREE, gw.ResearchAction.EXPORT},
        ResearchConsentState.WITHDRAWN: {
            gw.ResearchAction.AGREE,
            gw.ResearchAction.EXPORT,
        },
        ResearchConsentState.NEEDS_RECONSENT: {
            gw.ResearchAction.AGREE,
            gw.ResearchAction.WITHDRAW,
            gw.ResearchAction.EXPORT,
        },
        # No AGREE: an INACTIVE user already agreed to the current text, and
        # agreeing again cannot supply a missing key or lift a policy.
        ResearchConsentState.INACTIVE: {
            gw.ResearchAction.WITHDRAW,
            gw.ResearchAction.PAGE_COPIES,
            gw.ResearchAction.EXPORT,
        },
        ResearchConsentState.ACTIVE: {
            gw.ResearchAction.WITHDRAW,
            gw.ResearchAction.PAGE_COPIES,
            gw.ResearchAction.EXPORT,
        },
    }
    for state, want in expected.items():
        assert gw.actions_for(_status(state)) == frozenset(want), state
    for reason in ResearchConsentReason:
        assert gw.actions_for(
            _status(ResearchConsentState.INACTIVE, reason)
        ) == frozenset(expected[ResearchConsentState.INACTIVE])


def test_grant_is_reachable_only_from_the_rendered_dialog() -> None:
    """TEETH: the render-guard refuses a grant that fired without a
    rendered dialog, and every .grant( / .grant_page_copies( call site in
    the window passes through it."""
    grant = MagicMock(return_value="status")
    assert gw.grant_after_render(None, grant) is None
    grant.assert_not_called()
    assert gw.grant_after_render("2.4", grant) == "status"
    grant.assert_called_once_with()
    # Source-level: the only grant call sites are arguments to the guard.
    for line in _SRC.splitlines():
        if ".grant(" in line or ".grant_page_copies(" in line:
            assert "grant_after_render" in line, line
    # One def + exactly two call sites (research grant, page-copies grant).
    assert _SRC.count("grant_after_render(") == 3


def test_no_widget_default_action_grants() -> None:
    """TEETH: no default ring on the grant path; destructive confirmations
    default to NO; closing and Escape are wired to the decline path."""
    assert "default=tk.ACTIVE" not in _SRC
    assert 'default="active"' not in _SRC
    tree = ast.parse(_SRC)
    grant_view = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_show_grant_view"
    )
    segment = ast.get_source_segment(_SRC, grant_view) or ""
    assert "askyesno" not in segment, (
        "the grant view must be plain buttons — a messagebox has a default "
        "button, and Enter must never mean 'agree'"
    )
    assert _SRC.count("default=messagebox.NO") >= 2, (
        "withdraw and the irreversible delete confirm must default to NO"
    )
    assert "WM_DELETE_WINDOW" in _SRC
    assert 'bind("<Escape>"' in _SRC


def test_consent_text_comes_from_the_canonical_module() -> None:
    """GUARD (parity of text): the render helpers carry the canonical
    strings verbatim — titles, bodies, button labels and versions — and
    the re-consent render fills in the user's old version."""
    dialog = research_consent_text.consent_dialog()
    rendered = gw.dialog_render_text(dialog)
    assert research_consent_text.DIALOG_TITLE in rendered
    assert research_consent_text.DIALOG_BODY in rendered
    assert research_consent_text.AGREE_LABEL in rendered
    assert research_consent_text.DECLINE_LABEL in rendered
    assert CURRENT_CONSENT_VERSION in rendered

    reconsent = gw.reconsent_render_text(dialog, "2.3")
    assert research_consent_text.RECONSENT_TITLE in reconsent
    assert "2.3" in reconsent
    assert wording.view_changes_note() in reconsent

    copies = gw.page_copies_render_text(
        research_consent_text.PageCopiesDialog  # noqa: B018 — see below
        if hasattr(research_consent_text, "PageCopiesDialog")
        else None
    ) if False else None
    # The page-copies dialog comes from the manager's port method; build it
    # from the canonical strings directly.
    from auto_apply.domain.ports.research_consent_port import PageCopiesDialog

    copies_dialog = PageCopiesDialog(
        version=CURRENT_PAGE_COPIES_VERSION,
        title=research_consent_text.PAGE_COPIES_TITLE,
        body=research_consent_text.PAGE_COPIES_BODY,
        agree_label=research_consent_text.PAGE_COPIES_AGREE_LABEL,
        decline_label=research_consent_text.DECLINE_LABEL,
    )
    rendered_copies = gw.page_copies_render_text(copies_dialog)
    assert research_consent_text.PAGE_COPIES_TITLE in rendered_copies
    assert research_consent_text.PAGE_COPIES_BODY in rendered_copies
    assert research_consent_text.PAGE_COPIES_AGREE_LABEL in rendered_copies
    assert CURRENT_PAGE_COPIES_VERSION in rendered_copies


def test_keyboard_readability_is_wired() -> None:
    """GUARD (source): the long text is readable by keyboard alone — the
    text area takes focus, receives it on every view change, and scrolls
    to the top."""
    assert "takefocus=True" in _SRC
    assert "focus_set" in _SRC
    assert "ScrolledText" in _SRC
    assert "yview_moveto" in _SRC


def test_withdraw_result_text_is_honest_about_stopping() -> None:
    """TEETH: the confirmation says collection stopped only when it did,
    and names the purge count."""
    stopped = gw.withdraw_result_text(
        WithdrawalResult(
            purged=5,
            collection_stopped=True,
            status=_status(ResearchConsentState.WITHDRAWN),
        )
    )
    assert "has stopped" in stopped
    assert "5" in stopped
    not_stopped = gw.withdraw_result_text(
        WithdrawalResult(
            purged=0,
            collection_stopped=False,
            status=_status(ResearchConsentState.WITHDRAWN),
        )
    )
    assert "has stopped" not in not_stopped
    assert "could not be stopped" in not_stopped

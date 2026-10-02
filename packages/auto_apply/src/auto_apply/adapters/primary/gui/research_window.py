"""The GUI research-consent window (File → Research… / Settings → Research…).

The second of the two consent surfaces (the CLI ``--research`` screen is
the first; the parity pin in tests/adapters/test_research_consent_parity.py
asserts both read their words from
domain/services/research_consent_wording.py, their text from
domain/services/research_consent_text.py via the port, and offer the same
actions for every state).

Everything a test needs is a pure, widget-free helper below — the
format_results_lines / autonomy_state_text precedent — so no pin ever
constructs Tk. The window class only wires those helpers to widgets.

Rules this window exists to keep (shared with the CLI screen):

    * Grant only after the rendered dialog. Both grant buttons (research,
      page copies) are wired through :func:`grant_after_render` with the
      version of the dialog the window just displayed; firing without a
      render is a no-op, never a grant.
    * Decline is exactly as easy as agree, and no default action grants or
      deletes: closing the window and Escape decline; the destructive
      confirmations (delete collected data) default to NO; the grant view
      is plain buttons with no default ring.
    * Long text is readable by keyboard alone: the text area takes focus,
      receives focus on every view change, and scrolls.

Which consent instance it uses is the caller's decision (app.py): the
controller's instance during a session, build_research_consent() before or
between sessions — either is safe, because the stop channel is
process-wide (the S2 fix in application/services/research_consent.py).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from enum import Enum, auto
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from auto_apply.domain.config import RESEARCH_DB_PATH
from auto_apply.domain.ports.research_consent_port import (
    PageCopiesDialog,
    PageCopiesState,
    ResearchConsentDialog,
    ResearchConsentPort,
    ResearchConsentState,
    ResearchConsentStatus,
    WithdrawalResult,
)
from auto_apply.domain.services import research_consent_wording as _wording
from auto_apply.infrastructure.composition_root import export_research_bundle

__all__ = [
    "ResearchAction",
    "ResearchWindow",
    "actions_for",
    "dialog_render_text",
    "grant_after_render",
    "page_copies_render_text",
    "reconsent_render_text",
    "status_lines",
    "withdraw_result_text",
]


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers — every pin below tests these without constructing Tk
# ─────────────────────────────────────────────────────────────────────────────


class ResearchAction(Enum):
    """The actions a consent surface may offer. The parity pin asserts the
    GUI and the CLI offer the same set for every state."""

    AGREE = auto()
    WITHDRAW = auto()
    PAGE_COPIES = auto()
    EXPORT = auto()


#: Button captions (chrome, not consent text) for the main view.
ACTION_LABELS: dict[ResearchAction, str] = {
    ResearchAction.AGREE: "Turn research on…",
    ResearchAction.WITHDRAW: "Withdraw…",
    ResearchAction.PAGE_COPIES: "Page copies…",
    ResearchAction.EXPORT: "Export research data…",
}


def status_lines(status: ResearchConsentStatus) -> list[str]:
    """The status block the window shows — the same words the CLI prints,
    from the one wording module."""
    return [
        _wording.status_headline(status),
        _wording.status_detail(status),
        _wording.page_copies_line(status),
    ]


def dialog_render_text(dialog: ResearchConsentDialog) -> str:
    """The full consent dialog as one scrollable text — canonical strings
    only, never a local copy."""
    return (
        f"{dialog.title}  (version {dialog.version})\n\n"
        f"{dialog.body}\n\n"
        f"[{dialog.agree_label}]   [{dialog.decline_label}]"
    )


def reconsent_render_text(
    dialog: ResearchConsentDialog, old_version: str | None
) -> str:
    """The re-consent preamble: the canonical template with the user's old
    version filled in, plus the 'View Changes' substitute both surfaces
    show (FORK 4)."""
    return (
        f"{dialog.reconsent_title}\n\n"
        + dialog.reconsent_body_template.format(
            old_version=old_version or "unknown"
        )
        + "\n\n"
        + _wording.view_changes_note()
    )


def page_copies_render_text(dialog: PageCopiesDialog) -> str:
    """The full page-copies dialog as one scrollable text."""
    return (
        f"{dialog.title}  (version {dialog.version})\n\n"
        f"{dialog.body}\n\n"
        f"[{dialog.agree_label}]   [{dialog.decline_label}]"
    )


#: States in which there is no current agreement to the consent text.
_AGREE_STATES: frozenset[ResearchConsentState] = frozenset(
    {
        ResearchConsentState.OFF,
        ResearchConsentState.WITHDRAWN,
        ResearchConsentState.NEEDS_RECONSENT,
    }
)

#: Action buttons per row, so every button stays visible at the window's
#: minimum width (six captions overflowed one row at 780 px — measured).
_BUTTONS_PER_ROW = 3


def actions_for(status: ResearchConsentStatus) -> frozenset[ResearchAction]:
    """The actions available for a status — the GUI half of the parity
    table (the CLI's guards implement the same rules; the parity pin
    probes them and asserts equality for every state).

    EXPORT is always offered (the flow itself says plainly when there is
    nothing to export). AGREE is offered only when there is no current
    agreement (off, withdrawn, or the text changed) AND research is offered
    on this device: an INACTIVE user has already agreed, and offering
    "Turn research on" again would suggest a click could fix a missing key
    or a policy; an administrator's prohibition locks the opt-in
    (docs/research_module/index.md). WITHDRAW whenever a grant exists (granted, even stale or inactive).
    PAGE_COPIES whenever research consent is current — the manager's own
    grant_page_copies rule (the record, not collection), so INACTIVE /
    NO_SALT may turn them on and they start when collection does.
    """
    actions = {ResearchAction.EXPORT}
    if status.offered and status.state in _AGREE_STATES:
        actions.add(ResearchAction.AGREE)
    if status.state not in (
        ResearchConsentState.OFF,
        ResearchConsentState.WITHDRAWN,
    ):
        actions.add(ResearchAction.WITHDRAW)
    if status.state in (
        ResearchConsentState.ACTIVE,
        ResearchConsentState.INACTIVE,
    ):
        actions.add(ResearchAction.PAGE_COPIES)
    return frozenset(actions)


def grant_after_render(
    rendered_version: str | None, grant: Callable[[], Any]
) -> Any | None:
    """Invoke grant() only when the dialog was rendered first.

    Both grant buttons are wired through this with the version of the
    dialog the window just displayed. None means the action fired without
    a render — which the layout makes impossible and this guard makes
    harmless: a no-op, never a grant (pinned in
    tests/adapters/test_gui_research_window.py).
    """
    if rendered_version is None:
        return None
    return grant()


def withdraw_result_text(result: WithdrawalResult) -> str:
    """The confirmation text after a withdrawal — honest about whether
    collection actually stopped (the S2 ruling: never report a stop that
    did not happen)."""
    lines: list[str] = []
    if result.collection_stopped:
        lines.append("Research data collection has stopped.")
    else:
        lines.append(
            "A running collection could not be stopped from here. If a "
            "session is running in another window, it stops when that "
            "session ends; it collects nothing after its next start."
        )
    if result.purged:
        lines.append(f"Deleted {result.purged} research record(s).")
    lines.append(_wording.status_headline(result.status))
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# The window — wiring only; the pins never construct it
# ─────────────────────────────────────────────────────────────────────────────


class ResearchWindow(tk.Toplevel):
    """The research-consent window: status, the scrollable text area, and
    one row of action buttons rebuilt per view."""

    def __init__(self, parent: tk.Misc, consent: ResearchConsentPort) -> None:
        super().__init__(parent)
        self._service = consent
        self._rendered_version: str | None = None

        self.title("Research")
        self.geometry("780x640")
        self.minsize(640, 480)
        self.transient(parent)  # type: ignore[call-overload]

        # Closing and Escape are the decline path — never a grant.
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda _event: self._on_close())

        self._status_var = tk.StringVar()
        ttk.Label(
            self,
            textvariable=self._status_var,
            justify=tk.LEFT,
            wraplength=740,
            padding=(12, 10),
        ).pack(fill=tk.X)

        # Buttons pack side=BOTTOM BEFORE the text area so they reserve
        # their height — the Settings dialog's load-bearing layout lesson.
        self._buttons = ttk.Frame(self, padding=12)
        self._buttons.pack(fill=tk.X, side=tk.BOTTOM)

        self._text = ScrolledText(
            self,
            state="disabled",
            wrap=tk.WORD,
            takefocus=True,
            font=("Segoe UI", 10),
        )
        self._text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 6))

        self._ACTION_HANDLERS: dict[ResearchAction, Callable[[], None]] = {
            ResearchAction.AGREE: self._show_grant_view,
            ResearchAction.WITHDRAW: self._withdraw_flow,
            ResearchAction.PAGE_COPIES: self._show_page_copies_view,
            ResearchAction.EXPORT: self._export_flow,
        }

        self._show_main()

    # ── view plumbing ────────────────────────────────────────────────────────

    def _set_text(self, text: str) -> None:
        self._text.configure(state="normal")
        self._text.delete("1.0", tk.END)
        self._text.insert(tk.END, text)
        self._text.configure(state="disabled")
        self._text.yview_moveto(0.0)
        self._text.focus_set()

    def _clear_buttons(self) -> None:
        for child in self._buttons.winfo_children():
            child.destroy()
        self._button_count = 0

    def _add_button(self, label: str, command: Callable[[], None]) -> None:
        count = getattr(self, "_button_count", 0)
        ttk.Button(self._buttons, text=label, command=command).grid(
            row=count // _BUTTONS_PER_ROW,
            column=count % _BUTTONS_PER_ROW,
            sticky="ew",
            padx=(0, 8),
            pady=(0, 6),
        )
        self._button_count = count + 1

    # ── the main view ────────────────────────────────────────────────────────

    def _show_main(self) -> None:
        self._rendered_version = None
        status = self._service.status()
        self._status_var.set("\n".join(status_lines(status)))
        self._set_text(
            "Choose an action below. Nothing is recorded, changed, or "
            "deleted unless you choose it — and closing this window "
            "changes nothing."
        )
        self._clear_buttons()
        self._add_button("Read the research consent text", self._show_consent_text)
        for action in sorted(actions_for(status), key=lambda a: a.name):
            self._add_button(ACTION_LABELS[action], self._ACTION_HANDLERS[action])
        self._add_button("Close", self._on_close)

    def _show_consent_text(self) -> None:
        """Read-only: the text with a Back button. The grant path renders
        its own copy with the agree/decline buttons (mirrors the CLI's
        separate 'read' and 'agree' menu entries)."""
        self._set_text(dialog_render_text(self._service.consent_dialog()))
        self._clear_buttons()
        self._add_button("Back", self._show_main)

    # ── research grant ───────────────────────────────────────────────────────

    def _show_grant_view(self) -> None:
        status = self._service.status()
        dialog = self._service.consent_dialog()
        text = dialog_render_text(dialog)
        if status.state is ResearchConsentState.NEEDS_RECONSENT:
            text = (
                reconsent_render_text(dialog, status.consent_version)
                + "\n\n"
                + text
            )
        self._set_text(text)
        self._rendered_version = dialog.version
        self._clear_buttons()
        self._add_button(dialog.agree_label, self._agree)
        self._add_button(dialog.decline_label, self._show_main)

    def _agree(self) -> None:
        result = grant_after_render(self._rendered_version, self._service.grant)
        self._rendered_version = None
        if result is None:
            return  # fired without a rendered dialog: a no-op, never a grant
        self._show_main()

    # ── withdrawal ───────────────────────────────────────────────────────────

    def _withdraw_flow(self) -> None:
        if not messagebox.askyesno(
            "Withdraw research participation?",
            "This stops all future research data collection immediately.\n\n"
            "Withdraw?",
            parent=self,
            default=messagebox.NO,
        ):
            return
        delete = messagebox.askyesno(
            "Delete collected data?",
            "Also delete ALL research data collected so far? (recommended)",
            parent=self,
            default=messagebox.YES,
        )
        if delete:
            if RESEARCH_DB_PATH.exists() and messagebox.askyesno(
                "Export first?",
                "Export a copy of your research data first?",
                parent=self,
                default=messagebox.NO,
            ):
                self._export_flow()
            if not messagebox.askyesno(
                "This cannot be undone",
                "ALL research data will be deleted immediately and "
                "permanently, together with the private key that signed "
                "your rows.\n\nReally delete?",
                parent=self,
                default=messagebox.NO,
            ):
                return
        result = self._service.withdraw(purge_data=delete)
        messagebox.showinfo(
            "Withdrawn", withdraw_result_text(result), parent=self
        )
        self._show_main()

    # ── page copies ──────────────────────────────────────────────────────────

    def _show_page_copies_view(self) -> None:
        status = self._service.status()
        if status.page_copies is PageCopiesState.ON:
            self._rendered_version = None
            self._set_text(_wording.page_copies_line(status))
            self._clear_buttons()
            self._add_button("Turn page copies off…", self._page_copies_off_flow)
            self._add_button("Back", self._show_main)
            return
        dialog = self._service.page_copies_dialog()
        self._set_text(page_copies_render_text(dialog))
        self._rendered_version = dialog.version
        self._clear_buttons()
        self._add_button(dialog.agree_label, self._grant_page_copies)
        self._add_button(dialog.decline_label, self._show_main)

    def _grant_page_copies(self) -> None:
        result = grant_after_render(
            self._rendered_version, self._service.grant_page_copies
        )
        self._rendered_version = None
        if result is None:
            return  # fired without a rendered dialog: a no-op, never a grant
        self._show_main()

    def _page_copies_off_flow(self) -> None:
        if not messagebox.askyesno(
            "Turn page copies off?",
            "Stop keeping cleaned copies of job pages?",
            parent=self,
            default=messagebox.NO,
        ):
            return
        delete = messagebox.askyesno(
            "Delete kept copies?",
            "Delete every kept page copy?",
            parent=self,
            default=messagebox.YES,
        )
        removed = self._service.withdraw_page_copies(delete=delete)
        messagebox.showinfo(
            "Page copies off",
            (
                f"Page copies are off. Deleted {removed} kept copy(ies)."
                if delete
                else "Page copies are off; the kept copies remain on this device."
            ),
            parent=self,
        )
        self._show_main()

    # ── export ───────────────────────────────────────────────────────────────

    def _export_flow(self) -> None:
        if not RESEARCH_DB_PATH.exists():
            messagebox.showinfo(
                "No research data",
                "No research data on this device yet — there is nothing to export.",
                parent=self,
            )
            return
        try:
            result = export_research_bundle("csv")
        except Exception as exc:  # noqa: BLE001 — ExportError lives in a
            # secondary adapter this primary adapter may not import.
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        messagebox.showinfo(
            "Research exported",
            f"Export written to:\n{result.directory}\n\n"
            f"Bundle digest: {result.bundle_digest}",
            parent=self,
        )

    # ── close ────────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        self._rendered_version = None
        self.destroy()

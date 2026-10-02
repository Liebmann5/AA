"""The interactive research-consent screen for the CLI (``--research``).

One of the two consent surfaces (the GUI research window is the other; a
parity pin asserts both read their words from
domain/services/research_consent_wording.py and drive the same
ResearchConsentPort). Mirrors the ``--label`` precedent: main.py composes
(parses the flag, calls :func:`run`), and every print and input lives here
in the primary adapter, so main.py's pinned print-site count does not move.

Rules this screen exists to keep:

    * No grant without the rendered dialog. There is deliberately no
      non-interactive grant flag anywhere: ResearchConsentPort.grant
      requires the surface to have rendered consent_dialog() first, so the
      agree prompt only ever appears below the full text (a pin asserts the
      call order).
    * A blank line, EOF or Ctrl-C never grants and never deletes — it is a
      decline or an exit. The one deliberate default is export format
      (blank = CSV): export carries no consent consequence.
    * Withdrawal stops collection through the process-wide stop channel
      (application/services/research_consent.py), so withdrawing here stops
      an observer THIS process is running. It cannot reach a session in a
      DIFFERENT process — the screen says so when collection_stopped is
      False, and the withdrawn record means that session's next build
      collects nothing.
    * Export reaches the exporter through composition_root: primary
      adapters may not import the secondary exporter adapter
      (tests/architecture/test_safety_pins.py EXPECTED_REACHES) — which is
      also why _export_flow catches Exception rather than ExportError.

Deletion is irreversible, so the delete path offers export first and then
requires the typed DELETE — the same confirmation strength as profile
deletion (cli/startup.py _delete_profile_confirmed).
"""

from __future__ import annotations

from auto_apply.domain.config import RESEARCH_DB_PATH
from auto_apply.domain.ports.research_consent_port import (
    PageCopiesState,
    ResearchConsentPort,
    ResearchConsentState,
)
from auto_apply.domain.services import research_consent_wording as _wording
from auto_apply.infrastructure.composition_root import (
    build_research_consent,
    export_research_bundle,
)

__all__ = ["run"]


def _ask(prompt: str) -> str:
    """input() that treats EOF and Ctrl-C as "no answer" — never a grant."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()  # noqa: T201 — terminal surface; newline after ^C/^D
        return ""


def _confirm(prompt: str, *, default: bool) -> bool:
    """A y/N question whose blank answer is the stated default."""
    answer = _ask(prompt).strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def run(consent: object | None = None) -> int:
    """Show the current status, then loop the consent menu until quit.

    Args:
        consent: The consent service. None builds the pre-session service
            via composition_root.build_research_consent(); tests inject a
            service over a temporary consent database.

    Returns:
        0 always — the screen is informational; every refusal is a printed
        sentence, not an exit code.
    """
    service = consent if consent is not None else build_research_consent()
    if not isinstance(service, ResearchConsentPort):
        raise TypeError(
            "run() needs a ResearchConsentPort (e.g. from "
            "composition_root.build_research_consent()); got "
            f"{type(service).__name__}"
        )
    while True:
        _print_status(service)
        print()  # noqa: T201
        print("  [1] Read the research consent text")  # noqa: T201
        print("  [2] Turn research on / agree to the current text")  # noqa: T201
        print("  [3] Withdraw from research")  # noqa: T201
        print("  [4] Turn page copies on or off")  # noqa: T201
        print("  [5] Export research data")  # noqa: T201
        print("  [q] Quit")  # noqa: T201
        choice = _ask("\nSelect: ").strip().lower()
        if choice in ("", "q"):
            return 0
        if choice == "1":
            _show_dialog(service)
        elif choice == "2":
            _grant_flow(service)
        elif choice == "3":
            _withdraw_flow(service)
        elif choice == "4":
            _page_copies_flow(service)
        elif choice == "5":
            _export_flow()
        else:
            print(f"  '{choice}' is not on the list.")  # noqa: T201


def _print_status(service: ResearchConsentPort) -> None:
    """The headline, the detail, and the page-copies line — the same words
    the GUI shows, from the one wording module."""
    status = service.status()
    print("\nResearch — current status")  # noqa: T201
    print(f"  {_wording.status_headline(status)}")  # noqa: T201
    print(f"  {_wording.status_detail(status)}")  # noqa: T201
    print(f"  {_wording.page_copies_line(status)}")  # noqa: T201


def _show_dialog(service: ResearchConsentPort) -> None:
    dialog = service.consent_dialog()
    print(f"\n{dialog.title}  (version {dialog.version})\n")  # noqa: T201
    print(dialog.body)  # noqa: T201
    print(f"\n  [{dialog.agree_label}]   [{dialog.decline_label}]")  # noqa: T201


def _grant_flow(service: ResearchConsentPort) -> None:
    """Render the dialog, THEN ask. The agree prompt never appears without
    the text above it — the port's grant contract made structural."""
    status = service.status()
    if status.state is ResearchConsentState.ACTIVE:
        print("\nResearch participation is already on.")  # noqa: T201
        return
    if status.state is ResearchConsentState.INACTIVE:
        # Already agreed to the current text; agreeing again cannot supply
        # a missing key or lift a policy. The status block says why.
        print("\nYou have already agreed to the current text.")  # noqa: T201
        return
    if not status.offered:
        # The opt-in is locked (docs/research_module/index.md): an
        # administrator policy or this installation turned research off.
        print(f"\n{_wording.status_detail(status)}")  # noqa: T201
        return
    if status.state is ResearchConsentState.NEEDS_RECONSENT:
        dialog = service.consent_dialog()
        print(f"\n{dialog.reconsent_title}\n")  # noqa: T201
        print(  # noqa: T201
            dialog.reconsent_body_template.format(
                old_version=status.consent_version or "unknown"
            )
        )
        print()  # noqa: T201
        print(_wording.view_changes_note())  # noqa: T201
    _show_dialog(service)
    answer = _ask("\nDo you agree? [y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        print("  Nothing was recorded.")  # noqa: T201
        return
    new_status = service.grant()
    print(f"\n  {_wording.status_headline(new_status)}")  # noqa: T201
    print(f"  {_wording.status_detail(new_status)}")  # noqa: T201


def _withdraw_flow(service: ResearchConsentPort) -> None:
    status = service.status()
    if status.state in (ResearchConsentState.OFF, ResearchConsentState.WITHDRAWN):
        print("\nThere is no research consent to withdraw.")  # noqa: T201
        return
    print("\nWithdraw research participation?")  # noqa: T201
    print("This stops all future research data collection immediately.")  # noqa: T201
    if not _confirm("Withdraw? [y/N]: ", default=False):
        print("  Nothing was changed.")  # noqa: T201
        return
    delete = _confirm(
        "Also delete ALL research data collected so far? [Y/n] (recommended): ",
        default=True,
    )
    if delete:
        if RESEARCH_DB_PATH.exists() and _confirm(
            "Export a copy of your research data first? [y/N]: ", default=False
        ):
            _export_flow()
        typed = _ask("This cannot be undone. Type DELETE to confirm: ").strip()
        if typed != "DELETE":
            print("  Cancelled — nothing was withdrawn or deleted.")  # noqa: T201
            return
    result = service.withdraw(purge_data=delete)
    if delete:
        print(f"  Deleted {result.purged} research record(s).")  # noqa: T201
    if result.collection_stopped:
        print("  Research data collection has stopped.")  # noqa: T201
    else:
        print(  # noqa: T201
            "  WARNING: a running collection could not be stopped from here. "
            "If a session is running in another window, it stops when that "
            "session ends; it collects nothing after its next start."
        )
    print(f"  {_wording.status_headline(result.status)}")  # noqa: T201


def _page_copies_flow(service: ResearchConsentPort) -> None:
    status = service.status()
    if status.state not in (
        ResearchConsentState.ACTIVE,
        ResearchConsentState.INACTIVE,
    ):
        print(  # noqa: T201
            "\nPage copies need current research consent first — agree to "
            "the research text, then come back."
        )
        return
    if status.page_copies is PageCopiesState.ON:
        print(f"\n{_wording.page_copies_line(status)}")  # noqa: T201
        if not _confirm("Turn page copies off? [y/N]: ", default=False):
            print("  Nothing was changed.")  # noqa: T201
            return
        delete = _confirm("Delete every kept page copy? [Y/n]: ", default=True)
        removed = service.withdraw_page_copies(delete=delete)
        if delete:
            print(  # noqa: T201
                f"  Page copies are off. Deleted {removed} kept copy(ies)."
            )
        else:
            print(  # noqa: T201
                "  Page copies are off; the kept copies remain on this device."
            )
        return
    dialog = service.page_copies_dialog()
    print(f"\n{dialog.title}  (version {dialog.version})\n")  # noqa: T201
    print(dialog.body)  # noqa: T201
    answer = _ask(f"\n{dialog.agree_label}? [y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        print("  Nothing was recorded.")  # noqa: T201
        return
    service.grant_page_copies()
    print(f"\n  {_wording.page_copies_line(service.status())}")  # noqa: T201


def _export_flow() -> None:
    if not RESEARCH_DB_PATH.exists():
        print(  # noqa: T201
            "\nNo research data on this device yet — there is nothing to export."
        )
        return
    print("\nFormat: [1] CSV (default)  [2] NDJSON  [3] Parquet")  # noqa: T201
    choice = _ask("Select [1]: ").strip()
    fmt = {"": "csv", "1": "csv", "2": "ndjson", "3": "parquet"}.get(choice)
    if fmt is None:
        print("  Export cancelled.")  # noqa: T201
        return
    try:
        result = export_research_bundle(fmt)
    except Exception as exc:  # noqa: BLE001 — ExportError lives in a secondary
        # adapter this primary adapter may not import; its message is the
        # user-facing contract either way.
        print(f"  Export failed: {exc}")  # noqa: T201
        return
    if result.degraded:
        print(  # noqa: T201
            f"  {result.requested_format.upper()} unavailable — wrote "
            f"{result.format.upper()} instead (optional dependency not installed)."
        )
    print(f"  Export written to: {result.directory}")  # noqa: T201
    print(f"  Bundle digest:    {result.bundle_digest}")  # noqa: T201

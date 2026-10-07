"""Single-source wording for the lifecycle surfaces (install / uninstall).

Both surfaces — adapters/primary/cli/lifecycle_screen.py and
adapters/primary/gui/lifecycle_window.py — read every group title, choice,
label, default, order and confirmation token from here, and render the plan,
the research notice and both reports through the formatters below. A parity
pin (tests/adapters/test_lifecycle_parity.py) fails if either surface
carries its own copy.

This module lives in the APPLICATION layer, not the domain: the formatters
need UninstallPlan/InstallPlan, and a domain module importing application
models would be an upward import the boundary pins forbid. The choice
arithmetic itself is pure and pinned.
"""
from __future__ import annotations

from enum import Enum, auto

from auto_apply.application.services.install.engine import (
    EXTRA_ORDER,
    InstallEngine,
    InstallPlan,
    InstallReport,
    extra_support,
)
from auto_apply.application.services.uninstall.model import (
    GROUP_AA,
    GROUP_INSTALL,
    GROUP_PREEXISTING,
    GROUP_RESEARCH,
    PROMISE_TEXT,
    RetentionHold,
    UninstallPlan,
    UninstallReport,
)

__all__ = [
    "CHOICE_KEYS",
    "CHOICE_LABELS",
    "CONFIRM_DELETE",
    "CONFIRM_UNINSTALL",
    "GROUP_ORDER",
    "GROUP_TITLES",
    "PROMISE_TEXT",
    "ResearchChoice",
    "format_choice_menu_lines",
    "format_install_plan_lines",
    "format_install_report_lines",
    "format_plan_lines",
    "format_report_lines",
    "format_research_notice_lines",
    "format_size",
    "current_macos_version",
    "extras_for_display",
    "install_action_label",
    "research_choices",
]

#: Group titles, verbatim as the user guide quotes them.
GROUP_TITLES: dict[str, str] = {
    GROUP_AA: "AA created — will be removed",
    GROUP_INSTALL: "AA runtime — removed after AA closes",
    GROUP_PREEXISTING: "existed before AA — will not be touched",
    GROUP_RESEARCH: "research data — your choice",
}

#: Display order for the plan's groups (research is rendered separately,
#: always last, by format_plan_lines).
GROUP_ORDER: tuple[str, ...] = (GROUP_AA, GROUP_INSTALL, GROUP_PREEXISTING)

#: The typed tokens. Both surfaces require exactly these strings; a
#: misclick or a stray Enter must never be able to confirm.
CONFIRM_UNINSTALL = "UNINSTALL"
CONFIRM_DELETE = "DELETE"


class ResearchChoice(Enum):
    """What may happen to research data at uninstall."""

    KEEP_IN_PLACE = auto()
    MOVE = auto()
    EXPORT = auto()
    DELETE = auto()


CHOICE_LABELS: dict[ResearchChoice, str] = {
    ResearchChoice.KEEP_IN_PLACE: "Keep everything in place (default)",
    ResearchChoice.MOVE: "Move it to a folder I choose",
    ResearchChoice.EXPORT: "Export a verified copy, then remove the originals",
    ResearchChoice.DELETE: "Delete all research data permanently",
}

#: Menu keys for the CLI; the GUI shows the same choices as radio buttons.
CHOICE_KEYS: dict[str, ResearchChoice] = {
    "k": ResearchChoice.KEEP_IN_PLACE,
    "m": ResearchChoice.MOVE,
    "e": ResearchChoice.EXPORT,
    "d": ResearchChoice.DELETE,
}

#: ResearchChoice → the action string UninstallDecision.research expects.
CHOICE_TO_ACTION: dict[ResearchChoice, str | None] = {
    ResearchChoice.KEEP_IN_PLACE: None,  # engine default: keep-in-place
    ResearchChoice.MOVE: "keep",
    ResearchChoice.EXPORT: "export",
    ResearchChoice.DELETE: "delete",
}


def research_choices(hold_active: bool) -> tuple[ResearchChoice, ...]:
    """The choices, in display order, default first.

    Under a retention hold the surfaces offer KEEP_IN_PLACE and EXPORT only:
    DELETE is the thing the hold exists to forbid, and MOVE would relocate
    data the researcher's protocol expects to find in place. The ENGINE is
    deliberately more permissive (a scripted --research-keep under a hold
    still works); the surfaces are conservative. Both surfaces read this —
    that is what makes them identical.
    """
    if hold_active:
        return (ResearchChoice.KEEP_IN_PLACE, ResearchChoice.EXPORT)
    return (
        ResearchChoice.KEEP_IN_PLACE,
        ResearchChoice.MOVE,
        ResearchChoice.EXPORT,
        ResearchChoice.DELETE,
    )


def format_size(size_bytes: int) -> str:
    if size_bytes >= 1 << 20:
        return f"{size_bytes / (1 << 20):.1f} MB"
    if size_bytes >= 1 << 10:
        return f"{size_bytes / (1 << 10):.1f} KB"
    return f"{size_bytes} bytes"


def format_plan_lines(plan: UninstallPlan) -> list[str]:
    """The uninstall plan, one rendering for both surfaces."""
    lines = ["AutoApply uninstall — plan", ""]
    for group in GROUP_ORDER:
        rows = [i for i in plan.items if i.group == group]
        if not rows:
            continue
        lines.append(f"{GROUP_TITLES[group]}:")
        for item in rows:
            suffix = f"  [{item.note}]" if item.note else ""
            lines.append(f"  {item.path}  ({format_size(item.size_bytes)}){suffix}")
        lines.append("")
    if plan.research_items:
        lines.append(f"{GROUP_TITLES[GROUP_RESEARCH]}:")
        for item in plan.research_items:
            lines.append(f"  {item.path}  ({format_size(item.size_bytes)})")
        lines.append("")
    if plan.running_pids:
        lines.append(f"Running AA processes to stop first: {plan.running_pids}")
    if plan.discovery_mode:
        lines.append(
            "(no footprint ledger — discovery mode: locations inferred; "
            "shared or pre-existing items are never removed)"
        )
    if plan.hold is not None:
        lines.append(
            f"RESEARCH RETENTION HOLD active until {plan.hold.hold_until}"
            " — research records cannot be destroyed."
        )
        if plan.hold.note:
            lines.append(f"  reason: {plan.hold.note}")
    for warning in plan.warnings:
        lines.append(f"note: {warning}")
    return lines


def format_research_notice_lines(plan: UninstallPlan) -> list[str]:
    """The research-data notice: what exists, where, the hold, the choices."""
    lines = ["Research data on this device:"]
    for item in plan.research_items:
        lines.append(f"  {item.path}  ({format_size(item.size_bytes)})")
    hold: RetentionHold | None = plan.hold
    if hold is not None:
        lines.append(
            f"A retention hold is active until {hold.hold_until}"
            + (f" ({hold.note})" if hold.note else "")
            + ". Deleting research records is refused while it holds."
        )
    choices = research_choices(hold is not None)
    lines.append("Your choices:")
    lines.extend(format_choice_menu_lines(choices))
    return lines


def format_choice_menu_lines(choices: tuple[ResearchChoice, ...]) -> list[str]:
    key_for = {choice: key for key, choice in CHOICE_KEYS.items()}
    return [f"  [{key_for[c]}] {CHOICE_LABELS[c]}" for c in choices]


def format_report_lines(report: UninstallReport) -> list[str]:
    """The final uninstall report — the scoped promise included, verbatim."""
    lines = [
        "Uninstall report",
        f"  removed: {len(report.removed)} item(s); "
        f"stopped processes: {report.stopped_pids or 'none'}",
        f"  research: {report.research_action} — {report.research_detail}",
    ]
    for kept in report.kept:
        lines.append(f"  kept: {kept.path} ({kept.reason})")
    for failed in report.failed:
        lines.append(f"  FAILED: {failed.path} ({failed.reason})")
    for leftover in report.leftovers:
        lines.append(f"  leftover: {leftover.path} ({leftover.reason})")
    for scheduled in report.scheduled_for_reboot:
        lines.append(f"  scheduled at reboot: {scheduled}")
    lines += ["", report.promise]
    return lines


def format_install_plan_lines(plan: InstallPlan) -> list[str]:
    """The install consent screen's content, one rendering for both surfaces."""
    lines = ["AutoApply install — plan"]
    for item in plan.downloads:
        lines.append(f"  download: {item.what} ({item.size_text}) -> {item.dest}")
    for creation in plan.creations:
        lines.append(f"  create:   {creation}")
    for name in plan.extras_supported:
        lines.append(f"  extra:    {name}")
    for name, reason in plan.extras_skipped:
        lines.append(f"  extra {name}: NOT installed — {reason}")
    lines.append("Nothing is installed system-wide; no administrator rights are used.")
    return lines


def format_install_report_lines(report: InstallReport) -> list[str]:
    lines = ["Install complete"]
    for line in report.downloaded:
        lines.append(f"  downloaded: {line}")
    for line in report.existing:
        lines.append(f"  already present: {line}")
    for name in report.extras_installed:
        lines.append(f"  extra installed: {name}")
    for name, reason in report.extras_skipped:
        lines.append(f"  extra {name}: not installed — {reason}")
    if report.launcher is not None:
        lines.append(f"  start AutoApply with: {report.launcher}")
    if report.shortcut is not None:
        lines.append(f"  shortcut: {report.shortcut}")
    for note in report.notes:
        lines.append(f"  note: {note}")
    return lines


def install_action_label(needs_download: bool) -> str:
    """The GUI consent button's caption (GUI chrome; the CLI asks y/N)."""
    return "Download and install" if needs_download else "Install"


def extras_for_display(
    system: str, machine: str, macos_version: tuple[int, int] | None
) -> list[tuple[str, bool, str]]:
    """(name, installable, plain-words reason) in the engine's canonical
    order — the GUI checkbutton row and the CLI's --extra share the one
    table through here."""
    table = extra_support(system, machine, macos_version)
    return [(name, *table[name]) for name in EXTRA_ORDER if name in table]


def current_macos_version() -> tuple[int, int] | None:
    """The running machine's macOS version, or None — delegated so the GUI
    never imports the engine module for a static helper."""
    return InstallEngine._macos_version()

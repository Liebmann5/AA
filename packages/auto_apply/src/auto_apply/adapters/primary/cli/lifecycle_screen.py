"""The interactive lifecycle screen for the CLI (--install / --uninstall).

Mirrors the research-consent screen precedent: main.py composes (parses
flags, builds the environment); every interactive line lives here in the
primary adapter. Two hard rules, both pinned:

  * The CONVERSATION — plan, notices, choices, progress, every question —
    goes to STDERR. Only the final report goes to stdout, and the
    machine-readable report goes to its file. Measured defect: with
    `> session_log.txt` users could not see the questions (and input()'s
    own prompt writes to stdout, which is why _ask never passes one).
    --dry-run therefore writes zero bytes to stdout.
  * Wording, choices, defaults, order and confirmation tokens come from
    application/services/lifecycle_wording.py — the same source the GUI
    reads (tests/adapters/test_lifecycle_parity.py enforces it).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import IO, Callable

from auto_apply.infrastructure.composition_root import (
    InstallEngine,
    InstallEnvironment,
    InstallError,
    ResearchDecision,
    UninstallDecision,
    UninstallEngine,
    UninstallEnvironment,
    UninstallRefused,
    lifecycle_wording as _w,
)

__all__ = ["run_install", "run_uninstall"]


def _ask(prompt: str, *, err: IO[str], input_fn: Callable[[], str] | None = None) -> str:
    """Ask on stderr, read from stdin. input() is never given the prompt —
    it would write it to stdout, which is the defect this screen exists
    not to repeat. The callable resolves at CALL time (D6: a default of
    `input` bound it at definition time, so monkeypatched tests never
    reached it). EOF and Ctrl-C read as "no answer" — never a grant."""
    if input_fn is None:
        input_fn = input
    print(prompt, file=err, end=" ", flush=True)  # noqa: T201
    try:
        return input_fn().strip()
    except (EOFError, KeyboardInterrupt):
        print(file=err)  # noqa: T201 — newline after ^C/^D
        return ""


def run_uninstall(
    env: UninstallEnvironment,
    *,
    dry_run: bool = False,
    assume_yes: bool = False,
    report_path: Path | None = None,
    research_action: str | None = None,
    research_dest: Path | None = None,
    out: IO[str] | None = None,
    err: IO[str] | None = None,
) -> int:
    """Plan → confirm → stop → research step → remove → verify → report.

    Returns the exit code: 0 clean (or dry-run), 1 unexpected leftovers,
    2 refused/cancelled.
    """
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    engine = UninstallEngine(env)
    env.progress = lambda message: print(f"  … {message}", file=err)  # noqa: T201
    plan = engine.build_plan()

    for line in _w.format_plan_lines(plan):
        print(line, file=err)  # noqa: T201
    if plan.research_items:
        print(file=err)  # noqa: T201
        for line in _w.format_research_notice_lines(plan):
            print(line, file=err)  # noqa: T201

    if dry_run:
        print("\n--dry-run: nothing was stopped, moved, or deleted.", file=err)  # noqa: T201
        return 0

    action: str | None = research_action
    dest: Path | None = research_dest
    choices = _w.research_choices(plan.hold is not None)

    if action == "delete" and plan.hold is not None:
        print(  # noqa: T201
            f"Refused: a retention hold is active until {plan.hold.hold_until};"
            " research records stay. Offered: export.",
            file=err,
        )
        action = None
    if action == "delete" and not assume_yes:
        typed = _ask(f"Type {_w.CONFIRM_DELETE} to delete all research data:", err=err)
        if typed != _w.CONFIRM_DELETE:
            print("  Research deletion cancelled — keeping everything in place.", file=err)  # noqa: T201
            action = None

    interactive = sys.stdin.isatty() and not assume_yes
    if interactive:
        if _ask(f"\nType {_w.CONFIRM_UNINSTALL} to proceed:", err=err) != _w.CONFIRM_UNINSTALL:
            print("Cancelled — nothing was changed.", file=err)  # noqa: T201
            return 2
        if plan.research_items and action is None and len(choices) > 1:
            key = _ask("Select [k]:", err=err).lower() or "k"
            choice = _w.CHOICE_KEYS.get(key)
            if choice is None:
                print(f"  '{key}' is not on the list — keeping everything in place.", file=err)  # noqa: T201
                choice = _w.ResearchChoice.KEEP_IN_PLACE
            if choice in (_w.ResearchChoice.MOVE, _w.ResearchChoice.EXPORT):
                raw = _ask("Folder:", err=err)
                if not raw:
                    print("Cancelled — nothing was changed.", file=err)  # noqa: T201
                    return 2
                dest = Path(raw).expanduser()  # the one expanduser site (ratcheted)
            if choice is _w.ResearchChoice.DELETE:
                typed = _ask(f"Type {_w.CONFIRM_DELETE} to delete all research data:", err=err)
                if typed != _w.CONFIRM_DELETE:
                    print("  Research deletion cancelled — keeping everything in place.", file=err)  # noqa: T201
                    choice = _w.ResearchChoice.KEEP_IN_PLACE
            action = _w.CHOICE_TO_ACTION[choice]
    elif not assume_yes:
        print(  # noqa: T201
            "Refusing to uninstall without a terminal: pass --yes for scripted"
            " use (research data is kept in place by default).",
            file=err,
        )
        return 2

    try:
        report = engine.execute(
            plan,
            UninstallDecision(
                confirm=True, research=ResearchDecision(action=action, dest=dest)
            ),
        )
    except UninstallRefused as exc:
        print(f"Uninstall refused: {exc}", file=err)  # noqa: T201
        return 2

    if report_path is not None:
        report_path.write_bytes(report.to_json_bytes())
    print()  # noqa: T201 — the report is the command's output: stdout.
    for line in _w.format_report_lines(report):
        print(line)  # noqa: T201
    return 0 if report.clean else 1


def run_install(
    prepare: Callable[[], InstallEnvironment],
    *,
    frozen: bool = False,
    assume_yes: bool = False,
    capability_report: Callable[[], None] | None = None,
    out: IO[str] | None = None,
    err: IO[str] | None = None,
) -> int:
    """Frozen check → prepare → plan → consent → execute → report.

    *prepare* builds the environment (it loads the pins; its failure is
    user-facing text and therefore printed HERE, in the adapter — the
    print-sites pin keeps main.py at its inventory). Returns 0 or 1.
    """
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    if frozen:
        print(  # noqa: T201
            "This AutoApply is a self-contained build — there is nothing to install.",
            file=err,
        )
        return 0
    try:
        env = prepare()
    except Exception as exc:  # noqa: BLE001 — the message is the user-facing contract
        print(f"Cannot prepare the install: {exc}", file=err)  # noqa: T201
        return 1
    engine = InstallEngine(env)
    env.progress = lambda message: print(f"  … {message}", file=err)  # noqa: T201
    try:
        plan = engine.build_plan()
    except InstallError as exc:
        print(f"Install failed: {exc}", file=err)  # noqa: T201
        return 1
    for line in _w.format_install_plan_lines(plan):
        print(line, file=err)  # noqa: T201
    env.assume_yes = assume_yes
    env.confirm = (
        (lambda text: _ask(f"{text}\nProceed? [y/N]:", err=err).lower() in ("y", "yes"))
        if (sys.stdin.isatty() and not assume_yes)
        else None
    )
    try:
        report = engine.execute(plan)
    except InstallError as exc:
        print(f"\nInstall failed: {exc}", file=err)  # noqa: T201
        return 1
    print()  # noqa: T201
    for line in _w.format_install_report_lines(report):
        print(line)  # noqa: T201
    if capability_report is not None:
        print("\nCapability check (the same check --check-config runs):")  # noqa: T201
        try:
            capability_report()
        except Exception as exc:  # noqa: BLE001
            print(  # noqa: T201
                f"  capability check could not run ({exc}) — re-run later with --check-config"
            )
    return 0

"""Terminal rendering of a replay (``--replay``, item 7).

Owns the user-facing text, as the primary-adapter ratchet in
tests/architecture/test_safety_pins.py requires: main.py composes
(composition_root.run_replay) and this module only renders. It imports
nothing past the domain.
"""

from __future__ import annotations

from auto_apply.domain.models.replay import ReplayReport

__all__ = ["replay_lines", "print_replay_report", "print_replay_error"]


def replay_lines(report: ReplayReport) -> list[str]:
    """The report as display lines. The replay digest comes first: it is
    the one number that identifies the result, and two people who replay
    the same corpus with the same AA version must see the same one."""
    out = report.output
    lines = [
        "Replay finished — no browser, no network, no research key.",
        f"  Replay digest:   {out.manifest_sha256}",
        f"  Artifact digest: {out.artifact_sha256}   (replay.jsonl)",
        f"  Corpus digest:   {out.corpus_digest}",
        f"  Page copies replayed: {out.items}",
        f"  Signals:              {out.signals}",
    ]
    for signal_type, count in report.signals_by_type:
        lines.append(f"    {signal_type:<10} {count}")
    if out.skipped:
        lines.append(f"  Not replayed: {len(out.skipped)} file(s)")
        for skip in out.skipped:
            lines.append(f"    {skip.source}: {skip.reason}")
    lines.append(f"  Written to: {report.location}")
    lines.append(
        "  Same corpus + same AA version = same digest, on any machine. "
        "manifest.json lists what a replay cannot reproduce."
    )
    return lines


def print_replay_report(report: ReplayReport) -> None:
    for line in replay_lines(report):
        print(line)  # noqa: T201


def print_replay_error(message: str) -> None:
    print(f"Replay failed: {message}")  # noqa: T201

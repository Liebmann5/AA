"""Trace (CT-T-018, CT-DS-006): one append-only record of every tool run.

Privacy by construction (CT-NFR-014): a ``ToolRun`` holds ids, versions,
hashes, counts and enumerated reasons only. No URL, no page text, no user
value ever enters it, so the default level is safe to keep and to share.
Higher levels (values, text) are the consumer's choice and are not built
here.

Bounded (CT-NFR-018, CT-NFR-024): the trace keeps the last ``max_events``
runs and counts what it dropped.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolRun:
    seq: int
    tool: str
    ct_id: str
    tool_version: str
    params_hash: str
    input_hash: str
    output_hash: str
    outcome: str           # "ok" | "abstain" | "timeout" | "error"
    reason: str            # enumerated reason for non-ok outcomes, "" otherwise
    units: int
    cache_hit: bool
    epoch: int
    duration_ms: float | None = None   # only when the caller injects a clock


class Trace:
    def __init__(self, max_events: int = 10_000) -> None:
        self._events: deque[ToolRun] = deque(maxlen=max_events)
        self._seq = 0
        self.dropped = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def append(self, run: ToolRun) -> None:
        if len(self._events) == self._events.maxlen:
            self.dropped += 1
        self._events.append(run)

    def __iter__(self) -> Iterator[ToolRun]:
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)

    def summary(self) -> dict[str, dict[str, int]]:
        """Counts per tool and outcome (the L0 view)."""
        out: dict[str, dict[str, int]] = {}
        for run in self._events:
            row = out.setdefault(run.tool, {})
            row[run.outcome] = row.get(run.outcome, 0) + 1
            if run.cache_hit:
                row["cache_hit"] = row.get("cache_hit", 0) + 1
        return out

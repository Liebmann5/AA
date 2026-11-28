"""The day-one research record of answer decisions (Phase 0, P0-6).

AA_ENGINE_MATH.md §12: from the first live run, AA logs one record per
answer decision (approved, edited, unreviewed, …: §5's labels) and one per
validation message, so the evidence §5 and §4 need accumulates from day one.
A record carries a question key (hashed before it is stored: keys can hold
label text), the field's kind, the decision, the answer's source and a
confidence bucket — never a value, never a label, never page text.

Pure: dataclasses only.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ReviewEvent", "ValidationEvent", "confidence_bucket"]


@dataclass(frozen=True)
class ReviewEvent:
    """One answer decision. ``question_key`` is hashed before it is stored
    (it can contain label text); no value, no label."""

    question_key: str
    field_kind: str
    decision: str
    source: str
    confidence: float
    step_index: int
    trust_level: str
    form_language: str = ""


@dataclass(frozen=True)
class ValidationEvent:
    """The page flagged a question after AA tried to move on. A flag only —
    never the message."""

    question_key: str
    step_index: int
    message_present: bool


def confidence_bucket(confidence: float) -> int:
    """0..10: the answer's confidence in tenths (what the log stores)."""
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        return 0
    return max(0, min(10, int(c * 10 + 1e-9)))

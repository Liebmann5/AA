"""Which answers the person must see before they are sent (docs/adr/026).

Two settings, deliberately independent of each other and of everything
else:

* **Trust** (``answer_trust``) decides *which* answers need the person's OK.
  Levels widen one class at a time:

  ======== ==================================================================
  never    the default. Every answer AA wrote, matched by meaning, or drew
           from a sensitive part of the profile is reviewed. Plain profile
           facts (a name, an email) and the person's own in-place answers
           are not.
  own_words  the person's own words go without review: profile facts and
           declared answers, saved answers matched word for word, answers
           they gave earlier this session.
  matched  also saved answers matched by meaning.
  drafts   also AI drafts that pass AA's checks.
  ======== ==================================================================

  At every level an answer below the confidence floor
  (``review_below_confidence``) is reviewed, and an answer whose source AA
  does not recognise is treated as a draft (fail closed).

* **Timing** (``review_timing``) decides *when* the person sees them:
  ``each`` (as each one is filled), ``page`` (all of a page's, before AA
  moves on), ``end`` (all of them, before the application is sent).

**Independence (the coupling this module exists to prevent).** Neither
setting reads, or is read by, the submission setting (``human_review_
checkpoints`` / autonomy) or the human-in-the-loop transport (the gate that
carries a question to the person). This module is a pure function of an
answer and two values. The engine asks *when* the timing says, through
whatever gate it has; the workflow composes the result with the submission
decision at one point (``ApplicationsWorkflow._authorize_submission``):
submitting without being asked never means unreviewed answers go out — if
answers still need the person and no one can be asked, the application is
not sent.

Pure and deterministic: no imports beyond the answer model.
"""

from __future__ import annotations

from auto_apply.domain.applications.answers import Answer

TRUST_LEVELS: tuple[str, ...] = ("never", "own_words", "matched", "drafts")
REVIEW_TIMINGS: tuple[str, ...] = ("each", "page", "end")
DEFAULT_TRUST = "never"
DEFAULT_TIMING = "end"
DEFAULT_FLOOR = 0.8

#: Answer classes each trust level lets through without review.
_ALLOWED: dict[str, frozenset[str]] = {
    "never": frozenset(),
    "own_words": frozenset({"own"}),
    "matched": frozenset({"own", "matched"}),
    "drafts": frozenset({"own", "matched", "draft"}),
}

#: Sources that are the person's own words.
_OWN_PREFIXES = ("profile:", "session", "saved", "acknowledgement")


def answer_class(answer: Answer) -> str:
    """``person`` | ``own`` | ``matched`` | ``draft`` (unknown sources are
    drafts: fail closed)."""
    src = answer.source or ""
    if src == "human":
        return "person"
    if src.startswith("saved:meaning"):
        return "matched"
    if src.startswith("generated"):
        return "draft"
    if src.startswith(_OWN_PREFIXES):
        return "own"
    return "draft"


def normal_trust(value: object) -> str:
    """A trust level; anything unknown reads as the strictest (``never``)."""
    v = str(value or "").strip().lower()
    return v if v in TRUST_LEVELS else DEFAULT_TRUST


def normal_timing(value: object) -> str:
    """A review timing; anything unknown reads as ``end`` (always reached)."""
    v = str(value or "").strip().lower()
    return v if v in REVIEW_TIMINGS else DEFAULT_TIMING


def needs_review(answer: Answer, trust: object = DEFAULT_TRUST,
                 floor: float = DEFAULT_FLOOR) -> bool:
    """Must the person see ``answer`` before it is sent?"""
    cls = answer_class(answer)
    if cls == "person":
        return False
    if answer.confidence < floor:
        return True
    if cls in _ALLOWED[normal_trust(trust)]:
        return False
    return bool(answer.review or answer.sensitive) or cls in ("matched", "draft")


__all__ = [
    "DEFAULT_FLOOR", "DEFAULT_TIMING", "DEFAULT_TRUST", "REVIEW_TIMINGS", "TRUST_LEVELS",
    "answer_class", "needs_review", "normal_timing", "normal_trust",
]

"""What to do with one question: fill it, leave it, or ask the person. Pure.

The rules, in the order they are applied (the first that decides wins):

1. **Never touch** a trap, a skip, a password, a disabled control, or a
   control that is not on this step (not rendered, not visible). pagecomp's
   trap rule already weighs "filling a trap" ten times worse than "skipping a
   real field"; this layer never overrides it.
2. **Keep what is already there.** A value the site or the person put in the
   field (a résumé parse, a browser extension, the person typing) is kept,
   unless ``overwrite_prefilled`` is on.
3. **Acknowledgements.** A single required checkbox (``I certify...``,
   ``I agree to the privacy notice``) is ticked when ``acknowledge_required``
   is on; a single optional checkbox (job alerts, marketing, "keep my data
   for other roles") is left unticked — the privacy-preserving default.
4. **Answer.** A usable answer (at or above ``min_confidence``) is filled.
5. **No answer.** A REQUIRED question is asked in place; an OPTIONAL one is
   left; an UNKNOWN one is left too, and the page's own validation, read
   after the attempt to advance, decides whether it was needed (AA asks
   only when asking is necessary).

A sensitive question with no answer from the person's own data is never
guessed: it follows rule 5 like any other, so an optional demographic
question stays blank.
"""

from __future__ import annotations

from dataclasses import dataclass

from auto_apply.domain.applications.answers import Answer, is_protected
from auto_apply.domain.applications.form_model import (
    FILL,
    REQUIRED,
    ControlState,
    FormQuestion,
    QuestionKind,
)

FILL_ACTION = "fill"
LEAVE = "leave"
ASK = "ask"


@dataclass(frozen=True)
class FillSettings:
    """The policy's knobs (``applications.*`` in runtime_defaults.yaml)."""

    min_confidence: float = 0.75
    overwrite_prefilled: bool = False
    acknowledge_required: bool = True


@dataclass(frozen=True)
class FillDecision:
    action: str
    reason: str
    answer: Answer | None = None


def decide(
    q: FormQuestion,
    state: ControlState,
    answer: Answer | None,
    settings: FillSettings,
) -> FillDecision:
    """The action for one question, with the reason recorded as evidence."""
    if q.decision != FILL:
        return FillDecision(LEAVE, f"reader-decision:{q.decision.lower()}")
    if not state.present:
        return FillDecision(LEAVE, "not-found")
    if state.disabled:
        return FillDecision(LEAVE, "disabled")
    if not state.visible and q.kind != QuestionKind.FILE:
        return FillDecision(LEAVE, "not-on-this-step")

    if state.filled and not settings.overwrite_prefilled:
        return FillDecision(LEAVE, "prefilled")
    if q.kind == QuestionKind.PASSWORD:
        # AA never types a password. A required one that appears inside the
        # form (an "create an account" section) is the person's to fill.
        return FillDecision(ASK if q.is_required else LEAVE, "password")

    if q.kind == QuestionKind.CHECKBOX and len(q.controls) == 1:
        if answer is not None and answer.checked is not None \
                and answer.confidence >= settings.min_confidence:
            return FillDecision(FILL_ACTION, "answer", answer)
        if q.required == REQUIRED:
            if settings.acknowledge_required and not is_protected(q):
                return FillDecision(
                    FILL_ACTION, "acknowledgement",
                    Answer(checked=True, source="acknowledgement", confidence=1.0, review=True),
                )
            return FillDecision(ASK, "required-checkbox")
        return FillDecision(LEAVE, "optional-checkbox-left-unticked")

    if q.kind == QuestionKind.FILE:
        if answer is not None and answer.file_path:
            return FillDecision(FILL_ACTION, "answer", answer)
        if answer is not None and answer.source.endswith("_missing"):
            # A configured document that cannot be found blocks even an
            # optional upload: the person must learn it did not attach.
            return FillDecision(ASK, "document-missing", answer)
        if q.required == REQUIRED:
            return FillDecision(ASK, "required-upload-without-document")
        return FillDecision(LEAVE, "optional-upload-without-document")

    if answer is not None and answer.confidence >= settings.min_confidence:
        return FillDecision(FILL_ACTION, "answer", answer)

    if q.required == REQUIRED:
        return FillDecision(ASK, "required-without-answer")
    if answer is not None:
        return FillDecision(LEAVE, "low-confidence-answer-not-used")
    return FillDecision(LEAVE, "no-answer")

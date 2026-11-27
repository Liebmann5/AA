"""AA's language knowledge applied to one step, whatever language it is in. Pure.

The perception reader (pagecomp) types fields and classifies buttons from
structure first and from a small, mostly English vocabulary second. This
step adds what AA knows about other languages (``form_lexicon.py``), without
ever overriding a structural reading:

* **Buttons.** A button the reader left unclassified (``other``) or called
  ``submit`` only because of its HTML type, whose text is a "next" word in
  one of the page's candidate languages ("Avanti", "Далее", "次へ", "다음"),
  becomes a ``next`` control — exactly as the reader treats "Next" in
  English; a "back" word makes it ``back``. Never when the text also says it
  sends something in any language, and never for a "review" word: a
  "Review"/"Überprüfen"/"確認画面へ" control keeps the reader's verdict (it
  may submit), so the engine asks before clicking it, as it does in English.
  The engine's own rules still apply on top: a submit-type "Next" is clicked
  unconfirmed only when the page shows that more steps follow.
* **Field types.** A question the reader could only type by its widget
  (``default``, a bare select or radio group) gets the type its label names
  in a candidate language ("Vorname" → first_name, "Código postal" →
  postal_code). An ``autocomplete`` token, an input type or the reader's own
  lexicon is never overridden. A long label stays a question, as in the
  reader (CT-ALG: a label of more than six words is not a field name).
* **One bare "name" beside a given or a family name** is the other half
  ("Prénom" + "Nom", "Nombre" + "Apellidos", "Vorname" + "Name").
* **Requiredness.** An UNKNOWN question whose label carries a required word
  in any language ("Pflichtfeld", "obligatoire", "必須") becomes REQUIRED —
  the careful direction; an optional word in a candidate language
  ("facultatif", "任意") makes it OPTIONAL.
* **Step position** from the step's short visible texts, in any digits.

Every change is recorded where the reading records its evidence
(``type_source``, ``required_evidence``, ``role_source``), so a research
record shows which words in which language produced each decision.
Idempotent: localizing a localized step changes nothing.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from auto_apply.domain.applications.form_language import (
    best_class,
    field_type_of,
    fold,
    resolve,
    says,
    step_position,
    which,
)
from auto_apply.domain.applications.form_model import (
    OPTIONAL,
    REQUIRED,
    UNKNOWN,
    FormButton,
    FormQuestion,
    FormStep,
    QuestionKind,
    says_submit,
)
from auto_apply.domain.applications.selection_limits import selection_limit

#: Canonical types whose answers only the person may give (mirrors
#: ``answers.PROTECTED_TYPES``; pinned equal by a test).
_PROTECTED_TYPES = frozenset({
    "work_authorization", "sponsorship", "gender", "ethnicity", "race", "veteran",
    "disability", "pronouns", "birth_date", "age", "criminal_history",
    "sexual_orientation", "religion", "marital_status",
})
#: Field types a long label may still be (a question, not a field name).
QUESTION_FIELD_TYPES = frozenset({
    "work_authorization", "sponsorship", "gender", "ethnicity", "veteran", "disability",
    "pronouns", "salary", "start_date", "birth_date",
})
_WEAK_WIDGET_TYPES = frozenset({"text", "choice", "radio", "checkbox", ""})
_MAX_FIELD_WORDS = 6
_MAX_FIELD_CHARS_UNSPACED = 15


def _weak(q: FormQuestion) -> bool:
    """Did the reader say it typed this only by its widget (no name, no
    token)? A reading that does not say how it typed a question is left as
    it is: provenance unknown is not provenance weak."""
    src = q.type_source or ""
    if src == "default":
        return True
    return src.startswith("type=") and q.field_type in _WEAK_WIDGET_TYPES


def _long(label: str) -> bool:
    words = fold(label).split()
    if len(words) > _MAX_FIELD_WORDS:
        return True
    return len(words) <= 2 and len("".join(words)) > _MAX_FIELD_CHARS_UNSPACED and not any(
        ch.isascii() for ch in "".join(words)
    )


def _role(b: FormButton, locales: tuple[str, ...]) -> FormButton:
    hit = best_class(b.text, ("next", "review", "back"), locales)
    if hit is None:
        return b
    role, loc = hit
    if role == b.role:
        return b
    if role == "back":
        if b.role == "back":
            return b
        return replace(b, role="back", role_source=f"lexicon({loc})")
    if role != "next" or b.role == "back" or says_submit(b.text):
        # Only a "next" word makes a control a step control, as in the reader
        # (a "Review" keeps the reader's verdict: it may submit). Never a back
        # control, or one that says it sends, in any language.
        return b
    from_type_only = b.role == "submit" and b.button_type in ("submit", "image")
    if b.role == "other" or from_type_only:
        return replace(b, role="next", final=False, role_source=f"lexicon({loc})")
    return b


def _retype(q: FormQuestion, locales: tuple[str, ...]) -> FormQuestion:
    if not _weak(q) or not q.label.strip():
        return q
    hit = field_type_of(q.label, locales)
    if hit is None:
        return q
    t, loc = hit
    if _long(q.label) and t not in QUESTION_FIELD_TYPES:
        return q
    return replace(q, field_type=t, type_source=f"lexicon({loc})",
                   sensitive=q.sensitive or t in _PROTECTED_TYPES)


def _complement(questions: tuple[FormQuestion, ...]) -> tuple[FormQuestion, ...]:
    types = Counter(q.field_type for q in questions)
    if types["full_name"] != 1:
        return questions
    has_first, has_last = types["first_name"] > 0, types["last_name"] > 0
    if has_first == has_last:
        return questions
    out = []
    for q in questions:
        if q.field_type == "full_name" and (q.type_source or "").startswith("lexicon"):
            out.append(replace(q, field_type="last_name" if has_first else "first_name",
                               type_source=q.type_source + "+complement"))
        else:
            out.append(q)
    return tuple(out)


def _requiredness(q: FormQuestion, locales: tuple[str, ...]) -> FormQuestion:
    if q.required != UNKNOWN or not q.label.strip():
        return q
    optional = which(q.label, "optional", locales)
    required = which(q.label, "required") if says(q.label, "required") else None
    if optional:
        return replace(q, required=OPTIONAL,
                       required_evidence=q.required_evidence + (f"word-optional({optional})",))
    if required:
        return replace(q, required=REQUIRED,
                       required_evidence=q.required_evidence + (f"word-required({required})",))
    return q


def step_words(step: FormStep) -> list[str]:
    """The step's own words: labels, option labels and button texts."""
    texts = [q.label for q in step.questions]
    for q in step.questions:
        texts.extend(o.label for o in q.options[:30])
    texts.extend(b.text for b in step.buttons)
    return texts


#: Question kinds that take several options (and so may carry a limit).
_MULTI_KINDS = (QuestionKind.CHECKBOX_GROUP, QuestionKind.MULTI_SELECT)


def _limits(q: FormQuestion, locales: tuple[str, ...]) -> FormQuestion:
    """The selection bound a multi-choice question states in its words."""
    if q.kind not in _MULTI_KINDS or q.choose_min or q.choose_max:
        return q
    lim = selection_limit(f"{q.label}\n{q.description}", locales)
    if not lim.known:
        return q
    return replace(q, choose_min=lim.low, choose_max=lim.high, choose_evidence=lim.evidence)


def localize_step(step: FormStep) -> FormStep:
    """The step with AA's language knowledge applied (see the module docstring)."""
    ctx = resolve(step.language, step_words(step))
    locales = ctx.locales
    buttons = tuple(_role(b, locales) for b in step.buttons)
    questions = _complement(tuple(_retype(q, locales) for q in step.questions))
    questions = tuple(_limits(_requiredness(q, locales), locales) for q in questions)
    now, total, label = step.step_now, step.step_total, step.step_label
    if not (now and total):
        texts = list(step.step_texts) + ([step.step_label] if step.step_label else [])
        pos = step_position(texts)
        if pos is not None:
            now, total = pos[0], pos[1]
            label = label or pos[2]
    return replace(
        step, buttons=buttons, questions=questions,
        locales=locales, language_evidence=ctx.evidence,
        step_now=now, step_total=total, step_label=label,
    )


__all__ = ["QUESTION_FIELD_TYPES", "localize_step", "step_words"]

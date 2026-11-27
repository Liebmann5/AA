"""Accessibility barriers a form step shows, as research evidence. Pure.

ENGINEERING_PHILOSOPHY asks AA's records to be "useful for accountability —
... exclusionary design, ... accessibility issues". The step engine already
reads every application form a job seeker meets; this module turns what
that reading measured into a small, fixed set of signals, each tied to the
WCAG 2.2 success criterion it bears on:

* ``3.1.1:no-page-language`` — the page does not declare its language
  (``lang``), so a screen reader may read it with the wrong voice
  (SC 3.1.1 Language of Page, Level A; ACT rule "HTML page has lang
  attribute");
* ``1.3.1:unlabelled-question`` — a question with no programmatic name at
  all (SC 1.3.1 Info and Relationships / 4.1.2 Name, Role, Value, Level A);
* ``3.3.2:placeholder-only-label`` — a question named only by its
  placeholder, which disappears as soon as one types (SC 3.3.2 Labels or
  Instructions, Level A);
* ``1.3.1:required-not-programmatic`` — a question shown as required (an
  asterisk, a word) that does not say so to assistive technology (no
  ``required`` / ``aria-required``), so a screen reader never announces it;
* ``1.3.5:no-input-purpose`` — a field collecting the person's own details
  (name, email, phone, address) without an ``autocomplete`` token, so
  browsers and assistive tools cannot fill or explain it (SC 1.3.5 Identify
  Input Purpose, Level AA).

These are **observations, not a conformance verdict**: an automated reading
finds some failures and cannot find many others, and no list of findings —
empty or not — establishes that a form meets any WCAG level. Each signal is
counted per step; no label, value or answer is ever part of it.
"""

from __future__ import annotations

from collections import Counter

from auto_apply.domain.applications.form_model import (
    FILL,
    REQUIRED,
    FormStep,
    QuestionKind,
)

NO_PAGE_LANGUAGE = "3.1.1:no-page-language"
UNLABELLED = "1.3.1:unlabelled-question"
PLACEHOLDER_ONLY = "3.3.2:placeholder-only-label"
REQUIRED_NOT_PROGRAMMATIC = "1.3.1:required-not-programmatic"
NO_INPUT_PURPOSE = "1.3.5:no-input-purpose"

#: Field types that collect the person's own details (WCAG 2.2 §7 "Input
#: Purposes for User Interface Components").
_PERSONAL_TYPES = frozenset({
    "first_name", "last_name", "full_name", "middle_name", "email", "phone", "address",
    "city", "postal_code", "region", "country",
})
_TEXT_KINDS = frozenset({QuestionKind.TEXT, QuestionKind.TEXTAREA, QuestionKind.SELECT,
                         QuestionKind.COMBOBOX})


def barrier_signals(step: FormStep) -> Counter[str]:
    """The step's accessibility signals, counted (see the module docstring)."""
    out: Counter[str] = Counter()
    if step.purpose != "application" or not step.questions:
        return out
    if not step.language.strip():
        out[NO_PAGE_LANGUAGE] += 1
    for q in step.questions:
        if q.decision != FILL:
            continue  # traps and hidden controls are not questions a person meets
        src = q.label_source or ""
        if src == "none" or (not src and not q.label.strip()):
            out[UNLABELLED] += 1
        elif src == "placeholder":
            out[PLACEHOLDER_ONLY] += 1
        if q.required == REQUIRED and q.required_evidence and \
                "native-required" not in q.required_evidence:
            out[REQUIRED_NOT_PROGRAMMATIC] += 1
        if q.field_type in _PERSONAL_TYPES and q.kind in _TEXT_KINDS and \
                not (q.autocomplete or "").strip():
            out[NO_INPUT_PURPOSE] += 1
    return out


__all__ = [
    "NO_INPUT_PURPOSE", "NO_PAGE_LANGUAGE", "PLACEHOLDER_ONLY", "REQUIRED_NOT_PROGRAMMATIC",
    "UNLABELLED", "barrier_signals",
]

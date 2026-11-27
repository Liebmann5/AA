"""One way to offer, read and save a multiple-choice setting, for GUI and CLI.

A field whose schema lists its allowed values (``UIField.options`` — a name
suffix, an EEO answer, a time limit, an answer-review level) is shown as a
list of choices, never as free text: a free-text box let a person type "Jr"
for a suffix that must be "Jr.", or leave it empty when "no suffix" was a
legitimate answer, and the profile then refused to save.

The rules, in one place so the two surfaces cannot drift:

* an **optional** field offers "(none)" first, and choosing it stores None;
* a **required** field offers only its values;
* typed input (the CLI, or a pasted value) is read forgivingly — the
  choice's number, its value or label in any case and without punctuation
  ("jr" → "Jr."), or a unique beginning ("dec" → "Decline to self-identify")
  — and anything ambiguous or unknown is refused with the list of choices,
  never guessed.

Pure: the standard library and ``UIField`` only.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from auto_apply.application.services.ui_schema import UIField

NONE_LABEL = "(none)"


@dataclass(frozen=True)
class Choice:
    """One choice: the stored ``value`` (None = nothing chosen) and what the
    person reads."""

    value: str | None
    label: str


def _key(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).casefold()
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^0-9a-z\u0080-￿]+", "", t)


def choices_for(field: UIField, labels: Mapping[str, str] | None = None,
                none_label: str = NONE_LABEL) -> tuple[Choice, ...]:
    """The choices to offer for ``field`` (``(none)`` first when optional).

    ``labels`` gives plain-language labels for some values (an answer-review
    level's explanation); values without one are shown as they are stored.
    """
    labels = labels or {}
    out = [] if field.required else [Choice(None, none_label)]
    for value in field.options or ():
        out.append(Choice(value, labels.get(value, value)))
    return tuple(out)


def choice_index(choices: Sequence[Choice], value: object) -> int:
    """The position of the stored ``value`` among ``choices`` (0 when the
    value is not one of them: the first choice, "(none)" when optional)."""
    for i, c in enumerate(choices):
        if c.value == value:
            return i
    return 0


def parse_choice(choices: Sequence[Choice], text: str) -> str | None:
    """The stored value a person's typed answer means.

    Raises:
        ValueError: with a plain message listing the choices, when the
            answer is empty for a required field, unknown, or ambiguous.
    """
    raw = (text or "").strip()
    if not raw:
        if choices and choices[0].value is None:
            return None
        raise ValueError("Please choose one of: " + _listing(choices))
    if raw.isdigit() and 1 <= int(raw) <= len(choices):
        return choices[int(raw) - 1].value
    want = _key(raw)
    if want:
        exact = [c for c in choices if want in (_key(c.label), _key(c.value or ""))]
        if len(exact) == 1:
            return exact[0].value
        if want == _key(NONE_LABEL) or want == "none":
            for c in choices:
                if c.value is None:
                    return None
        starts = [c for c in choices
                  if _key(c.label).startswith(want) or _key(c.value or "").startswith(want)]
        if len(starts) == 1:
            return starts[0].value
        if len(starts) > 1:
            raise ValueError(f"“{raw}” could mean more than one choice: "
                             + _listing(starts))
    raise ValueError(f"“{raw}” is not one of the choices: " + _listing(choices))


def label_of(choices: Sequence[Choice], value: object) -> str:
    return choices[choice_index(choices, value)].label if choices else ""


def _listing(choices: Sequence[Choice]) -> str:
    return ", ".join(f"{i}. {c.label}" for i, c in enumerate(choices, 1))


__all__ = ["NONE_LABEL", "Choice", "choice_index", "choices_for", "label_of", "parse_choice"]

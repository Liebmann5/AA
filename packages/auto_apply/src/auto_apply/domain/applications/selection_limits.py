"""How many options a multi-choice question allows, read from its words.

"Pick the best 2", "select up to three", "choose at least one",
"wählen Sie bis zu 3", "sélectionnez au moins deux", "select 2-3": AA reads
the bound so it never ticks more, or fewer, than the question allows. HTML
has no standard attribute for a checkbox group's limit, so the words are
the evidence; digits are read in every language, number words in the
languages ``form_lexicon.NUMBER_WORDS`` covers.

Two kinds of words, by what a wrong match would do (ADR-025's rule):

* ``choose`` and ``exactly`` *set* a limit. Read where none was meant, AA
  only asks the person. Safety classes: matched in every language.
* ``at_most``, ``at_least``, ``or_more`` and ``all_that_apply`` *loosen*
  one. Read where none was meant, AA could tick more than allowed.
  Permissive classes: matched only in the page's candidate languages
  (``locales``), never by a look-alike word from another language.

Pure: the standard library and the lexicon only. Deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from auto_apply.domain.applications.form_language import fold, which
from auto_apply.domain.applications.form_lexicon import NUMBER_WORDS

#: Bounds above this are not selection limits ("10 years", "list 50 items").
MAX_LIMIT = 20

_SETTING = ("exactly", "choose")
_LOOSENING = ("at_most", "at_least")
_RANGE = re.compile(r"(?<!\d)(\d{1,2})\s*(?:-|–|to|bis|à|a|al|tot|até)\s*(\d{1,2})(?!\d)")


def _number_words() -> dict[str, int]:
    out: dict[str, int] = {}
    for words in NUMBER_WORDS.values():
        for i, alts in enumerate(words):
            for w in alts.split("|"):
                out.setdefault(fold(w), i + 1)
    return out


_NUMBERS = _number_words()


@dataclass(frozen=True)
class SelectionLimit:
    """``low``/``high``: 0 means unbounded on that side."""

    low: int = 0
    high: int = 0
    evidence: str = ""

    @property
    def known(self) -> bool:
        return bool(self.low or self.high)

    def allows(self, n: int) -> bool:
        if self.low and n < self.low:
            return False
        return not (self.high and n > self.high)


def _number(token: str) -> int | None:
    if token.isdigit():
        n = int(token)
        return n if 0 < n <= MAX_LIMIT else None
    return _NUMBERS.get(token)


def selection_limit(text: str, locales: tuple[str, ...] | None = None) -> SelectionLimit:
    """The selection bound stated in ``text`` (a label plus its help text).

    ``locales``: the page's candidate languages, for the loosening words
    (None: every language, for use outside a page).
    """
    if not text or not text.strip():
        return SelectionLimit()
    folded = fold(text)
    # "All that apply" removes any *implied* count ("which 3 tools? select
    # all that apply" is not "exactly 3"), but never an explicit bound:
    # "select all that apply (up to 3)" is at most 3.
    open_ended = which(text, "all_that_apply", locales) is not None
    # A range ("select 2-3", "choose 2 to 4") read on the raw text: folding
    # turns the hyphen into a space.
    for m in _RANGE.finditer(text.casefold()):
        lang = which(text[max(0, m.start() - 40):m.start()], "choose")
        low, high = sorted((int(m.group(1)), int(m.group(2))))
        if lang is not None and 0 < low < high <= MAX_LIMIT:
            return SelectionLimit(low, high, f"words({lang}):{low}-{high}")
    tokens = folded.split()
    for i, tok in enumerate(tokens):
        n = _number(tok)
        if n is None:
            continue
        window = " ".join(tokens[max(0, i - 4):i])
        after = " ".join(tokens[i + 1:i + 3])
        lang = None
        for cls in _SETTING + _LOOSENING:
            lang = which(window, cls, locales if cls in _LOOSENING else None)
            if lang is not None:
                break
        if lang is None:
            continue
        if which(after, "or_more", locales) is not None \
                or which(window, "at_least", locales) is not None:
            return SelectionLimit(low=n, evidence=f"words({lang}):at least {n}")
        if which(window, "at_most", locales) is not None:
            return SelectionLimit(high=n, evidence=f"words({lang}):at most {n}")
        # "exactly 2", or a bare "pick 2" / "choose the best two" / "your top 3".
        # In an open-ended question a bare number is not a count; keep
        # looking for an explicit bound.
        if not open_ended or which(window, "exactly") is not None:
            return SelectionLimit(low=n, high=n, evidence=f"words({lang}):exactly {n}")
    if open_ended:
        return SelectionLimit(evidence="words:all that apply")
    return SelectionLimit()


__all__ = ["MAX_LIMIT", "SelectionLimit", "selection_limit"]

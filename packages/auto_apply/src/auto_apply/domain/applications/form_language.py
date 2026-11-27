"""Reading application forms in any language. Pure, deterministic, standard library.

The words live in ``form_lexicon.py``; this module decides how they are
matched. Three layers, in the order AA trusts them:

1. **Structure first, in every language.** What a form says with markup —
   ``autocomplete`` tokens, input types, ``required``/``aria-required``,
   ``aria-current="step"``, option *values* such as ISO country codes — needs
   no lexicon and is used before any word is read (pagecomp's reader and the
   step engine already do).
2. **Words, by class** (:func:`says`, :func:`which`, :func:`best_class`).
   Safety classes are matched in every language at once; permissive classes
   only in the page's candidate languages (:class:`LanguageContext`). See
   ``form_lexicon.py`` for which class is which and why.
3. **The person.** Whatever neither structure nor words settle is asked, in
   AA's own window, with the form's own words shown as they are written —
   AA never translates a question it is going to answer.

**Candidate languages** (:func:`resolve`): the language the page declares
(``lang`` on the form or the document — often missing, sometimes wrong: a
site's template says ``en`` over a German form), every language whose
*own* words appear at least twice on the step (a word several lexicons
share, such as "email", proves nothing), the languages of the dominant
writing system (Hangul → Korean), and always English, the language most
application software is built in.

**Text is folded before matching** (:func:`fold`): Unicode NFKC (full-width
forms, ligatures, compatibility characters), case-folded (``ß`` → ``ss``,
Turkish ``İ`` → ``i``), accents removed from Latin, Greek, Arabic and
Hebrew letters (``é`` → ``e``; Arabic short vowels and hamza seats), Russian
``ё`` read as ``е``, bidirectional and zero-width controls dropped,
punctuation read as a space. Other scripts keep their marks: a Devanagari
vowel sign or a Japanese voicing mark changes the word.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache

from auto_apply.domain.applications.form_lexicon import (
    FIELD_TYPES,
    LANGUAGE_ALIASES,
    LEXICON,
    SCRIPT_LANGUAGES,
)

#: Scripts whose combining marks are optional accents, removed when folding.
_ACCENT_SCRIPTS = frozenset({"LATIN", "GREEK", "ARABIC", "HEBREW"})
#: Scripts written without spaces between words (or with particles attached):
#: a term in one of these is found anywhere in the text.
UNSPACED_SCRIPTS = frozenset({
    "CJK", "HIRAGANA", "KATAKANA", "KATAKANA-HIRAGANA", "HANGUL", "THAI", "LAO",
    "KHMER", "MYANMAR", "TIBETAN",
})
_SPACE = re.compile(r" +")
_DIGITS = re.compile(r"\d+")
#: Bounds of a plausible step indicator.
_MAX_STEPS = 50
_MAX_STEP_TEXT = 80


@lru_cache(maxsize=4096)
def script_of(ch: str) -> str:
    """The Unicode script of one letter, from its character name."""
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "UNKNOWN"
    return name.split(" ", 1)[0]


def fold(text: str, *, keep_case: bool = False) -> str:
    """The comparison form of ``text`` (see the module docstring)."""
    s = unicodedata.normalize("NFKC", text or "")
    if not keep_case:
        s = s.casefold()
    s = s.replace("ё", "е").replace("Ё", "Е")
    out: list[str] = []
    base = ""
    for ch in unicodedata.normalize("NFD", s):
        cat = unicodedata.category(ch)
        if cat == "Cf":
            continue  # bidi marks, zero-width joiners, soft hyphens
        if cat[0] == "M":
            # A mark belongs to its letter: an optional accent on a Latin,
            # Greek, Arabic or Hebrew letter is dropped; a Devanagari vowel
            # sign or a Thai tone mark is part of the word and kept.
            if cat != "Mc" and base in _ACCENT_SCRIPTS:
                continue
            out.append(ch)
        elif ch.isalnum():
            if ch.isalpha():
                base = script_of(ch)
            out.append(ch)
        else:
            out.append(" ")  # punctuation, symbols, separators, "_"
    s = unicodedata.normalize("NFC", "".join(out))
    return _SPACE.sub(" ", s).strip()


def _unspaced(term: str) -> bool:
    return any(ch.isalpha() and script_of(ch) in UNSPACED_SCRIPTS for ch in term)


def primary_tag(tag: str) -> str:
    """The lexicon key for a BCP 47 language tag ("de-CH" → "de", "no" → "nb")."""
    p = re.split(r"[-_\s]", (tag or "").strip().lower(), maxsplit=1)[0]
    return LANGUAGE_ALIASES.get(p, p) if p.isalpha() and 2 <= len(p) <= 3 else ""


# ---------------------------------------------------------------------------
# Compiled lexicon
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Matcher:
    """Every term of one class in one language, compiled once."""

    folded: re.Pattern[str] | None
    cased: re.Pattern[str] | None
    exact: frozenset[str]

    def find(self, folded: str, cased: str) -> int:
        """Length of the longest match (0: none)."""
        best = len(folded) if folded in self.exact else 0
        for rx, text in ((self.folded, folded), (self.cased, cased)):
            if rx is None:
                continue
            for m in rx.finditer(text):
                best = max(best, m.end() - m.start())
        return best


#: Folded text holds words and marks separated by single spaces, so a word
#: boundary is the start, the end, or a space (``\w`` would miss marks: a
#: Devanagari vowel sign is not ``\w``, and would end a word early).
_START = r"(?<![^ ])"
_END = r"(?![^ ])"


def _alternative(term: str) -> str:
    """One term as a regex alternative over folded text."""
    prefix = term.endswith("*")
    infix = term.startswith("*") and prefix
    core = term.strip("*")
    esc = re.escape(core)
    if _unspaced(core) or infix:
        return esc + (r"[^ ]*" if infix else "")
    if prefix:
        return _START + esc + r"[^ ]*"
    return _START + esc + _END


def _compile(terms: Iterable[str]) -> _Matcher:
    plain: list[str] = []
    cased: list[str] = []
    exact: set[str] = set()
    for raw in terms:
        t = raw.strip()
        if not t:
            continue
        if t.startswith("!"):
            exact.add(fold(t[1:]))
        elif t.startswith("="):
            cased.append(fold(t[1:], keep_case=True))
        else:
            star_l, star_r = t.startswith("*"), t.endswith("*")
            core = fold(t.strip("*"))
            if core:
                plain.append(("*" if star_l else "") + core + ("*" if star_r else ""))
    plain.sort(key=lambda s: len(s.strip("*")), reverse=True)
    cased.sort(key=len, reverse=True)
    rx = re.compile("|".join(_alternative(t) for t in plain)) if plain else None
    rc = re.compile("|".join(_START + re.escape(t) + _END for t in cased)) if cased else None
    return _Matcher(rx, rc, frozenset(exact))


def _terms(value: str) -> list[str]:
    return [t for t in (value or "").split("|") if t.strip()]


_MATCHERS: dict[tuple[str, str], _Matcher] = {
    (loc, cls): _compile(_terms(value))
    for loc, classes in LEXICON.items()
    for cls, value in classes.items()
}
_CLASSES: frozenset[str] = frozenset(cls for _, cls in _MATCHERS)
_UNION: dict[str, _Matcher] = {
    cls: _compile(t for loc, classes in LEXICON.items() for t in _terms(classes.get(cls, "")))
    for cls in _CLASSES
}

#: Classes whose words count as evidence of a page's language.
_EVIDENCE_CLASSES = frozenset(
    {"next", "back", "review", "submit", "yes", "no", "placeholder", "required", "optional",
     "step"} | {f"field.{t}" for t in FIELD_TYPES}
)


def _exclusive_terms() -> dict[str, frozenset[str]]:
    """Per language: folded evidence terms that no other language lists."""
    owners: dict[str, set[str]] = {}
    for loc, classes in LEXICON.items():
        for cls, value in classes.items():
            if cls not in _EVIDENCE_CLASSES:
                continue
            for t in _terms(value):
                core = fold(t.lstrip("!=").strip("*"))
                if core and len(core) >= 2:
                    owners.setdefault(core, set()).add(loc)
    out: dict[str, set[str]] = {}
    for core, locs in owners.items():
        if len(locs) == 1:
            out.setdefault(next(iter(locs)), set()).add(core)
    return {loc: frozenset(v) for loc, v in out.items()}


_EXCLUSIVE = _exclusive_terms()
_EVIDENCE_MATCHERS = {loc: _compile(sorted(v)) for loc, v in _EXCLUSIVE.items()}


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def says(text: str, cls: str) -> bool:
    """Does ``text`` contain a word of ``cls`` in **any** language?

    For safety classes (``submit``, ``protected`` ...): a match anywhere makes
    AA more careful, whatever language the page claims to be in.
    """
    m = _UNION.get(cls)
    if m is None or not text:
        return False
    return m.find(fold(text), fold(text, keep_case=True)) > 0


def which(text: str, cls: str, locales: Iterable[str] | None = None) -> str | None:
    """The language whose ``cls`` words match ``text`` longest, or None.

    ``locales`` None means every language (safety use); a permissive class
    must pass the page's candidates.
    """
    if not text:
        return None
    folded, cased = fold(text), fold(text, keep_case=True)
    best: tuple[int, str] | None = None
    for loc in (locales if locales is not None else LEXICON):
        m = _MATCHERS.get((loc, cls))
        if m is None:
            continue
        n = m.find(folded, cased)
        if n and (best is None or n > best[0]):
            best = (n, loc)
    return best[1] if best else None


def best_class(text: str, classes: Sequence[str],
               locales: Iterable[str]) -> tuple[str, str] | None:
    """The class (and language) whose word covers the most of ``text``.

    A tie between two different classes is no answer: "Previous step" is
    back, not next, because the longer word wins; a true tie is ambiguous.
    """
    if not text:
        return None
    folded, cased = fold(text), fold(text, keep_case=True)
    locs = list(locales)
    best_len = 0
    winners: set[str] = set()
    where: dict[str, str] = {}
    for cls in classes:
        for loc in locs:
            m = _MATCHERS.get((loc, cls))
            if m is None:
                continue
            n = m.find(folded, cased)
            if not n:
                continue
            if n > best_len:
                best_len, winners = n, {cls}
                where[cls] = loc
            elif n == best_len:
                winners.add(cls)
                where.setdefault(cls, loc)
    if len(winners) != 1:
        return None
    cls = next(iter(winners))
    return cls, where[cls]


def field_type_of(label: str, locales: Iterable[str]) -> tuple[str, str] | None:
    """The canonical field type a label names, in the candidate languages."""
    hit = best_class(label, [f"field.{t}" for t in FIELD_TYPES], locales)
    if hit is None:
        return None
    return hit[0].split(".", 1)[1], hit[1]


@lru_cache(maxsize=1)
def _polar_heads() -> tuple[frozenset[str], frozenset[str]]:
    yes = {fold(t) for c in LEXICON.values() for t in _terms(c.get("yes", ""))}
    no = {fold(t) for c in LEXICON.values() for t in _terms(c.get("no", ""))}
    yes.discard("")
    no.discard("")
    return frozenset(yes), frozenset(no)


def polarity(text: str) -> bool | None:
    """True for a yes-phrase, False for a no-phrase, else None — any language.

    Decided by the leading words, longest first, so "Yes, I am authorized"
    is yes, "No, I will require sponsorship" is no, "Ja, ich habe" is yes
    and "いいえ" is no. A word both lists hold would be refused (a pin keeps
    the lists disjoint), so a match is never a guess between languages.
    """
    words = fold(text).split()
    if not words:
        return None
    yes, no = _polar_heads()
    for size in (4, 3, 2, 1):
        head = " ".join(words[:size])
        in_yes, in_no = head in yes, head in no
        if in_yes and in_no:
            return None
        if in_no:
            return False
        if in_yes:
            return True
    return None


def polar_word(text: str) -> bool | None:
    """True/False when the whole text is exactly a yes or a no word."""
    head = " ".join(fold(text).split())
    if not head:
        return None
    yes, no = _polar_heads()
    if head in yes and head not in no:
        return True
    if head in no and head not in yes:
        return False
    return None


def is_decline(text: str) -> bool:
    """A "prefer not to answer" option, in any language."""
    return says(text, "decline")


@lru_cache(maxsize=1)
def _placeholders() -> frozenset[str]:
    out = set()
    for c in LEXICON.values():
        for t in _terms(c.get("placeholder", "")):
            f = fold(t.lstrip("!"))
            if f:
                out.add(f)
    return frozenset(out)


def is_placeholder(label: str) -> bool:
    """An option that stands for "nothing chosen yet", in any language:
    empty, only punctuation ("--", "..."), or exactly a placeholder phrase."""
    f = fold(label or "")
    return not f or f in _placeholders()


# ---------------------------------------------------------------------------
# Step indicators
# ---------------------------------------------------------------------------


def step_position(texts: Iterable[str],
                  locales: Iterable[str] | None = None) -> tuple[int, int, str] | None:
    """``(step, steps, text)`` from a visible indicator, in any digits.

    A short text with exactly two numbers (any decimal digits: Arabic-Indic
    and full-width ones too), a step word ("Step", "Schritt", "ステップ",
    "단계") and, between the numbers, a slash or a connector word of the
    **same** language as the step word ("of", "von", "из", "共", "중"). The
    same-language pairing is what makes the reading safe in every language
    at once: "Schritt 2 von 4" is an indicator on any page; "Step 2: 4
    questions" is not. The order of the numbers does not matter — Korean
    and Japanese say the total first — because the step can never exceed the
    total: the smaller is the step. ``locales`` narrows the languages tried
    (None: every language).
    """
    locs = list(locales) if locales is not None else list(LEXICON)
    for raw in texts:
        text = unicodedata.normalize("NFKC", raw or "").strip()
        if not text or len(text) > _MAX_STEP_TEXT:
            continue
        nums = list(_DIGITS.finditer(text))
        if len(nums) != 2:
            continue
        try:
            a, b = int(nums[0].group()), int(nums[1].group())
        except ValueError:
            continue
        if not (1 <= a <= _MAX_STEPS and 1 <= b <= _MAX_STEPS):
            continue
        between = text[nums[0].end():nums[1].start()]
        slash = "/" in between
        for loc in locs:
            if which(text, "step", [loc]) is None:
                continue
            if slash or which(between, "step_connector", [loc]) is not None:
                return min(a, b), max(a, b), text
    return None


# ---------------------------------------------------------------------------
# The page's languages
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LanguageContext:
    """Which languages a step is written in, and how AA knows.

    Attributes:
        declared: The ``lang`` the page declares for the form ("" when none).
        primary: Its lexicon key ("de"), or "" when AA has no words for it.
        locales: The candidate languages permissive classes are matched in,
            in priority order: the declared language, then languages by how
            many of their own words the step shows, then those its writing
            system implies, then English. Ordered, never a set: when a word
            belongs to two candidates, the one recorded as having matched
            must not depend on Python's per-run hash order (research data
            must be the same on every run).
        evidence: Per language, how many of its own words the step shows.
        script: The dominant writing system of the step's text.
    """

    declared: str = ""
    primary: str = ""
    locales: tuple[str, ...] = ("en",)
    evidence: tuple[tuple[str, int], ...] = ()
    script: str = ""

    @property
    def observed(self) -> tuple[str, ...]:
        return tuple(loc for loc, n in self.evidence if n >= 2)

    @property
    def covered(self) -> bool:
        """Does AA have words for the language this step is in?"""
        if self.declared:
            return bool(self.primary)
        return bool(self.observed) or self.script in ("LATIN", "")


def _dominant_script(texts: Sequence[str]) -> str:
    counts: Counter[str] = Counter()
    for t in texts:
        for ch in t[:400]:
            if ch.isalpha():
                s = script_of(ch)
                counts["CJK" if s.startswith("CJK") else s] += 1
    return counts.most_common(1)[0][0] if counts else ""


def resolve(declared: str, texts: Iterable[str]) -> LanguageContext:
    """The candidate languages of a step (see the module docstring)."""
    texts = [t for t in texts if t and t.strip()]
    hits: dict[str, set[str]] = {}
    for t in texts:
        folded = fold(t)
        cased = fold(t, keep_case=True)
        for loc, m in _EVIDENCE_MATCHERS.items():
            for rx, text in ((m.folded, folded), (m.cased, cased)):
                if rx is None:
                    continue
                for found in rx.finditer(text):
                    hits.setdefault(loc, set()).add(found.group(0))
            if folded in m.exact:
                hits.setdefault(loc, set()).add(folded)
    evidence = tuple(sorted(((loc, len(v)) for loc, v in hits.items()),
                            key=lambda kv: (-kv[1], kv[0])))
    primary = primary_tag(declared)
    if primary not in LEXICON:
        primary = ""
    script = _dominant_script(texts)
    ordered = [primary] if primary else []
    ordered += [loc for loc, n in evidence if n >= 2]  # evidence is already ranked
    ordered += list(SCRIPT_LANGUAGES.get(script, ()))
    ordered.append("en")
    locales = tuple(dict.fromkeys(loc for loc in ordered if loc in LEXICON))
    return LanguageContext(
        declared=(declared or "").strip(), primary=primary,
        locales=locales,
        evidence=evidence, script=script,
    )


__all__ = [
    "LanguageContext", "UNSPACED_SCRIPTS", "best_class", "field_type_of", "fold",
    "is_decline", "is_placeholder", "polar_word", "polarity", "primary_tag", "resolve", "says",
    "script_of", "step_position", "which",
]


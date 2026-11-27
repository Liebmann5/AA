"""Choosing the option that means an answer. Deterministic, standard library.

A form offers options in its own words ("Yes, I am authorized to work in the
U.S.", "United States of America", "CA - California"); an answer comes in the
profile's words ("yes", "United States", "CA"). Matching is a ladder, the
first rung that decides wins, and every result says which rung decided:

1. ``exact``   — equal after normalisation (case, accents, punctuation).
2. ``alias``   — the two sides belong to the same alias family (US states,
   country names, yes/no wording).
3. ``prefix``  — one side starts the other on a word boundary ("Yes" starts
   "Yes, I am authorized"), only when exactly one option qualifies.
4. ``overlap`` — token containment over content words, at or above a
   threshold, only when the best score beats the runner-up by a margin.

A placeholder ("Select...", "Bitte wählen", "請選擇", "--") is never a
match. A tie is never resolved by order: an ambiguous match returns no
option, and the engine asks the person or leaves the question, because
choosing wrongly is worse than not choosing.

Languages. Yes/no, "prefer not to say" and placeholders are recognised in
every language AA has words for (``form_language``: a word that would mean
yes in one language and no in another is never used). An option's *value*
is read too: a form in any language that lists countries or states by ISO
code (``<option value="DE">Deutschland</option>``) is matched by the code,
without knowing the country's name in that language. The country and state
alias tables below are English and United States centred; a country named
only in another language, with no code, is not matched — the person is
asked (E2E-X1, recorded in ADR-025).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from auto_apply.domain.applications import form_language

_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE = re.compile(r"\s+")
_STOP = frozenset(
    "a an and are as at be by do for from have i in is it of on or s the to we with you your".split()
)


US_STATES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
}

#: Each family is one meaning; any member matches any other member.
COUNTRY_FAMILIES: tuple[frozenset[str], ...] = (
    frozenset({"united states", "united states of america", "usa", "us", "u s",
               "u s a", "america"}),
    frozenset({"united kingdom", "uk", "u k", "great britain", "britain", "england"}),
    frozenset({"canada", "ca"}),
    frozenset({"germany", "deutschland", "de"}),
    frozenset({"france", "fr"}),
    frozenset({"india", "in"}),
    frozenset({"mexico", "méxico", "mx"}),
    frozenset({"australia", "au"}),
    frozenset({"netherlands", "the netherlands", "holland", "nl"}),
    frozenset({"ireland", "ie"}),
    frozenset({"spain", "españa", "es"}),
    frozenset({"brazil", "brasil", "br"}),
)

def is_decline(text: str) -> bool:
    """A "prefer not to answer" phrase, in any of its usual wordings and
    in any language AA has words for."""
    return form_language.is_decline(text)


def pure_polarity(text: str) -> bool | None:
    """True/False when the whole text is a yes or a no word ("Yes", "Nein",
    "はい"), in any language; None for anything longer or neither."""
    return form_language.polar_word(text)


def normalize(text: str) -> str:
    """Case-folded, accent-free, punctuation-free, single-spaced."""
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = _PUNCT.sub(" ", s.casefold())
    return _SPACE.sub(" ", s).strip()


def content_tokens(text: str) -> frozenset[str]:
    return frozenset(t for t in normalize(text).split() if t not in _STOP)


def is_placeholder(label: str) -> bool:
    """An option that stands for "nothing chosen yet", in any language."""
    return form_language.is_placeholder(label)


def _families(text: str) -> list[frozenset[str]]:
    """Alias families a normalised text belongs to (exact member, or a
    leading 'XX ' state code, or a trailing state name)."""
    n = normalize(text)
    out: list[frozenset[str]] = []
    for fam in COUNTRY_FAMILIES:
        if n in fam:
            out.append(fam)
    for code, name in US_STATES.items():
        fam = frozenset({code.lower(), normalize(name)})
        lead = n.split(" ", 1)[0] if n else ""
        if n in fam or (lead == code.lower() and normalize(name) in n) or n == normalize(name):
            out.append(fam)
    return out


def polarity(text: str) -> bool | None:
    """True for a yes-family phrase, False for a no-family phrase, else None.

    Decided by the leading words, so "Yes, I am authorized to work" is yes,
    "No, I will require sponsorship" is no — and "Ja, ich habe", "Non",
    "はい" too (``form_language.polarity``).
    """
    return form_language.polarity(text)


@dataclass(frozen=True)
class OptionMatch:
    index: int
    score: float
    rung: str

    @property
    def found(self) -> bool:
        return self.index >= 0


NO_MATCH = OptionMatch(-1, 0.0, "none")


def match_option(
    desired: str | Sequence[str],
    options: Sequence[str],
    *,
    threshold: float = 0.6,
    margin: float = 0.15,
    values: Sequence[str] | None = None,
) -> OptionMatch:
    """The option meaning ``desired`` (a phrase or several equivalent ones).

    ``values`` are the options' ``value`` attributes, when known: an ISO code
    there identifies a country or state whatever language its label is in.
    Returns ``NO_MATCH`` when nothing qualifies or two options tie.
    """
    wants = [desired] if isinstance(desired, str) else list(desired)
    wants = [w for w in wants if (w or "").strip()]
    if not wants or not options:
        return NO_MATCH
    live = [(i, o) for i, o in enumerate(options) if not is_placeholder(o)]
    if not live:
        return NO_MATCH
    norm = {i: normalize(o) for i, o in live}

    # 1. exact
    for w in wants:
        nw = normalize(w)
        hits = [i for i, _ in live if norm[i] == nw]
        if len(hits) == 1:
            return OptionMatch(hits[0], 1.0, "exact")

    # 2. alias families (country, state) — by label, or by the option's
    # value (an ISO code is the same in every language) — and yes/no polarity
    vals = list(values) if values is not None and len(values) == len(options) else None
    for w in wants:
        fams = set(_families(w))
        if fams:
            hits = [i for i, o in live if fams & set(_families(o))]
            if len(hits) == 1:
                return OptionMatch(hits[0], 0.95, "alias")
            if not hits and vals is not None:
                hits = [i for i, _ in live
                        if (vals[i] or "").strip() and fams & set(_families(vals[i]))]
                if len(hits) == 1:
                    return OptionMatch(hits[0], 0.95, "value")
        if is_decline(w):
            hits = [i for i, o in live if is_decline(o)]
            if len(hits) == 1:
                return OptionMatch(hits[0], 0.95, "alias")
        pol = pure_polarity(w)
        if pol is not None:
            # Only a pure yes/no answer is matched by polarity, so a phrase
            # answer can never pick an option merely because both start "No".
            hits = [i for i, o in live if polarity(o) is pol and not is_decline(o)]
            if len(hits) == 1:
                return OptionMatch(hits[0], 0.95, "alias")

    # 3. word-boundary prefix, either direction
    for w in wants:
        nw = normalize(w)
        if not nw:
            continue
        hits = [i for i, _ in live
                if norm[i].startswith(nw + " ") or nw.startswith(norm[i] + " ")]
        if len(hits) == 1:
            return OptionMatch(hits[0], 0.9, "prefix")

    # 4. content-token overlap (Dice) with a margin over the runner-up
    scores: dict[int, float] = {}
    for w in wants:
        tw = content_tokens(w)
        if not tw:
            continue
        for i, o in live:
            to = content_tokens(o)
            if not to:
                continue
            score = 2.0 * len(tw & to) / (len(tw) + len(to))
            scores[i] = max(scores.get(i, 0.0), score)
    if scores:
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        best_i, best = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        if best >= threshold and best - second >= margin:
            return OptionMatch(best_i, round(best, 4), "overlap")
    return NO_MATCH


def same_value(a: str, b: str) -> bool:
    """Read-back comparison: equal after normalisation, or equal as digits
    when both are mostly digits (an input mask reformatted a phone number)."""
    na, nb = normalize(a), normalize(b)
    if na == nb:
        return True
    da = _ascii_digits(a or "")
    db = _ascii_digits(b or "")
    if len(da) >= 7 and len(db) >= 7:
        return da == db or da.endswith(db) or db.endswith(da)
    return False


def _ascii_digits(text: str) -> str:
    """Every decimal digit of ``text``, in ASCII (Arabic-Indic, Devanagari,
    full-width ... digits read the same as 0-9)."""
    return "".join(str(unicodedata.decimal(ch)) for ch in text if ch.isdecimal())


def shows_choice(display: str, label: str) -> bool:
    """A custom widget shows the chosen option's label somewhere in its text."""
    nd, nl = normalize(display), normalize(label)
    return bool(nl) and (nd == nl or f" {nl} " in f" {nd} ")

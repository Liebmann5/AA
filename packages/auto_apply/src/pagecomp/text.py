"""Text tool (CT-T-003): normalised keys, tokens, script, direction, mojibake.

Language-agnostic by construction (CT-NFR-021): structure never needs a
lexicon. Lexicons elsewhere only add evidence, and every lexicon-dependent
decision says so in its evidence.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"\w+", re.UNICODE)
# Classic UTF-8-read-as-Latin-1/CP1252 sequences.
_MOJIBAKE = re.compile("Ã[\u0080-¿]|â€[\u0080-¿‘-”™]|Â[ -¿]")
_RTL_SCRIPTS = frozenset({"ARABIC", "HEBREW", "SYRIAC", "THAANA", "NKO", "ADLAM"})


def collapse(text: str) -> str:
    """Collapse runs of whitespace (incl. NBSP) to one space and strip."""
    return _WS.sub(" ", text.replace(" ", " ")).strip()


def key(text: str) -> str:
    """Comparison key: NFKC, case-folded, whitespace collapsed."""
    return collapse(unicodedata.normalize("NFKC", text).casefold())


def tokens(text: str) -> list[str]:
    """Word tokens of the comparison key, in order (``\\w+``, any script)."""
    return _TOKEN.findall(key(text))


def token_set(text: str, min_len: int = 1) -> frozenset[str]:
    return frozenset(t for t in tokens(text) if len(t) >= min_len)


def _script_of(ch: str) -> str:
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "UNKNOWN"
    return name.split(" ", 1)[0]


@dataclass(frozen=True)
class TextFacts:
    script: str           # dominant script among letters ("LATIN", "ARABIC", ...)
    direction: str        # "ltr" | "rtl"
    mojibake: bool        # looks like UTF-8 decoded with the wrong codec
    letters: int


def facts(text: str, sample: int = 4000) -> TextFacts:
    """Script, direction and mojibake flag from a bounded sample."""
    counts: Counter[str] = Counter()
    letters = 0
    for ch in text[:sample]:
        if ch.isalpha():
            letters += 1
            counts[_script_of(ch)] += 1
    script = counts.most_common(1)[0][0] if counts else "UNKNOWN"
    direction = "rtl" if script in _RTL_SCRIPTS else "ltr"
    return TextFacts(script, direction, bool(_MOJIBAKE.search(text[:sample])), letters)


def overlap(a: str, b: str, min_len: int = 4) -> float:
    """Share of ``a``'s meaningful tokens present in ``b`` (0..1)."""
    ta = token_set(a, min_len)
    if not ta:
        return 0.0
    return len(ta & token_set(b, min_len)) / len(ta)

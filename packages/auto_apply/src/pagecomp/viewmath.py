"""View equivalence (CT-ALG-028, 06 s14) and view selection (CT-ALG-029, 06 s15).

Pure, deterministic. A *view reading* is a mapping ``field -> value`` built
from a page (CT-T-009/017), a feed item, a sitemap entry or an API payload.

**Equivalence.** Per field, normalised comparison: text by key, locations
as place tuples, pay as intervals (overlap agrees), dates as calendar days
(|Δ| <= 1 agrees), apply targets by canonical URL, descriptions by token
Jaccard >= 0.8. *Equivalent*: identity agrees (title, and company or apply
target) and no present field disagrees. *Compatible*: identity agrees,
some fields differ (reported field by field, never averaged). *Distinct*:
otherwise.

**Selection.** Among verified (equivalent or compatible) public views that
carry the needed fields, the lexicographic minimum of
``(footprint, requests, kind order)``; if none carries them all, a greedy
cover in the same order.
"""

from __future__ import annotations

import datetime as _dt
import math
import random
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

from pagecomp.links import canonical_url
from pagecomp.text import key, token_set

EQUIVALENT, COMPATIBLE, DISTINCT = "equivalent", "compatible", "distinct"
KIND_ORDER = ("api", "feed", "jsonld", "page_guest", "page", "print", "amp", "mobile", "embedded",
              "own_url", "mirror", "lang")
_MONEY = re.compile(r"(\d[\d,.]*)\s*(k)?", re.I)


def _days(v: str) -> int | None:
    v = v.strip()
    if not v:
        return None
    try:
        d = _dt.date.fromisoformat(v[:10])
        return d.toordinal()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(v).date().toordinal()
    except (TypeError, ValueError, IndexError):
        return None


def _interval(v: str) -> tuple[float, float] | None:
    nums = []
    for m in _MONEY.finditer(v.replace("–", "-")):
        try:
            x = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if m.group(2):
            x *= 1000
        nums.append(x)
    if not nums:
        return None
    return (min(nums), max(nums))


def _place(v: str) -> tuple[str, ...]:
    return tuple(t for t in (key(x) for x in re.split(r"[,/|;]", v)) if t)


def field_agrees(field: str, a: str, b: str) -> bool | None:
    """True / False, or None when either side lacks the field."""
    if not a or not b:
        return None
    if field in ("title", "company"):
        return key(a) == key(b) or (len(token_set(a, 2) & token_set(b, 2)) /
                                    max(1, len(token_set(a, 2) | token_set(b, 2)))) >= 0.8
    if field == "location":
        pa, pb = _place(a), _place(b)
        return bool(pa) and bool(pb) and (pa[0] == pb[0] or set(pa) <= set(pb) or set(pb) <= set(pa))
    if field == "pay":
        ia, ib = _interval(a), _interval(b)
        if ia is None or ib is None:
            return key(a) == key(b)
        return ia[0] <= ib[1] and ib[0] <= ia[1]
    if field in ("date_posted", "valid_through"):
        da, db = _days(a), _days(b)
        if da is None or db is None:
            return key(a) == key(b)
        return abs(da - db) <= 1
    if field == "apply_target":
        return canonical_url(a) == canonical_url(b)
    if field == "description":
        ta, tb = token_set(a, 3), token_set(b, 3)
        return bool(ta | tb) and len(ta & tb) / len(ta | tb) >= 0.8
    return key(a) == key(b)


@dataclass(frozen=True)
class Equivalence:
    kind: str
    agree: tuple[str, ...]
    disagree: tuple[str, ...]


def compare_views(a: Mapping[str, str], b: Mapping[str, str]) -> Equivalence:
    agree, disagree = [], []
    for f in sorted(set(a) | set(b)):
        r = field_agrees(f, a.get(f, ""), b.get(f, ""))
        if r is True:
            agree.append(f)
        elif r is False:
            disagree.append(f)
    identity = "title" in agree and ("company" in agree or "apply_target" in agree)
    if identity and not disagree:
        kind = EQUIVALENT
    elif identity:
        kind = COMPATIBLE
    else:
        kind = DISTINCT
    return Equivalence(kind, tuple(agree), tuple(disagree))


def merge_fields(readings: Sequence[tuple[Mapping[str, str], Mapping[str, float]]]) -> dict[str, tuple[str, tuple[str, ...]]]:
    """Per field, the value from the view with the higher field confidence,
    plus the other values that disagree (kept, never averaged)."""
    out: dict[str, tuple[str, tuple[str, ...]]] = {}
    fields = sorted({f for r, _ in readings for f in r})
    for f in fields:
        cands = [(conf.get(f, 0.5), k, r[f]) for k, (r, conf) in enumerate(readings) if r.get(f)]
        if not cands:
            continue
        cands.sort(key=lambda c: (-c[0], c[1]))
        best = cands[0][2]
        others = tuple(v for _, _, v in cands[1:] if field_agrees(f, best, v) is False)
        out[f] = (best, others)
    return out


@dataclass(frozen=True)
class Candidate:
    kind: str
    locator: str
    access: str
    footprint: int
    requests: int
    fields: frozenset[str]
    verified: str      # equivalent | compatible | distinct | unverified


def choose_views(cands: Iterable[Candidate], needed: Iterable[str]) -> tuple[Candidate, ...]:
    """ALG-029: cheapest verified public view(s) covering ``needed``."""
    need = set(needed)
    ok = [c for c in cands if c.access == "public" and c.verified in (EQUIVALENT, COMPATIBLE)]

    def order(c: Candidate) -> tuple[int, int, int, str]:
        rank = KIND_ORDER.index(c.kind) if c.kind in KIND_ORDER else len(KIND_ORDER)
        return (c.footprint, c.requests, rank, c.locator)

    full = sorted((c for c in ok if need <= c.fields), key=order)
    if full:
        return (full[0],)
    chosen: list[Candidate] = []
    left = set(need)
    pool = sorted(ok, key=order)
    while left:
        best = max(pool, key=lambda c: (len(left & c.fields), [-x for x in order(c)[:3]]), default=None)
        if best is None or not (left & best.fields):
            break
        chosen.append(best)
        left -= best.fields
        pool.remove(best)
    return tuple(chosen)


def sample_for_reverification(record_keys: Sequence[str], seed: int) -> list[str]:
    """``max(3, ceil(0.05·n))`` records, seeded (06 s14)."""
    n = len(record_keys)
    k = min(n, max(3, math.ceil(0.05 * n)))
    rng = random.Random(seed)
    return sorted(rng.sample(list(record_keys), k))

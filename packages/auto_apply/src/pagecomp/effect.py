"""Filter effect verification and URL-parameter learning (CT-ALG-027, 06 s13).

Pure functions over two observations' readings. The engine operates a
control (never the toolkit), settles, re-observes, then asks here whether
the control did what it claims. Only ``APPLIED`` lets the engine count the
search piece as applied (ADR-021); the other outcomes are recorded and the
channel is benched for the session after the same outcome on two queries.

Decision order (06 s13):

1. after-set empty and the page says "no results" → ``APPLIED`` (empty=true);
2. ``J = 1``, same count, same query string → ``NO_EFFECT``;
3. ``J = 1`` but URL or count moved → ``NO_EFFECT`` with evidence
   (CT-PH-226: the URL moved, the results did not);
4. ``J < 1`` → ``APPLIED``; ``CONTRADICTED`` when records that carry the
   filtered field contradict the chosen value, ``APPLIED+consistent`` when
   they all satisfy it;
5. ``count_mismatch`` evidence when counts and records disagree (CT-PH-228).

``UNKNOWN`` when either side is truncated, blocked, or has no record
identities. ``RESET`` is decided on the next page by ``reset_check``.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pagecomp import links as L

APPLIED, NO_EFFECT, RESET, CONTRADICTED, UNKNOWN = "APPLIED", "NO_EFFECT", "RESET", "CONTRADICTED", "UNKNOWN"

#: Query keys that carry tracking or session state, never a filter.
TRACKING_KEYS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid",
    "msclkid", "ref", "refid", "trk", "trackingid", "sid", "session", "sessionid", "ved", "ei",
    "sa", "usg", "oq", "aqs", "sourceid", "ie", "vssid", "currentjobid", "origin", "_",
    "ts", "t", "cb", "rnd", "nonce", "fp", "vjk", "from", "tk",
})
_COUNTS = (
    re.compile(r"\bof\s+(?:about\s+)?(\d[\d,.]*)", re.I),
    re.compile(r"(\d[\d,.]*)\+?\s*(?:jobs|results|positions|openings|matches)\b", re.I),
    re.compile(r"\btotal[:\s]+(\d[\d,.]*)", re.I),
)
_NO_RESULTS = re.compile(r"\bno (?:jobs|results|matches|positions) (?:found|match)|\b0 (?:jobs|results)\b|"
                         r"did not match any|no matching jobs|we couldn't find", re.I)


def record_identity(rec: object) -> str | None:
    """A record's identity: canonical URL of its link, else None."""
    link = getattr(rec, "link", None)
    if link is None:
        return None
    if link.kind == L.OPAQUE:
        # Opaque tokens change per load; the shown host+path is the identity.
        return f"opaque:{link.expected_host}/{link.expected_path}" if link.expected_host else None
    return link.canonical or None


def record_set(records: Iterable[object]) -> frozenset[str]:
    return frozenset(x for x in (record_identity(r) for r in records) if x)


def total_count(text: str) -> int | None:
    """The page's stated total ("1,234 jobs", "Showing 1-25 of 300")."""
    head = text[:20_000]
    for rx in _COUNTS:
        m = rx.search(head)
        if m:
            raw = m.group(1).replace(",", "").replace(".", "")
            if raw.isdigit():
                return int(raw)
    return None


def says_empty(text: str) -> bool:
    return bool(_NO_RESULTS.search(text[:20_000]))


def query_delta(url_b: str, url_a: str) -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    """Keys whose values differ between two URLs: ``{key: (before, after)}``."""
    def qs(u: str) -> dict[str, tuple[str, ...]]:
        try:
            pairs = urllib.parse.parse_qsl(urllib.parse.urlsplit(u).query, keep_blank_values=True)
        except ValueError:
            return {}
        out: dict[str, list[str]] = {}
        for k, v in pairs:
            out.setdefault(k, []).append(v)
        return {k: tuple(sorted(v)) for k, v in out.items()}
    b, a = qs(url_b), qs(url_a)
    return {k: (b.get(k, ()), a.get(k, ())) for k in sorted(set(a) | set(b)) if b.get(k) != a.get(k)}


@dataclass(frozen=True)
class EffectResult:
    outcome: str
    jaccard: float
    consistent: bool | None
    empty: bool
    evidence: tuple[str, ...]
    delta: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]
    candidate: tuple[str, str] | None     # (key, value) parameter candidate


def effect_check(before: frozenset[str], after: frozenset[str], *, url_b: str, url_a: str,
                 count_b: int | None = None, count_a: int | None = None,
                 after_empty_state: bool = False, satisfied: int = 0, contradicted: int = 0,
                 truncated: bool = False, blocked: bool = False,
                 page_size: int | None = None) -> EffectResult:
    """ALG-027 decision. ``satisfied``/``contradicted`` count after-records
    that carry the filtered field and do / do not match the chosen value."""
    delta = query_delta(url_b, url_a)
    dtuple = tuple((k, b, a) for k, (b, a) in delta.items())
    ev: list[str] = []
    if truncated or blocked:
        return EffectResult(UNKNOWN, 0.0, None, False, ("truncated" if truncated else "blocked",), dtuple, None)
    if not after and after_empty_state:
        return EffectResult(APPLIED, 0.0, None, True, ("empty-results-state",), dtuple,
                            _candidate(delta))
    if not before and not after:
        return EffectResult(UNKNOWN, 1.0, None, False, ("no-record-identities",), dtuple, None)
    union = before | after
    j = len(before & after) / len(union) if union else 1.0
    if count_a is not None and page_size and len(after) > count_a and len(after) <= page_size:
        ev.append("count_mismatch")
    if j == 1.0:
        if delta:
            ev.append("url_changed")
        if count_a is not None and count_b is not None and count_a != count_b:
            ev.append("count_changed")
        return EffectResult(NO_EFFECT, 1.0, None, False, tuple(ev), dtuple, None)
    if contradicted:
        ev.append(f"{contradicted} records contradict the chosen value")
        return EffectResult(CONTRADICTED, round(j, 6), False, False, tuple(ev), dtuple, None)
    consistent = True if satisfied and not contradicted else None
    if count_a is not None and count_b is not None and count_a > count_b and "count_mismatch" not in ev:
        ev.append("count grew after a narrowing filter")
    return EffectResult(APPLIED, round(j, 6), consistent, False, tuple(ev), dtuple, _candidate(delta))


def _candidate(delta: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]]) -> tuple[str, str] | None:
    """Step 4: one changed key (tracking keys dropped first) → ``(key, value)``."""
    keys = [k for k in delta if k.lower() not in TRACKING_KEYS]
    if len(keys) != 1:
        return None
    k = keys[0]
    before, after = delta[k]
    new = [v for v in after if v not in before]
    if len(new) != 1:
        return None
    return (k, new[0])


def confirm_candidate(expected_after: frozenset[str], direct: frozenset[str], threshold: float = 0.9) -> bool:
    """Navigating straight to the learned URL must reproduce the result set
    (``J >= 0.9``: pagination and ads perturb a little)."""
    union = expected_after | direct
    if not union:
        return False
    return len(expected_after & direct) / len(union) >= threshold


@dataclass
class ParameterLearner:
    """Two independent confirmations on different queries promote a
    ``(host, piece, option) → (key, value)`` candidate to the catalog with
    provenance ``learned`` (06 s13). State is plain data: the caller
    persists it (the catalog lives in AA, ADR-019)."""

    confirmations: dict[tuple[str, str, str, str, str], set[str]]

    def __init__(self) -> None:
        self.confirmations = {}

    def confirm(self, host: str, piece: str, option: str, cand: tuple[str, str], query: str) -> bool:
        k = (host, piece, option, cand[0], cand[1])
        self.confirmations.setdefault(k, set()).add(query.strip().casefold())
        return len(self.confirmations[k]) >= 2

    def learned(self) -> list[tuple[str, str, str, str, str]]:
        return sorted(k for k, qs in self.confirmations.items() if len(qs) >= 2)


def reset_check(current_after_advance: tuple[str, ...], default: tuple[str, ...],
                applied: tuple[str, ...]) -> str:
    """After ``advance_page``: a control back at its default (and not at the
    applied value) means the filter was lost on pagination (CT-PH-227)."""
    if current_after_advance == default and current_after_advance != applied:
        return RESET
    return APPLIED

"""Record linkage: which records, across pages and engines, are one posting.

Built to resolve Google's opaque ``/goto`` links without a visit, and it does
four jobs with one piece of mathematics:

1. **Resolve** an opaque record to a direct URL that another page (another
   engine, a board, the ATS) already showed.
2. **De-duplicate** across engines and URL variants (``/p/x`` and
   ``/p/x/apply``), so AA never vets or applies to one posting twice.
3. **Check arrival** after a visit with the posting's *identifier*, not
   only its host: a redirect to another posting on the same host now fails.
4. **Tell reposts apart**: same title and company, different identifier →
   different postings.

Model (Fellegi and Sunter 1969, with likelihoods derived rather than fitted).
For records ``a``, ``b`` let ``M`` = "same posting", ``U`` = "different".
The evidence is compared field by field, and the log-likelihood ratio adds:

    W = Σ_i log2( P(agree_i | M) / P(agree_i | U) )      [bits]

* **Blocking:** only pairs on the same host are compared (``same_host``). A posting has one
  host; different hosts cannot be the same posting record.
* **Identifier fields:** an id-like token (``links.has_identifier``) that
  appears on both sides. Under ``M`` it agrees with probability ≈ 1 (the
  breadcrumb or URL shows the posting's own id). Under ``U`` it agrees only
  by chance: ≤ 2^-H for a token of entropy ``H``. Entropy is bounded from the
  token's alphabet (hex 4, digits log2 10, other alphanumerics log2 36 bits
  per character), less ``id_entropy_discount`` bits for non-uniform ids
  (sequences, dates). A token visibly cut by the page (``...``) counts only
  its shown characters. An identifier on both sides that **differs** is
  strong evidence for ``U``: ``-mismatch_bits``.
* **Title:** token Jaccard ≥ 0.8 adds ``title_bits_high``, ≥ 0.5 adds
  ``title_bits_low``, < 0.2 subtracts ``title_bits_high``. Titles repeat
  within a company, so title evidence alone never reaches the threshold
  in a block with more than one candidate.

**Threshold from a union bound, not a tuned constant.** Comparing ``n``
pairs, the expected number of false links is at most ``n · 2^-W_min``.
Requiring it to stay ≤ ε gives ``W_min = log2(n) + log2(1/ε)``. So the bar
rises with the number of comparisons and nobody tunes it: ε (default 10^-3)
is the only knob, and it is a risk level, not a score. A record is linked
only when exactly one candidate clears the bar; two clearing it is an
ambiguity, and the record stays opaque.

Pure, deterministic, standard library only. ``O(Σ block sizes)``.
"""

from __future__ import annotations

import math
import re
import urllib.parse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pagecomp import links as L
from pagecomp.text import token_set

_TRUNC = ("...", "…")
_PARTS = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True)
class LinkageParams:
    epsilon: float = 1e-3
    id_entropy_discount: float = 8.0
    mismatch_bits: float = 30.0
    title_bits_high: float = 6.0
    title_bits_low: float = 3.0
    min_id_chars: int = 6


@dataclass(frozen=True)
class RecordKey:
    """What a record shows about its destination."""

    host: str
    ids: tuple[tuple[str, bool], ...]   # (token, complete?) id-like tokens in shown order
    title: frozenset[str]
    url: str                            # direct destination if known, else ""
    ref: object = None                  # caller's handle (a RecordReading, an index...)


def _tokens(path: str) -> list[tuple[str, bool]]:
    """Id-like tokens of a displayed or real path, flagging a cut last token."""
    text = path.strip()
    cut = text.endswith(_TRUNC)
    for t in _TRUNC:
        text = text.replace(t, "")
    toks = _PARTS.findall(text)
    out = []
    for k, tok in enumerate(toks):
        complete = not (cut and k == len(toks) - 1)
        if L.has_identifier(tok):
            out.append((tok.lower(), complete))
    return out


def key_from_url(url: str, title: str = "", ref: object = None) -> RecordKey:
    parts = urllib.parse.urlsplit(url)
    return RecordKey((parts.hostname or "").lower(), tuple(_tokens(parts.path + " " + parts.query)),
                     token_set(title, 2), url, ref)


def key_from_breadcrumb(host: str, tail: str, title: str = "", ref: object = None) -> RecordKey:
    return RecordKey(host.lower(), tuple(_tokens(tail)), token_set(title, 2), "", ref)


def key_from_record(rec: object) -> RecordKey | None:
    """Key for a ``listing.RecordReading`` (direct, unwrapped or opaque)."""
    link = getattr(rec, "link", None)
    title = getattr(rec, "title", "")
    if link is None:
        return None
    if link.kind == L.OPAQUE:
        if not link.expected_host:
            return None
        return key_from_breadcrumb(link.expected_host, link.expected_path, title, rec)
    return key_from_url(link.url, title, rec)


def same_host(a: str, b: str) -> bool:
    """Blocking rule: the same host (``www.`` ignored), or one a subdomain of
    the other. Deliberately *not* "same site": on a multi-tenant ATS
    (``zact-inc.breezy.hr`` vs ``onedome.breezy.hr``) the subdomain is the
    company, and two companies' postings are never compared."""
    a, b = a.lower().removeprefix("www."), b.lower().removeprefix("www.")
    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def token_entropy(tok: str, shown: int | None = None, discount: float = 8.0) -> float:
    """Upper bound on the bits an id token carries (alphabet × length − discount)."""
    n = len(tok) if shown is None else shown
    if all(c in "0123456789abcdef" for c in tok):
        per = 3.3219 if tok.isdigit() else 4.0
    else:
        per = math.log2(36)
    return max(0.0, per * n - discount)


@dataclass(frozen=True)
class Comparison:
    bits: float
    reasons: tuple[str, ...]


def compare(a: RecordKey, b: RecordKey, p: LinkageParams = LinkageParams()) -> Comparison | None:
    """Log2 likelihood ratio that ``a`` and ``b`` are one posting; ``None`` if not comparable."""
    if not same_host(a.host, b.host):
        return None
    bits = 0.0
    reasons: list[str] = []
    a_ids = [(t, c) for t, c in a.ids if len(t) >= p.min_id_chars or t.isdigit()]
    b_ids = [(t, c) for t, c in b.ids if len(t) >= p.min_id_chars or t.isdigit()]
    agreed = False
    for ta, ca in a_ids:
        for tb, cb in b_ids:
            if ca and cb and ta == tb:
                h = token_entropy(ta, discount=p.id_entropy_discount)
            elif not ca and tb.startswith(ta):
                h = token_entropy(tb, shown=len(ta), discount=p.id_entropy_discount)
            elif not cb and ta.startswith(tb):
                h = token_entropy(ta, shown=len(tb), discount=p.id_entropy_discount)
            else:
                continue
            if h > 0:
                bits += h
                reasons.append(f"id agrees ({h:.0f} bits)")
                agreed = True
            break
        if agreed:
            break
    if not agreed:
        full_a = [t for t, c in a_ids if c]
        full_b = [t for t, c in b_ids if c]
        if full_a and full_b:
            bits -= p.mismatch_bits
            reasons.append("ids differ")
    if a.title and b.title:
        j = len(a.title & b.title) / len(a.title | b.title)
        if j >= 0.8:
            bits += p.title_bits_high
            reasons.append(f"title J={j:.2f}")
        elif j >= 0.5:
            bits += p.title_bits_low
            reasons.append(f"title J={j:.2f}")
        elif j < 0.2:
            bits -= p.title_bits_high
            reasons.append(f"title J={j:.2f}")
    return Comparison(round(bits, 3), tuple(reasons))


@dataclass(frozen=True)
class Link:
    left: RecordKey
    right: RecordKey
    bits: float
    threshold: float
    reasons: tuple[str, ...]


def threshold(pairs: int, epsilon: float) -> float:
    """``W_min = log2(n) + log2(1/ε)``: expected false links ≤ ε over ``n`` comparisons."""
    return math.log2(max(1, pairs)) + math.log2(1.0 / epsilon)


def link(left: Sequence[RecordKey], right: Sequence[RecordKey],
         p: LinkageParams = LinkageParams()) -> tuple[list[Link], list[RecordKey]]:
    """Link each ``left`` key to at most one ``right`` key.

    Returns the links and the left keys left unresolved (no candidate, below
    the bar, or ambiguous). ``n`` in the bar is the total number of compared
    pairs, so the guarantee holds for the whole call.
    """
    blocks: dict[str, list[RecordKey]] = {}
    for r in right:
        blocks.setdefault(r.host, []).append(r)
    scored: list[tuple[RecordKey, list[tuple[float, RecordKey, tuple[str, ...]]]]] = []
    pairs = 0
    for a in left:
        cands = []
        for host, rs in blocks.items():
            if not same_host(a.host, host):
                continue
            for b in rs:
                c = compare(a, b, p)
                if c is None:
                    continue
                pairs += 1
                cands.append((c.bits, b, c.reasons))
        scored.append((a, cands))
    bar = threshold(pairs, p.epsilon)
    links_out: list[Link] = []
    unresolved: list[RecordKey] = []
    for a, cands in scored:
        over = [c for c in cands if c[0] >= bar]
        # Several right-side records can be the same posting (an /apply
        # variant): they are one destination if their identifiers agree.
        distinct = {tuple(t for t, _ in c[1].ids) or (c[1].url,) for c in over}
        if over and len(distinct) == 1:
            best = max(over, key=lambda c: (c[0], -len(c[1].url)))
            links_out.append(Link(a, best[1], best[0], round(bar, 3), best[2]))
        else:
            unresolved.append(a)
    return links_out, unresolved


def arrival_bits(expected: RecordKey, landed_url: str, p: LinkageParams = LinkageParams()) -> float | None:
    """Evidence (bits) that a visit landed on the expected posting.

    Stronger than ``links.arrival_integrity`` (host only): when the record
    showed an identifier, the landed URL must carry it. ``None`` when the
    record showed nothing comparable.
    """
    c = compare(expected, key_from_url(landed_url), LinkageParams(
        epsilon=p.epsilon, id_entropy_discount=p.id_entropy_discount, mismatch_bits=p.mismatch_bits,
        title_bits_high=0.0, title_bits_low=0.0, min_id_chars=p.min_id_chars))
    if c is None:
        return -math.inf
    if not expected.ids:
        return None
    return c.bits


def dedupe(keys: Iterable[RecordKey], p: LinkageParams = LinkageParams()) -> list[list[RecordKey]]:
    """Group keys that are one posting (identifier agreement past the bar)."""
    ks = list(keys)
    parent = list(range(len(ks)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pairs = [(i, j) for i in range(len(ks)) for j in range(i + 1, len(ks))
             if same_host(ks[i].host, ks[j].host)]
    bar = threshold(len(pairs), p.epsilon)
    for i, j in pairs:
        c = compare(ks[i], ks[j], p)
        if c is not None and c.bits >= bar:
            parent[find(i)] = find(j)
    groups: dict[int, list[RecordKey]] = {}
    for i in range(len(ks)):
        groups.setdefault(find(i), []).append(ks[i])
    return list(groups.values())

"""Records (CT-T-008): CT-ALG-001 skeletons, 002 sibling runs, 003 ranking.

**ALG-001.** The skeleton multiset ``M(v)`` holds, for every element ``u``
in ``v``'s subtree down to ``D`` levels, the label ``(tag path v..u,
has_href(u), has_own_text(u))``. Classes and attributes are not in it, so a
promoted card with one extra class is the same skeleton; one extra badge
changes a few labels, and Lemma 2 bounds the damage:
``J >= (s-d)/s``. Similarity is weighted Jaccard (Ruzicka), computed as
``smin / (|A| + |B| - smin)`` by iterating the smaller multiset.

**ALG-002.** For each parent with ``k >= 2`` element children (capped at
``S``), windows of ``m = 1..K`` adjacent children at every offset form
generalised nodes; a run is a maximal stretch of ``>= r_min`` of them with
adjacent similarity ``>= tau`` whose members each stay within ``tau_c``
of the run's consensus (element-wise median), which stops single-linkage
drift. A run that fails consensus is split at the failing members.
Cost (corrected from the blueprint's ``O(n·D·K)``): skeletons are
``O(n·D)``; windows at offset ``s`` of width ``m`` re-sum ``m`` child
multisets each, and there are ``m`` offsets per width, so the window work
is ``O(n·D·K^2)`` in the worst case (constant: K=4 gives at most 1+4+9+16
= 30 passes over each parent's labels).

**ALG-003.** Every run is scored log-linearly on documented features and
**all runs are returned ranked** (defect 8). The blueprint's record-root
lift does not apply here: members of a sibling run share their parent, so
any lift ``l >= 1`` collapses them (Lemma 3 makes ``l = 0`` the only
non-collapsed level). The lift's third criterion (a title candidate and a
primary anchor in >= 80% of members) is kept as the ``carries`` feature.

Overlapping runs under one parent are suppressed smallest-width-first, so a
uniform list is read with ``m = 1`` and a two-row-per-record table with
``m = 2``.
"""

from __future__ import annotations

import math
from array import array
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pagecomp.doc import ELEMENT, FRAME, SHADOW, TEXT, Doc
from pagecomp.params import ParamSpec
from pagecomp.registry import ToolSpec
from pagecomp.results import Abstain, Evidence, Ok

_SKIP = frozenset({"script", "style", "template", "noscript", "svg", "path", "meta", "link"})
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_CHROME_TAGS = frozenset({"nav", "header", "footer", "aside"})
_CHROME_ROLES = frozenset({"navigation", "banner", "contentinfo", "complementary", "menu", "menubar", "tablist"})
_ID_SKIP = frozenset({"class", "style", "role", "tabindex", "lang", "dir", "hidden", "jsaction", "jscontroller"})

Multiset = dict


def signature_similarity(a: "Run", b: "Run") -> float:
    """Ruzicka similarity of two runs' consensus skeletons (same label space
    only within one ``Records`` result: path ids are interned per analysis)."""
    da, db = dict(a.signature), dict(b.signature)
    return ruzicka(da, db, sum(da.values()), sum(db.values()))


def ruzicka(a: Mapping[int, int], b: Mapping[int, int], sa: int, sb: int) -> float:
    if sa == 0 and sb == 0:
        return 1.0
    if len(a) > len(b):
        a, b = b, a
    smin = 0
    for k, v in a.items():
        w = b.get(k)
        if w:
            smin += v if v < w else w
    return smin / (sa + sb - smin)


@dataclass(frozen=True)
class Run:
    parent: int
    width: int                          # m: children per record
    members: tuple[tuple[int, ...], ...]  # each record = m adjacent children
    score: float
    features: tuple[tuple[str, float], ...]
    signature: tuple[tuple[int, int], ...] = ()   # consensus skeleton (label, count), sorted
    gaps: tuple[int, ...] = ()                    # foreign children bridged over (ads)

    @property
    def roots(self) -> tuple[int, ...]:
        return tuple(m[0] for m in self.members)

    def feature(self, name: str) -> float:
        return dict(self.features).get(name, 0.0)


@dataclass(frozen=True)
class Records:
    runs: tuple[Run, ...]     # ranked, best first
    parents_scanned: int
    sibling_cap_hits: int


class _Facts:
    """Per-node prefix sums and flags computed once per document (O(n))."""

    def __init__(self, doc: Doc, vis: Any) -> None:
        n = len(doc)
        self.has_text = array("B", bytes(n))
        self.has_href = array("B", bytes(n))
        text_pref = array("i", [0]) * (n + 1)
        a_pref = array("i", [0]) * (n + 1)
        h_pref = array("i", [0]) * (n + 1)
        acc_t = acc_a = acc_h = 0
        for i in range(n):
            k = doc.kind[i]
            if k == TEXT:
                p = doc.parent[i]
                t = doc.own_text(i)
                if t.strip() and not (vis and vis.reason[i]) and doc.tag_name(p) not in _SKIP:
                    self.has_text[p] = 1
                    acc_t += len(t.strip())
            elif k == ELEMENT:
                tag = doc.tag_name(i)
                href = doc.attr(i, "href")
                if href is not None or doc.has_attr(i, "data-href"):
                    self.has_href[i] = 1
                    h = (href or "").strip().lower()
                    if not h.startswith(("#", "javascript:")) or doc.has_attr(i, "data-href"):
                        acc_a += 1
                if tag in _HEADINGS or doc.attr(i, "role") == "heading":
                    acc_h += 1
            text_pref[i + 1] = acc_t
            a_pref[i + 1] = acc_a
            h_pref[i + 1] = acc_h
        self.text_pref, self.a_pref, self.h_pref = text_pref, a_pref, h_pref
        self.total_text = acc_t

    def span(self, pref: array, nodes: tuple[int, ...], doc: Doc) -> int:
        return sum(pref[doc.end[x]] - pref[x] for x in nodes)


def skeleton(doc: Doc, v: int, depth_limit: int, facts: _Facts,
             intern: dict[tuple[int, ...], int]) -> tuple[dict[int, int], int]:
    """``M(v)`` as ``{label: count}`` and its total size. O(|T_D(v)|)."""
    ms: dict[int, int] = {}
    size = 0
    base = doc.depth[v]
    paths: dict[int, tuple[int, ...]] = {}
    j, stop = v, doc.end[v]
    while j < stop:
        k = doc.kind[j]
        if k not in (ELEMENT, SHADOW, FRAME):
            j += 1
            continue
        tag = doc.tag[j]
        if doc.strings[tag] in _SKIP or doc.depth[j] - base >= depth_limit:
            j = doc.end[j]
            continue
        parent_path = paths.get(doc.parent[j], ()) if j != v else ()
        path = parent_path + (tag,)
        paths[j] = path
        pid = intern.get(path)
        if pid is None:
            pid = len(intern)
            intern[path] = pid
        label = (pid << 2) | (facts.has_href[j] << 1) | facts.has_text[j]
        ms[label] = ms.get(label, 0) + 1
        size += 1
        j += 1
    return ms, size


def _merge(parts: list[dict[int, int]]) -> dict[int, int]:
    if len(parts) == 1:
        return parts[0]
    out: dict[int, int] = {}
    for p in parts:
        for k, v in p.items():
            out[k] = out.get(k, 0) + v
    return out


def _consensus(ms: list[dict[int, int]]) -> tuple[dict[int, int], int]:
    keys: set[int] = set()
    for m in ms:
        keys.update(m)
    out: dict[int, int] = {}
    n = len(ms)
    for k in keys:
        vals = sorted(m.get(k, 0) for m in ms)
        med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) // 2
        if med:
            out[k] = med
    return out, sum(out.values())


def _runs_for_parent(groups: list[tuple[int, ...]], gms: list[dict[int, int]], sizes: list[int],
                     p: Mapping[str, Any], tick: Any) -> list[tuple[list[int], float, float, dict[int, int]]]:
    """Runs over generalised nodes: ``(member group indexes, cohesion, min
    consensus similarity, consensus multiset)``.

    Gap bridging (``max_gaps``, default 1; 06 s1 ``allow_gap``): two runs
    separated by exactly one foreign group (an ad, a "promoted" banner, a
    newsletter box between cards) are one run when their consensus
    skeletons are within ``tau`` of each other. The foreign group is not a
    member; it is reported in ``Run.gaps``. A bridge never spans two
    foreign groups, so two lists separated by a heading stay two lists.
    """
    tau, tau_c, r_min = float(p["tau"]), float(p["tau_consensus"]), int(p["r_min"])
    max_gaps = int(p["max_gaps"])
    n = len(groups)
    sims = []
    for j in range(n - 1):
        tick(len(gms[j]) + 1)
        sims.append(ruzicka(gms[j], gms[j + 1], sizes[j], sizes[j + 1]))
    found: list[tuple[list[int], float, float, dict[int, int], int]] = []
    work: list[tuple[int, int]] = []
    j = 0
    while j < n - 1:
        if sims[j] >= tau:
            s = j
            while j < n - 1 and sims[j] >= tau:
                j += 1
            work.append((s, j + 1))
        j += 1
    while work:
        s, e = work.pop()
        if e - s < r_min:
            continue
        cons, csize = _consensus(gms[s:e])
        tick((e - s) * (len(cons) + 1))
        dist = [ruzicka(gms[x], cons, sizes[x], csize) for x in range(s, e)]
        bad = [x for x, d in zip(range(s, e), dist) if d < tau_c]
        if not bad:
            coh = sum(sims[s:e - 1]) / max(1, e - 1 - s)
            found.append((list(range(s, e)), coh, min(dist), cons, csize))
            continue
        cut = s
        for b in bad:
            if b - cut >= r_min:
                work.append((cut, b))
            cut = b + 1
        if e - cut >= r_min:
            work.append((cut, e))
    found.sort(key=lambda r: r[0][0])
    merged: list[tuple[list[int], float, float, dict[int, int], int]] = []
    gaps_used: list[int] = []
    for run in found:
        if merged and max_gaps > 0:
            prev = merged[-1]
            gap = run[0][0] - prev[0][-1] - 1
            if gap == 1 and gaps_used[-1] < max_gaps:
                tick(len(prev[3]) + len(run[3]) + 1)
                if ruzicka(prev[3], run[3], prev[4], run[4]) >= tau:
                    members = prev[0] + run[0]
                    cons, csize = _consensus([gms[x] for x in members])
                    k = len(prev[0]) + len(run[0])
                    coh = (prev[1] * len(prev[0]) + run[1] * len(run[0])) / k
                    merged[-1] = (members, coh, min(prev[2], run[2]), cons, csize)
                    gaps_used[-1] += 1
                    continue
        merged.append(run)
        gaps_used.append(0)
    return [(m, coh, mc, cons) for m, coh, mc, cons, _ in merged]


def _in_chrome(doc: Doc, i: int) -> bool:
    for a in [i, *doc.ancestors(i, 64)]:
        if doc.kind[a] != ELEMENT:
            continue
        if doc.tag_name(a) in _CHROME_TAGS or (doc.attr(a, "role") or "") in _CHROME_ROLES:
            return True
    return False


def _identity(doc: Doc, roots: tuple[int, ...]) -> float:
    """Attributes whose values identify members (pairwise distinct, present on >= 80%)."""
    counts: dict[str, list[str]] = {}
    for r in roots:
        for k, v in doc.attrs(r).items():
            if k in _ID_SKIP or k.startswith("aria-") or not v:
                continue
            counts.setdefault(k, []).append(v)
    found = 0
    for k, vals in counts.items():
        if len(vals) >= 0.8 * len(roots) and len(set(vals)) == len(vals) and len(vals) >= 2:
            found += 1
    return float(min(found, 2))


def score_run(doc: Doc, facts: _Facts, members: tuple[tuple[int, ...], ...], coh: float,
              w: Mapping[str, Any]) -> tuple[float, tuple[tuple[str, float], ...]]:
    n = len(members)
    texts = sorted(facts.span(facts.text_pref, m, doc) for m in members)
    median_text = texts[n // 2]
    covered = sum(texts)
    anchors = [facts.span(facts.a_pref, m, doc) for m in members]
    heads = [facts.span(facts.h_pref, m, doc) for m in members]
    anchor_share = sum(1 for a in anchors if a) / n
    heading_share = sum(1 for h in heads if h) / n
    carries = sum(1 for a, h in zip(anchors, heads) if a and h) / n
    per_link = (covered / max(1, sum(anchors))) if sum(anchors) else float(median_text)
    chrome = 1.0 if _in_chrome(doc, members[0][0]) else 0.0
    # A menu: every member a short link, and no member under a heading.
    # Short job titles ("Nurse", "Engineer II") sit under headings; menus don't.
    menu = 1.0 if (anchor_share >= 0.8 and per_link < 14.0 and heading_share < 0.5) else 0.0
    feats = (
        ("log_members", math.log(n)),
        ("coverage", covered / max(1, facts.total_text)),
        ("anchor_share", anchor_share),
        ("heading_share", heading_share),
        ("carries", carries),
        ("log_median_text", math.log10(1 + median_text)),
        ("cohesion", coh),
        ("identity", _identity(doc, tuple(m[0] for m in members))),
        ("chrome", chrome),
        ("menu_like", menu),
    )
    score = sum(float(w["w_" + name]) * value for name, value in feats)
    return round(score, 6), tuple((k, round(v, 6)) for k, v in feats)


def _demote_nested(doc: Doc, runs: list[Run], weight: float) -> list[Run]:
    """A run whose members each *contain* a record list is a list of lists
    (sibling ``<ul>`` blocks, result sections): its members are not records.
    ``nested_share`` = share of members holding another run's parent; the
    score drops by ``weight × share`` and the job-list gate skips runs at
    ``>= 0.5``. O(R log R + R·m) with the pre-order ranges."""
    import bisect

    # Only inner runs that are themselves record lists count: >= 3 members,
    # >= 80% carrying a heading and a link. A card's own repeats (skill
    # chips, badges, star icons) are runs too, but not records.
    parents = sorted({r.parent for r in runs
                      if len(r.members) >= 3 and r.feature("carries") >= 0.8})
    out = []
    for r in runs:
        held = 0
        for m in r.members:
            lo, hi = m[0], doc.end[m[-1]]
            k = bisect.bisect_left(parents, lo)
            if k < len(parents) and parents[k] < hi:
                held += 1
        share = held / len(r.members)
        if share:
            feats = r.features + (("nested_share", round(share, 6)),)
            out.append(Run(r.parent, r.width, r.members, round(r.score + weight * share, 6),
                           feats, r.signature, r.gaps))
        else:
            out.append(r)
    return out


def find_runs(doc: Doc, vis: Any, p: Mapping[str, Any], tick: Any) -> Records:
    facts = _Facts(doc, vis)
    tick(len(doc))
    intern: dict[tuple[int, ...], int] = {}
    depth_limit, K, S = int(p["depth"]), int(p["max_width"]), int(p["sibling_cap"])
    min_labels = int(p["min_member_labels"])
    all_runs: list[Run] = []
    parents = cap_hits = 0
    for parent in range(len(doc)):
        if doc.kind[parent] not in (ELEMENT, SHADOW, FRAME) or (vis and vis.reason[parent]):
            continue
        if doc.tag_name(parent) in _SKIP:
            continue
        kids = [c for c in doc.children(parent)
                if doc.kind[c] in (ELEMENT, SHADOW) and doc.tag_name(c) not in _SKIP
                and not (vis and vis.reason[c])]
        if len(kids) < 2:
            continue
        if len(kids) > S:
            kids = kids[:S]
            cap_hits += 1
        parents += 1
        child_ms: list[dict[int, int]] = []
        child_sz: list[int] = []
        for c in kids:
            ms, sz = skeleton(doc, c, depth_limit, facts, intern)
            tick(sz + 1)
            child_ms.append(ms)
            child_sz.append(sz)
        accepted: list[Run] = []
        covered: set[int] = set()
        for m in range(1, min(K, len(kids) // 2) + 1):
            for s in range(m):
                groups = [tuple(kids[s + j * m: s + (j + 1) * m])
                          for j in range((len(kids) - s) // m)]
                if len(groups) < int(p["r_min"]):
                    continue
                idx = [list(range(s + j * m, s + (j + 1) * m)) for j in range(len(groups))]
                gms = [_merge([child_ms[x] for x in ix]) for ix in idx]
                sizes = [sum(child_sz[x] for x in ix) for ix in idx]
                tick(sum(sizes))
                for ixs, coh, _mc, cons in _runs_for_parent(groups, gms, sizes, p, tick):
                    members = tuple(groups[x] for x in ixs)
                    med = sorted(sizes[x] for x in ixs)[len(ixs) // 2]
                    if med < min_labels * m:
                        continue
                    nodes = {x for g in members for x in g}
                    if len(nodes & covered) > 0.5 * len(nodes):
                        continue
                    ixset = set(ixs)
                    gaps = tuple(groups[x][0] for x in range(ixs[0], ixs[-1] + 1) if x not in ixset)
                    score, feats = score_run(doc, facts, members, coh, p)
                    accepted.append(Run(parent, m, members, score, feats,
                                        tuple(sorted(cons.items())), gaps))
                    covered |= nodes
        all_runs.extend(accepted)
    all_runs = _demote_nested(doc, all_runs, float(p["w_nested"]))
    all_runs.sort(key=lambda r: (-r.score, r.parent, r.width))
    max_runs = int(p["max_runs"])
    return Records(tuple(all_runs[:max_runs]), parents, cap_hits)


def _run(q: Any, params: Mapping[str, Any]) -> Ok[Records] | Abstain:
    vis = q.maybe("visibility")
    recs = find_runs(q.doc, vis, params, q.tick)
    ev: list[Evidence] = []
    if recs.sibling_cap_hits:
        ev.append(Evidence("sibling-cap", f"{recs.sibling_cap_hits} parents cut at {params['sibling_cap']}"))
    if not recs.runs:
        return Abstain("no-repeat", tuple(ev))
    top = recs.runs[0]
    margin = top.score - recs.runs[1].score if len(recs.runs) > 1 else None
    return Ok(recs, confidence=1.0, evidence=tuple(ev), margin=margin)


PARAMS = (
    ParamSpec("depth", 6, 2, 12, doc="D: skeleton depth"),
    ParamSpec("max_width", 4, 1, 8, doc="K: max children per record"),
    ParamSpec("tau", 0.75, 0.3, 0.99, doc="adjacent similarity threshold"),
    ParamSpec("tau_consensus", 0.65, 0.3, 0.99, doc="member-to-consensus threshold"),
    ParamSpec("r_min", 2, 2, 10, doc="minimum run length"),
    ParamSpec("max_gaps", 1, 0, 3, doc="foreign siblings a run may bridge (06 s1 allow_gap)"),
    ParamSpec("sibling_cap", 2000, 10, 100_000, doc="S: children read per parent (05 s14)"),
    ParamSpec("min_member_labels", 3, 1, 50, doc="ignore runs of trivial nodes (br, spacer)"),
    ParamSpec("max_runs", 40, 1, 1000),
    ParamSpec("w_log_members", 0.6), ParamSpec("w_coverage", 3.0),
    ParamSpec("w_anchor_share", 1.0), ParamSpec("w_heading_share", 1.0),
    ParamSpec("w_carries", 1.0), ParamSpec("w_log_median_text", 0.5),
    ParamSpec("w_cohesion", 1.0), ParamSpec("w_identity", 0.5),
    ParamSpec("w_chrome", -2.0), ParamSpec("w_menu_like", -1.5),
    ParamSpec("w_nested", -4.0, -20.0, 0.0, doc="list-of-lists demotion per nested share"),
)

TOOL = ToolSpec(id="records", ct_id="CT-T-008", version="0.2.0", run=_run,
                needs=("visibility",), params=PARAMS,
                summary="ranked sibling runs of repeated records (ALG-001..003)")

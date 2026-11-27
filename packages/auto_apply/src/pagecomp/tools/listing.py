"""Fields per record (CT-T-009, CT-ALG-004): title, destination, evidence.

For each of the top ``max_runs`` runs, every record gets:

* a **title** from a scored candidate (heading +2, anchor-related +1,
  its own link leads to a posting address +1 (``links.posting_path``),
  length up to 60 characters +0.5, first in reading order +0.5,
  metadata-like -1.5, dead-end text -1.0, renders a URL or breadcrumb -1.0;
  lines inside a link are candidates too), text by the full-subtree rule
  (defect 4) and the accessible name first;
* its **links**, scored by ``pagecomp.links`` with a title relation when
  the anchor contains, sits inside, or names the title (defects 25/26/28);
  a record whose root sits inside an anchor (the card *is* a link) gets
  that anchor as a candidate (defect 7);
* a **resolution state** (``resolved`` / ``multi_route`` / ``deferred`` /
  ``no_destination``), the link **kind** (``direct`` / ``unwrapped`` /
  ``opaque``) and, for opaque links, the **expected host** read from the
  card's breadcrumb, which the engine checks on arrival.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pagecomp import links as L
from pagecomp.doc import ELEMENT, TEXT, Doc
from pagecomp.params import ParamSpec
from pagecomp.registry import ToolSpec
from pagecomp.results import Abstain, Evidence, Ok
from pagecomp.tools.records import Run

_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_BARE_HOST = re.compile(L._HOST_RE + r"/?")
_META = re.compile(
    r"^\s*(\d+\s*(minutes?|hours?|days?|weeks?|months?|d|h|w|mo)\s*ago|"
    r"\d{4}-\d{2}-\d{2}|\$?\d[\d,.]*\s*(k|/hr|/yr|an hour|a year)?|today|yesterday|new|"
    r"posted .*|just posted|promoted|sponsored|easily apply)\s*$", re.I)


@dataclass(frozen=True)
class RecordReading:
    nodes: tuple[int, ...]
    title: str
    title_node: int
    title_score: float
    state: str
    link: L.LinkCandidate | None
    candidates: int
    rejections: int
    lines: tuple[str, ...]     # other short visible lines (company, place, date...)


@dataclass(frozen=True)
class RunReading:
    run: Run
    records: tuple[RecordReading, ...]


@dataclass(frozen=True)
class Listing:
    runs: tuple[RunReading, ...]


def _title_candidates(doc: Doc, nodes: tuple[int, ...], vis: Any) -> list[tuple[int, str, bool]]:
    out: list[tuple[int, str, bool]] = []
    for root in nodes:
        j, stop = root, doc.end[root]
        while j < stop:
            if vis is not None and vis.reason[j]:
                j = doc.end[j]
                continue
            if doc.kind[j] == ELEMENT:
                tag = doc.tag_name(j)
                heading = tag in _HEADINGS or doc.attr(j, "role") == "heading"
                if heading or (tag == "a" and doc.has_attr(j, "href")):
                    name = doc.accessible_name(j)
                    if name:
                        out.append((j, name, heading))
                    if heading:
                        j = doc.end[j]
                        continue
                elif tag not in ("script", "style", "svg") and _inside_anchor(doc, j, nodes[0]):
                    # A line inside a link (cards without headings: the link
                    # holds site name, breadcrumb and title as separate lines).
                    own = "".join(doc.own_text(c) for c in doc.children(j) if doc.kind[c] == TEXT).strip()
                    if len(own) >= 8:
                        out.append((j, " ".join(own.split()), False))
            j += 1
    return out


def _inside_anchor(doc: Doc, j: int, root: int) -> bool:
    for a in doc.ancestors(j, 12):
        if doc.kind[a] == ELEMENT and doc.tag_name(a) == "a" and doc.has_attr(a, "href"):
            return True
        if a == root:
            return False
    return False


def _anchors(doc: Doc, nodes: tuple[int, ...], vis: Any) -> list[int]:
    out = []
    for root in nodes:
        for j in doc.subtree(root):
            if doc.kind[j] == ELEMENT and (doc.has_attr(j, "href") or doc.has_attr(j, "data-href")) \
                    and not (vis is not None and vis.reason[j]):
                out.append(j)
    # the card itself may be inside an anchor (defect 7)
    for a in doc.ancestors(nodes[0], 3):
        if doc.kind[a] == ELEMENT and doc.has_attr(a, "href"):
            out.append(a)
            break
    return out


def _lines(doc: Doc, nodes: tuple[int, ...], vis: Any, skip: str, limit: int = 6) -> tuple[str, ...]:
    seen: list[str] = []
    for root in nodes:
        for j in doc.subtree(root):
            if doc.kind[j] != ELEMENT or (vis is not None and vis.reason[j]):
                continue
            if doc.tag_name(j) in ("script", "style", "svg"):
                continue
            own = " ".join(doc.own_text(c).strip() for c in doc.children(j) if doc.kind[c] == TEXT).strip()
            own = " ".join(own.split())
            if own and own != skip and own not in seen and len(own) <= 120:
                seen.append(own)
                if len(seen) >= limit:
                    return tuple(seen)
    return tuple(seen)


def read_record(doc: Doc, nodes: tuple[int, ...], vis: Any, page_url: str) -> RecordReading:
    cands = _title_candidates(doc, nodes, vis)
    anchors = _anchors(doc, nodes, vis)
    anchor_set = set(anchors)
    scored: list[tuple[float, int, str]] = []
    for order, (j, name, heading) in enumerate(cands):
        rel = (j in anchor_set) or any(doc.is_ancestor(a, j) or doc.is_ancestor(j, a) for a in anchors)
        s = (2.0 if heading else 0.0) + (1.0 if rel else 0.0) + 0.5 * min(len(name), 60) / 60
        # The candidate, the anchor around it, or (a heading wrapping its
        # link: <h3><a href=...>Title</a></h3>) the first anchor inside it
        # leads to a posting address. Review round 2: the last case was
        # missed, so the commonest card shape never got this evidence.
        own = j if j in anchor_set else next(
            (a for a in anchors if doc.is_ancestor(a, j) or doc.is_ancestor(j, a)), -1)
        if own >= 0:
            s += 1.0 * L.posting_path(L.resolve_href(doc.attr(own, "href") or "", page_url))
        s += 0.5 if order == 0 else 0.0
        if _META.match(name):
            s -= 1.5
        if L.is_dead_end_text(name):
            s -= 1.0
        if L.evidence_host([name]) or "\u203a" in name or _BARE_HOST.fullmatch(name.strip()) \
                or doc.tag_name(j) == "cite":
            s -= 1.0   # the name renders a URL, a breadcrumb or a bare host: not a title
        scored.append((round(s, 6), j, name))
    scored.sort(key=lambda t: (-t[0], t[1]))
    if scored:
        tscore, tnode, title = scored[0]
    else:
        tscore, tnode, title = 0.0, -1, ""
    items = []
    for a in anchors:
        href = doc.attr(a, "href") or doc.attr(a, "data-href") or ""
        text = doc.accessible_name(a)
        structural = tnode >= 0 and (a == tnode or doc.is_ancestor(a, tnode) or doc.is_ancestor(tnode, a))
        textual = bool(title) and L.title_overlap(title, text) >= 0.5
        items.append((a, href, text, "title-structural" if structural else ("title" if textual else "")))
    evidence = [doc.text_content(c, 200)[0] for r in nodes for c in doc.subtree(r)
                if doc.kind[c] == ELEMENT and doc.tag_name(c) == "cite"]
    evidence.append(doc.text_content(nodes[0], 400)[0])
    cs, rs = L.evaluate(items, title=title, page_url=page_url, evidence_texts=evidence)
    state, chosen = L.decide(cs, rs)
    return RecordReading(nodes, title, tnode, tscore, state, chosen, len(cs), len(rs),
                         _lines(doc, nodes, vis, title))


def _run(q: Any, params: Mapping[str, Any]) -> Ok[Listing] | Abstain:
    recs = q.need_ok("records")
    vis = q.maybe("visibility")
    doc = q.doc
    out: list[RunReading] = []
    for run in recs.runs[: int(params["max_runs"])]:
        rows = []
        for members in run.members[: int(params["max_records"])]:
            q.tick(sum(doc.size(x) for x in members) * 2)
            rows.append(read_record(doc, members, vis, q.obs.url))
        out.append(RunReading(run, tuple(rows)))
    ev = tuple(Evidence("run", f"run {k}: {len(r.records)} records, "
                        f"{sum(1 for x in r.records if x.state == L.RESOLVED)} resolved")
               for k, r in enumerate(out))
    return Ok(Listing(tuple(out)), evidence=ev)


TOOL = ToolSpec(
    id="listing", ct_id="CT-T-009", version="0.2.2", run=_run, needs=("records", "visibility"),
    params=(ParamSpec("max_runs", 8, 1, 100), ParamSpec("max_records", 200, 1, 5000)),
    summary="title, destination and resolution state per record",
)

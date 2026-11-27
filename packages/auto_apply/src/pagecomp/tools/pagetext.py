"""Visible page text, computed once and shared (DRY: one definition of
"what the page says", used by the verdict, the family model and the
phrase checks). Bounded by the 2,000,000-character text budget of 05
section 14; the cut is reported.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pagecomp.doc import ELEMENT, INLINE, TEXT
from pagecomp.params import ParamSpec
from pagecomp.registry import ToolSpec
from pagecomp.results import Evidence, Ok
from pagecomp.text import collapse, facts, key


@dataclass(frozen=True)
class PageText:
    text: str           # collapsed visible text, reading order
    folded: str         # comparison key (lower, NFKC)
    truncated: bool
    script: str
    direction: str
    mojibake: bool
    prose_blocks: int   # elements whose own text is >= 80 characters (paragraph-like)


def _run(q: Any, params: Mapping[str, Any]) -> Ok[PageText]:
    doc = q.doc
    vis = q.need_ok("visibility")
    cap = int(params["max_chars"])
    parts: list[str] = []
    total = 0
    truncated = False
    n = len(doc)
    q.tick(n)
    prose = 0
    closes: list[int] = []
    i = 0
    while i < n:
        while closes and i >= closes[-1]:
            closes.pop()
            parts.append(" ")
        if vis.reason[i]:
            i = doc.end[i]
            continue
        k = doc.kind[i]
        if k == TEXT:
            t = doc.own_text(i)
            if len(t) >= 80 and doc.tag_name(doc.parent[i]) not in ("script", "style"):
                prose += 1
            parts.append(t)
            total += len(t)
            if total > cap:
                truncated = True
                break
        elif k == ELEMENT and doc.tag_name(i) not in INLINE:
            parts.append(" ")
            closes.append(doc.end[i])
        i += 1
    text = collapse("".join(parts))[:cap]
    tf = facts(text)
    ev: tuple[Evidence, ...] = (Evidence("text-truncated", f"cap {cap}"),) if truncated else ()
    if tf.mojibake:
        ev += (Evidence("mojibake", "text looks mis-decoded; phrase checks may miss"),)
    return Ok(PageText(text, key(text), truncated, tf.script, tf.direction, tf.mojibake, prose),
              evidence=ev)


TOOL = ToolSpec(
    id="pagetext", ct_id="CT-T-003", version="0.1.0", run=_run, needs=("visibility",),
    params=(ParamSpec("max_chars", 2_000_000, 1_000, 20_000_000,
                      doc="visible-text budget per observation (05 s14)"),),
    summary="visible text of the page, once",
)

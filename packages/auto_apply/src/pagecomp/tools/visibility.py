"""Visibility (CT-T-005, CT-ALG-013), static form.

Without the layout capability (``SNAPSHOT_LAYOUT``) the only evidence of
"a person cannot see this" is in the markup: the ``hidden`` attribute,
``type=hidden``, inline ``display:none`` / ``visibility:hidden`` /
``opacity:0`` / zero size / far off-screen positioning, ``<template>``
content, a closed ``<details>`` body, a ``<dialog>`` that is not open, and
``inert``. ``aria-hidden`` is recorded separately: it hides from assistive
technology, not from sight (06 section 6).

A node with no such evidence is ``VISIBLE_UNPROVEN``, never "visible": CSS
classes can hide anything, and only computed style can say. Consumers that
must not act on a hidden element (the trap rule) treat ``VISIBLE_UNPROVEN``
as "not shown to be hidden", and the evidence says the layout capability
was missing.

Hidden status propagates to descendants in one forward pass (pre-order).
"""

from __future__ import annotations

import re
from array import array
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pagecomp.doc import ELEMENT, TEXT, Doc
from pagecomp.registry import ToolSpec
from pagecomp.results import Evidence, Ok

VISIBLE_UNPROVEN = 0
HIDDEN_ATTR = 1
INPUT_HIDDEN = 2
STYLE_DISPLAY = 3
STYLE_VISIBILITY = 4
STYLE_OPACITY = 5
STYLE_ZERO = 6
STYLE_OFFSCREEN = 7
TEMPLATE = 8
CLOSED_DETAILS = 9
CLOSED_DIALOG = 10
INERT = 11
NON_RENDERED = 12   # script, style, head, noscript...
NO_BOX = 13         # layout known: no box here or anywhere below (display:none, not rendered)

REASONS = {
    VISIBLE_UNPROVEN: "visible-unproven", HIDDEN_ATTR: "hidden-attribute",
    INPUT_HIDDEN: "input-type-hidden", STYLE_DISPLAY: "display-none",
    STYLE_VISIBILITY: "visibility-hidden", STYLE_OPACITY: "opacity-zero",
    STYLE_ZERO: "zero-size", STYLE_OFFSCREEN: "off-screen", TEMPLATE: "template",
    CLOSED_DETAILS: "closed-details", CLOSED_DIALOG: "closed-dialog", INERT: "inert",
    NON_RENDERED: "non-rendered", NO_BOX: "no-box",
}

_NON_RENDERED = frozenset({"script", "style", "head", "noscript", "meta", "link", "title", "base"})
_DECL = re.compile(r"([a-z-]+)\s*:\s*([^;]+)")
_OFFSCREEN = re.compile(r"^-\s*(\d{3,})(px)?$")


_STYLE_SCAN = 4096


def _style_reason(style: str) -> int:
    # Declarations that hide an element are short and come early; a 1 MB
    # inline style (an embedded data: image) is not read past 4 KB.
    decls = {k: v.strip().lower().replace("!important", "").strip()
             for k, v in _DECL.findall(style[:_STYLE_SCAN].lower())}
    if decls.get("display") == "none":
        return STYLE_DISPLAY
    if decls.get("visibility") in ("hidden", "collapse"):
        return STYLE_VISIBILITY
    op = decls.get("opacity")
    if op is not None:
        try:
            if float(op) <= 0.01:
                return STYLE_OPACITY
        except ValueError:
            pass
    w, h = decls.get("width", ""), decls.get("height", "")
    if (w in ("0", "0px") and h in ("0", "0px")) or (
        decls.get("overflow") == "hidden" and (w in ("0", "0px", "1px") or h in ("0", "0px", "1px"))
    ):
        return STYLE_ZERO
    if decls.get("position") in ("absolute", "fixed"):
        for side in ("left", "top", "right"):
            m = _OFFSCREEN.match(decls.get(side, ""))
            if m and int(m.group(1)) >= 1000:
                return STYLE_OFFSCREEN
    if "clip" in decls and "rect(0" in decls["clip"].replace(" ", ""):
        return STYLE_ZERO
    return VISIBLE_UNPROVEN


@dataclass(frozen=True)
class VisibilityMap:
    reason: array            # array('B') per node, codes above
    aria_hidden: array       # array('B') per node, 1 when inside aria-hidden="true"
    layout_known: bool

    def hidden(self, i: int) -> bool:
        return self.reason[i] != VISIBLE_UNPROVEN

    def why(self, i: int) -> str:
        if self.layout_known and self.reason[i] == VISIBLE_UNPROVEN:
            return "visible"
        return REASONS[self.reason[i]]


def compute(doc: Doc) -> VisibilityMap:
    if doc.layout is not None and len(doc.layout.has_box) == len(doc):
        return _compute_layout(doc)
    return _compute_static(doc)


def _compute_layout(doc: Doc) -> VisibilityMap:
    """Computed style and boxes decide (``SNAPSHOT_LAYOUT``).

    * ``display:none`` and unrendered nodes have no box; a node is ``no-box``
      only when nothing in its subtree has one (``display:contents``
      wrappers keep visible children);
    * ``visibility`` is read per node from computed style, which CSS already
      inherits, so a ``visibility:visible`` child of a hidden parent is
      visible, as in a browser;
    * ``opacity:0`` hides the subtree (opacity is not inherited in computed
      style but composites over descendants);
    * a box of zero width or height whose subtree has no larger box is
      ``zero-size``; a box wholly left of or above the page is ``off-screen``.
    Markup facts (``template``, closed ``<dialog>``, ``inert``) still apply.
    """
    lay = doc.layout
    assert lay is not None
    n = len(doc)
    reason = array("B", bytes(n))
    aria = array("B", bytes(n))
    any_box = array("B", lay.has_box.tobytes())
    big_box = array("B", bytes(n))
    for i in range(n):
        if lay.has_box[i] and lay.w[i] > 0 and lay.h[i] > 0:
            big_box[i] = 1
    for i in range(n - 1, 0, -1):  # pre-order: children after parents
        p = doc.parent[i]
        if p >= 0:
            if any_box[i]:
                any_box[p] = 1
            if big_box[i]:
                big_box[p] = 1
    for i in range(1, n):
        p = doc.parent[i]
        inherited = reason[p] if p >= 0 else VISIBLE_UNPROVEN
        aria[i] = aria[p] if p >= 0 else 0
        if inherited == STYLE_VISIBILITY:
            inherited = VISIBLE_UNPROVEN  # re-decided from this node's own computed style
        own = VISIBLE_UNPROVEN
        k = doc.kind[i]
        tag = doc.tag_name(i) if k == ELEMENT else ""
        st = lay.style[i]
        if k == ELEMENT and tag in _NON_RENDERED:
            own = NON_RENDERED
        elif tag == "template":
            own = TEMPLATE
        elif tag == "input" and (doc.attr(i, "type") or "").lower() == "hidden":
            own = INPUT_HIDDEN
        elif k == ELEMENT and doc.has_attr(i, "inert"):
            own = INERT
        elif k in (ELEMENT, TEXT) and not any_box[i]:
            own = STYLE_DISPLAY if st & lay.DISPLAY_NONE else NO_BOX
        elif st & lay.OPACITY_ZERO:
            own = STYLE_OPACITY
        elif st & lay.VIS_HIDDEN and k in (ELEMENT, TEXT):
            own = STYLE_VISIBILITY
        elif k == ELEMENT and lay.has_box[i] and not big_box[i]:
            own = STYLE_ZERO
        elif k == ELEMENT and lay.has_box[i] and (lay.x[i] + lay.w[i] <= 0 or lay.y[i] + lay.h[i] <= 0):
            own = STYLE_OFFSCREEN
        if k == ELEMENT and doc.attr(i, "aria-hidden") == "true":
            aria[i] = 1
        reason[i] = inherited if inherited != VISIBLE_UNPROVEN else own
    return VisibilityMap(reason, aria, True)


def _compute_static(doc: Doc) -> VisibilityMap:
    n = len(doc)
    reason = array("B", bytes(n))
    aria = array("B", bytes(n))
    for i in range(1, n):
        p = doc.parent[i]
        inherited = reason[p] if p >= 0 else VISIBLE_UNPROVEN
        aria[i] = aria[p] if p >= 0 else 0
        if doc.kind[i] != ELEMENT:
            reason[i] = inherited
            continue
        own = VISIBLE_UNPROVEN
        tag = doc.tag_name(i)
        if tag in _NON_RENDERED:
            own = NON_RENDERED
        elif tag == "template":
            own = TEMPLATE
        elif doc.has_attr(i, "hidden"):
            own = HIDDEN_ATTR
        elif tag == "input" and (doc.attr(i, "type") or "").lower() == "hidden":
            own = INPUT_HIDDEN
        elif doc.has_attr(i, "inert"):
            own = INERT
        elif tag == "dialog" and not doc.has_attr(i, "open"):
            own = CLOSED_DIALOG
        else:
            style = doc.attr(i, "style")
            if style:
                own = _style_reason(style)
        if own == VISIBLE_UNPROVEN and p >= 0 and doc.tag_name(p) == "details" \
                and not doc.has_attr(p, "open") and tag != "summary":
            own = CLOSED_DETAILS
        if doc.attr(i, "aria-hidden") == "true":
            aria[i] = 1
        reason[i] = inherited if inherited != VISIBLE_UNPROVEN else own
    return VisibilityMap(reason, aria, False)


def _run(q: Any, params: Mapping[str, Any]) -> Ok[VisibilityMap]:
    q.tick(len(q.doc))
    vm = compute(q.doc)
    ev: tuple[Evidence, ...] = ()
    if not vm.layout_known:
        ev = (Evidence("layout-capability-missing",
                       "static markup only: CSS-class hiding cannot be seen"),)
    return Ok(vm, confidence=0.6 if ev else 1.0, evidence=ev)


TOOL = ToolSpec(id="visibility", ct_id="CT-T-005", version="0.2.0", run=_run,
                summary="static visibility evidence per node")

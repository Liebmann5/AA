"""S8f pins — job-card detection: selection policy + marker-aware guard.

Pin labels (honest, per standing method):
  A, B  TEETH      — fail on the pre-S8f tree for the reason stated.
  C     DIFFERENTIAL — documents an intended behavior change (dominant-style
                     selection); fails pre-stage, but the old behavior was the
                     defect under repair, not a contract.
  D, E  BEHAVIOUR-PRESERVING — pass on both trees; guard the link branch and
                     the exclusion branch of is_card_like.

Note: this file is new, but A/B/C exercise PRE-EXISTING code
(MathFormUnderstandingService._detect_job_listings and is_card_like), so the
teeth are real — they are not coverage-of-new-module pins.
"""
from __future__ import annotations

from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.services.dom_segmentation import MathFormUnderstandingService
from auto_apply.domain.services.structural_hashing import is_card_like


# --------------------------------------------------------------------------
# Fixture builders
# --------------------------------------------------------------------------

def _node(tag, cls=None, text="", geom=None, attrs=(), children=(), depth=0):
    attr_list = []
    if cls:
        attr_list.append(("class", cls))
    attr_list.extend(attrs)
    return DOMNode(
        tag=tag,
        attributes=tuple(attr_list),
        text=text,
        geometry=geom,
        children=tuple(children),
        depth=depth,
    )


def _g(x, y, w, h):
    return Geometry(x=float(x), y=float(y), width=float(w), height=float(h))


def _card_chain(idx: int, *, with_link: bool, y_offset: int) -> DOMNode:
    """One Google-measured card chain:
    div.tNxQIb.PUpOsf < div.GoEOPd < div.u9g6vf < span.gmxZue
        < div.MQUd2b < div[role=button]{data-preview-id}.

    The span level is intentional: it is below the container-tag gate, so it
    never becomes a candidate — mirroring the real page.
    """
    leaf_children = [
        _node("div", text=f"Senior Engineer {idx}", geom=_g(20, 20, 100, 20), depth=6),
    ]
    if with_link:
        leaf_children.append(
            _node("a", text="Apply",
                  attrs=(("href", f"https://jobs.example.com/{idx}"),),
                  geom=_g(20, 50, 60, 18), depth=6)
        )
    l5 = _node("div", attrs=(("role", "button"),
                             ("data-preview-id", f"htidocid{idx}"),),
               geom=_g(0, y_offset + 15, 350, 210),
               children=leaf_children, depth=5)
    l4 = _node("div", cls="MQUd2b", geom=_g(0, y_offset + 12, 360, 220),
               children=(l5,), depth=4)
    l3 = _node("span", cls="gmxZue", geom=_g(0, y_offset + 9, 370, 230),
               children=(l4,), depth=3)
    l2 = _node("div", cls="u9g6vf", geom=_g(0, y_offset + 6, 380, 240),
               children=(l3,), depth=2)
    l1 = _node("div", cls="GoEOPd", geom=_g(0, y_offset + 3, 390, 250),
               children=(l2,), depth=1)
    l0 = _node("div", cls="tNxQIb PUpOsf", geom=_g(0, y_offset, 400, 260),
               children=(l1,), depth=0)
    return l0


def _tab(idx: int, y_offset: int) -> DOMNode:
    """One chrome tab: link-bearing, role=tab, tracking-only data attr."""
    link = _node("a", text=f"Tab {idx}",
                 attrs=(("href", f"https://google.com/tab{idx}"),),
                 geom=_g(0, 0, 80, 20), depth=1)
    return _node("div", cls="hdtb-tab",
                 attrs=(("role", "tab"), ("data-hveid", f"CA{idx:02d}")),
                 geom=_g(idx * 110, y_offset, 100, 40),
                 children=(link,), depth=0)


def _page(children) -> DOMNode:
    return _node("body", geom=_g(0, 0, 1200, 3000), children=children, depth=0)


def _analyze(children):
    service = MathFormUnderstandingService()
    return service.analyze(_page(children), url="https://serp.example/jobs",
                           title="jobs")


# --------------------------------------------------------------------------
# Pin A (TEETH): nested-chain over-collection collapses to the outermost 9
# --------------------------------------------------------------------------

def test_nested_chain_union_collapses_to_outermost_cards():
    """Pre-S8f: 5 guard-passing chain levels x 9 cards + 12 tabs = 57 nodes
    returned (union of every repeated group). Post-S8f: exactly the 9
    outermost card roots. Fails pre-stage with 57 != 9."""
    children = [_card_chain(i, with_link=True, y_offset=i * 300) for i in range(9)]
    children += [_tab(i, y_offset=2900) for i in range(12)]
    listings = _analyze(children).job_listings

    assert len(listings) == 9, (
        f"expected the 9 outermost card roots, got {len(listings)} nodes "
        f"(nested-chain union / chrome over-collection)"
    )
    for node in listings:
        assert node.get_attribute("class") == "tNxQIb PUpOsf", (
            "selection must return the outermost chain level (largest area), "
            f"got class={node.get_attribute('class')!r}"
        )
    # No selected node may contain another selected node.
    selected_ids = {id(n) for n in listings}
    for node in listings:
        for inner in node.iter_nodes():
            if inner is not node:
                assert id(inner) not in selected_ids, (
                    "a selected card contains another selected card — "
                    "nested-chain over-collection survived"
                )


# --------------------------------------------------------------------------
# Pin B (TEETH): anchorless, marker-bearing cards are admitted
# --------------------------------------------------------------------------

def test_anchorless_marker_bearing_cards_are_detected():
    """Pre-S8f: is_card_like requires a descendant <a>; Google cards have
    none (measured), so every real card was excluded and this returned 0.
    Post-S8f: the role=button / data-preview-id marker admits them."""
    children = [_card_chain(i, with_link=False, y_offset=i * 300) for i in range(9)]
    listings = _analyze(children).job_listings
    assert len(listings) == 9, (
        f"anchorless cards with semantic markers were not detected "
        f"(got {len(listings)}); the link-only guard excludes Google's "
        f"real cards by construction"
    )


# --------------------------------------------------------------------------
# Pin C (DIFFERENTIAL): two distinct card styles -> dominant style only
# --------------------------------------------------------------------------

def test_two_distinct_card_styles_yield_dominant_group_only():
    """Documented trade-off of single-group selection (ruling R-1/CB-1):
    a page mixing two structurally distinct card styles returns only the
    dominant group. Pre-S8f this returned both groups (10 nodes)."""
    style_x = [
        _node("div", cls="card-x",
              geom=_g(0, i * 200, 400, 180),
              children=(
                  _node("a", text=f"Job X{i}",
                        attrs=(("href", f"https://x.example/{i}"),),
                        geom=_g(10, 10, 100, 20), depth=1),
              ), depth=0)
        for i in range(6)
    ]
    style_y = [
        _node("li", cls="card-y",
              geom=_g(0, 1400 + i * 200, 400, 180),
              children=(
                  _node("a", text=f"Job Y{i}",
                        attrs=(("href", f"https://y.example/{i}"),),
                        geom=_g(10, 10, 100, 20), depth=1),
              ), depth=0)
        for i in range(4)
    ]
    listings = _analyze(style_x + style_y).job_listings
    assert len(listings) == 6
    assert all(n.get_attribute("class") == "card-x" for n in listings)


# --------------------------------------------------------------------------
# Pin D (BEHAVIOUR-PRESERVING): linked, markerless cards still pass the guard
# --------------------------------------------------------------------------

def test_linked_markerless_card_still_card_like():
    card = _node(
        "div", cls="plain-card", geom=_g(0, 0, 400, 200),
        children=(
            _node("a", text="Engineer",
                  attrs=(("href", "https://jobs.example/1"),),
                  geom=_g(10, 10, 100, 20), depth=1),
        ),
    )
    assert is_card_like(card) is True


# --------------------------------------------------------------------------
# Pin E (BEHAVIOUR-PRESERVING): linkless, markerless containers stay excluded
# --------------------------------------------------------------------------

def test_linkless_markerless_container_still_not_card_like():
    container = _node(
        "div", cls="mystery-box", geom=_g(0, 0, 400, 200),
        children=(_node("div", text="just some text", geom=_g(10, 10, 100, 20), depth=1),),
    )
    assert is_card_like(container) is False

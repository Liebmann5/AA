"""Pins for the pure structural stages of card resolution.

Every tree here is a synthetic DOM shape built from DOMNode/Geometry. The
shapes encode the cases: groups that collapse at hop 1, identity learned
several levels up, tracking and positional attributes, anchorless cards
with a learnable identity, ad-only cards, and apply-intent multi-route
groups.
"""

from __future__ import annotations

from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.ports.page_understanding_port import CardResolutionState
from auto_apply.domain.services.card_static_resolution import (
    climb_card_levels,
    extract_card_title,
    extract_company_location,
    learn_identity_attributes,
    pick_identity_level,
    resolve_card_group,
)

PAGE_URL = "https://serp.example.com/search"


def _node(
    tag: str = "div",
    attrs: tuple = (),
    text: str = "",
    geom: Geometry | None = None,
    children: tuple = (),
    depth: int = 0,
) -> DOMNode:
    return DOMNode(
        tag=tag,
        attributes=attrs,
        text=text,
        geometry=geom,
        children=children,
        depth=depth,
    )


def _card(
    ref: str,
    *,
    y: float = 0.0,
    extra_attrs: tuple = (),
    children: tuple | None = None,
) -> DOMNode:
    if children is None:
        children = (
            _node(attrs=(("role", "heading"),), text=f"Engineer {ref}", depth=2),
            _node(text=f"Company {ref}", depth=2),
        )
    return _node(
        attrs=(("role", "button"), ("class", "jc"), ("data-job-ref", ref)) + extra_attrs,
        geom=Geometry(x=0, y=y, width=200, height=100),
        children=children,
        depth=1,
    )


def _chain(root_child: DOMNode) -> DOMNode:
    return _node(tag="body", children=(root_child,), depth=0)


# ─────────────────────────────────────────────────────────────────────────────
# Climb
# ─────────────────────────────────────────────────────────────────────────────


def test_climb_keeps_levels_until_collapse() -> None:
    card1 = _card("a1", y=0)
    card2 = _card("b2", y=110)
    wrap1a = _node(children=(card1,), depth=2)
    wrap2a = _node(children=(card2,), depth=2)
    wrap1b = _node(children=(wrap1a,), depth=3)
    wrap2b = _node(children=(wrap2a,), depth=3)
    root = _node(tag="body", children=(wrap1b, wrap2b), depth=4)

    levels, parent_count, note = climb_card_levels([card1, card2], root)

    assert [label for label, _ in levels] == ["detected", "+1", "+2"]
    assert parent_count == 2
    assert "hop 3" in note


def test_climb_collapses_immediately_with_fewer_parents() -> None:
    """The anchor-board shape: detected nodes share a container, so the very
    first hop collapses and the detected level stays the working level."""
    card1 = _card("a1", y=0)
    card2 = _card("b2", y=110)
    card3 = _card("c3", y=220)
    container = _node(children=(card1, card2, card3), depth=2)
    root = _node(tag="body", children=(container,), depth=3)

    levels, parent_count, note = climb_card_levels([card1, card2, card3], root)

    assert [label for label, _ in levels] == ["detected"]
    assert parent_count == 1
    assert "hop 1" in note


# ─────────────────────────────────────────────────────────────────────────────
# Sibling-diff identity learning
# ─────────────────────────────────────────────────────────────────────────────


def test_sibling_diff_learns_identity() -> None:
    cards = [_card("k1001", y=0), _card("k1002", y=110), _card("k1003", y=220)]
    root = _chain(_node(children=tuple(cards), depth=2))
    learned, _evidence = learn_identity_attributes(cards, root)
    assert "data-job-ref" in learned


def test_constant_attr_is_chrome() -> None:
    def zoned(ref: str, y: float) -> DOMNode:
        return _card(ref, y=y, extra_attrs=(("data-zone", "north"),))

    cards = [zoned("a1", 0), zoned("b2", 110), zoned("c3", 220)]
    root = _chain(_node(children=tuple(cards), depth=2))
    learned, evidence = learn_identity_attributes(cards, root)
    assert "data-zone" not in learned
    assert "page chrome" in evidence["data-zone"]


def test_tracking_attrs_excluded() -> None:
    def tracked(ref: str, tag_value: str, y: float) -> DOMNode:
        return _card(ref, y=y, extra_attrs=(("data-ved", tag_value),))

    cards = [tracked("a1", "t1", 0), tracked("b2", "t2", 110), tracked("c3", "t3", 220)]
    root = _chain(_node(children=tuple(cards), depth=2))
    learned, evidence = learn_identity_attributes(cards, root)
    assert "data-ved" not in learned
    assert "tracking-shaped" in evidence["data-ved"]


def test_positional_attrs_excluded() -> None:
    def positioned(ref: str, idx: str, y: float) -> DOMNode:
        return _card(ref, y=y, extra_attrs=(("tabindex", idx),))

    cards = [positioned("a1", "0", 0), positioned("b2", "1", 110), positioned("c3", "2", 220)]
    root = _chain(_node(children=tuple(cards), depth=2))
    learned, evidence = learn_identity_attributes(cards, root)
    assert "tabindex" not in learned
    assert "positional" in evidence["tabindex"]


def test_single_card_learns_nothing() -> None:
    cards = [_card("k1001", y=0)]
    root = _chain(_node(children=tuple(cards), depth=2))
    learned, _ = learn_identity_attributes(cards, root)
    assert learned == []


def test_page_unique_rejection() -> None:
    """Values that legitimately repeat across the page are not identity."""

    def roled(ref: str, code: str, y: float) -> DOMNode:
        return _card(ref, y=y, extra_attrs=(("data-role-code", code),))

    cards = [roled("a1", "eng", 0), roled("b2", "eng", 110), roled("c3", "mgr", 220)]
    root = _chain(_node(children=tuple(cards), depth=2))
    learned, evidence = learn_identity_attributes(cards, root)
    assert "data-role-code" not in learned
    assert "page-unique" in evidence["data-role-code"]


def test_identity_learned_several_levels_up() -> None:
    """Identity that lives only on an ancestor must be found by the climb.

    The detected cards deliberately carry NO learnable identity — only
    chrome, tracking, and positional attributes at every level below +4.
    """

    def chained(ref: str, batch: str) -> tuple[DOMNode, DOMNode]:
        card = _node(
            attrs=(("role", "button"), ("class", "jc"), ("data-ved", f"t-{ref}")),
            geom=Geometry(x=0, y=0, width=200, height=100),
            children=(
                _node(attrs=(("role", "heading"),), text=f"Engineer {ref}", depth=6),
            ),
            depth=6,
        )
        p1 = _node(attrs=(("data-zone", "north"),), children=(card,), depth=5)
        p2 = _node(attrs=(("data-trace-id", f"tr-{ref}"),), children=(p1,), depth=4)
        p3 = _node(attrs=(("tabindex", "0"),), children=(p2,), depth=3)
        p4 = _node(attrs=(("data-batch-id", batch),), children=(p3,), depth=2)
        p5 = _node(children=(p4,), depth=1)
        return p5, card

    chain1, card1 = chained("a1", "b100")
    chain2, card2 = chained("b2", "b200")
    root = _node(tag="body", children=(chain1, chain2), depth=0)

    levels, _, _ = climb_card_levels([card1, card2], root)
    label, learned, _, _nodes = pick_identity_level(levels, root)

    assert label == "+4"
    assert "data-batch-id" in learned


# ─────────────────────────────────────────────────────────────────────────────
# Static resolution over a group
# ─────────────────────────────────────────────────────────────────────────────


def test_static_relative_anchor_resolves() -> None:
    children = (
        _node(attrs=(("role", "heading"),), text="Structural Engineer", depth=2),
        _node(text="Beamworks Ltd", depth=2),
        _node(tag="a", attrs=(("href", "/openings/eng-101"),), text="Apply for this role", depth=2),
    )
    card = _card("r101", y=0, children=children)
    container = _node(children=(card, _card("r102", y=110)), depth=2)
    root = _node(tag="body", children=(container,), depth=3)

    job_cards, _report = resolve_card_group([card], root, PAGE_URL)

    assert job_cards[0].resolution_state == CardResolutionState.RESOLVED.value
    assert job_cards[0].url == "https://serp.example.com/openings/eng-101"


def test_ad_only_card_deferred_with_ad_rejection() -> None:
    children = (
        _node(attrs=(("role", "heading"),), text="Structural Engineer", depth=2),
        _node(
            tag="a",
            attrs=(("href", "https://ads-track.example.net/clk?ad_campaign=spring"),),
            text="",
            depth=2,
        ),
    )
    card = _card("r101", y=0, children=children)
    container = _node(children=(card, _card("r102", y=110)), depth=2)
    root = _node(tag="body", children=(container,), depth=3)

    job_cards, _report = resolve_card_group([card], root, PAGE_URL)

    assert job_cards[0].resolution_state == CardResolutionState.DEFERRED.value
    assert job_cards[0].has_ad_rejection is True
    assert job_cards[0].url == ""


def test_title_comes_from_headings_only() -> None:
    """Heading nodes are the only title candidates — prominence breaks ties
    between them, but a long non-heading text must never become the title."""
    heading = _node(attrs=(("role", "heading"),), text="Petroleum Engineer", depth=2)
    filler = _node(
        text="x" * 60, geom=Geometry(x=0, y=0, width=100, height=5), depth=2
    )
    card = _card("r101", y=0, children=(heading, filler))
    assert extract_card_title(card) == "Petroleum Engineer"

    no_heading = _card(
        "r102",
        y=110,
        children=(
            _node(text="Senior Drilling Engineer", depth=2),
            _node(text="Apply", depth=2),
        ),
    )
    assert extract_card_title(no_heading) == ""


def test_company_location_extraction_preserved() -> None:
    children = (
        _node(attrs=(("role", "heading"),), text="Petroleum Engineer", depth=2),
        _node(text="Acme Drilling Co", depth=2),
        _node(text="Austin, TX", depth=2),
    )
    card = _card("r101", y=0, children=children)
    title = extract_card_title(card)
    company, location = extract_company_location(card, title)
    assert company == "Acme Drilling Co"
    assert location == "Austin, TX"


def test_no_anchor_card_is_no_destination_but_keeps_identity() -> None:
    card = _card("k1001", y=0)
    sibling = _card("k1002", y=110)
    container = _node(children=(card, sibling), depth=2)
    root = _node(tag="body", children=(container,), depth=3)

    # The whole group goes in: sibling-diff identity needs at least two cards.
    job_cards, report = resolve_card_group([card, sibling], root, PAGE_URL)

    assert job_cards[0].resolution_state == CardResolutionState.NO_DESTINATION.value
    assert job_cards[0].url == ""
    assert job_cards[0].identity_attribute == "data-job-ref"
    assert job_cards[0].identity_value == "k1001"
    assert "data-job-ref" in report.learned_identity


def test_multi_apply_group_becomes_multi_route_with_empty_url() -> None:
    children = (
        _node(attrs=(("role", "heading"),), text="Senior Marine Engineer", depth=2),
        *(
            _node(
                tag="a",
                attrs=(("href", f"/out?u={'Z9xQ' * 20}{i}"),),
                text="Apply now",
                depth=2,
            )
            for i in range(3)
        ),
    )
    card = _card("r101", y=0, children=children)
    container = _node(children=(card, _card("r102", y=110)), depth=2)
    root = _node(tag="body", children=(container,), depth=3)

    job_cards, _report = resolve_card_group([card], root, PAGE_URL)

    assert job_cards[0].resolution_state == CardResolutionState.MULTI_ROUTE.value
    assert job_cards[0].url == ""
    assert len(job_cards[0].candidates) == 3


def test_report_fields_populated() -> None:
    cards = [_card("k1001", y=0), _card("k1002", y=110), _card("k1003", y=220)]
    container = _node(children=tuple(cards), depth=2)
    root = _node(tag="body", children=(container,), depth=3)

    _job_cards, report = resolve_card_group(cards, root, PAGE_URL)

    assert report.learned_identity == ("data-job-ref",)
    assert report.chosen_level == "detected"
    assert report.detected_parent_count == 1


def test_empty_group_returns_defaults() -> None:
    job_cards, report = resolve_card_group([], _chain(_node()), PAGE_URL)
    assert job_cards == []
    assert report.learned_identity == ()
    assert report.chosen_level == "detected"
    assert report.detected_parent_count == 0

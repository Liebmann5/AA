"""Adapter-level pins: analyze_serp through the real segmentation service.

Trees are synthetic shapes that satisfy the structural card detector
(container tag, area >= 1500, text present, interactive marker, identical
structure across siblings). No fixture carries a real provider's markup.
"""

from __future__ import annotations

from auto_apply.adapters.secondary.perception.math_dom_adapter import (
    MathPageUnderstandingAdapter,
)
from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.ports.page_understanding_port import (
    CardResolutionState,
    NullPageUnderstandingAdapter,
    PageContext,
)
from auto_apply.domain.services.dom_segmentation import MathFormUnderstandingService

PAGE_URL = "https://serp.example.test/search"


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


def _anchorful_card(index: int, y: float) -> DOMNode:
    return _node(
        attrs=(("role", "button"), ("class", "jc")),
        geom=Geometry(x=0, y=y, width=200, height=100),
        children=(
            _node(attrs=(("role", "heading"),), text=f"Field Engineer {index}", depth=2),
            _node(text=f"Utility Group {index}", depth=2),
            _node(
                tag="a",
                attrs=(("href", f"/openings/eng-{index}"),),
                text="Apply now for this role",
                depth=2,
            ),
        ),
        depth=1,
    )


def _anchorless_card(ref: str, y: float) -> DOMNode:
    return _node(
        attrs=(("role", "button"), ("class", "jc"), ("data-job-ref", ref)),
        geom=Geometry(x=0, y=y, width=200, height=100),
        children=(
            _node(attrs=(("role", "heading"),), text=f"Field Engineer {ref}", depth=2),
            _node(text=f"Utility Group {ref}", depth=2),
        ),
        depth=1,
    )


def _adapter_for(root: DOMNode) -> MathPageUnderstandingAdapter:
    class _StubDom:
        def extract_full_dom_tree(self):
            return root

    return MathPageUnderstandingAdapter(_StubDom(), MathFormUnderstandingService())


def test_analyze_serp_resolves_anchorful_group_with_absolute_urls() -> None:
    cards = [_anchorful_card(i, y=i * 110) for i in range(3)]
    root = _node(tag="body", children=(_node(children=tuple(cards), depth=2),))

    structure = _adapter_for(root).analyze_serp(PageContext(url=PAGE_URL))

    assert len(structure.job_cards) == 3
    for i, card in enumerate(structure.job_cards):
        assert card.resolution_state == CardResolutionState.RESOLVED.value
        assert card.url == f"https://serp.example.test/openings/eng-{i}"
    assert structure.resolution_report.chosen_level == "detected"


def test_analyze_serp_anchorless_group_keeps_learned_identity() -> None:
    cards = [_anchorless_card("k101", 0), _anchorless_card("k102", 110), _anchorless_card("k103", 220)]
    root = _node(tag="body", children=(_node(children=tuple(cards), depth=2),))

    structure = _adapter_for(root).analyze_serp(PageContext(url=PAGE_URL))

    assert len(structure.job_cards) == 3
    for card, ref in zip(structure.job_cards, ("k101", "k102", "k103")):
        assert card.resolution_state == CardResolutionState.NO_DESTINATION.value
        assert card.url == ""
        assert card.identity_attribute == "data-job-ref"
        assert card.identity_value == ref
    assert structure.resolution_report.learned_identity == ("data-job-ref",)
    assert structure.resolution_report.detected_parent_count == 1


def test_analyze_serp_on_barren_page_returns_empty_with_default_report() -> None:
    root = _node(
        tag="body",
        children=(_node(text="no repeated structure here", depth=1),),
    )

    structure = _adapter_for(root).analyze_serp(PageContext(url=PAGE_URL))

    assert structure.job_cards == ()
    assert structure.resolution_report.learned_identity == ()
    assert structure.page_pass_yield is False


def test_null_adapter_still_returns_empty_structure() -> None:
    structure = NullPageUnderstandingAdapter().analyze_serp(PageContext(url=PAGE_URL))
    assert structure.job_cards == ()
    assert structure.resolution_report.learned_identity == ()

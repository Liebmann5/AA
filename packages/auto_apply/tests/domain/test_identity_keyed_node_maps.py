"""Pins for identity-keyed node maps in ``MathFormUnderstandingService``.

Why this stage exists, in one measurement. On a live Google SERP the fast
extraction route reached ``analyze()`` in 0.21 s and then did not finish for
six minutes. The traceback landed on ``self._parent_map[curr]`` with
``DOMNode.__hash__`` recursing 25 frames deep. Profiling one reproduction:
116,585,460 calls to ``builtins.hash``, and **31,023 dict lookups costing 35
seconds — 1.1 ms each**. ``DOMNode`` is a frozen dataclass, so its generated
hash recurses through ``children``: hashing one node hashes its whole subtree,
and nothing caches it.

Speed is only half of it. ``DOMNode`` equality is structural, so two identical
sibling job cards are *the same dict key*. A node-keyed parent map collapses
them and returns the wrong parent. On a SERP — repeated identical cards, by
definition — that is most of the page.

The fix keys the maps in this module by ``id(node)``. ``DOMNode`` itself is
untouched: its value semantics are pinned deliberately elsewhere
(``test_domnode_in_set``, ``test_domnode_in_dict``,
``test_domnode_structural_equality``), and an identity ``__hash__`` on the
model breaks all three. ``test_domnode_value_semantics_are_untouched`` below
guards that tempting wrong fix from being applied later.

Pin labelling, honestly — measured against the pre-stage tree, not assumed:

* **5 teeth** — fail on the pre-stage tree for the reason they state:
  ``test_parent_map_is_keyed_by_identity``,
  ``test_identical_siblings_get_their_own_parent``,
  ``test_identical_containers_score_the_same_as_distinct_ones``,
  ``test_analyze_finishes_on_a_serp_sized_tree``,
  ``test_parent_map_covers_every_node`` (this one was drafted as a regression
  guard and turned out to bite: pre-stage the map is *smaller* than the tree,
  because value-equal nodes share a key).
* **4 behaviour-preserving** — pass on both trees, so they are regression
  guards rather than evidence.
"""

import time

import pytest

from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.services.dom_segmentation import MathFormUnderstandingService


def _geo(i: int = 0) -> Geometry:
    return Geometry(x=10.0, y=float(i % 2000), width=280.0, height=32.0)


def _card() -> DOMNode:
    """A leaf shaped like a job card. Two calls give equal-but-distinct nodes."""
    return DOMNode(tag="div", text="Job", geometry=_geo(1))


def _serp_sized_tree(n_inputs: int, n_labels: int, n_filler: int) -> DOMNode:
    """A tree with the element mix a real SERP has.

    The mix is the point. An earlier timing of ``analyze()`` used a tree of
    ``div``/``span``/``a`` only — no interactables — so ``_find_form_containers``
    returned nothing, ``_analyze_form_container`` never ran, and the pathological
    path was never entered. That measurement reported 0.006 s and was
    structurally blind to this bug. Inputs and labels are what exercise it.
    """
    leaves: list[DOMNode] = [
        DOMNode(
            tag="input",
            attributes=(("type", "text"), ("name", f"f{i}")),
            geometry=_geo(i),
        )
        for i in range(n_inputs)
    ]
    leaves += [
        DOMNode(tag="span", text=f"Label text {i}", geometry=_geo(i))
        for i in range(n_labels)
    ]
    leaves += [DOMNode(tag="div", text="", geometry=_geo(i)) for i in range(n_filler)]

    layer = leaves
    while len(layer) > 1:
        layer = [
            DOMNode(tag="div", children=tuple(layer[i : i + 4]), geometry=_geo(i))
            for i in range(0, len(layer), 4)
        ]
    return DOMNode(tag="body", children=tuple(layer), geometry=_geo(0))


# ===========================================================================
# TEETH — these fail on the pre-stage tree
# ===========================================================================


def test_parent_map_is_keyed_by_identity():
    """The map's keys must be ``id()`` values, not nodes.

    This is the whole stage in one assertion: a node-keyed map is both O(subtree)
    per lookup and wrong for equal siblings.
    """
    svc = MathFormUnderstandingService()
    root = DOMNode(tag="body", children=(_card(), _card()), geometry=_geo())

    parent_map = svc._build_parent_map(root)

    assert parent_map, "parent map is empty"
    assert all(isinstance(k, int) for k in parent_map), (
        "MathFormUnderstandingService._build_parent_map is keyed by DOMNode. "
        "DOMNode is a frozen dataclass whose generated __hash__ recurses through "
        "children, so every lookup hashes an entire subtree and is not cached — "
        "measured at ~1.1 ms per lookup on a 2,641-node Google SERP, which is "
        "what made analyze() take six minutes. Key by id(node)."
    )


def test_identical_siblings_get_their_own_parent():
    """Two equal-but-distinct cards must not collapse into one key."""
    svc = MathFormUnderstandingService()
    left, right = _card(), _card()
    assert left == right, "fixture is wrong: the two cards should be value-equal"
    assert left is not right, "fixture is wrong: they should be distinct objects"

    parent_left = DOMNode(tag="li", children=(left,), geometry=_geo())
    parent_right = DOMNode(tag="li", children=(right,), geometry=_geo())
    root = DOMNode(tag="ul", children=(parent_left, parent_right), geometry=_geo())

    parent_map = svc._build_parent_map(root)

    assert parent_map.get(id(left)) is parent_left, (
        "The parent map returns the wrong parent for structurally identical "
        "siblings. DOMNode equality is structural, so two identical job cards "
        "are the same dict key and the second overwrites the first. A SERP is "
        "repeated identical cards by definition, so this is most of the page — "
        "a correctness bug, not only a slow one."
    )
    assert parent_map.get(id(right)) is parent_right


def test_identical_containers_score_the_same_as_distinct_ones():
    """Repeated content must not change which subtree wins.

    ``_find_form_containers`` scores a node by how many interactables it
    contains, then greedily takes the highest scorer. With node-keyed maps, two
    identical forms shared a key and their inputs merged, so the enclosing body
    scored 2 instead of 4 and lost a tie it should have won — the same page
    shape gave a different answer purely because its content repeated.

    The assertion is the property, not the value: identical forms and distinct
    forms must select the same container.
    """
    svc = MathFormUnderstandingService()

    def form(prefix: str) -> DOMNode:
        return DOMNode(
            tag="form",
            geometry=_geo(),
            children=(
                DOMNode(
                    tag="input",
                    attributes=(("name", prefix + "a"),),
                    geometry=_geo(1),
                ),
                DOMNode(
                    tag="input",
                    attributes=(("name", prefix + "b"),),
                    geometry=_geo(2),
                ),
            ),
        )

    distinct = DOMNode(tag="body", children=(form("x"), form("y")), geometry=_geo())
    identical = DOMNode(tag="body", children=(form("z"), form("z")), geometry=_geo())

    picked_distinct = [
        n.tag
        for n in svc._find_form_containers(
            distinct, svc._extract_interactables(distinct)
        )
    ]
    picked_identical = [
        n.tag
        for n in svc._find_form_containers(
            identical, svc._extract_interactables(identical)
        )
    ]

    assert picked_identical == picked_distinct, (
        f"Two identical forms select {picked_identical} while two distinct "
        f"forms of the same shape select {picked_distinct}. node_to_inputs is "
        f"keyed by DOMNode, so identical containers share a key and their input "
        f"sets merge — the score no longer reflects how many inputs a subtree "
        f"actually holds. A SERP is repeated identical cards by definition."
    )


def test_analyze_finishes_on_a_serp_sized_tree():
    """A tree the size of a real SERP must analyse in well under a second.

    Budget is deliberately loose. Pre-stage this shape measured 21.74 s;
    post-stage it measures ~0.02 s. Five seconds sits far from both, so the pin
    discriminates the bug without being a machine-speed test.
    """
    svc = MathFormUnderstandingService()
    root = _serp_sized_tree(n_inputs=24, n_labels=400, n_filler=2200)

    started = time.perf_counter()
    svc.analyze(root, url="https://example.test/jobs", title="Jobs")
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0, (
        f"analyze() took {elapsed:.1f}s on a SERP-sized tree. Over 99% of that "
        f"is DOMNode.__hash__: the label/input cost matrix calls _tree_distance "
        f"per cell, which walks the parent map, which hashes a whole subtree per "
        f"lookup. On the live Google SERP that produced a six-minute hang inside "
        f"the fast extraction route."
    )


# ===========================================================================
# BEHAVIOUR-PRESERVING — these pass on both trees
# ===========================================================================


def test_domnode_value_semantics_are_untouched():
    """The fix must stay inside this module.

    Giving DOMNode an identity __hash__ also makes analyze() fast, and breaks
    test_domnode_structural_equality, test_domnode_in_set and
    test_domnode_in_dict, which pin value semantics on purpose. This pin makes
    that trade explicit so nobody re-discovers it the expensive way.
    """
    a, b = _card(), _card()
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1


def test_parent_map_covers_every_node():
    svc = MathFormUnderstandingService()
    root = _serp_sized_tree(n_inputs=2, n_labels=4, n_filler=8)

    parent_map = svc._build_parent_map(root)

    assert len(parent_map) == sum(1 for _ in root.iter_nodes())
    assert parent_map[id(root)] is None


def test_node_depth_counts_edges_from_the_root():
    svc = MathFormUnderstandingService()
    leaf = DOMNode(tag="span", text="x", geometry=_geo())
    mid = DOMNode(tag="div", children=(leaf,), geometry=_geo())
    root = DOMNode(tag="body", children=(mid,), geometry=_geo())
    svc._parent_map = svc._build_parent_map(root)

    assert svc._node_depth(root) == 0
    assert svc._node_depth(mid) == 1
    assert svc._node_depth(leaf) == 2


def test_tree_distance_between_siblings_is_two():
    svc = MathFormUnderstandingService()
    left = DOMNode(tag="span", text="l", geometry=_geo())
    right = DOMNode(tag="input", attributes=(("name", "r"),), geometry=_geo())
    root = DOMNode(tag="body", children=(left, right), geometry=_geo())
    svc._parent_map = svc._build_parent_map(root)

    assert svc._tree_distance(left, left) == 0
    assert svc._tree_distance(left, right) == 2


def test_analyze_still_detects_a_form():
    """The speed fix must not cost the capability it speeds up."""
    svc = MathFormUnderstandingService()
    form = DOMNode(
        tag="form",
        geometry=_geo(),
        children=(
            DOMNode(tag="span", text="Email", geometry=_geo(1)),
            DOMNode(tag="input", attributes=(("name", "email"),), geometry=_geo(2)),
            DOMNode(tag="span", text="Full name", geometry=_geo(3)),
            DOMNode(tag="input", attributes=(("name", "name"),), geometry=_geo(4)),
        ),
    )
    root = DOMNode(tag="body", children=(form,), geometry=_geo())

    structure = svc.analyze(root, url="https://example.test/apply", title="Apply")

    assert structure.forms, "no form region detected on a two-input form"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])

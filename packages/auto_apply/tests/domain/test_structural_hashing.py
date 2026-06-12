"""Unit tests for domain/services/structural_hashing.py."""

import pytest

from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.services.structural_hashing import (
    are_structurally_identical,
    compute_structural_hash,
    compute_structural_hash_shallow,
    find_repeated_patterns,
    group_by_structural_hash,
)


# ── compute_structural_hash ──────────────────────────────────────────────────

def test_identical_leaf_nodes_same_hash():
    a = DOMNode(tag="div", attributes={"class": "card"}, depth=0)
    b = DOMNode(tag="div", attributes={"class": "card"}, depth=0)
    assert compute_structural_hash(a) == compute_structural_hash(b)


def test_different_tags_different_hash():
    a = DOMNode(tag="div", depth=0)
    b = DOMNode(tag="span", depth=0)
    assert compute_structural_hash(a) != compute_structural_hash(b)


def test_different_classes_same_hash():
    """Attributes are intentionally ignored — class="card" vs "row" should produce the same hash."""
    a = DOMNode(tag="div", attributes={"class": "card"}, depth=0)
    b = DOMNode(tag="div", attributes={"class": "row"}, depth=0)
    assert compute_structural_hash(a) == compute_structural_hash(b)


def test_classes_ignored_both_ways():
    """A node with no class and a node with a class are structurally identical."""
    a = DOMNode(tag="div", depth=0)
    b = DOMNode(tag="div", attributes={"class": "card"}, depth=0)
    assert compute_structural_hash(a) == compute_structural_hash(b)


def test_text_content_does_not_affect_hash():
    a = DOMNode(tag="p", text="Hello world", depth=0)
    b = DOMNode(tag="p", text="Completely different text", depth=0)
    assert compute_structural_hash(a) == compute_structural_hash(b)


def test_geometry_does_not_affect_hash():
    a = DOMNode(tag="div", geometry=Geometry(x=0, y=0, width=100, height=50), depth=0)
    b = DOMNode(tag="div", geometry=Geometry(x=999, y=999, width=1, height=1), depth=0)
    assert compute_structural_hash(a) == compute_structural_hash(b)


def test_children_affect_hash():
    child = DOMNode(tag="span", depth=1)
    with_child = DOMNode(tag="div", depth=0, children=[child])
    without_child = DOMNode(tag="div", depth=0)
    assert compute_structural_hash(with_child) != compute_structural_hash(without_child)


def test_child_order_affects_hash():
    child_a = DOMNode(tag="p", depth=1)
    child_b = DOMNode(tag="span", depth=1)
    node1 = DOMNode(tag="div", depth=0, children=[child_a, child_b])
    node2 = DOMNode(tag="div", depth=0, children=[child_b, child_a])
    assert compute_structural_hash(node1) != compute_structural_hash(node2)


def test_hash_is_deterministic():
    node = DOMNode(tag="div", attributes={"class": "container row"}, depth=0)
    assert compute_structural_hash(node) == compute_structural_hash(node)


def test_hash_is_hex_string():
    node = DOMNode(tag="div", depth=0)
    h = compute_structural_hash(node)
    assert isinstance(h, str)
    assert len(h) == 32
    int(h, 16)  # must be valid hex


# ── compute_structural_hash_shallow ─────────────────────────────────────────

def test_shallow_includes_child_count_but_ignores_child_structure():
    # Two 'div' nodes, each with exactly one child of a different tag.
    parent_a = DOMNode(tag="div", depth=0, children=[DOMNode(tag="span", depth=1)])
    parent_b = DOMNode(tag="div", depth=0, children=[DOMNode(tag="p", depth=1)])
    # Shallow hashes should be equal because they both have 1 child (tag and count match, child structure is ignored).
    assert compute_structural_hash_shallow(parent_a) == compute_structural_hash_shallow(parent_b)

    # A 'div' node with no children.
    parent_c = DOMNode(tag="div", depth=0)
    # Should NOT be equal because child count differs.
    assert compute_structural_hash_shallow(parent_a) != compute_structural_hash_shallow(parent_c)


def test_shallow_still_differs_by_tag():
    a = DOMNode(tag="div", depth=0)
    b = DOMNode(tag="article", depth=0)
    assert compute_structural_hash_shallow(a) != compute_structural_hash_shallow(b)


# ── are_structurally_identical ───────────────────────────────────────────────

def test_identical_trees():
    child = DOMNode(tag="span", attributes={"class": "icon"}, depth=1)
    a = DOMNode(tag="div", attributes={"class": "card"}, depth=0, children=[child])
    b = DOMNode(tag="div", attributes={"class": "card"}, depth=0, children=[
        DOMNode(tag="span", attributes={"class": "icon"}, depth=1)
    ])
    assert are_structurally_identical(a, b)


def test_non_identical_trees():
    a = DOMNode(tag="div", depth=0)
    b = DOMNode(tag="section", depth=0)
    assert not are_structurally_identical(a, b)


# ── group_by_structural_hash ─────────────────────────────────────────────────

def test_group_by_hash_clusters_identical_nodes():
    card1 = DOMNode(tag="div", attributes={"class": "card"}, depth=0)
    card2 = DOMNode(tag="div", attributes={"class": "card"}, depth=0)
    other = DOMNode(tag="span", depth=0)
    groups = group_by_structural_hash([card1, card2, other])
    assert len(groups) == 2
    card_hash = compute_structural_hash(card1)
    assert len(groups[card_hash]) == 2


def test_group_by_hash_single_node():
    node = DOMNode(tag="p", depth=0)
    groups = group_by_structural_hash([node])
    assert len(groups) == 1


def test_group_by_hash_empty():
    assert group_by_structural_hash([]) == {}


# ── find_repeated_patterns ───────────────────────────────────────────────────

def test_find_repeated_patterns_detects_job_cards():
    def _card():
        return DOMNode(
            tag="div",
            attributes={"class": "job-card"},
            depth=1,
            children=[DOMNode(tag="h3", depth=2), DOMNode(tag="p", depth=2)],
        )

    root = DOMNode(
        tag="section",
        depth=0,
        children=[_card(), _card(), _card()],
    )
    patterns = find_repeated_patterns(root, min_occurrences=2)
    assert len(patterns) >= 1
    assert any(len(group) >= 2 for group in patterns)


def test_find_repeated_patterns_no_repeats():
    root = DOMNode(
        tag="div",
        depth=0,
        children=[
            DOMNode(tag="header", depth=1, children=[DOMNode(tag="h1", depth=2)]),
            DOMNode(tag="main", depth=1, children=[DOMNode(tag="p", depth=2)]),
        ],
    )
    patterns = find_repeated_patterns(root, min_occurrences=3)
    assert patterns == []
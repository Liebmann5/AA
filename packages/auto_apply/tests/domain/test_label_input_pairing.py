"""Unit tests for domain/services/label_input_pairing.py — Hungarian algorithm pairing."""

from unittest.mock import patch

import pytest

from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.services.label_input_pairing import (
    assign_labels_to_inputs,
    build_parent_map,
    hungarian_assign,
    pairing_cost,
    tree_distance,
)

_TREE_DISTANCE_PATH = "auto_apply.domain.services.label_input_pairing.tree_distance"


# ── hungarian_assign ─────────────────────────────────────────────────────────

def test_hungarian_empty_matrix():
    rows, cols = hungarian_assign([])
    assert rows == []
    assert cols == []


def test_hungarian_1x1():
    rows, cols = hungarian_assign([[5.0]])
    assert len(rows) == 1
    assert rows[0] == 0
    assert cols[0] == 0


def test_hungarian_2x2_optimal():
    # Cost: [[4, 1], [2, 3]] — optimal: (0,1)=1 + (1,0)=2 = 3
    cost = [[4.0, 1.0], [2.0, 3.0]]
    rows, cols = hungarian_assign(cost)
    total = sum(cost[r][c] for r, c in zip(rows, cols))
    assert total == pytest.approx(3.0)


def test_hungarian_3x3_docstring_example():
    # Docstring assigns [(0,1),(1,0),(2,2)]:
    # cost[0][1]=1, cost[1][0]=2, cost[2][2]=2 → total = 5
    cost = [[4.0, 1.0, 3.0], [2.0, 0.0, 5.0], [3.0, 2.0, 2.0]]
    rows, cols = hungarian_assign(cost)
    total = sum(cost[r][c] for r, c in zip(rows, cols))
    assert total == pytest.approx(5.0)


def test_hungarian_identity_optimal():
    n = 4
    cost = [[1000.0] * n for _ in range(n)]
    for i in range(n):
        cost[i][i] = 0.0
    rows, cols = hungarian_assign(cost)
    total = sum(cost[r][c] for r, c in zip(rows, cols))
    assert total == pytest.approx(0.0)


def test_hungarian_returns_all_assignments():
    cost = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
    rows, cols = hungarian_assign(cost)
    assert len(rows) == 3
    assert len(cols) == 3
    assert len(set(rows)) == 3
    assert len(set(cols)) == 3


# ── pairing_cost ─────────────────────────────────────────────────────────────

def test_pairing_cost_close_nodes():
    inp = DOMNode(tag="input", geometry=Geometry(x=100, y=100, width=200, height=40))
    lbl = DOMNode(tag="label", geometry=Geometry(x=100, y=70, width=80, height=20))
    cost = pairing_cost(inp, lbl, max_distance=500.0)
    assert cost < 100.0


def test_pairing_cost_far_nodes_saturates():
    inp = DOMNode(tag="input", geometry=Geometry(x=0, y=0, width=100, height=40))
    lbl = DOMNode(tag="label", geometry=Geometry(x=10000, y=10000, width=80, height=20))
    cost = pairing_cost(inp, lbl, max_distance=500.0)
    assert cost >= 500.0


def test_pairing_cost_no_geometry_returns_max():
    inp = DOMNode(tag="input")
    lbl = DOMNode(tag="label")
    cost = pairing_cost(inp, lbl, max_distance=500.0)
    assert cost == pytest.approx(500.0)


def test_pairing_cost_with_dom_penalty():
    """DOM penalty adds to cost; tree_distance patched to bypass DOMNode hash bug."""
    inp = DOMNode(tag="input", geometry=Geometry(x=100, y=100, width=200, height=40))
    lbl = DOMNode(tag="label", geometry=Geometry(x=100, y=70, width=80, height=20))
    cost_without = pairing_cost(inp, lbl)

    with patch(_TREE_DISTANCE_PATH, return_value=10):
        cost_with = pairing_cost(inp, lbl, parent_map={"_": None})

    assert cost_with > cost_without


# ── tree_distance (DOMNode is hashable: __hash__ = id(self)) ─────────────────

def test_tree_distance_same_node_is_zero():
    root = DOMNode(tag="div", depth=0)
    parent_map = {root: None}
    assert tree_distance(root, root, parent_map) == 0


def test_tree_distance_parent_child_is_one():
    parent = DOMNode(tag="div", depth=0)
    child = DOMNode(tag="input", depth=1)
    parent_map = {parent: None, child: parent}
    assert tree_distance(parent, child, parent_map) == 1


def test_tree_distance_siblings_is_two():
    root = DOMNode(tag="form", depth=0)
    sibling_a = DOMNode(tag="input", depth=1)
    sibling_b = DOMNode(tag="label", depth=1)
    parent_map = {root: None, sibling_a: root, sibling_b: root}
    assert tree_distance(sibling_a, sibling_b, parent_map) == 2


def test_tree_distance_cousins():
    root = DOMNode(tag="form", depth=0)
    div_a = DOMNode(tag="div", depth=1)
    div_b = DOMNode(tag="div", depth=1)
    inp = DOMNode(tag="input", depth=2)
    lbl = DOMNode(tag="label", depth=2)
    parent_map = {root: None, div_a: root, div_b: root, inp: div_a, lbl: div_b}
    assert tree_distance(inp, lbl, parent_map) == 4


# ── build_parent_map (DOMNode is hashable: __hash__ = id(self)) ──────────────

def test_build_parent_map_root_is_none():
    root = DOMNode(tag="div", depth=0)
    pm = build_parent_map(root)
    assert pm[root] is None


def test_build_parent_map_children_point_to_parent():
    child = DOMNode(tag="input", depth=1)
    root = DOMNode(tag="form", depth=0, children=(child,))
    pm = build_parent_map(root)
    assert pm.get(child) == root


def test_build_parent_map_deep_tree():
    grandchild = DOMNode(tag="input", depth=2)
    child = DOMNode(tag="div", depth=1, children=(grandchild,))
    root = DOMNode(tag="form", depth=0, children=(child,))
    pm = build_parent_map(root)
    assert pm.get(grandchild) == child
    assert pm.get(child) == root
    assert pm.get(root) is None


# ── assign_labels_to_inputs ───────────────────────────────────────────────────

def test_assign_no_inputs():
    result = assign_labels_to_inputs([], [], {})
    assert result == []


def test_assign_no_labels():
    inp = DOMNode(tag="input", depth=1)
    result = assign_labels_to_inputs([inp], [], {})
    assert result == [(inp, None)]


def test_assign_one_to_one_close_pair(simple_form_root):
    inputs = simple_form_root.find_by_tag("input")
    labels = simple_form_root.find_by_tag("label")
    # parent_map=None skips DOM penalty and avoids unhashable-DOMNode bug
    pairs = assign_labels_to_inputs(inputs, labels, None)
    assert len(pairs) == 1
    assert pairs[0][0] is inputs[0]
    assert pairs[0][1] is labels[0]


def test_assign_more_labels_than_inputs_terminates_and_pairs_nearest():
    """Regression: more labels than inputs must NOT hang.

    The square cost matrix gains all-dummy rows; padding them with +inf used to
    spin the solver forever. With a finite penalty it terminates and the input
    is paired to its nearest label.
    """
    inp = DOMNode(tag="input", attributes=(("name", "q"),), geometry=Geometry(60, 0, 100, 20))
    near = DOMNode(tag="label", text="Email", geometry=Geometry(0, 0, 50, 20))
    far1 = DOMNode(tag="label", text="Phone", geometry=Geometry(0, 200, 50, 20))
    far2 = DOMNode(tag="label", text="Name", geometry=Geometry(0, 400, 50, 20))

    pairs = assign_labels_to_inputs([inp], [near, far1, far2], None)

    assert len(pairs) == 1
    assert pairs[0][0] is inp
    assert pairs[0][1] is near


def test_hungarian_does_not_hang_on_all_dummy_row():
    """A finite-padded square matrix with a high-cost row stays solvable."""
    pad = 1e9
    cost = [[5.0, 8.0], [pad, pad]]
    rows, cols = hungarian_assign(cost)
    assert len(rows) == 2
    # Real row 0 takes its cheaper real column.
    assignment = dict(zip(rows, cols))
    assert assignment[0] == 0
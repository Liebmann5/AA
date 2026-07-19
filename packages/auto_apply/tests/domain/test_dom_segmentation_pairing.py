"""Tests for MathFormUnderstandingService label↔input pairing (BUG-4).

The Hungarian cost matrix is padded to a square. Padding cells must use +inf,
not 0.0 — a 0.0 pad is the cheapest cell in the matrix and can divert a real
input onto a dummy column, leaving a labelable input unlabeled. These tests
exercise the padded (non-square) path and assert the input keeps its real,
nearest label.
"""

from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.services.dom_segmentation import MathFormUnderstandingService


def test_input_gets_nearest_label_under_matrix_padding():
    svc = MathFormUnderstandingService()

    near = DOMNode(tag="label", text="Email", geometry=Geometry(0, 0, 50, 20), depth=2)
    far = DOMNode(tag="label", text="Phone", geometry=Geometry(0, 500, 50, 20), depth=2)
    inp = DOMNode(
        tag="input",
        attributes=(("name", "email"),),
        geometry=Geometry(60, 0, 100, 20),
        depth=2,
    )
    # 1 input × 2 labels → non-square → exercises the square padding.
    context = DOMNode(tag="form", depth=1, children=(near, inp, far))

    fields = svc._pair_labels_to_inputs([inp], context)

    assert len(fields) == 1
    # The input must be paired to the nearby label, never left unlabeled by a
    # zero-cost dummy padding cell.
    assert fields[0].label_node is not None
    assert fields[0].label_text == "Email"


def test_more_inputs_than_labels_still_labels_the_closest():
    svc = MathFormUnderstandingService()

    label = DOMNode(tag="label", text="Email", geometry=Geometry(0, 0, 50, 20), depth=2)
    close_input = DOMNode(
        tag="input", attributes=(("name", "email"),),
        geometry=Geometry(60, 0, 100, 20), depth=2,
    )
    far_input = DOMNode(
        tag="input", attributes=(("name", "other"),),
        geometry=Geometry(60, 800, 100, 20), depth=2,
    )
    # 2 inputs × 1 label → dummy column; the closer input should win the label.
    context = DOMNode(tag="form", depth=1, children=(label, close_input, far_input))

    fields = svc._pair_labels_to_inputs([close_input, far_input], context)

    by_input = {id(f.input_node): f for f in fields}
    assert by_input[id(close_input)].label_text == "Email"


# ── _is_descendant: uses the cached parent map (no per-call O(n²) rebuild) ─────

def _tree():
    grandchild = DOMNode(tag="input", attributes=(("name", "q"),), depth=2)
    child_a = DOMNode(tag="div", depth=1, children=(grandchild,))
    child_b = DOMNode(tag="span", text="x", depth=1)
    root = DOMNode(tag="div", depth=0, children=(child_a, child_b))
    return root, child_a, child_b, grandchild


def test_is_descendant_uses_cached_parent_map_without_rebuilding():
    svc = MathFormUnderstandingService()
    root, child_a, _child_b, grandchild = _tree()
    svc._parent_map = svc._build_parent_map(root)

    # Any rebuild during the membership test would be the O(n²) regression.
    def _boom(_root):
        raise AssertionError("_build_parent_map must not be called when cache exists")

    svc._build_parent_map = _boom

    assert svc._is_descendant(grandchild, root) is True
    assert svc._is_descendant(grandchild, child_a) is True
    assert svc._is_descendant(root, root) is True
    assert svc._is_descendant(child_a, grandchild) is False


def test_is_descendant_falls_back_to_local_build_without_cache():
    svc = MathFormUnderstandingService()  # fresh: no _parent_map attribute
    root, _child_a, _child_b, grandchild = _tree()
    assert svc._is_descendant(grandchild, root) is True
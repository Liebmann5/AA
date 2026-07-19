"""Computational geometry for Z-axis ray casting.

Defeats 'clickjacking' and transparent overlay traps. By shooting a
mathematical ray through the exact centre of a target element, we calculate
whether any other DOM node intercepts the ray before it hits the target.

Limitation: z-index, pointer-events, and opacity are read from the element's
inline *style* attribute only. Computed styles (cascaded CSS rules, stylesheet
classes) are not visible here. A deeper implementation using Chrome DevTools
Protocol's ``DOMSnapshot.captureSnapshot`` command (Session 8) or
``getComputedStyle`` via script injection (Session 5) will be required for
sites that set these properties via external CSS rather than inline style.
"""

from __future__ import annotations

import re

from auto_apply.domain.models.math_dom import DOMNode


def _parse_style_value(style: str, property_name: str) -> str:
    """Return the value of a single CSS property from an inline style string.

    Handles both ``property: value`` and ``property:value`` (no space) forms.
    Returns an empty string when the property is absent.
    """
    pattern = re.compile(
        r"(?:^|;)\s*" + re.escape(property_name) + r"\s*:\s*([^;]+)",
        re.IGNORECASE,
    )
    match = pattern.search(style)
    return match.group(1).strip() if match else ""


def _get_z_index(node: DOMNode) -> int:
    """Extract and safely parse the z-index from the node's inline style.

    Returns 0 for 'auto', missing, or unparseable values.
    """
    style = node.get_attribute("style", "")
    z_str = _parse_style_value(style, "z-index")
    if not z_str or z_str == "auto":
        return 0
    try:
        return int(z_str)
    except ValueError:
        return 0


def _is_pointer_events_none(node: DOMNode) -> bool:
    """Return True if the node has ``pointer-events: none`` in its inline style."""
    style = node.get_attribute("style", "")
    return _parse_style_value(style, "pointer-events").lower() == "none"


def _is_opacity_zero(node: DOMNode) -> bool:
    """Return True if the node's inline opacity is effectively zero (< 0.05)."""
    style = node.get_attribute("style", "")
    value = _parse_style_value(style, "opacity")
    if not value:
        return False
    try:
        return float(value) < 0.05
    except ValueError:
        return False


def is_occluded(
    target_node: DOMNode,
    all_nodes_in_paint_order: list[DOMNode],
    parent_map: dict[DOMNode, DOMNode | None],
) -> tuple[bool, str]:
    """Determine if the target_node is covered by a trap overlay.

    Shoots a ray through the centre of *target_node* and checks whether any
    other node in paint order covers that point with a higher effective
    stacking level.

    Args:
        target_node: The node we intend to click or interact with.
        all_nodes_in_paint_order: Flattened list of DOM nodes.
        parent_map: Mapping of node → parent, used to verify tree hierarchy.

    Returns:
        ``(True, reason)`` if the target is occluded; ``(False, "")`` otherwise.
    """
    if not target_node.geometry:
        return False, ""

    cx, cy = target_node.geometry.center
    target_z = _get_z_index(target_node)

    try:
        target_dom_index = all_nodes_in_paint_order.index(target_node)
    except ValueError:
        return False, ""

    for index, node in enumerate(all_nodes_in_paint_order):
        if node is target_node:
            continue

        if not node.geometry or node.geometry.area == 0:
            continue

        if not node.geometry.contains_point(cx, cy):
            continue

        if _is_pointer_events_none(node):
            continue

        node_z = _get_z_index(node)

        is_above = False
        if node_z > target_z:
            is_above = True
        elif node_z == target_z and index > target_dom_index:
            is_above = True

        if is_above:
            # If the candidate is a child/descendant of the target (e.g., an
            # <i> icon inside a <button>), the click will bubble up — not a trap.
            if _is_ancestor(target_node, node, parent_map):
                continue

            node_id = str(id(node))
            if _is_opacity_zero(node):
                return True, f"Transparent overlay trap detected (node {node_id})"

            return True, f"Occluded by overlapping element (node {node_id}, z-index: {node_z})"

    return False, ""


def _is_ancestor(
    ancestor: DOMNode,
    descendant: DOMNode,
    parent_map: dict[DOMNode, DOMNode | None],
) -> bool:
    """Return True if ``ancestor`` is in the parent chain of ``descendant``."""
    current = parent_map.get(descendant)
    while current is not None:
        if current is ancestor:
            return True
        current = parent_map.get(current)
    return False
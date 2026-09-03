"""Deterministic label‑to‑input pairing using the Hungarian algorithm.

This module provides functions to associate form labels with their corresponding
input fields based on spatial proximity and DOM structure. The core algorithm
is a pure‑Python implementation of the Kuhn‑Munkres (Hungarian) method for
solving the assignment problem in O(n³) time.

All functions operate on `DOMNode` objects and require no external libraries.
"""

from __future__ import annotations

import math

from auto_apply.domain.models.math_dom import DOMNode

# Penalty for dummy (padding) cells in the square cost matrix.
_DUMMY_PAIR_COST: float = 1e9


def hungarian_assign(cost_matrix: list[list[float]]) -> tuple[list[int], list[int]]:
    """Solve the minimum‑cost assignment problem using the Hungarian algorithm.

    This implementation works on square matrices. For rectangular problems,
    pad the matrix with rows/columns of zeros (or a large cost) before calling.

    Args:
        cost_matrix: Square matrix (n x n) of non‑negative costs. Lower is better.

    Returns:
        A tuple (row_indices, col_indices) of equal length, where each pair
        (row_indices[i], col_indices[i]) is an optimal assignment.

    Complexity:
        O(n³) time, O(n²) space.

    Example:
        >>> cost = [[4, 1, 3], [2, 0, 5], [3, 2, 2]]
        >>> rows, cols = hungarian_assign(cost)
        >>> list(zip(rows, cols))
        [(0, 1), (1, 0), (2, 2)]
    """
    n = len(cost_matrix)
    if n == 0:
        return [], []

    u: list[float] = [0.0] * (n + 1)
    v: list[float] = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost_matrix[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    row_ind = []
    col_ind = []
    for j in range(1, n + 1):
        if p[j] != 0:
            row_ind.append(p[j] - 1)
            col_ind.append(j - 1)
    return row_ind, col_ind


def pairing_cost(
    input_node: DOMNode,
    label_node: DOMNode,
    max_distance: float = 500.0,
    dom_penalty_weight: float = 1.0,
    parent_map: dict[DOMNode, DOMNode | None] | None = None,
) -> float:
    """Compute the cost of assigning a label to an input.

    The cost is a weighted sum of:
        - Euclidean distance between the centers of the two nodes.
        - DOM tree distance (log‑scaled) to penalize labels far away in the hierarchy.

    If geometry is missing for either node, a large default cost is returned.

    Args:
        input_node: The input element.
        label_node: The candidate label element.
        max_distance: Distance beyond which cost saturates (px).
        dom_penalty_weight: Multiplier for the DOM distance penalty.
        parent_map: Pre‑computed dictionary mapping node → parent. If None,
            DOM distance is not computed (cost is purely spatial).

    Returns:
        A non‑negative cost; lower is better.
    """
    spatial_cost = max_distance
    if input_node.geometry and label_node.geometry:
        dist = input_node.geometry.distance_to(label_node.geometry)
        spatial_cost = min(dist, max_distance)

    dom_cost = 0.0
    if parent_map is not None:
        dom_dist = tree_distance(input_node, label_node, parent_map)
        dom_cost = math.log1p(dom_dist) * dom_penalty_weight

    return spatial_cost + dom_cost


def tree_distance(
    node_a: DOMNode,
    node_b: DOMNode,
    parent_map: dict[DOMNode, DOMNode | None],
) -> int:
    """Compute the distance between two nodes in the DOM tree.

    Distance is defined as the number of edges on the path between the nodes.
    This implementation uses a depth‑equalization approach that correctly
    handles cousin nodes.

    Args:
        node_a: First node.
        node_b: Second node.
        parent_map: Mapping from node to its parent (root maps to None).

    Returns:
        Integer distance (≥ 0). If nodes are not in the same tree, returns a large value.
    """
    # Compute depth of each node
    depth_a = _node_depth(node_a, parent_map)
    depth_b = _node_depth(node_b, parent_map)

    # Equalize depths: move the deeper node up. Every parent lookup goes
    # through a narrowed local because parent_map values are DOMNode | None
    # and mypy cannot narrow through a subscript.
    if depth_a > depth_b:
        distance = depth_a - depth_b
        up_a = node_a
        up_b = node_b
        for _ in range(distance):
            next_a = parent_map.get(up_a)
            if next_a is None:
                return 1_000_000
            up_a = next_a
    else:
        distance = depth_b - depth_a
        up_a = node_a
        up_b = node_b
        for _ in range(distance):
            next_b = parent_map.get(up_b)
            if next_b is None:
                return 1_000_000
            up_b = next_b

    # Move both up together until they meet
    while up_a is not up_b:
        next_a = parent_map.get(up_a)
        next_b = parent_map.get(up_b)
        if next_a is None or next_b is None:
            # Not in the same tree – shouldn't happen
            return 1_000_000
        up_a = next_a
        up_b = next_b
        distance += 2

    return distance


def _node_depth(node: DOMNode, parent_map: dict[DOMNode, DOMNode | None]) -> int:
    """Return the depth of a node (root = 0)."""
    depth = 0
    curr = node
    while True:
        parent = parent_map.get(curr)
        if parent is None:
            return depth
        depth += 1
        curr = parent


def build_parent_map(root: DOMNode) -> dict[DOMNode, DOMNode | None]:
    """Perform a BFS/DFS to map each node to its parent.

    Args:
        root: The root of the DOM tree.

    Returns:
        Dictionary where keys are nodes and values are their parent.
        The root maps to None.
    """
    parent_map: dict[DOMNode, DOMNode | None] = {root: None}
    stack = [root]
    while stack:
        node = stack.pop()
        for child in node.children:
            parent_map[child] = node
            stack.append(child)
    return parent_map


def assign_labels_to_inputs(
    inputs: list[DOMNode],
    label_candidates: list[DOMNode],
    parent_map: dict[DOMNode, DOMNode | None],
    max_distance: float = 500.0,
) -> list[tuple[DOMNode, DOMNode | None]]:
    """Assign each input to its best label candidate using the Hungarian algorithm.

    If there are more inputs than labels, extra inputs will be paired with None.
    If there are more labels than inputs, extra labels are ignored.

    Args:
        inputs: List of input elements.
        label_candidates: List of potential label elements.
        parent_map: Parent map for the entire tree (used for DOM distance).
        max_distance: Maximum spatial distance considered reasonable.

    Returns:
        A list of tuples (input_node, label_node) where label_node may be None
        if no suitable label was found.
    """
    n_inputs = len(inputs)
    n_labels = len(label_candidates)

    if n_inputs == 0:
        return []
    if n_labels == 0:
        return [(inp, None) for inp in inputs]

    cost = [[0.0] * n_labels for _ in range(n_inputs)]
    for i, inp in enumerate(inputs):
        for j, lbl in enumerate(label_candidates):
            cost[i][j] = pairing_cost(inp, lbl, max_distance, parent_map=parent_map)

    size = max(n_inputs, n_labels)
    square_cost = [[_DUMMY_PAIR_COST] * size for _ in range(size)]
    for i in range(n_inputs):
        for j in range(n_labels):
            square_cost[i][j] = cost[i][j]

    row_ind, col_ind = hungarian_assign(square_cost)

    result: list[tuple[DOMNode, DOMNode | None]] = []
    assigned_inputs: set[int] = set()

    for i, j in zip(row_ind, col_ind):
        if i < n_inputs and j < n_labels:
            if cost[i][j] < max_distance * 2:
                result.append((inputs[i], label_candidates[j]))
                assigned_inputs.add(i)

    for i, inp in enumerate(inputs):
        if i not in assigned_inputs:
            result.append((inp, None))

    return result

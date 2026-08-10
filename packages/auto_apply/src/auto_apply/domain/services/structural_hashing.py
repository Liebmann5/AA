"""Deterministic structural hashing for DOM trees.

This module provides functions to compute a fingerprint of a DOMNode's structure,
ignoring text content but considering tag names, attributes (especially class),
and the structure of children. These hashes enable efficient detection of
repeated patterns (e.g., job cards, form rows) without relying on brittle
CSS selectors.
"""

from __future__ import annotations

import hashlib
from typing import Callable

from auto_apply.domain.models.math_dom import DOMNode

# Container tags + minimum rendered area (px²) distinguishing a job/listing card
# from a repeated nav/footer/comment structure. Shared by structural-pattern
# card detection (mathematical_web_analyzer) and listing detection
# (dom_segmentation) so both apply the same guard.
_CARD_CONTAINER_TAGS = frozenset({"div", "li", "article", "tr", "section"})
_MIN_CARD_AREA = 1500.0   #2500.0

# Interactive/structural ARIA roles that mark a real, operable listing card.
# Chrome roles (tab, tablist, navigation, menu, menuitem, option, listbox)
# are deliberately absent so tab bars and filter chips cannot satisfy the
# marker test.
_CARD_MARKER_ROLES = frozenset({"button", "link", "article", "listitem"})

# data-* attributes search engines stamp on essentially every element for
# measurement. They carry no semantic content and must not count as markers.
_TRACKING_DATA_ATTRS = frozenset({"data-hveid", "data-ved", "data-hd", "data-lht"})


def has_semantic_marker(node: DOMNode) -> bool:
    """Return True if the node or any descendant carries a semantic marker.

    A marker is an ARIA role in :data:`_CARD_MARKER_ROLES`, or any ``data-*``
    attribute that is not a known tracking attribute. Class names are never
    consulted: they are obfuscated and rotate per deploy.
    """
    for n in node.iter_nodes():
        role = n.get_attribute("role", "").strip().lower()
        if role in _CARD_MARKER_ROLES:
            return True
        for name, _value in n.attributes:
            if name.startswith("data-") and name not in _TRACKING_DATA_ATTRS:
                return True
    return False


def is_card_like(node: DOMNode) -> bool:
    """Return True if a node looks like a job/listing card.

    A card is a rendered container of sensible size that holds visible text
    and is operable: either it contains at least one link, or it carries a
    semantic marker (interactive ARIA role / non-tracking data-* attribute).
    The marker branch exists because Google's jobs vertical renders real
    cards as ``div[role=button]`` with no anchor anywhere (measured, S8f).

    Used by both card detectors (_detect_job_listings on the SERP fast path
    and MathematicalWebAnalyzer._detect_job_cards on the careers-page path);
    the two MUST stay in lockstep — do not fork this guard per caller.

    Args:
        node: The candidate container node.

    Returns:
        True if the node passes the geometry + structure guard.
    """
    geom = node.geometry
    if geom is None or geom.area < _MIN_CARD_AREA:
        return False
    if node.tag not in _CARD_CONTAINER_TAGS:
        return False
    has_text = any(n.text.strip() for n in node.iter_nodes())
    if not has_text:
        return False
    return len(node.find_by_tag("a")) > 0 or has_semantic_marker(node)


def compute_structural_hash(node: DOMNode) -> str:
    """Return a deterministic hash representing the structural signature of a node.

    The hash is computed recursively:
        base = node.tag + ":" + str(len(node.children))
        child_hashes = concatenation of children's hashes (in order)
        hash = md5(base + child_hashes)

    This ensures that two nodes with the same tag and same child structure 
    (including order) will have identical hashes. We explicitly ignore CSS 
    classes to prevent dynamic obfuscation (e.g. Google SERP) from breaking 
    structural matching.

    Args:
        node: The root of the subtree to hash.

    Returns:
        A 32‑character hexadecimal MD5 hash string.
    """
    # # Sort class names for order independence
    # class_str = node.attributes.get("class", "")
    # classes = sorted(class_str.split())
    # base = node.tag + "".join(classes)
    base = f"{node.tag}:{len(node.children)}"

    # Recursively hash children
    child_hashes = "".join(compute_structural_hash(child) for child in node.children)

    full = base + "[" + child_hashes + "]"
    return hashlib.md5(full.encode("utf-8")).hexdigest()


def compute_structural_hash_shallow(node: DOMNode) -> str:
    """Compute a hash of the node itself, ignoring children.

    Useful for comparing the "type" of a node without considering its contents.
    """
    # class_str = node.attributes.get("class", "")
    # classes = sorted(class_str.split())
    # base = node.tag + "".join(classes)
    base = f"{node.tag}:{len(node.children)}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def group_by_structural_hash(nodes: list[DOMNode]) -> dict:
    """Group a list of nodes by their full structural hash.

    Returns:
        A dictionary mapping hash string to list of nodes with that hash.
    """
    groups: dict = {}
    for node in nodes:
        h = compute_structural_hash(node)
        groups.setdefault(h, []).append(node)
    return groups


def find_repeated_patterns(
    root: DOMNode,
    min_occurrences: int = 2,
    audit_hook: "Callable[[dict, str], None] | None" = None,
) -> list[list[DOMNode]]:
    """Find subtrees that appear multiple times in the DOM.

    This is useful for detecting job cards, product listings, or repeated
    form sections. The algorithm traverses the tree and groups nodes by
    their shallow hash, then checks for structural equality.

    Args:
        root: The root of the DOM tree to search.
        min_occurrences: Minimum number of identical subtrees to consider a pattern.
        audit_hook: Optional callback ``(groups, stage_name) -> None`` invoked
            at each grouping stage, for callers that want to record/audit
            intermediate structural-hash groupings (e.g. the application
            layer's DiscoveryMathAuditor). Domain code stays decoupled from
            any specific application-layer auditor — pass the hook in from
            the caller instead of importing one here. Errors raised by the
            hook are swallowed (best-effort auditing must never break the
            actual pattern-finding computation).

    Returns:
        A list of groups, where each group is a list of nodes that are
        structurally identical.
    """
    # Collect all nodes that could be container candidates
    candidates = []
    for node in root.iter_nodes():
        # Heuristic: only consider elements with a reasonable number of children
        if len(node.children) >= 1 and node.tag not in {"script", "style"}:
            candidates.append(node)

    # Group by shallow hash to reduce expensive full‑hash comparisons
    shallow_groups: dict = {}
    for node in candidates:
        sh = compute_structural_hash_shallow(node)
        shallow_groups.setdefault(sh, []).append(node)

    if audit_hook is not None:
        try:
            audit_hook(shallow_groups, "find_repeated_patterns_shallow")
        except Exception:
            pass

    patterns = []
    for nodes in shallow_groups.values():
        if len(nodes) < min_occurrences:
            continue
        # Within each shallow group, compute full structural hash
        full_groups = group_by_structural_hash(nodes)
        for group_nodes in full_groups.values():
            if len(group_nodes) >= min_occurrences:
                patterns.append(group_nodes)

    if audit_hook is not None:
        try:
            audit_hook(
                {gp[0].structural_hash: gp for gp in patterns},
                "find_repeated_patterns_full",
            )
        except Exception:
            pass

    return patterns


def are_structurally_identical(node_a: DOMNode, node_b: DOMNode) -> bool:
    """Return True if the two subtrees have identical structure.

    This is a more efficient direct comparison that can short‑circuit.
    """
    return compute_structural_hash(node_a) == compute_structural_hash(node_b)
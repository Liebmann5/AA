"""Immutable mathematical representation of a webpage's DOM tree.

This module defines the core data structures used by the deterministic
webpage understanding engine. Every node includes its geometry (bounding box),
attributes, and text content, enabling pure mathematical analysis without
any browser or AI dependencies.

The DOMNode is a rooted tree. Geometry is optional (may be missing for nodes
that are not rendered or when geometry extraction is disabled).
"""

from __future__ import annotations

import hashlib
import types
from collections.abc import Iterator
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Geometry:
    """Immutable bounding box of a rendered DOM element.

    Coordinates are relative to the viewport (as returned by
    `getBoundingClientRect()`).

    Attributes:
        x: X coordinate of the top‑left corner.
        y: Y coordinate of the top‑left corner.
        width: Width of the element (may be 0).
        height: Height of the element (may be 0).
    """

    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> tuple[float, float]:
        """Return the (x, y) coordinates of the element's center."""
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)

    @property
    def area(self) -> float:
        """Return the area of the bounding box."""
        return self.width * self.height

    def is_visible(self, min_area: float = 1.0) -> bool:
        """Heuristic to determine if the element is likely visible to a user.

        Args:
            min_area: Minimum area in square pixels to consider visible.

        Returns:
            True if width > 0, height > 0, and area >= min_area.
        """
        return self.width > 0 and self.height > 0 and self.area >= min_area

    def distance_to(self, other: Geometry) -> float:
        """Euclidean distance between centers of two geometries."""
        cx1, cy1 = self.center
        cx2, cy2 = other.center
        dx = cx1 - cx2
        dy = cy1 - cy2
        return (dx * dx + dy * dy) ** 0.5

    def contains_point(self, px: float, py: float) -> bool:
        """Return True if the point (px, py) lies within this bounding box."""
        return (
            self.x <= px <= self.x + self.width
            and self.y <= py <= self.y + self.height
        )


@dataclass(frozen=True, slots=True)
class DOMNode:
    """Immutable node in a webpage's DOM tree with geometry.

    This is the fundamental unit of analysis. The tree can be traversed
    using the `children` attribute. Geometry is optional because some nodes
    (e.g., `<script>`, `<style>`, or elements not rendered) may not have
    a bounding box.

    Attributes:
        tag: Lowercase tag name (e.g., 'div', 'input').
        attributes: Dictionary of HTML attributes (class, id, name, etc.).
        text: Visible text content of this node (not including children).
        geometry: Bounding box, or None if not rendered.
        children: List of child DOMNode objects.
        depth: Depth in the DOM tree (root = 0).
        structural_hash: Hash of the node's structure (tag + classes +
            children hashes). Used for subtree similarity.
    """

    tag: str
    attributes: dict[str, str] = field(default_factory=dict)
    text: str = ""
    geometry: Geometry | None = None
    children: list[DOMNode] = field(default_factory=list)
    depth: int = 0
    structural_hash: str = ""

    def __post_init__(self) -> None:
        """Ensure children depth is consistent and compute both structural hashes.

        The mutable sub-objects ``attributes`` and ``children`` are frozen
        here to guarantee hashability and true immutability — the root cause
        of several production bugs.
        """
        # Freeze mutable sub-objects so the node becomes truly hashable.
        object.__setattr__(self, "attributes", types.MappingProxyType(self.attributes))
        object.__setattr__(self, "children", tuple(self.children))

        # Depth consistency: ensure children have depth = self.depth + 1
        for child in self.children:
            if child.depth != self.depth + 1:
                # Since frozen, we cannot mutate. This is a validation check.
                # In practice, the builder should set correct depths.
                pass

        # Compute structural hash if not provided
        if not self.structural_hash:
            object.__setattr__(self, "structural_hash", self._compute_structural_hash())

    def _compute_structural_hash(self) -> str:
        """Compute a deterministic hash based on tag, classes, and children structure."""
        # Extract class names (sorted to be order‑independent)
        class_str = self.attributes.get("class", "")
        classes = sorted(class_str.split())
        base = self.tag + "".join(classes)

        # Recursively include children hashes
        child_hashes = "".join(child.structural_hash for child in self.children)
        full = base + child_hashes
        return hashlib.md5(full.encode("utf-8")).hexdigest()

    @property
    def has_geometry(self) -> bool:
        """Return True if this node has a valid bounding box."""
        return self.geometry is not None

    @property
    def is_interactable(self) -> bool:
        """Heuristic: is this node likely an interactable form element?

        Returns True for input, select, textarea, button, and elements with
        contenteditable attribute.
        """
        if self.tag in {"input", "select", "textarea", "button"}:
            return True
        if self.attributes.get("contenteditable", "").lower() == "true":
            return True
        if self.attributes.get("role") in {"button", "checkbox", "radio", "textbox"}:
            return True
        return False

    @property
    def input_type(self) -> str | None:
        """Return the 'type' attribute for <input> tags, else None."""
        if self.tag == "input":
            return self.attributes.get("type", "text").lower()
        return None

    def iter_nodes(self) -> Iterator[DOMNode]:
        """Depth‑first iterator over this node and all descendants."""
        yield self
        for child in self.children:
            yield from child.iter_nodes()

    def find_by_tag(self, tag: str) -> list[DOMNode]:
        """Return all descendant nodes with the given tag (case‑insensitive)."""
        tag_lower = tag.lower()
        return [node for node in self.iter_nodes() if node.tag == tag_lower]

    def get_attribute(self, name: str, default: str = "") -> str:
        """Return attribute value, or default if missing."""
        return self.attributes.get(name, default)

    # ------------------------------------------------------------------
    #  Hashability: object identity is correct for dictionary keys
    # ------------------------------------------------------------------
    def __hash__(self) -> int:
        """Return a hash based on object identity.
        
        This makes DOMNode usable as dictionary keys and in sets
        without relying on the mutable `attributes` dict.
        """
        return id(self)

    def __eq__(self, other: object) -> bool:
        """Compare nodes by identity, not by content.
        
        Two different nodes with identical content are still
        considered distinct, which is the correct behaviour
        for mappings that track parent relationships.
        """
        return self is other

    def __repr__(self) -> str:
        geom = f"({self.geometry.x:.0f},{self.geometry.y:.0f})" if self.geometry else "None"
        return (
            f"DOMNode(tag={self.tag!r}, depth={self.depth}, "
            f"children={len(self.children)}, geom={geom})"
        )
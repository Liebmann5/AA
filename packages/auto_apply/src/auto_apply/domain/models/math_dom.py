"""Immutable mathematical representation of a webpage's DOM tree.

This module defines the core data structures used by the deterministic
webpage understanding engine. Every node includes its geometry (bounding box),
attributes, and text content, enabling pure mathematical analysis without
any browser or AI dependencies.

The DOMNode is a rooted tree. Geometry is optional (may be missing for nodes
that are not rendered or when geometry extraction is disabled).

Attributes and children are stored as immutable tuples to guarantee
structural hashability and true value‑type semantics.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field

#: Upper bound, in characters, on the full-subtree text and the accessible
#: name kept per node (05 section 14, text cap). Titles and link names on the
#: specimen pages are far shorter (longest heading or link name measured on the
#: S1 fixtures: under 200 characters); the cap bounds the payload, and a node
#: whose text was cut carries ``text_truncated``.
TEXT_CAP = 256

#: Elements whose text never reaches a reader.
_NON_TEXT_TAGS = frozenset({"script", "style", "noscript", "template"})


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
        return (self.center_x, self.center_y)

    @property
    def center_x(self) -> float:
        """X coordinate of the element's center."""
        return self.x + self.width / 2.0

    @property
    def center_y(self) -> float:
        """Y coordinate of the element's center."""
        return self.y + self.height / 2.0

    @property
    def area(self) -> float:
        """Return the area of the bounding box."""
        return self.width * self.height

    def is_visible(self, min_area: float = 1.0) -> bool:
        """Heuristic to determine if the element is likely visible to a user.

        Args:
            min_area: Minimum area in square pixels to consider visible.

        Returns:
            ``True`` if width > 0, height > 0, and area >= min_area.
        """
        return self.width > 0 and self.height > 0 and self.area >= min_area

    def distance_to(self, other: Geometry) -> float:
        """Euclidean distance between centers of two geometries."""
        cx1, cy1 = self.center_x, self.center_y
        cx2, cy2 = other.center_x, other.center_y
        dx = cx1 - cx2
        dy = cy1 - cy2
        return (dx * dx + dy * dy) ** 0.5

    def contains_point(self, px: float, py: float) -> bool:
        """Return ``True`` if the point ``(px, py)`` lies within this bounding box."""
        return (
            self.x <= px <= self.x + self.width
            and self.y <= py <= self.y + self.height
        )


@dataclass(frozen=True, slots=True)
class DOMNode:
    """Immutable node in a webpage's DOM tree with geometry.

    This is the fundamental unit of analysis. The tree can be traversed
    using the ``children`` attribute. Geometry is optional because some nodes
    (e.g. ``<script>``, ``<style>``, or elements not rendered) may not have
    a bounding box.

    Attributes and children are stored as immutable tuples so that the node
    is truly hashable and supports structural equality.  Two ``DOMNode``
    instances with the same tag, attributes, children, geometry, and text are
    equal and have the same hash.

    Use ``get_attribute()`` to look up individual attribute values; use
    ``attrs_as_dict()`` for a plain dictionary copy when needed.

    Attributes:
        tag: Lowercase tag name (e.g. ``"div"``, ``"input"``).
        attributes: Tuple of ``(name, value)`` pairs.  Order is preserved from
            parsing but does not affect equality.
        text: Visible text content of this node (not including children).
        full_text: Whitespace-normalised text of the whole subtree as a reader
            sees it (``script``/``style`` and hidden elements excluded), at most
            :data:`TEXT_CAP` characters. Filled by the extraction adapter;
            empty when the adapter did not supply it (then
            :meth:`subtree_text` derives it from the children).
        accessible_name: The element's accessible name (WAI-ARIA Accessible
            Name Computation, the subset in the S1 extraction script), for
            elements that are named (headings, links, buttons, elements with
            ``aria-label``/``aria-labelledby``); empty otherwise.
        text_truncated: True when ``full_text`` or ``accessible_name`` was cut
            at :data:`TEXT_CAP`.
        geometry: Bounding box, or ``None`` if not rendered.
        children: Tuple of child ``DOMNode`` objects.
        depth: Depth in the DOM tree (root = 0).
        structural_hash: Hash of the node's structure (tag + classes +
            children hashes).  Used for subtree similarity, NOT for equality.
    """

    tag: str
    attributes: tuple[tuple[str, str], ...] = field(default=())
    text: str = ""
    geometry: Geometry | None = None
    children: tuple[DOMNode, ...] = field(default=())
    depth: int = 0
    structural_hash: str = ""
    full_text: str = ""
    accessible_name: str = ""
    text_truncated: bool = False

    def __post_init__(self) -> None:
        """Ensure children depth is consistent and compute structural hash."""
        for child in self.children:
            if child.depth != self.depth + 1:
                pass  # Non‑fatal validation hint
        if not self.structural_hash:
            object.__setattr__(self, "structural_hash", self._compute_structural_hash())

    # ------------------------------------------------------------------
    # Attribute access helpers
    # ------------------------------------------------------------------

    def get_attribute(self, name: str, default: str = "") -> str:
        """Return attribute value by name.

        If duplicate keys exist, returns the **last** value (consistent with
        dict construction). If the attribute is absent, returns *default*.

        Args:
            name: Attribute name (case‑sensitive).
            default: Fallback value when attribute is not present.

        Returns:
            The attribute value string.

        Example:
            >>> node = DOMNode(tag="input", attributes=(("type","text"), ("type","password")))
            >>> node.get_attribute("type")
            'password'
            >>> node.get_attribute("missing", "fallback")
            'fallback'
        """
        last_value = default
        for k, v in self.attributes:
            if k == name:
                last_value = v
        return last_value

    def attrs_as_dict(self) -> dict[str, str]:
        """Return a plain ``dict`` copy of the attributes."""
        return dict(self.attributes)

    # ------------------------------------------------------------------
    # Structural hashing
    # ------------------------------------------------------------------

    def _compute_structural_hash(self) -> str:
        class_str = self.get_attribute("class", "")
        classes = sorted(class_str.split())
        base = self.tag + "".join(classes)
        child_hashes = "".join(child.structural_hash for child in self.children)
        full = base + child_hashes
        return hashlib.md5(full.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def has_geometry(self) -> bool:
        """Return ``True`` if this node has a valid bounding box."""
        return self.geometry is not None

    @property
    def is_interactable(self) -> bool:
        if self.tag in {"input", "select", "textarea", "button"}:
            return True
        if self.get_attribute("contenteditable", "").lower() == "true":
            return True
        role = self.get_attribute("role")
        if role in {"button", "checkbox", "radio", "textbox"}:
            return True
        return False

    @property
    def input_type(self) -> str | None:
        if self.tag == "input":
            return self.get_attribute("type", "text").lower()
        return None

    def subtree_text(self, cap: int = TEXT_CAP) -> tuple[str, bool]:
        """Return ``(text, truncated)``: the subtree's reader-visible text.

        Uses ``full_text`` when the adapter supplied it (exact: the script
        reads text in document order). Otherwise walks the subtree
        iteratively (no recursion, so depth is not a hazard), skipping
        non-text elements and those marked ``hidden``, and stops once ``cap``
        characters are collected. This fallback is approximate: a ``DOMNode``
        keeps an element's own text apart from its children, so text mixed
        with child elements is read own-text first, and pieces are joined
        with a space so words are never glued together. Whitespace is
        normalised. This is the full-subtree text rule of 06 section 2
        (defect 4).
        """
        if self.full_text:
            return self.full_text, self.text_truncated
        parts: list[str] = []
        size = 0
        truncated = False
        stack: list[DOMNode] = [self]
        while stack:
            item = stack.pop()
            if item.tag in _NON_TEXT_TAGS or (
                item is not self and any(k == "hidden" for k, _ in item.attributes)
            ):
                continue
            if item.text:
                parts.append(" " + item.text + " ")
                size += len(item.text)
                if size > 2 * cap:  # room for whitespace normalisation
                    truncated = True
                    break
            stack.extend(reversed(item.children))
        text = " ".join("".join(parts).split())
        if len(text) > cap:
            text, truncated = text[:cap].rstrip(), True
        return text, truncated

    def display_name(self) -> str:
        """Accessible name if known, else the subtree text (06 section 2)."""
        if self.accessible_name:
            return self.accessible_name
        return self.subtree_text()[0]

    def iter_nodes(self) -> Iterator[DOMNode]:
        yield self
        for child in self.children:
            yield from child.iter_nodes()

    def find_by_tag(self, tag: str) -> list[DOMNode]:
        tag_lower = tag.lower()
        return [node for node in self.iter_nodes() if node.tag == tag_lower]

    def __repr__(self) -> str:
        geom = f"({self.geometry.x:.0f},{self.geometry.y:.0f})" if self.geometry else "None"
        return (
            f"DOMNode(tag={self.tag!r}, depth={self.depth}, "
            f"children={len(self.children)}, geom={geom})"
        )
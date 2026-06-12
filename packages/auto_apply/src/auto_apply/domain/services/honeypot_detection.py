"""Deterministic detection of honeypot and security trap fields.

This module provides pure mathematical heuristics to identify form fields
that are intended to catch bots. Honeypots typically manifest as:
    - Hidden via CSS (zero size, off‑screen, opacity:0).
    - Containing suspicious name patterns (e.g., "email2", "fax").
    - Lacking any visible label or placeholder.
    - Being the only field inside an invisible container.

All functions operate on `DOMNode` objects and require no external libraries.
"""

from __future__ import annotations

from auto_apply.domain.models.math_dom import DOMNode
from auto_apply.domain.services.entropy import is_randomized_trap_string
from auto_apply.domain.services.occlusion import is_occluded


class HoneypotDetector:
    """Detect likely honeypot fields using deterministic heuristics.

    This class is stateless and can be instantiated once and reused.
    """

    # Suspicious substrings in name/id attributes (lowercase)
    SUSPICIOUS_NAME_PATTERNS: set[str] = {
        "fax",
        "confirm_email",
        "email2",
        "extra",
        "hidden",
        "url2",
        "phone2",
        "address2",
        "captcha",
        "verification",
        "validate",
        "test",
    }

    # Minimum area (px²) for an element to be considered potentially visible.
    MIN_VISIBLE_AREA: float = 4.0

    # Maximum opacity to consider an element hidden.
    MAX_HIDDEN_OPACITY: float = 0.1

    _WEIGHT_ENTROPY_TRAP: float = 0.95  # Almost certainly a trap
    _WEIGHT_OCCLUDED: float = 1.0       # Definitive trap (cannot be safely clicked)

    def __init__(self, **kwargs) -> None:
        """Allow overriding thresholds via constructor."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def is_honeypot(
        self,
        input_node: DOMNode,
        parent_map: dict | None = None,
    ) -> tuple[bool, str]:
        """Return (True, reason) if the input is likely a honeypot.

        Args:
            input_node: The input element to examine.
            parent_map: Optional dictionary mapping node → parent for
                ancestor visibility checks.

        Returns:
            A tuple (is_honeypot: bool, reason: str).
        """
        # 1. Geometry checks (zero size, off‑screen)
        geom_issue = self._check_geometry(input_node)
        if geom_issue:
            return True, geom_issue

        # 2. Suspicious name/id patterns
        name_issue = self._check_suspicious_names(input_node)
        if name_issue:
            return True, name_issue

        # 3. Invisible due to ancestor (requires parent_map)
        if parent_map is not None:
            ancestor_issue = self._check_ancestor_visibility(input_node, parent_map)
            if ancestor_issue:
                return True, ancestor_issue

        # 4. Missing both label and placeholder
        if self._has_no_visible_label(input_node):
            # Also check if it's the only field in a form (common trap)
            return True, "no visible label or placeholder"

        return False, ""

    def honeypot_score(self, input_node: DOMNode, all_nodes: list[DOMNode], parent_map: dict) -> tuple[float, str]:
        # ── 1. The Entropy Check ──────────────────────────────────────────
        name_val = input_node.attributes.get("name") or input_node.attributes.get("id") or ""
        if is_randomized_trap_string(name_val):
            return self._WEIGHT_ENTROPY_TRAP, f"High entropy (randomized) string detected: {name_val}"

        # ── 2. The Ray Casting Occlusion Check ─────────────────────────────
        occluded, occlusion_reason = is_occluded(input_node, all_nodes, parent_map)
        if occluded:
            return self._WEIGHT_OCCLUDED, occlusion_reason

        return 0.0, ""

    # ----------------------------------------------------------------------
    # Geometry Checks
    # ----------------------------------------------------------------------

    def _check_geometry(self, node: DOMNode) -> str:
        """Return a reason string if geometry indicates hidden."""
        geom = node.geometry
        if geom is None:
            return ""  # Cannot determine; assume not honeypot
        if geom.width <= 0 or geom.height <= 0:
            return "zero size"
        if geom.area < self.MIN_VISIBLE_AREA:
            return f"too small (area={geom.area:.1f}px²)"
        if geom.x < -1000 or geom.y < -1000:
            return "offscreen"
        # Note: opacity is not stored in DOMNode; would need style extraction.
        # For now, we rely on geometry and attribute heuristics.
        return ""

    # ----------------------------------------------------------------------
    # Attribute Pattern Checks
    # ----------------------------------------------------------------------

    def _check_suspicious_names(self, node: DOMNode) -> str:
        """Return reason if name/id/class contains suspicious substrings."""
        attributes = node.attributes
        for attr in ("name", "id", "class"):
            value = attributes.get(attr, "").lower()
            for pattern in self.SUSPICIOUS_NAME_PATTERNS:
                if pattern in value:
                    return f"suspicious {attr} contains '{pattern}'"
        return ""

    # ----------------------------------------------------------------------
    # Ancestor Visibility
    # ----------------------------------------------------------------------

    def _check_ancestor_visibility(
        self, node: DOMNode, parent_map: dict
    ) -> str:
        """Check if any ancestor is hidden (zero geometry)."""
        curr = parent_map.get(node)
        while curr is not None:
            if curr.geometry is not None:
                if curr.geometry.width <= 0 or curr.geometry.height <= 0:
                    return f"ancestor <{curr.tag}> has zero size"
                if curr.geometry.area < self.MIN_VISIBLE_AREA:
                    return f"ancestor <{curr.tag}> too small"
            curr = parent_map.get(curr)
        return ""

    # ----------------------------------------------------------------------
    # Label Presence
    # ----------------------------------------------------------------------

    def _has_no_visible_label(self, input_node: DOMNode) -> bool:
        """Return True if the input lacks any visible label or placeholder."""
        # Placeholder is a weak label but often sufficient.
        if input_node.attributes.get("placeholder", "").strip():
            return False
        # ARIA label
        if input_node.attributes.get("aria-label", "").strip():
            return False
        # We cannot check associated <label> without DOM traversal,
        # but the pairing service will provide that context.
        # Here we assume that if we reach this point, no label was paired.
        return True


def detect_honeypots(
    fields: list[DOMNode],
    parent_map: dict | None = None,
) -> list[DOMNode]:
    """Convenience function to filter a list of fields to only honeypots.

    Args:
        fields: List of input DOMNodes.
        parent_map: Optional parent map for ancestor checks.

    Returns:
        List of fields identified as honeypots.
    """
    detector = HoneypotDetector()
    honeypots = []
    for field in fields:
        is_hp, _ = detector.is_honeypot(field, parent_map)
        if is_hp:
            honeypots.append(field)
    return honeypots

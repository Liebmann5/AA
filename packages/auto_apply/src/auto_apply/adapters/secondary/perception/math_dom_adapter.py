"""Secondary adapter that extracts a mathematical DOM tree from a live browser.

This module implements `MathematicalPerceptionPort` using the framework‑agnostic
`BrowserInterface`. It injects JavaScript into the page to traverse the DOM,
collect tag names, attributes, visible text, and bounding boxes. The result is
a complete, immutable `DOMNode` tree suitable for deterministic analysis.

Works with both Selenium and Playwright backends.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from auto_apply.application.services.auditing.discovery_math_auditor import DiscoveryMathAuditor
from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.ports.math_perception_port import MathematicalPerceptionPort

# Sentinel type alias used only in _graft_iframes signature.
_Expansions = dict[int, DOMNode]

logger = logging.getLogger(__name__)


class MathDOMAdapter(MathematicalPerceptionPort):
    """Extract a geometry‑aware DOM tree using the BrowserInterface.

    This adapter executes a JavaScript function inside the browser that
    recursively walks the DOM and serializes each node into a lightweight
    JSON structure. The JSON is then parsed and converted into an immutable
    `DOMNode` tree.

    The adapter is stateless; it can be reused for multiple page analyses.

    Args:
        browser: An initialized BrowserInterface (e.g., SeleniumAdapter,
            PlaywrightAdapter, or ResilientDriver).
        max_depth: Maximum DOM depth to traverse (prevents infinite recursion).
            Default 50.
        include_computed_styles: If True, also extract computed styles (not yet
            implemented). Default False.
    """

    # JavaScript function that runs in the browser context.
    # It must be self‑contained and return a JSON‑serializable object.
    _EXTRACTION_SCRIPT = """
    return (function() {
        function extractNode(element, depth, maxDepth) {
            if (depth > maxDepth) return null;
            var node = {
                tag: element.tagName ? element.tagName.toLowerCase() : '#text',
                attributes: {},
                text: '',
                geometry: null,
                children: []
            };
            // Collect attributes
            if (element.attributes) {
                for (var i = 0; i < element.attributes.length; i++) {
                    var attr = element.attributes[i];
                    node.attributes[attr.name] = attr.value;
                }
            }
            // Extract visible text (only direct text nodes, not nested)
            if (element.childNodes) {
                for (var j = 0; j < element.childNodes.length; j++) {
                    var child = element.childNodes[j];
                    if (child.nodeType === Node.TEXT_NODE) {
                        node.text += child.textContent;
                    }
                }
                node.text = node.text.trim();
            }
            // Geometry via getBoundingClientRect — adjusted for scroll offset
            try {
                var rect = element.getBoundingClientRect();
                if (rect && (rect.width > 0 || rect.height > 0)) {
                    node.geometry = {
                        x: rect.x + window.scrollX,
                        y: rect.y + window.scrollY,
                        width: rect.width,
                        height: rect.height
                    };
                }
            } catch (e) {
                // Cross‑origin iframes may throw; ignore geometry.
            }
            // Recurse into children
            if (element.children) {
                for (var k = 0; k < element.children.length; k++) {
                    var childNode = extractNode(element.children[k], depth + 1, maxDepth);
                    if (childNode) {
                        node.children.push(childNode);
                    }
                }
            }
            return node;
        }
        // Start from document.body or fallback to document.documentElement
        var rootElement = document.body || document.documentElement;
        if (!rootElement) return null;
        return extractNode(rootElement, 0, %d);
    })();
    """

    def __init__(
        self,
        browser: BrowserInterface,
        max_depth: int = 50,
        include_computed_styles: bool = False,
    ) -> None:
        """Initialize the adapter.

        Args:
            browser: The browser interface to use for extraction.
            max_depth: Maximum depth to traverse in the DOM tree.
            include_computed_styles: (Future) whether to extract computed CSS.
        """
        self._browser = browser
        self._max_depth = max_depth
        self._include_computed_styles = include_computed_styles
        self._script = self._EXTRACTION_SCRIPT % max_depth

    def extract_full_dom_tree(self) -> DOMNode | None:
        """Execute the extraction script and build a DOMNode tree.

        Returns:
            Root DOMNode (typically <body>), or None if extraction fails.
        """
        try:
            raw_json = self._browser.execute_script(self._script)
            if raw_json is None:
                logger.warning("Extraction script returned null; page may be empty.")
                return None
            root_dict = json.loads(json.dumps(raw_json))
            root = self._build_dom_node(root_dict, depth=0)
            return self._stitch_iframes(root)
        except Exception as e:
            logger.error("Failed to extract DOM tree: %s", e, exc_info=True)
            return None

    def _stitch_iframes(self, root: DOMNode) -> DOMNode:
        """Graft accessible iframe DOMs into the main tree.

        Finds every <iframe> in the tree, switches the browser context into it,
        extracts its DOM with corrected geometry offsets, then grafts the result
        back as children of the iframe node.  Cross-origin frames throw a
        SecurityError which is caught and skipped gracefully.

        Args:
            root: The main-frame DOMNode tree.

        Returns:
            A new DOMNode tree with iframe content stitched in where accessible.
        """
        live_iframes = self._browser.find_elements("css selector", "iframe")
        if not live_iframes:
            return root

        iframe_nodes: list[DOMNode] = root.find_by_tag("iframe")
        if not iframe_nodes:
            return root

        # The two lists are paired positionally below: iframe_nodes is DFS
        # (tree) order and live_iframes is document order. These coincide only
        # when the counts match; a mismatch (an iframe dropped from the tree, or
        # one added dynamically) would graft inner DOM onto the wrong frame, so
        # skip stitching rather than risk corrupting geometry.
        if len(iframe_nodes) != len(live_iframes):
            logger.warning(
                "Iframe count mismatch (tree=%d live=%d); skipping iframe "
                "stitching to avoid grafting onto the wrong frame.",
                len(iframe_nodes),
                len(live_iframes),
            )
            return root

        expansions: _Expansions = {}

        for idx, (node, live_el) in enumerate(zip(iframe_nodes, live_iframes)):
            offset_x = node.geometry.x if node.geometry else 0.0
            offset_y = node.geometry.y if node.geometry else 0.0
            try:
                self._browser.switch_to_iframe(live_el)
                raw_json = self._browser.execute_script(self._script)
                if raw_json is not None:
                    inner_dict = json.loads(json.dumps(raw_json))
                    inner_root = self._build_dom_node(inner_dict, depth=node.depth + 1)
                    inner_root = self._offset_geometry(inner_root, offset_x, offset_y)
                    expansions[id(node)] = inner_root
            except Exception as exc:
                logger.warning(
                    "Skipping iframe %d (inaccessible, likely cross-origin): %s",
                    idx,
                    exc,
                )
            finally:
                try:
                    self._browser.switch_to_default_content()
                except Exception:
                    pass

        if not expansions:
            return root

        return self._graft_iframes(root, expansions)

    def _offset_geometry(self, node: DOMNode, dx: float, dy: float) -> DOMNode:
        """Return a copy of the subtree with all geometry shifted by (dx, dy).

        Args:
            node: Root of the subtree to adjust.
            dx: Horizontal offset (the iframe's viewport-relative x coordinate).
            dy: Vertical offset (the iframe's viewport-relative y coordinate).

        Returns:
            A new DOMNode tree with adjusted coordinates.
        """
        new_geom: Geometry | None = None
        if node.geometry is not None:
            new_geom = Geometry(
                x=node.geometry.x + dx,
                y=node.geometry.y + dy,
                width=node.geometry.width,
                height=node.geometry.height,
            )
        new_children = [self._offset_geometry(c, dx, dy) for c in node.children]
        return DOMNode(
            tag=node.tag,
            attributes=dict(node.attributes),
            text=node.text,
            geometry=new_geom,
            children=new_children,
            depth=node.depth,
        )

    def _graft_iframes(self, node: DOMNode, expansions: _Expansions) -> DOMNode:
        """Recursively rebuild the tree, replacing iframe children with stitched content.

        Args:
            node: Current node being visited.
            expansions: Mapping of id(original_iframe_node) → inner DOMNode root.

        Returns:
            Rebuilt DOMNode with iframe content grafted in.
        """
        if node.tag == "iframe" and id(node) in expansions:
            inner = expansions[id(node)]
            return DOMNode(
                tag=node.tag,
                attributes=dict(node.attributes),
                text=node.text,
                geometry=node.geometry,
                children=list(inner.children),
                depth=node.depth,
            )

        new_children = [self._graft_iframes(c, expansions) for c in node.children]

        # Avoid allocating a new node when nothing changed.
        if new_children == list(node.children):
            return node

        return DOMNode(
            tag=node.tag,
            attributes=dict(node.attributes),
            text=node.text,
            geometry=node.geometry,
            children=new_children,
            depth=node.depth,
        )

    def _build_dom_node(self, data: dict[str, Any], depth: int) -> DOMNode:
        """Recursively construct a DOMNode from the serialized dictionary.

        Args:
            data: Dictionary as returned by the JavaScript extractor.
            depth: Current depth (used to set node.depth).

        Returns:
            An immutable DOMNode instance.
        """
        geom = None
        if data.get("geometry"):
            g = data["geometry"]
            geom = Geometry(
                x=float(g.get("x", 0.0)),
                y=float(g.get("y", 0.0)),
                width=float(g.get("width", 0.0)),
                height=float(g.get("height", 0.0)),
            )

        children = [
            self._build_dom_node(child, depth + 1)
            for child in data.get("children", [])
        ]

        # return DOMNode(
        #     tag=data.get("tag", "div"),
        #     attributes=data.get("attributes", {}),
        #     text=data.get("text", "").strip(),
        #     geometry=geom,
        #     children=children,
        #     depth=depth,
        #     # structural_hash is computed automatically in __post_init__
        # )
        #! temporary
        node = DOMNode(
            tag=data.get("tag", "div"),
            attributes=data.get("attributes", {}),
            text=data.get("text", "").strip(),
            geometry=geom,
            children=children,
            depth=depth,
        )

        if DiscoveryMathAuditor._ENABLED and node.is_interactable and not node.has_geometry:
            DiscoveryMathAuditor.audit_text_extraction(node, node.text or '', 'MathDOM')

        return node

    def get_current_url(self) -> str:
        """Return the current page URL, if available."""
        try:
            return self._browser.current_url or ""
        except Exception:
            return ""

    def get_page_title(self) -> str:
        """Return the current page title, if available."""
        try:
            return self._browser.title or ""
        except Exception:
            return ""
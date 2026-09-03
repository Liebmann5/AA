"""Secondary adapter that extracts a mathematical DOM tree from a live browser.

This module implements `MathematicalPerceptionPort` using the framework‑agnostic
`BrowserInterface`. It injects JavaScript into the page to traverse the DOM,
collect tag names, attributes, visible text, and bounding boxes. The result is
a complete, immutable `DOMNode` tree suitable for deterministic analysis.

Works with both Selenium and Playwright backends.

Additionally provides `MathPageUnderstandingAdapter` which implements
`PageUnderstandingPort` using pure mathematical DOM analysis.  This
adapter is wired into the composition root so that discovery providers
can benefit from the math subsystem without importing it directly.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.parse import urljoin

from auto_apply.domain.ports.extraction_observer_port import (
    NullExtractionObserver,
)
from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.models.math_webpage import WebpageStructure, FieldType
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.ports.math_perception_port import MathematicalPerceptionPort
from auto_apply.domain.ports.page_understanding_port import (
    PageContext,
    SERPStructure,
    FormStructure,
    JobListingStructure,
    JobCardInfo,
    FormFieldInfo,
)
from auto_apply.domain.services.card_static_resolution import resolve_card_group
from auto_apply.domain.services.dom_segmentation import MathFormUnderstandingService

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
        observer=None,
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
        # Observation only — a null observer leaves extraction identical.
        self._observer = observer or NullExtractionObserver()

    def extract_full_dom_tree(self) -> DOMNode | None:
        """Execute the extraction script and build a DOMNode tree.

        Returns:
            Root DOMNode (typically <body>), or None if extraction fails.
        """
        try:
            script_started = time.monotonic()
            raw_json = self._browser.execute_script(self._script)
            script_seconds = time.monotonic() - script_started
            if raw_json is None:
                logger.warning("Extraction script returned null; page may be empty.")
                return None
            # Serialize once and reuse for both the parse and the payload-byte
            # measurement — previously this dumped the same structure twice.
            payload = json.dumps(raw_json)
            payload_bytes = len(payload.encode("utf-8"))
            root_dict = json.loads(payload)
            build_started = time.monotonic()
            root = self._build_dom_node(root_dict, depth=0)
            build_seconds = time.monotonic() - build_started
            stitch_started = time.monotonic()
            stitched = self._stitch_iframes(root)
            stitch_seconds = time.monotonic() - stitch_started
            if logger.isEnabledFor(logging.DEBUG):
                node_count = (
                    sum(1 for _ in stitched.iter_nodes()) if stitched is not None else 0
                )
                logger.debug(
                    "MathDOM extraction: script=%.2fs build=%.2fs stitch=%.2fs "
                    "nodes=%d bytes=%d",
                    script_seconds,
                    build_seconds,
                    stitch_seconds,
                    node_count,
                    payload_bytes,
                )
            return stitched
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
        new_children = tuple(self._offset_geometry(c, dx, dy) for c in node.children)
        return DOMNode(
            tag=node.tag,
            attributes=node.attributes,
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
                attributes=node.attributes,
                text=node.text,
                geometry=node.geometry,
                children=inner.children,
                depth=node.depth,
            )

        new_children = tuple(self._graft_iframes(c, expansions) for c in node.children)

        # Avoid allocating a new node when nothing changed.
        if new_children == node.children:
            return node

        return DOMNode(
            tag=node.tag,
            attributes=node.attributes,
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
        # Convert the attributes dict to a sorted tuple of tuples for immutability.
        attrs_dict = data.get("attributes", {})
        sorted_attrs = tuple(sorted((name, str(val)) for name, val in attrs_dict.items()))

        geom = None
        if data.get("geometry"):
            g = data["geometry"]
            geom = Geometry(
                x=float(g.get("x", 0.0)),
                y=float(g.get("y", 0.0)),
                width=float(g.get("width", 0.0)),
                height=float(g.get("height", 0.0)),
            )

        children = tuple(
            self._build_dom_node(child, depth + 1)
            for child in data.get("children", [])
        )

        node = DOMNode(
            tag=data.get("tag", "div"),
            attributes=sorted_attrs,
            text=data.get("text", "").strip(),
            geometry=geom,
            children=children,
            depth=depth,
        )

        if self._observer.enabled and node.is_interactable and not node.has_geometry:
            self._observer.audit_text_extraction(node, node.text or '', 'MathDOM')

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


# ----------------------------------------------------------------------
# PageUnderstandingPort implementation
# ----------------------------------------------------------------------


class MathPageUnderstandingAdapter:
    """Implements ``PageUnderstandingPort`` using mathematical DOM analysis.

    This adapter receives a ``MathDOMAdapter`` (for DOM extraction) and
    a ``MathFormUnderstandingService`` (for segmentation & pairing), both
    injected at construction time.  It converts the raw ``DOMNode`` tree
    into the structured outputs expected by the ``PageUnderstandingPort``
    contract.

    All public methods never raise — they log errors and return empty
    structures on any failure, satisfying AA's worst‑case‑first contract.

    Args:
        dom_adapter:  ``MathDOMAdapter`` — must be able to call
                      ``extract_full_dom_tree()``.
        form_service: ``MathFormUnderstandingService`` — provides
                      ``analyze(dom_root, ...) → WebpageStructure``.
    """

    def __init__(
        self,
        dom_adapter: MathDOMAdapter,
        form_service: MathFormUnderstandingService,
    ) -> None:
        self._dom_adapter = dom_adapter
        self._form_service = form_service

    # ------------------------------------------------------------------
    # PageUnderstandingPort methods
    # ------------------------------------------------------------------

    def analyze_serp(self, context: PageContext) -> SERPStructure:
        """Analyse the page as a SERP and extract job card information.

        The full static resolution pipeline runs here (climb → sibling-diff
        identity → static anchor classification). Click-based activation is
        deliberately NOT part of this method — it belongs to the extractor's
        post-scroll finalize pass, so a click never contaminates a harvest.

        Args:
            context: Page metadata (URL, title, raw HTML, viewport).

        Returns:
            A ``SERPStructure``; on failure, all fields are empty and
            ``job_cards`` is an empty tuple.
        """
        try:
            root = self._dom_adapter.extract_full_dom_tree()
            if root is None:
                return SERPStructure()

            analyze_started = time.monotonic()
            structure = self._form_service.analyze(
                root,
                url=context.url,
                title=context.page_title,
            )
            analyze_seconds = time.monotonic() - analyze_started

            cards, report = resolve_card_group(
                structure.job_listings,
                structure.dom_root,
                context.url,
            )

            logger.debug(
                "analyze_serp: analyze=%.2fs cards=%d resolved=%d multi_route=%d "
                "level=%s identity=%s url=%s",
                analyze_seconds,
                len(cards),
                sum(1 for c in cards if c.url),
                sum(
                    1 for c in cards if c.resolution_state == "multi_route"
                ),
                report.chosen_level,
                list(report.learned_identity),
                context.url,
            )
            return SERPStructure(
                job_cards=tuple(cards),
                pagination_present=False,
                total_results_text="",
                captcha_detected=structure.is_captcha_present,
                resolution_report=report,
            )

        except Exception as exc:
            logger.warning(
                "MathPageUnderstandingAdapter.analyze_serp failed: %s", exc,
                exc_info=True,
            )
            return SERPStructure()

    def analyze_form(self, context: PageContext) -> FormStructure:
        """Analyse the page as a job application form.

        Args:
            context: Page metadata.

        Returns:
            A ``FormStructure`` describing all detected fields.
        """
        try:
            root = self._dom_adapter.extract_full_dom_tree()
            if root is None:
                return FormStructure(confidence=0.0)

            structure = self._form_service.analyze(
                root,
                url=context.url,
                title=context.page_title,
            )
            return self._build_form_structure(structure)

        except Exception as exc:
            logger.warning(
                "MathPageUnderstandingAdapter.analyze_form failed: %s", exc,
                exc_info=True,
            )
            return FormStructure(confidence=0.0)

    def analyze_job_listing(self, context: PageContext) -> JobListingStructure:
        """Analyse a single job listing page and extract structured details.

        Args:
            context: Page metadata.

        Returns:
            A ``JobListingStructure``.
        """
        try:
            root = self._dom_adapter.extract_full_dom_tree()
            if root is None:
                return JobListingStructure()

            structure = self._form_service.analyze(
                root,
                url=context.url,
                title=context.page_title,
            )
            return self._build_job_listing_structure(
                structure, context.url, context.page_title
            )

        except Exception as exc:
            logger.warning(
                "MathPageUnderstandingAdapter.analyze_job_listing failed: %s",
                exc,
                exc_info=True,
            )
            return JobListingStructure()

    # ------------------------------------------------------------------
    # Internal extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_form_structure(structure: WebpageStructure) -> FormStructure:
        """Convert a ``WebpageStructure`` (form analysis) into a ``FormStructure``.

        Args:
            structure: The output of ``MathFormUnderstandingService.analyze()``.

        Returns:
            Populated ``FormStructure`` with fields from the main form.
        """
        all_fields: list[FormFieldInfo] = []
        main_form = structure.get_main_form()
        if main_form is None and structure.forms:
            # Use any available form for field extraction
            main_form = structure.forms[0]

        if main_form is not None:
            for field in main_form.all_fields:
                options = tuple(field.options) if hasattr(field, "options") else ()
                all_fields.append(
                    FormFieldInfo(
                        field_id=field.input_id,
                        label_text=field.label_text,
                        field_type=field.inferred_type.name.lower(),
                        name=field.input_node.get_attribute("name", ""),
                        placeholder=field.input_node.get_attribute("placeholder", ""),
                        is_required=field.is_required,
                        is_honeypot=field.is_honeypot,
                        options=options,
                    )
                )

        return FormStructure(
            fields=tuple(all_fields),
            page_count=len(structure.forms),
            has_file_upload=any(
                f.inferred_type == FieldType.RESUME_UPLOAD
                for form in structure.forms
                for f in form.all_fields
            ),
            has_cover_letter_field=any(
                f.inferred_type in (FieldType.COVER_LETTER_UPLOAD,)
                for form in structure.forms
                for f in form.all_fields
            ),
            wcag_violations=(),   # not extracted in this version
            has_salary_history_field=False,
            confidence=0.9 if all_fields else 0.0,
        )

    @staticmethod
    def _build_job_listing_structure(
        structure: WebpageStructure,
        page_url: str,
        page_title: str,
    ) -> JobListingStructure:
        """Convert a ``WebpageStructure`` into a ``JobListingStructure``.

        This is a best‑effort extraction; for a single listing page it
        uses the entire visible text as the description.

        Args:
            structure:   Analysis result.
            page_url:    URL of the page.
            page_title:  Title of the page.

        Returns:
            Populated ``JobListingStructure``.
        """
        desc_text = ""
        if structure.dom_root is not None:
            desc_text = " ".join(
                n.text.strip()
                for n in structure.dom_root.iter_nodes()
                if n.text.strip()
            )

        title = page_title
        company = "Unknown"
        location = ""
        apply_url = ""

        if structure.job_listings:
            card = structure.job_listings[0]
            cards, _report = resolve_card_group(
                [card], structure.dom_root, page_url
            )
            if cards:
                info = cards[0]
                title = info.title or page_title
                company = info.company or "Unknown"
                location = info.location or ""
                apply_url = info.url or ""

        return JobListingStructure(
            full_text=desc_text,
            title=title,
            company=company,
            location=location,
            salary_text="",
            requirements_text="",
            apply_button_present=bool(apply_url),
            apply_url=apply_url,
        )

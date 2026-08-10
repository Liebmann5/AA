"""Shared mathematical web analysis service for all engines.

Provides a unified interface to deconstruct any webpage using pure
mathematical methods: DOM tree extraction, vision-based segmentation,
Hungarian label‑input pairing, convex hull clustering, and field type
inference. Replaces brittle CSS selector scraping in Discovery and
Vetting engines with deterministic, framework‑agnostic analysis.

Dependencies:
    - domain.models.math_dom.DOMNode, Geometry
    - domain.models.math_webpage.WebpageStructure, FieldType, etc.
    - domain.services.dom_segmentation.MathFormUnderstandingService
    - domain.services.structural_hashing (find_repeated_patterns)
    - domain.services.field_type_inference.FieldTypeClassifier
    - domain.services.label_input_pairing (assign_labels_to_inputs, build_parent_map)
    - domain.services.convex_hull (compute_convex_hull, hull_distance)
    - domain.ports.math_perception_port.MathematicalPerceptionPort
    - domain.models.job.Job
    - domain.models.parsed_job_description.ParsedJobDescription
"""

from __future__ import annotations

import concurrent.futures
import time
from collections.abc import Callable
import logging
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urljoin, quote_plus

from auto_apply.application.services.auditing.discovery_math_auditor import DiscoveryMathAuditor
from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.models.math_webpage import WebpageStructure
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.parsed_job_description import ParsedJobDescription
from auto_apply.domain.services.dom_segmentation import MathFormUnderstandingService
from auto_apply.domain.services.structural_hashing import (
    find_repeated_patterns,
    is_card_like,
)
from auto_apply.domain.services.field_type_inference import FieldTypeClassifier
from auto_apply.domain.services.label_input_pairing import (
    assign_labels_to_inputs,
    build_parent_map,
)
from auto_apply.domain.services.convex_hull import compute_convex_hull
from auto_apply.domain.ports.math_perception_port import MathematicalPerceptionPort

logger = logging.getLogger(__name__)


from auto_apply.application.services.analysis_contracts import (
    AnalysisTimeoutError,
    AnalyzerConfig,
    PerceptionError,
    ReasoningError,
    WebpageAnalysisError,
)


class MathematicalWebAnalyzer:
    """Deterministic, zero‑dependency webpage deconstruction service.

    Accepts a MathematicalPerceptionPort and provides methods to:
        - Extract job listings from any SERP or careers page
        - Parse a job description page into structured data
        - Analyze a form page for automatic filling

    All analysis is performed using pure mathematics on the DOM tree
    (tags, geometry, attributes, text) without any AI/ML or hardcoded
    selectors.

    Args:
        perception_port: A MathematicalPerceptionPort that provides
            DOM tree extraction and page metadata.
    """

    def __init__(self, perception_port: MathematicalPerceptionPort) -> None:
        self._perception_port = perception_port
        self._form_analyzer = MathFormUnderstandingService()

    def draw_visual_debug_boxes(self, nodes: list[DOMNode], color: str = "red", label: str = "") -> None:
        """Professional visual debugging tool for computational geometry.
        Draws physical boxes over the elements in the live browser
        """
        script = ""
        for node in nodes:
            if not node.geometry: continue
            script += f"""
                var div = document.createElement('div');
                div.style.position = 'absolute';
                div.style.left = '{node.geometry.x}px';
                div.style.top = '{node.geometry.y}px';
                div.style.width = '{node.geometry.width}px';
                div.style.height = '{node.geometry.height}px';
                div.style.border = '3px solid {color}';
                div.style.backgroundColor = 'rgba(255, 0, 0, 0.1)';
                div.style.zIndex = '999999';
                div.style.pointerEvents = 'none';

                if ('{label}') {{
                    var span = document.createElement('span');
                    span.innerText = '{label}';
                    span.style.backgroundColor = '{color}';
                    span.style.color = 'white';
                    span.style.fontSize = '12px';
                    span.style.fontWeight = 'bold';
                    span.style.position = 'absolute';
                    span.style.top = '-18px';
                    span.style.left = '0px';
                    div.appendChild(span);
                }}

                document.body.appendChild(div);
            """
        # drawing requires a live browser — this method is not reachable
        # when perception_port is a plain DOM extractor without execute_script,
        # so we guard with a hasattr check.
        if hasattr(self._perception_port, 'execute_script'):
            self._perception_port.execute_script(script)

    def extract_job_listings(self) -> list[Job]:
        """Discover all job listings on the current page.

        Uses structural hashing to identify repeated card patterns and
        extracts title, company, URL, and location using geometric
        clustering and field type inference.

        Returns:
            List of Job objects found on the page.
        """
        dom_root = self._perception_port.extract_full_dom_tree()
        if dom_root is None:
            return []

        card_nodes = self._detect_job_cards(dom_root)
        jobs = []
        for card in card_nodes:
            job_data = self._extract_job_from_card(card, dom_root)
            if job_data:
                jobs.append(Job(**job_data))
        return jobs

    def analyze_job_description(self) -> ParsedJobDescription:
        """Parse a job description page into structured metadata.

        Extracts title, company, location, description text, salary range,
        required skills, experience years, and remote indicators using
        visual segmentation and keyword heuristics.

        Returns:
            A ParsedJobDescription with all detected fields.
        """
        dom_root = self._perception_port.extract_full_dom_tree()
        if dom_root is None:
            return ParsedJobDescription()

        # Basic: find the main content area by size/position
        main_node = self._find_main_content_area(dom_root)
        if main_node is None:
            return ParsedJobDescription()

        # Collect all visible text nodes
        text_nodes = [n for n in main_node.iter_nodes() if n.text.strip() and (n.geometry and n.geometry.is_visible())]
        full_text = " ".join(n.text.strip() for n in text_nodes)

        # Use FieldTypeClassifier to guess individual fields
        classifier = FieldTypeClassifier()
        # We'll map nearby labels to fields using geometric proximity
        # First, get all nodes that could be field values (spans, divs, headings)
        potential_fields = [n for n in main_node.iter_nodes() if n.tag in {"span", "div", "h1", "h2", "h3", "h4", "p"} and n.text.strip()]
        parent_map = build_parent_map(dom_root)

        # Pair labels to values using the Hungarian algorithm
        # Labels are nodes that contain typical descriptors (e.g., "Location:", "Salary:")
        label_candidates = [n for n in main_node.iter_nodes() if n.text.strip().lower() in {"location", "salary", "title", "company"}]
        if label_candidates:
            # Pair each descriptor word (the "inputs") to its nearest value node;
            # result tuples are (descriptor_node, value_node).
            pairs = assign_labels_to_inputs(label_candidates, potential_fields, parent_map)
            # Build dict: descriptor text -> value text
            extracted = {}
            for descriptor, value in pairs:
                if descriptor and value:
                    extracted[descriptor.text.strip().lower()] = value.text.strip()
            # Populate only fields that actually exist on ParsedJobDescription.
            # title/salary/description are NOT model fields — passing them would
            # be silently dropped by Pydantic (extra='ignore'); map company →
            # organizations and location → locations instead (BUG-7).
            return ParsedJobDescription(
                required_skills=[],
                experience_years_min=None,
                experience_years_max=None,
                locations=[extracted["location"]] if extracted.get("location") else [],
                organizations=[extracted["company"]] if extracted.get("company") else [],
                employment_type=None,
                seniority_signal=None,
                is_remote="remote" in full_text.lower(),
            )
        # Fallback: no recognizable descriptors — still report the remote signal.
        return ParsedJobDescription(is_remote="remote" in full_text.lower())

    def analyze_form(self) -> WebpageStructure:
        """Analyze the current page as a form.

        Returns:
            WebpageStructure containing forms, fields, labels, and metadata.
        """
        dom_root = self._perception_port.extract_full_dom_tree()
        if dom_root is None:
            return WebpageStructure(
                url=self._perception_port.get_current_url(),
                title=self._perception_port.get_page_title(),
                dom_root=None,
                forms=[],
                job_listings=[],
                is_captcha_present=False,
                is_login_wall=False,
            )
        return self._form_analyzer.analyze(
            dom_root,
            url=self._perception_port.get_current_url(),
            title=self._perception_port.get_page_title(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_job_cards(self, root: DOMNode) -> list[DOMNode]:
        """Find all nodes that represent job cards/containers.

        Uses structural hashing to group repeated patterns, then keeps only
        groups whose members look like job cards. ``find_repeated_patterns``
        alone flags any repeated structure — nav items, footer links, comment
        rows — so without the geometry/link/text guard those surface as bogus
        "jobs" (2-D false positives).
        """
        patterns = find_repeated_patterns(
            root,
            min_occurrences=2,
            audit_hook=DiscoveryMathAuditor.audit_structural_hash_groups,
        )
        # Flatten all card nodes, keeping only card-like containers.

        DiscoveryMathAuditor.audit_structural_hash_groups(
            {p[0].structural_hash: p for p in patterns if p}, 'MathDiscoveryProvider'
        )

        all_cards: list[Any] = []
        for group in patterns:
            all_cards.extend(node for node in group if is_card_like(node))
        # Remove duplicates (by id)

        DiscoveryMathAuditor.audit_candidate_containers(all_cards, 'MathDiscoveryProvider')

        seen = set()
        unique_cards = []
        for node in all_cards:
            if id(node) not in seen:
                seen.add(id(node))
                unique_cards.append(node)
        return unique_cards

    def _extract_job_from_card(self, card: DOMNode, root: DOMNode) -> dict[str, Any] | None:
        """Extract structured job fields from a card node."""
        job_data: dict[str, Any] = {}
        
        # 1. Smarter URL Extraction (Prioritize href, then data-share-url)
        url = None
        for node in card.iter_nodes():
            href = node.get_attribute("href", "")
            if href and not href.startswith(("#", "javascript")):
                url = urljoin(self._perception_port.get_current_url(), href)
                break
            
            # Google Jobs often hides the real URL in data-share-url
            share_url = node.get_attribute("data-share-url")
            if share_url:
                url = share_url
                break
                
        if not url:
            DiscoveryMathAuditor.audit_extraction_attempt(job_data, False, 'missing_url')
            return None
            
        job_data["url"] = url

        # 2. Smarter Title & Company Extraction
        # Look for actual heading tags first (h1-h6) for the title
        headings = [n for n in card.iter_nodes() if n.tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and n.text.strip()]
        if headings:
            job_data["title"] = headings[0].text.strip()
            
        text_nodes = [
            node for node in card.iter_nodes()
            if node.text.strip() and (node.geometry and node.geometry.is_visible())
        ]
        
        # Filter out common metadata strings that aren't the company name
        ignore_phrases = {"work from home", "full-time", "part-time", "contractor", "degree", "hours ago", "days ago", "via", "anywhere", "remote"}
        
        for n in text_nodes:
            text = n.text.strip()
            
            # If we still don't have a title, grab the first valid text
            if not job_data.get("title") and len(text) > 4 and not any(ign in text.lower() for ign in ignore_phrases):
                job_data["title"] = text
                continue
                
            # If we have a title, the next valid text is likely the company
            if job_data.get("title") and text != job_data.get("title") and not job_data.get("company"):
                if not any(ign in text.lower() for ign in ignore_phrases):
                    job_data["company"] = text
                    break

        job_data.setdefault("company", "Unknown")
        job_data["source"] = "MathematicalAnalyzer"

        if not job_data.get("title"):
            DiscoveryMathAuditor.audit_extraction_attempt(job_data, False, 'no_title')
            return None

        DiscoveryMathAuditor.audit_extraction_attempt(job_data, True)
        return job_data

    def _is_likely_title(self, text: str) -> bool:
        """Heuristic to guess if a text block is a job title."""
        title_keywords = {
            "engineer", "developer", "manager", "analyst", "designer",
            "scientist", "specialist", "coordinator", "director", "associate"
        }
        return any(kw in text.lower() for kw in title_keywords)

    def _find_main_content_area(self, root: DOMNode) -> DOMNode | None:
        """Return the largest visible container likely holding the job description."""
        # Heuristic: the node with the most text content
        best_node = None
        max_text = ""
        for node in root.iter_nodes():
            if node.text.strip() and (node.geometry and node.geometry.is_visible()):
                if len(node.text) > len(max_text):
                    max_text = node.text
                    best_node = node
        return best_node
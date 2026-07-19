"""Deterministic DOM segmentation and form analysis using pure mathematics.

This module provides `MathFormUnderstandingService`, a concrete
implementation of `FormUnderstandingPort`. It performs:
  - Vision‑based page segmentation (VIPS‑inspired).
  - Geometric clustering of form fields.
  - Bipartite matching of labels to inputs (Hungarian algorithm).
  - Heuristic field type inference.
  - Honeypot detection.
  - Multi‑step form detection.

All algorithms operate on the immutable `DOMNode` tree and require
no external machine‑learning libraries.
"""

from __future__ import annotations

import math
from collections import defaultdict

from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.models.math_webpage import (
    FieldCluster,
    FieldType,
    FormRegion,
    LabeledField,
    WebpageStructure,
)
from auto_apply.domain.ports.math_reasoning_port import FormUnderstandingPort
from auto_apply.domain.services.label_input_pairing import hungarian_assign
from auto_apply.domain.services.structural_hashing import is_card_like

# Penalty for dummy (padding) cells in the square Hungarian cost matrix. Must be
# far larger than any real pairing cost (which is bounded by MAX_LABEL_DISTANCE
# plus a small DOM-distance term) yet finite — +inf would make an all-dummy row
# loop forever in the potentials-based solver.
_DUMMY_PAIR_COST: float = 1e9


class MathFormUnderstandingService(FormUnderstandingPort):
    """Pure mathematical implementation of webpage form analysis.

    This service is stateless and thread‑safe. It can be instantiated
    once and reused across multiple pages.

    All configurable thresholds are exposed as constructor parameters
    to allow tuning without code changes.
    """

    # ----------------------------------------------------------------------
    # Configuration constants (tunable thresholds)
    # ----------------------------------------------------------------------
    # Minimum area (px²) for an element to be considered visible.
    MIN_VISIBLE_AREA: float = 4.0

    # Maximum distance (px) between a label and an input to consider them paired.
    MAX_LABEL_DISTANCE: float = 300.0

    # Vertical gap (px) that separates form sections.
    SECTION_GAP_THRESHOLD: float = 60.0

    # Horizontal tolerance for clustering fields in the same line.
    HORIZONTAL_TOLERANCE: float = 30.0

    # Minimum number of inputs to consider a subtree a form container.
    MIN_INPUTS_FOR_FORM: int = 2

    def __init__(self, **kwargs) -> None:
        """Initialize with optional overrides for thresholds."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    # ======================================================================
    # Public API
    # ======================================================================

    def analyze(self, dom_root: DOMNode, url: str = "", title: str = "") -> WebpageStructure:
        """Execute full analysis pipeline and return WebpageStructure."""
        self._root_for_label_search = dom_root

        # Build parent map once for the entire tree (used in multiple places)
        self._parent_map = self._build_parent_map(dom_root)

        # Step 1: Extract all interactable nodes (inputs, buttons, etc.)
        interactables = self._extract_interactables(dom_root)

        # Step 2: Segment page into visual blocks (optional, used for form detection)
        # For simplicity, we directly find form containers via ancestor scoring.
        form_containers = self._find_form_containers(dom_root, interactables)

        # Step 3: For each form container, build FormRegion
        forms: list[FormRegion] = []
        for container in form_containers:
            region = self._analyze_form_container(container, interactables)
            if region:
                forms.append(region)

        # Step 4: Detect job listings (structural similarity based on hashes)
        job_listings = self._detect_job_listings(dom_root)

        # Step 5: Detect CAPTCHA and login walls (simple heuristics)
        is_captcha = self._detect_captcha(dom_root)
        is_login = self._detect_login_wall(dom_root)

        return WebpageStructure(
            url=url,
            title=title,
            dom_root=dom_root,
            forms=forms,
            job_listings=job_listings,
            is_captcha_present=is_captcha,
            is_login_wall=is_login,
        )

    # ======================================================================
    # Interactable Extraction
    # ======================================================================

    def _extract_interactables(self, root: DOMNode) -> list[DOMNode]:
        """Return all visible, interactable form elements."""
        result: list[DOMNode] = []
        for node in root.iter_nodes():
            if not self._is_visible(node):
                continue
            if node.is_interactable:
                result.append(node)
        return result

    @staticmethod
    def _is_visible(node: DOMNode, min_area: float = 4.0) -> bool:
        """Heuristic visibility check using geometry."""
        if not node.geometry:
            return False
        geom = node.geometry
        return geom.width > 0 and geom.height > 0 and geom.area >= min_area

    # ======================================================================
    # Form Container Detection
    # ======================================================================

    def _find_form_containers(
        self, root: DOMNode, interactables: list[DOMNode]
    ) -> list[DOMNode]:
        """Return a list of DOMNodes that are likely to be form containers.

        Scores each node based on the number of interactable descendants,
        then selects the highest‑scoring subtrees that do not overlap.
        """
        # Map each node to the set of interactables it contains
        node_to_inputs: dict[DOMNode, set[DOMNode]] = defaultdict(set)
        for inp in interactables:
            # Walk up the tree and add this input to each ancestor
            # Since DOMNode doesn't have parent pointer, we pre‑compute
            # a parent map during a single traversal.
            pass

        # For efficiency, we build a parent map first.
        parent_map = self._build_parent_map(root)

        for inp in interactables:
            current = inp
            while current is not None:
                node_to_inputs[current].add(inp)
                current = parent_map.get(current)

        # Score each node: number of inputs it contains
        candidates = []
        for node, inputs in node_to_inputs.items():
            if len(inputs) >= self.MIN_INPUTS_FOR_FORM:
                candidates.append((len(inputs), node))

        if not candidates:
            return []

        # Sort by score descending
        candidates.sort(key=lambda x: x[0], reverse=True)

        # Greedy selection: pick highest scoring, then remove any node
        # that is an ancestor/descendant of a chosen one to avoid overlaps.
        selected: list[DOMNode] = []
        chosen_ancestors: set[DOMNode] = set()
        for _, node in candidates:
            # Check if node is ancestor/descendant of already chosen
            if self._has_overlap(node, chosen_ancestors, parent_map):
                continue
            selected.append(node)
            # Mark all ancestors and descendants (simplified: mark only node)
            chosen_ancestors.add(node)

        return selected

    def _build_parent_map(self, root: DOMNode) -> dict[DOMNode, DOMNode | None]:
        """Return a dictionary mapping each node to its parent."""
        parent_map: dict[DOMNode, DOMNode | None] = {root: None}
        stack = [root]
        while stack:
            node = stack.pop()
            for child in node.children:
                parent_map[child] = node
                stack.append(child)
        return parent_map

    @staticmethod
    def _has_overlap(
        node: DOMNode, selected: set[DOMNode], parent_map: dict[DOMNode, DOMNode | None]
    ) -> bool:
        """Return True if node is ancestor or descendant of any node in selected."""
        # Check if any selected node is an ancestor of node
        current = node
        while current:
            if current in selected:
                return True
            current = parent_map.get(current)
        # Check if node is ancestor of any selected
        for sel in selected:
            current = sel
            while current:
                if current == node:
                    return True
                current = parent_map.get(current)
        return False

    # ======================================================================
    # Form Region Analysis
    # ======================================================================

    def _analyze_form_container(
        self, container: DOMNode, all_interactables: list[DOMNode]
    ) -> FormRegion | None:
        """Build a FormRegion from a container node."""
        # Get inputs that are inside this container
        inputs = [inp for inp in all_interactables if self._is_descendant(inp, container)]
        if len(inputs) < self.MIN_INPUTS_FOR_FORM:
            return None

        # Pair labels with inputs
        labeled_fields = self._pair_labels_to_inputs(inputs, container)

        # Cluster fields into sections
        clusters = self._cluster_fields(labeled_fields)

        # Identify navigation buttons
        submit_btn = self._find_button(labeled_fields, {"submit", "apply"})
        next_btn = self._find_button(labeled_fields, {"next", "continue"})
        prev_btn = self._find_button(labeled_fields, {"previous", "back"})

        # Detect multi‑step
        is_multi_step = next_btn is not None

        return FormRegion(
            root_node=container,
            clusters=clusters,
            submit_button=submit_btn,
            next_button=next_btn,
            previous_button=prev_btn,
            is_multi_step=is_multi_step,
        )

    def _is_descendant(self, node: DOMNode, ancestor: DOMNode) -> bool:
        """Return True if ``node`` is ``ancestor`` or sits beneath it.

        Walks up the global parent map built once per ``analyze()`` call, rather
        than rebuilding a parent map for ``ancestor`` on every call — the latter
        made the container × interactable membership test O(n²). Falls back to a
        local build only when the cache is absent (e.g. called outside analyze).
        """
        parent_map = getattr(self, "_parent_map", None)
        if parent_map is None:
            parent_map = self._build_parent_map(ancestor)
        current: DOMNode | None = node
        while current is not None:
            if current == ancestor:
                return True
            current = parent_map.get(current)
        return False

    # ======================================================================
    # Label‑Input Pairing (Hungarian Algorithm)
    # ======================================================================

    def _pair_labels_to_inputs(
        self, inputs: list[DOMNode], context: DOMNode
    ) -> list[LabeledField]:
        """Associate each input with its most likely label.

        Steps:
          1. Collect candidate label nodes (text nodes, <label> elements).
          2. Build cost matrix: distance + DOM penalty.
          3. Solve assignment using Hungarian algorithm.
          4. For unassigned inputs, use placeholder or nearby text.
        """
        # Build parent map for the context if not already global
        # (global parent map already exists from analyze())
        labels = self._collect_label_candidates(context)
        # Cache text nodes for later use in _has_associated_label
        self._text_nodes_cache = labels  # reuse the same list

        if not labels:
            # Fallback: create LabeledField with placeholder text
            return [self._create_unlabeled_field(inp) for inp in inputs]

        n_inputs = len(inputs)
        n_labels = len(labels)

        # Build cost matrix (n_inputs x n_labels)
        cost = [[0.0] * n_labels for _ in range(n_inputs)]
        for i, inp in enumerate(inputs):
            for j, lbl in enumerate(labels):
                cost[i][j] = self._pairing_cost(inp, lbl)

        # Pad to a square matrix for the Hungarian solver. Dummy cells carry a
        # large *finite* penalty (BUG-4): the misleading original used 0.0, but
        # +inf is unusable here — an all-inf dummy row (when n_labels > n_inputs)
        # makes the potentials-based solver loop forever. A finite penalty keeps
        # dummy assignments maximally unattractive while remaining solvable; it
        # cancels across perfect matchings, so real pairings are unaffected.
        size = max(n_inputs, n_labels)
        square_cost = [[_DUMMY_PAIR_COST] * size for _ in range(size)]
        for i in range(n_inputs):
            for j in range(n_labels):
                square_cost[i][j] = cost[i][j]

        row_ind, col_ind = hungarian_assign(square_cost)

        labeled_fields: list[LabeledField] = []
        assigned_inputs: set[int] = set()
        assigned_labels: set[int] = set()

        for i, j in zip(row_ind, col_ind):
            if i < n_inputs and j < n_labels:
                inp = inputs[i]
                lbl = labels[j]
                field = self._build_labeled_field(inp, lbl)
                labeled_fields.append(field)
                assigned_inputs.add(i)
                assigned_labels.add(j)

        # Handle unassigned inputs (fallback)
        for i, inp in enumerate(inputs):
            if i not in assigned_inputs:
                labeled_fields.append(self._create_unlabeled_field(inp))

        return labeled_fields

    def _collect_label_candidates(self, context: DOMNode) -> list[DOMNode]:
        """Return all visible text‑containing nodes that could serve as labels."""
        candidates: list[DOMNode] = []
        for node in context.iter_nodes():
            if not self._is_visible(node, min_area=0):
                continue
            # Consider <label> elements, or any node with non‑empty text
            if node.tag == "label" or (node.text and len(node.text.strip()) > 0):
                candidates.append(node)
        return candidates

    def _pairing_cost(self, input_node: DOMNode, label_node: DOMNode) -> float:
        """Compute cost (lower is better) for assigning label to input.

        The cost is a weighted combination of:
            - Euclidean distance between the centers of the two nodes.
            - DOM tree distance (log‑scaled) to penalize labels far away in the hierarchy.

        Missing geometry results in a high default cost.
        """
        # Spatial distance
        spatial_cost = 1000.0  # default high cost
        if input_node.geometry and label_node.geometry:
            dist = input_node.geometry.distance_to(label_node.geometry)
            spatial_cost = min(dist, self.MAX_LABEL_DISTANCE)

        # DOM tree distance (using parent map)
        dom_cost = 0.0
        if hasattr(self, '_parent_map') and self._parent_map is not None:
            try:
                # Compute distance via lowest common ancestor
                dist_tree = self._tree_distance(input_node, label_node)
                # Use log to dampen; +1 ensures log(1) = 0
                dom_cost = math.log1p(dist_tree) * 2.0  # weight factor 2.0
            except Exception:
                dom_cost = 10.0  # fallback penalty if LCA fails

        # Combined cost: spatial dominates, but DOM proximity helps break ties
        return spatial_cost + dom_cost

    def _tree_distance(self, node_a: DOMNode, node_b: DOMNode) -> int:
        """Compute the number of edges between two nodes in the DOM tree."""
        if node_a is node_b:
            return 0
        # Build path from node_a to root
        path_a = set()
        curr = node_a
        while curr is not None:
            path_a.add(curr)
            curr = self._parent_map.get(curr)
        # Walk up from node_b until we hit a node in path_a (the LCA)
        curr = node_b
        lca = None
        while curr is not None:
            if curr in path_a:
                lca = curr
                break
            curr = self._parent_map.get(curr)
        if lca is None:
            # Should not happen if both are in the same tree
            return 1_000_000
        depth_a = self._node_depth(node_a)
        depth_b = self._node_depth(node_b)
        depth_lca = self._node_depth(lca)
        return depth_a + depth_b - 2 * depth_lca

    def _node_depth(self, node: DOMNode) -> int:
        """Return depth of a node (root = 0)."""
        depth = 0
        curr = node
        while self._parent_map.get(curr) is not None:
            depth += 1
            curr = self._parent_map[curr]
        return depth

    def _build_labeled_field(
        self, input_node: DOMNode, label_node: DOMNode
    ) -> LabeledField:
        """Construct a LabeledField from paired nodes."""
        label_text = label_node.text.strip() if label_node.text else ""
        # Use placeholder or aria-label as fallback
        if not label_text:
            label_text = input_node.get_attribute("placeholder", "")
        if not label_text:
            label_text = input_node.get_attribute("aria-label", "")

        field_type = self._infer_field_type(input_node, label_text)
        is_required = self._is_required(input_node)
        is_honeypot = self._is_honeypot(input_node)

        options: list[str] = []
        if input_node.tag == "select":
            options = self._extract_select_options(input_node)

        return LabeledField(
            input_node=input_node,
            label_node=label_node,
            label_text=label_text,
            inferred_type=field_type,
            is_required=is_required,
            is_honeypot=is_honeypot,
            options=options,
        )

    def _create_unlabeled_field(self, input_node: DOMNode) -> LabeledField:
        """Create a LabeledField without an associated label node."""
        label_text = (
            input_node.get_attribute("placeholder", "")
            or input_node.get_attribute("aria-label", "")
            or ""
        )
        field_type = self._infer_field_type(input_node, label_text)
        return LabeledField(
            input_node=input_node,
            label_node=None,
            label_text=label_text,
            inferred_type=field_type,
            is_required=self._is_required(input_node),
            is_honeypot=self._is_honeypot(input_node),
        )

    # ======================================================================
    # Field Clustering
    # ======================================================================

    def _cluster_fields(self, fields: list[LabeledField]) -> list[FieldCluster]:
        """Group fields into sections based on vertical gaps."""
        if not fields:
            return []

        # Sort fields by vertical position (top to bottom)
        sorted_fields = sorted(
            fields,
            key=lambda f: f.input_node.geometry.y if f.input_node.geometry else 0.0,
        )

        clusters: list[FieldCluster] = []
        current_cluster_fields: list[LabeledField] = [sorted_fields[0]]
        prev_y = self._get_bottom_y(sorted_fields[0].input_node)

        for field in sorted_fields[1:]:
            current_y = field.input_node.geometry.y if field.input_node.geometry else 0.0
            if current_y - prev_y > self.SECTION_GAP_THRESHOLD:
                # Start new cluster
                clusters.append(FieldCluster(fields=current_cluster_fields))
                current_cluster_fields = [field]
            else:
                current_cluster_fields.append(field)
            prev_y = max(prev_y, self._get_bottom_y(field.input_node))

        if current_cluster_fields:
            clusters.append(FieldCluster(fields=current_cluster_fields))

        return clusters

    @staticmethod
    def _get_bottom_y(node: DOMNode) -> float:
        if node.geometry:
            return node.geometry.y + node.geometry.height
        return 0.0

    # ======================================================================
    # Field Type Inference (Mathematical Scoring)
    # ======================================================================

    def _infer_field_type(self, input_node: DOMNode, label_text: str) -> FieldType:
        """Determine the semantic type of an input using scoring heuristics."""
        scores: dict[FieldType, int] = defaultdict(int)

        # Attributes
        type_attr = input_node.get_attribute("type", "").lower()
        name_attr = input_node.get_attribute("name", "").lower()
        id_attr = input_node.get_attribute("id", "").lower()
        placeholder = input_node.get_attribute("placeholder", "").lower()
        autocomplete = input_node.get_attribute("autocomplete", "").lower()

        combined = f"{label_text} {name_attr} {id_attr} {placeholder} {autocomplete}".lower()

        # Email patterns
        if type_attr == "email" or "email" in combined:
            scores[FieldType.EMAIL] += 20
        if "e-mail" in combined or "email" in name_attr:
            scores[FieldType.EMAIL] += 10

        # Telephone
        if type_attr == "tel" or "phone" in combined or "mobile" in combined:
            scores[FieldType.TELEPHONE] += 20

        # Name fields
        if "first" in combined and "name" in combined:
            scores[FieldType.FIRST_NAME] += 25
        if "last" in combined and "name" in combined:
            scores[FieldType.LAST_NAME] += 25
        if ("full" in combined or "your name" in combined) and "name" in combined:
            scores[FieldType.FULL_NAME] += 20

        # Address
        if "address" in combined:
            scores[FieldType.STREET_ADDRESS] += 15
        if "city" in combined:
            scores[FieldType.CITY] += 20
        if "state" in combined or "province" in combined:
            scores[FieldType.STATE] += 20
        if "zip" in combined or "postal" in combined:
            scores[FieldType.ZIP_CODE] += 20

        # File uploads
        if type_attr == "file":
            if "resume" in combined or "cv" in combined:
                scores[FieldType.RESUME_UPLOAD] += 30
            elif "cover" in combined:
                scores[FieldType.COVER_LETTER_UPLOAD] += 30

        # URLs
        if "linkedin" in combined:
            scores[FieldType.LINKEDIN_URL] += 25
        if "github" in combined:
            scores[FieldType.GITHUB_URL] += 25
        if "portfolio" in combined or "website" in combined:
            scores[FieldType.PORTFOLIO_URL] += 20

        # Legal
        if "authorized" in combined or "eligibility" in combined:
            scores[FieldType.WORK_AUTHORIZATION] += 15
        if "sponsor" in combined:
            scores[FieldType.SPONSORSHIP] += 15

        # Select boxes
        if input_node.tag == "select":
            scores[FieldType.SELECT] += 10

        # Determine highest scoring type
        if scores:
            best_type = max(scores.items(), key=lambda x: x[1])[0]
            return best_type

        # Fallbacks based on input type
        if type_attr == "email":
            return FieldType.EMAIL
        if type_attr == "tel":
            return FieldType.TELEPHONE
        if type_attr == "file":
            return FieldType.RESUME_UPLOAD  # default assumption

        return FieldType.TEXT

    @staticmethod
    def _is_required(input_node: DOMNode) -> bool:
        """Check for 'required' attribute or aria-required."""
        return (
            input_node.get_attribute("required") is not None
            or input_node.get_attribute("aria-required", "").lower() == "true"
        )

    # ======================================================================
    # Honeypot Detection
    # ======================================================================

    def _is_honeypot(self, input_node: DOMNode) -> bool:
        """Return True if the input is likely a security trap."""
        # Hidden via CSS (zero size)
        if input_node.geometry and not input_node.geometry.is_visible(min_area=1.0):
            return True

        # Off‑screen (far left/top)
        if input_node.geometry:
            if input_node.geometry.x < -1000 or input_node.geometry.y < -1000:
                return True

        # Suspicious name patterns
        name = input_node.get_attribute("name", "").lower()
        suspicious = {"fax", "confirm_email", "extra", "hidden", "url2", "email2"}
        if any(bad in name for bad in suspicious):
            return True

        # No label and no placeholder
        if not input_node.get_attribute("placeholder") and not self._has_associated_label(input_node):
            return True

        return False

    def _has_associated_label(self, input_node: DOMNode) -> bool:
        """Heuristic: check if there is any visible text near the input."""
        if not input_node.geometry:
            return False

        # We'll use a pre‑collected list of text nodes in the current context.
        # For simplicity, we assume the caller (e.g., `_pair_labels_to_inputs`)
        # passes a list of candidate label nodes. However, this method is called
        # during honeypot detection where we may not have the full label list.
        # Fallback: search for any text node within a generous bounding box.
        candidates = getattr(self, '_text_nodes_cache', [])
        if not candidates:
            # If cache not built, build it from the root (expensive; do once)
            candidates = self._collect_visible_text_nodes(self._root_for_label_search)
            self._text_nodes_cache = candidates

        input_geom = input_node.geometry
        # Define a search region: above and to the left of the input
        search_rect = Geometry(
            x=input_geom.x - 150,               # extend left
            y=input_geom.y - 50,                # extend up
            width=300,                          # wide enough for typical labels
            height=input_geom.height + 50,      # cover input and area above
        )

        for node in candidates:
            if node.geometry is None:
                continue
            # Check if node's center is within the search rectangle
            cx, cy = node.geometry.center
            if (search_rect.x <= cx <= search_rect.x + search_rect.width and
                search_rect.y <= cy <= search_rect.y + search_rect.height):
                # Also ensure node has non‑empty text
                if node.text and len(node.text.strip()) > 0:
                    return True
        return False

    def _collect_visible_text_nodes(self, root: DOMNode) -> list[DOMNode]:
        """Return all visible nodes that contain text and could serve as labels."""
        result = []
        for node in root.iter_nodes():
            if not self._is_visible(node, min_area=0):
                continue
            if node.text and len(node.text.strip()) > 0:
                result.append(node)
        return result

    # ======================================================================
    # Select Option Extraction
    # ======================================================================

    @staticmethod
    def _extract_select_options(select_node: DOMNode) -> list[str]:
        """Extract visible text of <option> children."""
        options: list[str] = []
        for child in select_node.children:
            if child.tag == "option":
                text = child.text.strip()
                if text:
                    options.append(text)
        return options

    # ======================================================================
    # Button Identification
    # ======================================================================

    @staticmethod
    def _find_button(
        fields: list[LabeledField], keywords: set[str]
    ) -> LabeledField | None:
        """Return the first field whose label or text contains any keyword."""
        for field in fields:
            text = field.label_text.lower()
            if any(kw in text for kw in keywords):
                return field
        return None

    # ======================================================================
    # Job Listing Detection
    # ======================================================================

    def _detect_job_listings(self, root: DOMNode) -> list[DOMNode]:
        """Find nodes that likely represent job cards using structural similarity."""
        # Collect all nodes that could be cards (e.g., <li>, <div> with certain classes)
        candidates = []
        for node in root.iter_nodes():
            if self._is_likely_card(node):
                candidates.append(node)

        # Group by structural hash to find repeated patterns
        hash_groups: dict[str, list[DOMNode]] = defaultdict(list)
        for node in candidates:
            hash_groups[node.structural_hash].append(node)

        # If a hash appears multiple times, it's likely a repeated card
        listings = []
        for nodes in hash_groups.values():
            if len(nodes) >= 2:
                listings.extend(nodes)

        return listings

    @staticmethod
    def _is_likely_card(node: DOMNode) -> bool:
        """Heuristics for a job card container (geometry + structure).

        Delegates to the shared :func:`is_card_like` guard so listing detection
        here and structural-pattern card detection in MathematicalWebAnalyzer
        stay in lockstep.
        """
        return is_card_like(node)

    # ======================================================================
    # CAPTCHA / Login Detection
    # ======================================================================

    @staticmethod
    def _detect_captcha(root: DOMNode) -> bool:
        """Check for known CAPTCHA indicators."""
        for node in root.iter_nodes():
            if node.tag == "iframe":
                src = node.get_attribute("src", "").lower()
                if "recaptcha" in src or "hcaptcha" in src:
                    return True
            classes = node.get_attribute("class", "").lower()
            if "g-recaptcha" in classes:
                return True
        return False

    @staticmethod
    def _detect_login_wall(root: DOMNode) -> bool:
        """Check if page is primarily a login screen."""
        # Count password fields and login buttons
        password_count = 0
        login_button = False
        for node in root.iter_nodes():
            if node.tag == "input" and node.get_attribute("type") == "password":
                password_count += 1
            if node.tag == "button":
                text = node.text.lower()
                if "sign in" in text or "log in" in text:
                    login_button = True
        return password_count >= 1 and login_button
"""Deterministic DOM segmentation and form analysis using pure mathematics.

This module provides `MathFormUnderstandingService`, a concrete
implementation of `FormUnderstandingPort`. It performs:
  - Vision‑based page segmentation (VIPS‑inspired).
  - Geometric clustering of form fields.
  - Reading each form's fields (domain/services/form_fields.py, slice S4):
    the label pairing ladder with a capped residual assignment, question
    groups, tri-state requiredness and the honeypot decision rule.
  - Multi‑step form detection.

All algorithms operate on the immutable `DOMNode` tree and require
no external machine‑learning libraries.
"""

from __future__ import annotations

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

from auto_apply.domain.models.math_dom import DOMNode
from auto_apply.domain.models.math_webpage import (
    FieldCluster,
    FieldType,
    FormRegion,
    LabeledField,
    WebpageStructure,
)
from auto_apply.domain.ports.math_reasoning_port import FormUnderstandingPort
from auto_apply.domain.models.page_record import FormRecord, ListingDetectionFacts
from auto_apply.domain.services.form_fields import (
    FormReadingParams,
    build_index,
    is_form_control,
    read_form,
)
from auto_apply.domain.services.structural_hashing import (
    chrome_node_ids,
    has_semantic_marker,
    is_card_like,
)



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
        # Ids, label[for] targets and document order, once per page (S4).
        self._index = build_index(dom_root)

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
        job_listings, listing_facts = self._detect_job_listings_with_facts(dom_root)

        # No step 5: page identity (challenge / login wall) is answered by the
        # ONE page verdict (domain/services/page_assessment.py). This service
        # used to compute its own answer into fields nothing read.
        return WebpageStructure(
            url=url,
            title=title,
            dom_root=dom_root,
            forms=forms,
            job_listings=job_listings,
            listing_facts=listing_facts,
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
        # Map each node to the set of interactables it contains.
        #
        # Keyed by ``id(node)``, not by the node. ``DOMNode`` is a frozen
        # dataclass, so its generated ``__hash__`` recurses through
        # ``children`` — hashing one node hashes its whole subtree, uncached.
        # Using nodes as keys here cost ~1.1 ms per dict operation on a real
        # SERP and, worse, made two structurally identical sibling cards a
        # single key, merging their input sets. Identity is what this map
        # means: which node, not which shape.
        node_to_inputs: dict[int, set[int]] = defaultdict(set)
        nodes_by_id: dict[int, DOMNode] = {}

        # For efficiency, we build a parent map first.
        parent_map = self._build_parent_map(root)

        for inp in interactables:
            current: DOMNode | None = inp
            while current is not None:
                nodes_by_id[id(current)] = current
                node_to_inputs[id(current)].add(id(inp))
                current = parent_map.get(id(current))

        # Score each node: number of inputs it contains
        candidates = []
        for node_id, inputs in node_to_inputs.items():
            if len(inputs) >= self.MIN_INPUTS_FOR_FORM:
                candidates.append((len(inputs), nodes_by_id[node_id]))

        if not candidates:
            return []

        # Sort by score descending
        candidates.sort(key=lambda x: x[0], reverse=True)

        # Greedy selection: pick highest scoring, then remove any node
        # that is an ancestor/descendant of a chosen one to avoid overlaps.
        selected: list[DOMNode] = []
        chosen_ancestors: set[int] = set()
        for _, node in candidates:
            # Check if node is ancestor/descendant of already chosen
            if self._has_overlap(node, chosen_ancestors, parent_map):
                continue
            selected.append(node)
            # Mark all ancestors and descendants (simplified: mark only node)
            chosen_ancestors.add(id(node))

        return selected

    def _build_parent_map(self, root: DOMNode) -> dict[int, DOMNode | None]:
        """Return a dictionary mapping each node's ``id()`` to its parent.

        Keyed by identity rather than by the node itself, for two reasons that
        are both load-bearing:

        * **Correctness.** ``DOMNode`` equality is structural, so two identical
          sibling job cards are the same dict key. A node-keyed map silently
          collapses them and then hands back the wrong parent — on a SERP,
          which is repeated identical cards by definition, that is most of the
          page.
        * **Cost.** The frozen dataclass ``__hash__`` recurses through
          ``children`` and is not cached, so every lookup hashes an entire
          subtree. Measured at ~1.1 ms per lookup on a 2,641-node Google SERP,
          which is what made ``analyze()`` take minutes.

        Values stay real ``DOMNode`` objects, and ``analyze()`` holds the root
        for the map's whole lifetime, so no node can be collected and no id
        reused while the map is in use.

        Args:
            root: Root of the tree to index.

        Returns:
            ``{id(node): parent_node_or_None}`` for every node in the tree.
        """
        parent_map: dict[int, DOMNode | None] = {id(root): None}
        stack = [root]
        while stack:
            node = stack.pop()
            for child in node.children:
                parent_map[id(child)] = node
                stack.append(child)
        return parent_map

    @staticmethod
    def _has_overlap(
        node: DOMNode,
        selected: set[int],
        parent_map: dict[int, DOMNode | None],
    ) -> bool:
        """Return True if node is ancestor or descendant of any selected node.

        ``selected`` holds ``id()`` values and comparisons are by identity, to
        match :meth:`_build_parent_map`. Structural equality would treat two
        distinct-but-identical cards as overlapping and discard one of them.

        Args:
            node: Candidate container.
            selected: ``id()`` of the containers already chosen.
            parent_map: Identity-keyed parent map from ``_build_parent_map``.

        Returns:
            True if the candidate overlaps anything already chosen.
        """
        # Check if any selected node is an ancestor of node
        current: DOMNode | None = node
        while current is not None:
            if id(current) in selected:
                return True
            current = parent_map.get(id(current))
        # Check if node is ancestor of any selected
        for sel_id in selected:
            current = parent_map.get(sel_id)
            while current is not None:
                if current is node:
                    return True
                current = parent_map.get(id(current))
        return False

    # ======================================================================
    # Form Region Analysis
    # ======================================================================

    def _analyze_form_container(
        self, container: DOMNode, all_interactables: list[DOMNode]
    ) -> FormRegion | None:
        """Build a FormRegion from a container node.

        The container is found from visible controls; its fields are every
        form control inside it, visible or not, so a required control hidden
        by CSS is still reported, flagged hidden (defect 13, EC-36).
        """
        # Get inputs that are inside this container
        inputs = [inp for inp in all_interactables if self._is_descendant(inp, container)]
        if len(inputs) < self.MIN_INPUTS_FOR_FORM:
            return None
        visible = {id(inp) for inp in inputs}
        controls = list(inputs) + [
            node for node in container.iter_nodes()
            if id(node) not in visible and is_form_control(node)
        ]

        # Pair labels with inputs
        labeled_fields, record = self._read_fields(controls, container)

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
            record=record,
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
            if current is ancestor:
                return True
            current = parent_map.get(id(current))
        return False

    # ======================================================================
    # Label‑Input Pairing: the ladder, then geometry on the residual
    # ======================================================================

    def _read_fields(
        self, inputs: list[DOMNode], context: DOMNode
    ) -> tuple[list[LabeledField], FormRecord]:
        """Read the controls of one form (domain/services/form_fields.py).

        The pairing ladder runs first (explicit associations are constraints);
        geometry assigns only the residual, capped at ``m <= 120`` per
        section; groups, requiredness and the trap decision follow. The
        document index is the one built for this page by :meth:`analyze`,
        or one built for ``context`` when called on its own.
        """
        index = getattr(self, "_index", None)
        if index is None or id(context) not in index.order:
            index = build_index(context)
        params = FormReadingParams(
            max_label_distance=self.MAX_LABEL_DISTANCE,
            section_gap=self.SECTION_GAP_THRESHOLD,
        )
        return read_form(context, inputs, index, params)

    def _pair_labels_to_inputs(
        self, inputs: list[DOMNode], context: DOMNode
    ) -> list[LabeledField]:
        """Associate each input with its label (the fields of :meth:`_read_fields`)."""
        return self._read_fields(inputs, context)[0]

    def _tree_distance(self, node_a: DOMNode, node_b: DOMNode) -> int:
        """Compute the number of edges between two nodes in the DOM tree."""
        if node_a is node_b:
            return 0
        # Build path from node_a to root
        path_a = set()
        curr: DOMNode | None = node_a
        while curr is not None:
            path_a.add(id(curr))
            curr = self._parent_map.get(id(curr))
        # Walk up from node_b until we hit a node in path_a (the LCA)
        curr = node_b
        lca = None
        while curr is not None:
            if id(curr) in path_a:
                lca = curr
                break
            curr = self._parent_map.get(id(curr))
        if lca is None:
            # Should not happen if both are in the same tree
            return 1_000_000
        depth_a = self._node_depth(node_a)
        depth_b = self._node_depth(node_b)
        depth_lca = self._node_depth(lca)
        return depth_a + depth_b - 2 * depth_lca

    def _node_depth(self, node: DOMNode) -> int:
        """Return depth of a node (root = 0).

        Every parent lookup goes through a narrowed local because
        ``self._parent_map`` values are ``DOMNode | None`` and mypy cannot
        narrow through a subscript.
        """
        depth = 0
        curr = node
        while True:
            parent = self._parent_map.get(id(curr))
            if parent is None:
                return depth
            depth += 1
            curr = parent

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

    @staticmethod
    def _is_required(input_node: DOMNode) -> bool:
        """Check for 'required' attribute or aria-required."""
        return (
            any(name == "required" for name, _ in input_node.attributes)
            or input_node.get_attribute("aria-required", "").lower() == "true"
        )

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

    def detect_job_listings(
        self, root: DOMNode
    ) -> tuple[list[DOMNode], ListingDetectionFacts]:
        """Detect the listing group only, with its numbers; no form analysis.

        Discovery needs the listings and nothing else. :meth:`analyze` also
        segments forms and pairs labels, whose cost is cubic in the visible
        text nodes of a form's container (defect 11): 165 s on one Hacker
        News item page in the S1 specimen run, where the listings took under
        a second. Pure; same result as ``analyze(root).job_listings``.
        """
        return self._detect_job_listings_with_facts(root)

    def _detect_job_listings(self, root: DOMNode) -> list[DOMNode]:
        """Return the single best group of structurally-identical card containers.

        S8f selection policy. The previous implementation UNIONED every
        structural-hash group with >= 2 members. On a live Google SERP that
        returned 71 candidates where 9 real cards exist: each level of a
        nested card chain forms its own structurally-identical group, and
        every level was concatenated. Now:

          1. Group guard-passing candidates by structural hash (unchanged).
          2. Rank groups by (marker fraction, group size, mean area), desc.
          3. Return only the top-ranked group's members.

        If the top group is page chrome rather than cards, the title/url gate
        in PageUnderstandingExtractor drops every record, the fast route
        returns nothing, and FallbackSerpExtractor commits to the DOM miner
        for the page — a wrong selection degrades to pre-S8f behavior, not to
        bogus jobs. This function is a selection change only; it does not
        alter what _extract_job_cards accepts as a Job.

        Known trade-off (ruling R-1/CB-1): a SERP mixing two structurally
        distinct card styles (e.g. promoted + organic) yields only the
        dominant style. Discovery is a sampling exercise; accepted.

        Note: grouping uses DOMNode.structural_hash (tag + sorted classes +
        child hashes). domain/services/structural_hashing.py carries a second
        vocabulary (tag:len(children)) used by find_repeated_patterns. Both
        group identically within a single page load; unifying them is tracked
        as the P3 detector-sub-fork item and is out of scope here.
        """
        return self._detect_job_listings_with_facts(root)[0]

    def _detect_job_listings_with_facts(
        self, root: DOMNode
    ) -> tuple[list[DOMNode], ListingDetectionFacts]:
        """:meth:`_detect_job_listings` plus the numbers the S1 trace records.

        S1 adds one rule: card-like nodes inside a chrome landmark (navigation,
        banner, footer, complementary, search, menu, tab list, toolbar) are
        not candidates. Measured on a LinkedIn guest list (fixture): the
        footer's link list out-ranked the job cards whenever the cards split
        into small exact-hash groups. This is the chrome penalty of the
        blueprint's Algorithm 003 in its smallest form; slice S2's ranked runs
        replace the whole selection.
        """
        chrome = chrome_node_ids(root)
        card_like = [n for n in root.iter_nodes() if self._is_likely_card(n)]
        candidates = [n for n in card_like if id(n) not in chrome]
        excluded = len(card_like) - len(candidates)

        hash_groups: dict[str, list[DOMNode]] = defaultdict(list)
        for node in candidates:
            hash_groups[node.structural_hash].append(node)

        groups = [nodes for nodes in hash_groups.values() if len(nodes) >= 2]
        if not groups:
            return [], ListingDetectionFacts(
                candidate_count=len(candidates), chrome_excluded=excluded
            )

        def _marker_fraction(nodes: list[DOMNode]) -> float:
            return sum(1 for n in nodes if has_semantic_marker(n)) / len(nodes)

        def _mean_area(nodes: list[DOMNode]) -> float:
            areas = [n.geometry.area for n in nodes if n.geometry is not None]
            return sum(areas) / len(areas) if areas else 0.0

        def _rank(ns: list[DOMNode]) -> tuple[float, int, float]:
            return (_marker_fraction(ns), len(ns), _mean_area(ns))

        ranked = sorted(groups, key=_rank, reverse=True)
        best = max(groups, key=_rank)
        facts = ListingDetectionFacts(
            candidate_count=len(candidates),
            chrome_excluded=excluded,
            group_sizes=(len(best),) + tuple(len(g) for g in ranked if g is not best),
        )

        logger.info(
            "card detection: %d candidate group(s) sizes=%s -> "
            "selected %d card(s) (marker_frac=%.2f)",
            len(groups),
            sorted(len(g) for g in groups),
            len(best),
            _marker_fraction(best),
        )
        return best, facts

    @staticmethod
    def _is_likely_card(node: DOMNode) -> bool:
        """Heuristics for a job card container (geometry + structure).

        Delegates to the shared :func:`is_card_like` guard so listing detection
        here and structural-pattern card detection in MathematicalWebAnalyzer
        stay in lockstep.
        """
        return is_card_like(node)


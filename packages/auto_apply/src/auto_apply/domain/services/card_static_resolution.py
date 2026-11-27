"""Pure structural stages of SERP card resolution.

Detection stays in ``MathFormUnderstandingService`` (dom_segmentation). This
module owns the next structural decisions, all pure functions over the
immutable DOMNode tree:

* climb from the detected unit to the addressable unit (one-node-per-card
  invariant, stop at collapse);
* sibling-diff identity learning (same name + same value is chrome; same
  name + distinct values is identity; tracking and positional names
  excluded; page-uniqueness required);
* heading-gated title extraction and the existing company/location
  heuristic (preserved verbatim from the old ``_extract_job_cards``);
* static anchor collection and group orchestration.

Slice S1 changes, each pinned in ``tests/domain/test_s1_record_reading.py``
and found from the S1 trace on real page fixtures:

* titles and link names use the full-subtree text and accessible name
  (defect 4), not only an element's own text nodes;
* the records are read at the **record root** (06 section 1, Lemma 3): the
  lowest non-collapsed level whose nodes hold a title candidate and a primary
  link, instead of the lowest level that has an identity attribute (defect 3).
  Identity is still learned where it is distinct, at any level;
* a record with no heading may take its primary link's name as its title,
  only outside chrome landmarks and only when those names and destinations
  are distinct across the group (06 section 2; table rows on careers boards);
* an anchor that contains the title, or sits inside it, carries
  ``relation="title"`` into the link score;
* anchors leading to one canonical destination are one route.

The record-root rule and the anchor-name title are the smallest correct
form of what slice S2's records tool (CT-T-008) replaces with ranked runs.

No browser, no I/O, no RNG, no vendor strings.
"""

from __future__ import annotations

import urllib.parse

from auto_apply.domain.models.math_dom import TEXT_CAP, DOMNode
from auto_apply.domain.ports.page_understanding_port import (
    CardResolutionState,
    JobCardInfo,
    SerpResolutionReport,
)
from auto_apply.domain.services.structural_hashing import (
    _TRACKING_DATA_ATTRS,
    chrome_node_ids,
)
from auto_apply.domain.services.url_evidence import (
    DENIED_SCHEMES,
    canonical_url,
    decide_resolution_state,
    evaluate_candidates,
    is_dead_end_text,
    merge_candidates,
    resolve_href,
    title_overlap,
)

# Substring hints for attribute names that identify the *element* (tracking
# tokens) or its *position* (which renumbers when a list virtualises).
_TRACKING_ATTR_HINTS = ("ved", "hveid", "lht", "-hd", "bm", "eid", "trace", "nonce")
_POSITIONAL_ATTR_HINTS = ("index", "pos", "idx", "order", "tabindex")

_MIN_ATTR_PRESENCE = 0.6
_MIN_ATTR_DISTINCT = 0.6
_MIN_PAGE_UNIQUE = 0.8
_MAX_CLIMB_HOPS = 12

#: Share of a level's nodes that must hold a title candidate and a primary
#: link for the level to be the record root (06 section 1, condition (c)).
RECORD_ROOT_SHARE = 0.8
#: Share of distinct names and destinations an anchor-titled group needs.
ANCHOR_TITLE_DISTINCT_SHARE = 0.8
#: Anchors read per record (06 section 12, ALG-004 cap).
MAX_ANCHORS_PER_RECORD = 64


def learn_identity_attributes(
    cards: list[DOMNode],
    dom_root: DOMNode | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Return ``(learned_names, evidence)`` from sibling attribute diffing.

    An attribute name qualifies when present on >= 60% of cards with >= 60%
    distinct values, is not tracking-shaped or positional, and (when
    *dom_root* is given) at least 80% of its values occur exactly once in the
    whole tree — the check that kills attributes like ``data-stdtitle`` whose
    values legitimately repeat across a page.
    """
    per_card = [dict(c.attributes) for c in cards]
    names = set().union(*(d.keys() for d in per_card)) if per_card else set()

    learned: list[str] = []
    evidence: dict[str, str] = {}

    page_counts: dict[str, dict[str, int]] = {}
    if dom_root is not None:
        for node in dom_root.iter_nodes():
            for name, value in node.attributes:
                if value:
                    page_counts.setdefault(name, {})
                    page_counts[name][value] = page_counts[name].get(value, 0) + 1

    for name in sorted(names):
        low = name.lower()
        present = [d[name] for d in per_card if name in d and d[name].strip()]

        if len(present) < max(2, int(_MIN_ATTR_PRESENCE * len(per_card))):
            evidence[name] = "not present on enough cards"
            continue

        distinct = len(set(present))
        if distinct == 1:
            evidence[name] = "same value on every card -> page chrome"
        elif name in _TRACKING_DATA_ATTRS or any(h in low for h in _TRACKING_ATTR_HINTS):
            evidence[name] = f"distinct ({distinct}) but tracking-shaped -> excluded"
        elif any(h in low for h in _POSITIONAL_ATTR_HINTS):
            evidence[name] = f"distinct ({distinct}) but positional -> excluded"
        elif distinct < max(2, int(_MIN_ATTR_DISTINCT * len(present))):
            evidence[name] = f"only {distinct}/{len(present)} distinct -> ambiguous"
        elif dom_root is not None:
            counts_for_name = page_counts.get(name, {})
            unique = sum(1 for v in present if counts_for_name.get(v, 0) == 1)
            if unique / len(present) < _MIN_PAGE_UNIQUE:
                evidence[name] = (
                    f"distinct but only {unique}/{len(present)} page-unique -> excluded"
                )
            else:
                evidence[name] = f"distinct and page-unique on {distinct}/{len(present)} -> IDENTITY"
                learned.append(name)
        else:
            evidence[name] = f"distinct on {distinct}/{len(present)} -> IDENTITY"
            learned.append(name)

    learned.sort(key=lambda n: (0 if n == "id" else 1, n))
    return learned, evidence


def parent_map(root: DOMNode) -> dict[int, DOMNode]:
    """Map ``id(child)`` to its parent, by an iterative walk (no recursion)."""
    parents: dict[int, DOMNode] = {}
    stack = [root]
    while stack:
        node = stack.pop()
        for child in node.children:
            parents[id(child)] = node
            stack.append(child)
    return parents


def climb_card_levels(
    cards: list[DOMNode],
    root: DOMNode,
    max_hops: int = _MAX_CLIMB_HOPS,
    parents: dict[int, DOMNode] | None = None,
) -> tuple[list[tuple[str, list[DOMNode]]], int, str]:
    """Return ``(levels, detected_parent_count, note)``.

    Every level that remains one-node-per-card is kept; the walk stops at
    the first hop where the parents collapse to fewer nodes than cards.
    The bound exists only for safety; collapse is the real stop.
    """
    if not cards:
        return [], 0, "no cards"

    parent_of = parents if parents is not None else parent_map(root)

    detected_parent_count = len(
        {id(parent_of.get(id(c))) for c in cards if parent_of.get(id(c)) is not None}
    )

    levels: list[tuple[str, list[DOMNode]]] = [("detected", list(cards))]
    current = list(cards)
    note = "never collapsed"

    for hop in range(1, max_hops + 1):
        up: list[DOMNode] = []
        for node in current:
            parent = parent_of.get(id(node))
            up.append(parent if parent is not None else node)
        unique_count = len({id(n) for n in up})
        if unique_count != len(cards):
            note = (
                f"hop {hop}: collapses to {unique_count} node(s) "
                f"for {len(cards)} card(s)"
            )
            break
        levels.append((f"+{hop}", up))
        current = up

    return levels, detected_parent_count, note


def pick_identity_level(
    levels: list[tuple[str, list[DOMNode]]],
    dom_root: DOMNode | None = None,
) -> tuple[str, tuple[str, ...], dict[str, str], list[DOMNode]]:
    """Pick the lowest level that yields a learnable identity attribute.

    Returns ``(level_label, learned, evidence, cards_at_that_level)``.
    Falls back to the detected level with empty identity.
    """
    if not levels:
        return "none", (), {}, []
    for label, nodes in levels:
        learned, evidence = learn_identity_attributes(nodes, dom_root)
        if learned:
            return label, tuple(learned), evidence, nodes
    label, nodes = levels[0]
    _, evidence = learn_identity_attributes(nodes, dom_root)
    return label, (), evidence, nodes


_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
#: A name this long reached the extraction's text cap.
TEXT_CAP_GUARD = TEXT_CAP


def _is_heading(node: DOMNode) -> bool:
    return (
        node.tag in _HEADING_TAGS
        or node.get_attribute("role", "").strip().lower() == "heading"
    )


def _named_text(node: DOMNode) -> tuple[str, bool]:
    """A node's name for reading: accessible name, else full-subtree text."""
    if node.accessible_name:
        return node.accessible_name, node.text_truncated
    return node.subtree_text()


def heading_title(card: DOMNode) -> tuple[str, bool, DOMNode | None]:
    """Return ``(title, truncated, heading_node)`` from heading candidates.

    The heading gate and tie-break of :func:`extract_card_title`; the text is
    the heading's accessible name or full-subtree text (defect 4).
    """
    best = ""
    best_score = 0.0
    best_truncated = False
    best_node: DOMNode | None = None
    for node in card.iter_nodes():
        if not _is_heading(node):
            continue
        text, truncated = _named_text(node)
        text = text.strip()
        if not text:
            continue
        height = node.geometry.height if node.geometry else 0.0
        score = height + min(len(text), 60) / 10.0
        if score > best_score:
            best, best_score, best_truncated, best_node = text, score, truncated, node
    return best, best_truncated, best_node


def extract_card_title(card: DOMNode) -> str:
    """Pick the card's title from its heading candidates.

    Title extraction is heading-gated on purpose: only nodes with heading
    semantics (``h1``–``h6`` or ARIA ``role="heading"``) and non-empty text
    are candidates. A card with no heading gets ``""`` — never a
    placeholder, and never the longest prominent text on the card. That
    gate is what keeps navigation chrome (tab bars, filter chips) out of
    the job pipeline: those elements carry plenty of prominent text and no
    heading. Rendered height and text length only break ties *between*
    heading candidates. The heading's text is its accessible name or its
    full-subtree text, so ``<h3><span>Title</span></h3>`` has a title.
    (The group-level anchor-name title is applied in
    :func:`resolve_card_group`, never here.)
    """
    return heading_title(card)[0]


def extract_company_location(card: DOMNode, title: str) -> tuple[str, str]:
    """The pre-existing heuristic, preserved verbatim from the old
    ``_extract_job_cards``: first non-title text node is the company, the
    next is the location."""
    text_nodes = [
        n.text.strip()
        for n in card.iter_nodes()
        if n.text.strip() and n.tag not in {"script", "style"}
    ]
    if title:
        text_nodes = [t for t in text_nodes if t != title]
    company = text_nodes[0] if text_nodes else ""
    location = text_nodes[1] if len(text_nodes) > 1 else ""
    return company, location


def _contains(outer: DOMNode, inner: DOMNode) -> bool:
    return any(n is inner for n in outer.iter_nodes())


def static_candidates(
    card: DOMNode, title_node: DOMNode | None = None
) -> list[dict[str, str]]:
    """Collect in-card anchors in document order, without preferring the first.

    Each item carries the anchor's name (accessible name or full-subtree
    text) and ``relation="title"`` when the anchor contains ``title_node``
    or sits inside it. At most :data:`MAX_ANCHORS_PER_RECORD` anchors with an
    ``href`` are read. An anchor with no ``href`` is never a candidate.
    """
    candidates: list[dict[str, str]] = []
    stack: list[tuple[DOMNode, bool]] = [(card, False)]
    while stack and len(candidates) < MAX_ANCHORS_PER_RECORD:
        node, inside_title = stack.pop()
        inside = inside_title or (title_node is not None and node is title_node)
        if node.tag == "a":
            href = (node.get_attribute("href") or "").strip()
            if href:
                related = inside or (
                    title_node is not None and _contains(node, title_node)
                )
                item = {"href": href, "text": _named_text(node)[0], "source": "static"}
                if related:
                    item["relation"] = "title"
                candidates.append(item)
        for child in reversed(node.children):
            stack.append((child, inside))
    return candidates


def _primary_href(item: dict[str, str], base_url: str) -> str:
    """Canonical destination of an anchor item, or "" when it is not one."""
    href = item.get("href", "")
    if not href or href.startswith("#"):
        return ""
    try:
        absolute = resolve_href(href, base_url)
    except Exception:  # noqa: BLE001 - malformed href is simply not primary
        return ""
    scheme = urllib.parse.urlsplit(absolute).scheme.lower()
    if scheme in DENIED_SCHEMES or scheme not in {"http", "https"}:
        return ""
    return canonical_url(absolute)


#: Title overlap at which a link's name or URL counts as naming the title.
RELATED_LINK_OVERLAP = 0.5


def _has_heading_record(node: DOMNode, base_url: str) -> bool:
    """Condition (c), heading tier: a heading title and a link related to it.

    Related: the link contains the heading or sits inside it, or its name or
    URL carries at least :data:`RELATED_LINK_OVERLAP` of the title's tokens.
    A link that merely shares the block (a company link beside the title) is
    not the record's primary link, so a block holding only the title and a
    company link is not yet the record root (LinkedIn fixture).
    """
    title, _truncated, title_node = heading_title(node)
    if not title:
        return False
    for item in static_candidates(node, title_node):
        destination = _primary_href(item, base_url)
        if not destination:
            continue
        if item.get("relation") == "title":
            return True
        if title_overlap(title, item.get("text", "") + " " + destination) >= RELATED_LINK_OVERLAP:
            return True
    return False


def _has_named_link_record(node: DOMNode, base_url: str) -> bool:
    """Condition (c), link tier: a primary link with a name (no heading)."""
    return any(
        _primary_href(item, base_url) and item.get("text", "").strip()
        for item in static_candidates(node)
    )


def _pairwise_disjoint(nodes: list[DOMNode], parents: dict[int, DOMNode]) -> bool:
    members = {id(n) for n in nodes}
    for node in nodes:
        up = parents.get(id(node))
        while up is not None:
            if id(up) in members:
                return False
            up = parents.get(id(up))
    return True


def choose_record_level(
    levels: list[tuple[str, list[DOMNode]]],
    parents: dict[int, DOMNode],
    base_url: str,
) -> int:
    """Index of the record-root level, or -1 when no level qualifies.

    The smallest lift whose nodes are one per card (true of every level the
    climb keeps), pairwise disjoint, and of which at least
    :data:`RECORD_ROOT_SHARE` hold a title candidate and a primary link
    (06 section 1, Lemma 3: the search is over a prefix of levels and stops).
    Headings are tried first over all levels; only when no level qualifies
    with a heading are records titled by their link's name considered, so a
    link-only block below the heading (a result's URL line) never wins.
    """
    for test in (_has_heading_record, _has_named_link_record):
        for index, (_label, nodes) in enumerate(levels):
            if not nodes:
                continue
            good = sum(1 for n in nodes if test(n, base_url))
            if good / len(nodes) >= RECORD_ROOT_SHARE and _pairwise_disjoint(nodes, parents):
                return index
    return -1


def anchor_titles(
    records: list[DOMNode],
    chrome: set[int],
    base_url: str,
) -> dict[int, tuple[str, bool]]:
    """Titles from primary-link names for records without a heading.

    Returns ``{record index: (title, truncated)}``. Applied only when the
    group has at least two such records, none inside a chrome landmark, and
    their names and destinations are each at least
    :data:`ANCHOR_TITLE_DISTINCT_SHARE` distinct: a tab bar or a column of
    "Apply" links fails that test, a list of postings passes it.
    """
    picks: dict[int, tuple[str, bool, str]] = {}
    for index, record in enumerate(records):
        if id(record) in chrome or heading_title(record)[0]:
            continue
        for item in static_candidates(record):
            destination = _primary_href(item, base_url)
            name = item.get("text", "").strip()
            if destination and name and not is_dead_end_text(name):
                node_truncated = len(name) >= TEXT_CAP_GUARD
                picks[index] = (name, node_truncated, destination)
                break
    if len(picks) < 2:
        return {}
    names = [p[0].casefold() for p in picks.values()]
    destinations = [p[2] for p in picks.values()]
    share = ANCHOR_TITLE_DISTINCT_SHARE
    if len(set(names)) < share * len(names) or len(set(destinations)) < share * len(destinations):
        return {}
    return {i: (p[0], p[1]) for i, p in picks.items()}


def resolve_card_group(
    cards: list[DOMNode],
    dom_root: DOMNode,
    page_url: str,
    serp_host: str | None = None,
) -> tuple[list[JobCardInfo], SerpResolutionReport]:
    """Run the full static resolution pipeline over a detected card group.

    Returns ``(job_cards, report)``. Cards with no static destination keep
    their learned identity so a later activation stage can re-locate them
    in the live DOM.
    """
    if not cards:
        return [], SerpResolutionReport()

    parents = parent_map(dom_root)
    levels, parent_count, note = climb_card_levels(cards, dom_root, parents=parents)
    identity_label, learned, _evidence, identity_nodes = pick_identity_level(
        levels, dom_root
    )
    record_index = choose_record_level(levels, parents, page_url)
    if record_index >= 0:
        record_label, working = levels[record_index]
    else:
        record_label, working = identity_label, identity_nodes
    serp_host = (serp_host or urllib.parse.urlsplit(page_url).netloc).lower()
    chrome = chrome_node_ids(dom_root)
    fallback_titles = anchor_titles(working, chrome, page_url)

    results: list[JobCardInfo] = []
    for index, card in enumerate(working):
        title, truncated, title_node = heading_title(card)
        source = "heading" if title else "none"
        if not title and index in fallback_titles:
            title, truncated = fallback_titles[index]
            source = "anchor_name"
        company, location = extract_company_location(card, title)
        anchors = static_candidates(card, title_node)
        if source == "anchor_name":
            for item in anchors:
                if item.get("text", "").strip() == title:
                    item["relation"] = "title"
                    break

        if anchors:
            candidates, rejections = evaluate_candidates(
                anchors, title=title, serp_host=serp_host, base_url=page_url
            )
            # Anchors leading to one canonical destination are one route.
            candidates = merge_candidates(candidates)
            state, selected = decide_resolution_state(
                candidates, rejections, material_seen=True
            )
        else:
            candidates, rejections = (), ()
            state, selected = CardResolutionState.NO_DESTINATION, None

        id_attr = id_value = ""
        identity_card = identity_nodes[index] if index < len(identity_nodes) else card
        for attr_name in learned:
            candidate_value = identity_card.get_attribute(attr_name, "")
            if candidate_value:
                id_attr, id_value = attr_name, candidate_value
                break

        results.append(
            JobCardInfo(
                title=title,
                company=company or "Unknown",
                location=location or "",
                url=selected.url if selected else "",
                confidence=1.0 if title else 0.5,
                card_index=index,
                candidates=candidates,
                rejections=rejections,
                resolution_state=state.value,
                identity_attribute=id_attr,
                identity_value=id_value,
                title_source=source,
                title_truncated=bool(title) and truncated,
            )
        )

    report = SerpResolutionReport(
        learned_identity=tuple(learned),
        chosen_level=record_label,
        detected_parent_count=parent_count,
        note=note,
        record_level=record_label if record_index >= 0 else "",
        identity_level=identity_label,
        level_count=len(levels),
    )
    return results, report

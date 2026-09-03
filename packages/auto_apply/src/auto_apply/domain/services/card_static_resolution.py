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

No browser, no I/O, no RNG, no vendor strings.
"""

from __future__ import annotations

import urllib.parse

from auto_apply.domain.models.math_dom import DOMNode
from auto_apply.domain.ports.page_understanding_port import (
    CardResolutionState,
    JobCardInfo,
    SerpResolutionReport,
)
from auto_apply.domain.services.structural_hashing import _TRACKING_DATA_ATTRS
from auto_apply.domain.services.url_evidence import (
    decide_resolution_state,
    evaluate_candidates,
)

# Substring hints for attribute names that identify the *element* (tracking
# tokens) or its *position* (which renumbers when a list virtualises).
_TRACKING_ATTR_HINTS = ("ved", "hveid", "lht", "-hd", "bm", "eid", "trace", "nonce")
_POSITIONAL_ATTR_HINTS = ("index", "pos", "idx", "order", "tabindex")

_MIN_ATTR_PRESENCE = 0.6
_MIN_ATTR_DISTINCT = 0.6
_MIN_PAGE_UNIQUE = 0.8
_MAX_CLIMB_HOPS = 12


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


def climb_card_levels(
    cards: list[DOMNode],
    root: DOMNode,
    max_hops: int = _MAX_CLIMB_HOPS,
) -> tuple[list[tuple[str, list[DOMNode]]], int, str]:
    """Return ``(levels, detected_parent_count, note)``.

    Every level that remains one-node-per-card is kept; the walk stops at
    the first hop where the parents collapse to fewer nodes than cards.
    The bound exists only for safety; collapse is the real stop.
    """
    if not cards:
        return [], 0, "no cards"

    parent_of: dict[int, DOMNode | None] = {}
    for node in root.iter_nodes():
        for child in node.children:
            parent_of[id(child)] = node

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


def extract_card_title(card: DOMNode) -> str:
    """Pick the card's title from its heading candidates.

    Title extraction is heading-gated on purpose: only nodes with heading
    semantics (``h1``–``h6`` or ARIA ``role="heading"``) and non-empty text
    are candidates. A card with no heading gets ``""`` — never a
    placeholder, and never the longest prominent text on the card. That
    gate is what keeps navigation chrome (tab bars, filter chips) out of
    the job pipeline: those elements carry plenty of prominent text and no
    heading. Rendered height and text length only break ties *between*
    heading candidates.
    """
    best = ""
    best_score = 0.0
    for node in card.iter_nodes():
        text = (node.text or "").strip()
        if not text:
            continue
        is_heading = (
            node.tag in _HEADING_TAGS
            or node.get_attribute("role", "").strip().lower() == "heading"
        )
        if not is_heading:
            continue
        height = node.geometry.height if node.geometry else 0.0
        score = height + min(len(text), 60) / 10.0
        if score > best_score:
            best, best_score = text, score
    return best


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


def static_candidates(card: DOMNode) -> list[dict[str, str]]:
    """Collect all in-card anchors without giving the first one preference."""
    seen: set[int] = set()
    candidates: list[dict[str, str]] = []
    for node in card.iter_nodes():
        if node.tag != "a" or id(node) in seen:
            continue
        seen.add(id(node))
        href = (node.get_attribute("href") or "").strip()
        if not href:
            continue
        candidates.append(
            {"href": href, "text": (node.text or "").strip(), "source": "static"}
        )
    return candidates


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

    levels, parent_count, note = climb_card_levels(cards, dom_root)
    chosen_label, learned, _evidence, working = pick_identity_level(levels, dom_root)
    serp_host = (serp_host or urllib.parse.urlsplit(page_url).netloc).lower()

    results: list[JobCardInfo] = []
    for index, card in enumerate(working):
        title = extract_card_title(card)
        company, location = extract_company_location(card, title)
        anchors = static_candidates(card)

        if anchors:
            candidates, rejections = evaluate_candidates(
                anchors, title=title, serp_host=serp_host, base_url=page_url
            )
            state, selected = decide_resolution_state(
                candidates, rejections, material_seen=True
            )
        else:
            candidates, rejections = (), ()
            state, selected = CardResolutionState.NO_DESTINATION, None

        id_attr = id_value = ""
        for attr_name in learned:
            candidate_value = card.get_attribute(attr_name, "")
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
            )
        )

    report = SerpResolutionReport(
        learned_identity=tuple(learned),
        chosen_level=chosen_label,
        detected_parent_count=parent_count,
        note=note,
    )
    return results, report

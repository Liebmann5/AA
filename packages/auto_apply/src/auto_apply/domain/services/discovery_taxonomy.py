"""Discovery taxonomy — what the discovery tables say, with their denominators.

The first reader of ``discovery_pages`` / ``discovery_cards`` /
``discovery_candidates`` (item 2, the 4b follow-on). Item 4c connected
storage ahead of analysis; this module is the analysis: a pure function from
rows to counts. Every share it reports carries its own denominator, so no
number can be read without knowing what it is a share of.

Observation versus inference. The rows hold what AA observed (hosts, states,
outcomes). The one inference here — which hiring platform a destination host
belongs to — is computed at READ time from a classifier the caller supplies,
never stored on the row. A better classifier therefore reclassifies every
row ever written, with no migration, and the classifier's identity is
reported alongside the result so an analysis states which one it used.

The ATS-host confound (item 2). Grouping destinations by raw host is not
comparable across platforms: a platform that puts the employer in the host
(``acme.wd5.myworkdayjobs.com``) shows fifty employers as fifty hosts, while
one that puts it in the path (``boards.greenhouse.io/acme``) shows fifty
employers as one host. Destinations are therefore grouped by PLATFORM where
the classifier knows the host, and only otherwise by host.

Pure, deterministic, standard library only. No I/O.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "Share",
    "DiscoveryTaxonomy",
    "UNCLASSIFIED",
    "summarize_discovery",
]

#: Label for a destination whose host no platform claims.
UNCLASSIFIED = "(unclassified host)"

Row = Mapping[str, Any]


@dataclass(frozen=True)
class Share:
    """A count together with the denominator it is a share of."""

    count: int
    of: int

    @property
    def rate(self) -> float | None:
        """count / of, or None when the denominator is zero."""
        return self.count / self.of if self.of else None


@dataclass(frozen=True)
class DiscoveryTaxonomy:
    """The discovery funnel, page -> card -> candidate -> destination.

    Every ``*_by_*`` field is a tuple of ``(label, Share)`` ordered by count
    descending, then label, so two summaries of the same rows are identical.
    An empty label is reported as ``"(none)"``.

    Attributes:
        pages: Results pages observed.
        pages_by_provider: Pages per search provider (of: pages).
        blocked_pages: Pages that were a block interstitial (of: pages).
        pages_by_state: Pages per page_state (of: pages).
        pages_by_architecture: Pages per card-group architecture (of: pages).
        cards: Result cards observed.
        cards_by_resolution: Cards per resolution_state (of: cards).
        sponsored_only_cards: Cards whose only URL material was advertising,
            as each page counted them (of: cards).
        activations_resolved: Cards resolved by clicking, out of the cards
            clicked (of: activation attempts).
        candidates: URL candidates examined across all cards.
        candidates_by_outcome: selected / candidate / rejected (of: candidates).
        rejections_by_reason: Rejected candidates per reason
            (of: rejected candidates).
        destinations: Cards with a selected destination host.
        destinations_by_platform: Selected destinations per hiring platform;
            hosts no platform claims are grouped as UNCLASSIFIED
            (of: destinations).
        unclassified_hosts: Distinct hosts inside the UNCLASSIFIED group —
            how many separate sites that one label stands for.
        classifier: Identity of the host classifier used, as the caller gave
            it, so a reported split can be reproduced.
    """

    pages: int
    pages_by_provider: tuple[tuple[str, Share], ...]
    blocked_pages: Share
    pages_by_state: tuple[tuple[str, Share], ...]
    pages_by_architecture: tuple[tuple[str, Share], ...]
    cards: int
    cards_by_resolution: tuple[tuple[str, Share], ...]
    sponsored_only_cards: Share
    activations_resolved: Share
    candidates: int
    candidates_by_outcome: tuple[tuple[str, Share], ...]
    rejections_by_reason: tuple[tuple[str, Share], ...]
    destinations: int
    destinations_by_platform: tuple[tuple[str, Share], ...]
    unclassified_hosts: int
    classifier: str


def _label(value: Any) -> str:
    text = "" if value is None else str(value)
    return text if text else "(none)"


def _breakdown(values: Iterable[Any], of: int) -> tuple[tuple[str, Share], ...]:
    counts = Counter(_label(v) for v in values)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return tuple((label, Share(count, of)) for label, count in ordered)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def summarize_discovery(
    pages: Iterable[Row],
    cards: Iterable[Row],
    candidates: Iterable[Row],
    *,
    platform_for_host: Callable[[str], str | None],
    classifier: str = "",
) -> DiscoveryTaxonomy:
    """Summarise discovery rows into the funnel taxonomy.

    Args:
        pages: ``discovery_pages`` rows (mappings keyed by column name).
        cards: ``discovery_cards`` rows.
        candidates: ``discovery_candidates`` rows.
        platform_for_host: Host -> platform name, or None when unclaimed.
            Supplied by the caller so this module stays free of any
            platform knowledge (ATSRegistry.platform_for_host in production).
        classifier: A description of that classifier, reported verbatim.
    """
    page_rows = list(pages)
    card_rows = list(cards)
    candidate_rows = list(candidates)

    n_pages = len(page_rows)
    n_cards = len(card_rows)
    n_candidates = len(candidate_rows)

    rejected = [c for c in candidate_rows if c.get("outcome") == "rejected"]

    selected_hosts = [
        str(c.get("selected_host") or "").lower()
        for c in card_rows
        if c.get("selected_host")
    ]
    platform_labels: list[str] = []
    unclassified: set[str] = set()
    for host in selected_hosts:
        platform = platform_for_host(host)
        if platform:
            platform_labels.append(platform)
        else:
            platform_labels.append(UNCLASSIFIED)
            unclassified.add(host)

    return DiscoveryTaxonomy(
        pages=n_pages,
        pages_by_provider=_breakdown((p.get("provider") for p in page_rows), n_pages),
        blocked_pages=Share(
            sum(1 for p in page_rows if _int(p.get("blocked"))), n_pages
        ),
        pages_by_state=_breakdown((p.get("page_state") for p in page_rows), n_pages),
        pages_by_architecture=_breakdown(
            (p.get("architecture") for p in page_rows), n_pages
        ),
        cards=n_cards,
        cards_by_resolution=_breakdown(
            (c.get("resolution_state") for c in card_rows), n_cards
        ),
        sponsored_only_cards=Share(
            sum(_int(p.get("sponsored_card_count")) for p in page_rows), n_cards
        ),
        activations_resolved=Share(
            sum(_int(p.get("activation_resolved")) for p in page_rows),
            sum(_int(p.get("activation_attempts")) for p in page_rows),
        ),
        candidates=n_candidates,
        candidates_by_outcome=_breakdown(
            (c.get("outcome") for c in candidate_rows), n_candidates
        ),
        rejections_by_reason=_breakdown(
            (c.get("rejection_reason") for c in rejected), len(rejected)
        ),
        destinations=len(selected_hosts),
        destinations_by_platform=_breakdown(platform_labels, len(selected_hosts)),
        unclassified_hosts=len(unclassified),
        classifier=classifier,
    )

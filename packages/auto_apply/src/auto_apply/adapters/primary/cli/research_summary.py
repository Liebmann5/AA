"""Terminal rendering of the discovery research summary (``--research-summary``).

Owns the user-facing text for the summary, as the primary-adapter ratchet in
tests/architecture/test_safety_pins.py requires: main.py composes (reads the
database, classifies, summarises) and this module only renders. It imports
nothing past the domain, so a GUI research view can render the same
DiscoveryTaxonomy without touching the read side.
"""

from __future__ import annotations

from auto_apply.domain.services.discovery_taxonomy import DiscoveryTaxonomy, Share

__all__ = [
    "format_share",
    "summary_lines",
    "print_discovery_summary",
    "print_no_research_data",
    "print_research_read_error",
]


def format_share(share: Share) -> str:
    """'n of N (p%)' — a share is never shown without its denominator."""
    if share.rate is None:
        return f"{share.count} of {share.of}"
    return f"{share.count} of {share.of} ({share.rate * 100:.1f}%)"


def _section(title: str, breakdown: tuple[tuple[str, Share], ...]) -> list[str]:
    lines = [f"  {title}"]
    if not breakdown:
        lines.append("    (none)")
    for label, share in breakdown:
        lines.append(f"    {label:<34} {format_share(share)}")
    return lines


def summary_lines(summary: DiscoveryTaxonomy) -> list[str]:
    """The summary as display lines, in funnel order: page, card, candidate,
    destination. Pure, so any surface can render it."""
    lines = [
        "Discovery research summary",
        f"  Results pages:  {summary.pages}",
        f"  Blocked pages:  {format_share(summary.blocked_pages)}",
    ]
    lines += _section("Pages by provider", summary.pages_by_provider)
    lines += _section("Pages by state", summary.pages_by_state)
    lines += _section("Pages by card architecture", summary.pages_by_architecture)
    lines.append(f"  Result cards:   {summary.cards}")
    lines += _section("Cards by resolution", summary.cards_by_resolution)
    lines.append(
        f"  Advertising-only cards: {format_share(summary.sponsored_only_cards)}"
    )
    lines.append(
        "  Resolved by clicking:   "
        f"{format_share(summary.activations_resolved)} attempts"
    )
    lines.append(f"  URL candidates: {summary.candidates}")
    lines += _section("Candidates by outcome", summary.candidates_by_outcome)
    lines += _section("Rejections by reason", summary.rejections_by_reason)
    lines.append(f"  Selected destinations: {summary.destinations}")
    lines += _section(
        "Destinations by hiring platform", summary.destinations_by_platform
    )
    lines.append(f"  Distinct unclassified hosts: {summary.unclassified_hosts}")
    lines.append(f"  Platform classifier: {summary.classifier}")
    return lines


def print_discovery_summary(summary: DiscoveryTaxonomy) -> None:
    """Print the summary to the terminal."""
    print("\n".join(summary_lines(summary)))


def print_no_research_data() -> None:
    """Say plainly that there is nothing to summarise."""
    print(
        "No research data on this device yet "
        "(research is off, or nothing was collected)."
    )


def print_research_read_error(exc: Exception) -> None:
    """Report a research database that exists but cannot be read."""
    print(f"  ✗ Could not read the research database: {exc}")

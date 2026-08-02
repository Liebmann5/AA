"""Task-queue priority bands for the discovery pipeline (ADR-011).

The work queue dispatches ``ORDER BY priority ASC, created_at ASC`` — a lower
number is more urgent. These named bands make the discovery pipeline INTERLEAVE
per search instead of running as a batch: within a run, a discovered search's
APPLICATIONS outrank its VETTING, which outranks the next search's DISCOVERY. So
each search flows discover -> vet -> apply before the next search's discovery
begins, which is the "one search -> vet -> apply -> next search" behaviour.

Applications remain fit-ordered *within* their band (best fit first), so within a
single search the strongest matches are applied to first — the hybrid choice
recorded in ADR-011.

Direct user-initiated and reactive work — resolving a pasted apply URL, handling
a live CAPTCHA, scraping a user-provided careers page — intentionally uses the
lower numbers (1-4) already assigned at those sites, and therefore stays ABOVE
this pipeline. The user's explicit requests and in-flight blockers come first.
This module owns only the discovery-pipeline bands; it deliberately does not
re-home those separate, correctly-more-urgent priorities.
"""
from __future__ import annotations


class TaskPriority:
    """Named discovery-pipeline priority bands (lower number = more urgent)."""

    # Discovery applications, best-fit first, spanning APPLY_BASE .. APPLY_BASE +
    # APPLY_SPREAD. The whole band sits below VET and DISCOVER so a search's
    # applications drain before the next search is vetted or discovered.
    APPLY_BASE: int = 10
    APPLY_SPREAD: int = 9

    # Vetting a discovered job: above the next search's discovery, below applying.
    VET: int = 50

    # Finding new jobs: the least-urgent pipeline stage, so that a search's
    # vetting and applications complete before the next search is discovered.
    DISCOVER: int = 100

    @staticmethod
    def apply_for_fit(fit_score: float | None) -> int:
        """Application priority ordered best-fit-first within the APPLY band.

        fit 1.0 -> APPLY_BASE (most urgent application); fit 0.0 -> APPLY_BASE +
        APPLY_SPREAD (least urgent application). The result is always below VET
        and DISCOVER, so a search's applications outrank the next search's
        vetting and discovery, while remaining fit-ordered among themselves.
        """
        fit = max(0.0, min(1.0, fit_score or 0.0))
        return TaskPriority.APPLY_BASE + round((1.0 - fit) * TaskPriority.APPLY_SPREAD)

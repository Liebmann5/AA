"""Lightweight‑first page analysis router.

Chooses the cheapest effective analysis strategy for a given page so that
heavy mathematical DOM extraction is only used when simpler alternatives
cannot provide sufficient form structure.

Rail‑Safety Contract: the router is advisory — if the lightweight path
fails, the caller MUST fall back to FULL_MATH_DOM.  The router itself
never raises.
"""

from __future__ import annotations

import logging
import re
from enum import Enum, auto
from typing import TYPE_CHECKING, Optional

from auto_apply.domain.ports.ats_port import ATSRegistryPort

if TYPE_CHECKING:
    from auto_apply.application.services.page_feedback_service import PageFeedbackService

logger = logging.getLogger(__name__)


class PageAnalysisTier(Enum):
    """Analysis tiers ordered from cheapest to most expensive."""

    STRUCTURED_DATA = auto()    # JSON‑LD present → skip scraping
    KNOWN_PLATFORM = auto()     # Known ATS with explicit selectors
    CSS_EXTRACTION = auto()     # DOMScanner + FieldClassifier
    FULL_MATH_DOM = auto()      # MathDOM + Hungarian


class PageAnalysisRouter:
    """Router that selects an analysis tier for a given page.

    The router is stateless; ``determine_tier`` uses only the URL and
    optional raw HTML to make a recommendation.  When a ``PageFeedbackService``
    is injected, historical success rates of each tier for the same
    page signature are used as a gentle tie‑breaker that can shift the
    recommendation toward a tier that has proven more reliable in the
    past, but only after a minimum number of observations.

    Args:
        ats_registry: The ATS platform registry (may be None).
        feedback_service: Optional feedback service for historical data.
    """

    # Weights controlling how strongly static rules and feedback
    # contribute to the final combined score.
    _STATIC_WEIGHT_BASE: float = 3.0  # multiplier for raw static score
    _FEEDBACK_MAX_CONTRIBUTION: float = 0.30

    def __init__(
        self,
        ats_registry: ATSRegistryPort | None = None,
        feedback_service: "PageFeedbackService | None" = None,
    ) -> None:
        self._ats_registry = ats_registry
        self._feedback_service = feedback_service

    # ==================================================================
    # PUBLIC
    # ==================================================================

    def determine_tier(
        self,
        url: str,
        page_html: str | None = None,
    ) -> PageAnalysisTier:
        """Return the recommended analysis tier for the given URL.

        Args:
            url: The current page URL.
            page_html: Optional raw HTML (e.g. ``browser.page_source``)
                used for cheap heuristic checks.  When absent, only URL‑based
                checks (ATS registry) are possible.

        Returns:
            The recommended tier; *always* returns a valid tier.
            Falls back to ``FULL_MATH_DOM`` in the worst case.
        """
        # ── 1. Compute static scores for every tier ──────────────────────
        static_scores = self._static_tier_scores(url, page_html)

        # ── 2. Optionally adjust with historical feedback ────────────────
        if self._feedback_service is not None and page_html is not None:
            page_signature = self._make_page_signature(url, page_html)
            feedback_stats = self._feedback_service.get_tier_stats(page_signature)
            best_tier = self._pick_with_feedback(static_scores, feedback_stats)
        else:
            best_tier = self._pick_best(static_scores)

        logger.debug(
            "PageAnalysisTier: %s | url=%s static=%s feedback=%s",
            best_tier.name,
            url[:80],
            static_scores,
            "available" if self._feedback_service else "disabled",
        )
        return best_tier

    # ==================================================================
    # STATIC SCORING
    # ==================================================================

    def _static_tier_scores(
        self,
        url: str,
        page_html: str | None = None,
    ) -> dict[PageAnalysisTier, float]:
        """Return a score for every tier based purely on page content.

        The scores are designed so that ``max(scores)`` reproduces the
        original ``determine_tier`` behaviour when feedback is absent.
        """
        scores = {
            PageAnalysisTier.STRUCTURED_DATA: 0.0,
            PageAnalysisTier.KNOWN_PLATFORM:   0.0,
            PageAnalysisTier.CSS_EXTRACTION:   0.0,
            PageAnalysisTier.FULL_MATH_DOM:    0.2,  # always available (heavy)
        }

        # ── ATS registry (strongest static signal) ───────────────────────
        if self._ats_registry is not None:
            descriptor = self._ats_registry.match(url)
            if descriptor is not None:
                if descriptor.submit_button_selector:
                    # Strong, direct platform knowledge.
                    scores[PageAnalysisTier.KNOWN_PLATFORM] = 0.95
                else:
                    # Platform recognised, but no dedicated selector;
                    # CSS extraction is still preferred.
                    scores[PageAnalysisTier.CSS_EXTRACTION] = max(
                        scores[PageAnalysisTier.CSS_EXTRACTION], 0.70
                    )
                    scores[PageAnalysisTier.KNOWN_PLATFORM] = max(
                        scores[PageAnalysisTier.KNOWN_PLATFORM], 0.40
                    )

        # ── Structured data (JSON‑LD) ───────────────────────────────────
        if page_html and self._has_json_ld(page_html):
            scores[PageAnalysisTier.STRUCTURED_DATA] = max(
                scores[PageAnalysisTier.STRUCTURED_DATA], 0.95
            )

        # ── Generic form detection ──────────────────────────────────────
        if page_html and self._has_form(page_html):
            scores[PageAnalysisTier.CSS_EXTRACTION] = max(
                scores[PageAnalysisTier.CSS_EXTRACTION], 0.60
            )

        return scores

    # ==================================================================
    # DECISION HELPERS
    # ==================================================================

    @staticmethod
    def _pick_best(
        scores: dict[PageAnalysisTier, float],
    ) -> PageAnalysisTier:
        """Choose the tier with the highest static score.

        Ties are broken in favour of the lighter tier (lower cost).
        """
        # Secondary sort: priority from cheapest to most expensive.
        priority = {
            PageAnalysisTier.STRUCTURED_DATA: 0,
            PageAnalysisTier.KNOWN_PLATFORM:   1,
            PageAnalysisTier.CSS_EXTRACTION:   2,
            PageAnalysisTier.FULL_MATH_DOM:    3,
        }
        return max(
            scores.items(),
            key=lambda item: (item[1], -priority[item[0]]),
        )[0]

    def _pick_with_feedback(
        self,
        static_scores: dict[PageAnalysisTier, float],
        feedback_stats: dict[str, tuple[float, int]],
    ) -> PageAnalysisTier:
        """Combine static scores with historical success rates.

        A tier must have ``count >= min_samples`` in *feedback_stats* before
        its historical data contributes.  The contribution weight grows
        linearly from 0 to ``_FEEDBACK_MAX_CONTRIBUTION`` as the sample
        count reaches ``min_samples``, then stays capped.

        Combined score = static × (1 – weight) + feedback_avg × weight
        """
        min_samples = getattr(self._feedback_service, "_min_samples", 5) if self._feedback_service else 5
        combined: dict[PageAnalysisTier, float] = {}

        for tier, static_score in static_scores.items():
            stat = feedback_stats.get(tier.name)
            if stat:
                avg, count = stat
                if count >= min_samples:
                    # Weight up to _FEEDBACK_MAX_CONTRIBUTION
                    weight = min(1.0, count / min_samples) * self._FEEDBACK_MAX_CONTRIBUTION
                    combined[tier] = (
                        static_score * (1.0 - weight) + avg * weight
                    )
                else:
                    combined[tier] = static_score
            else:
                combined[tier] = static_score

        return self._pick_best(combined)

    # ==================================================================
    # PAGE SIGNATURE (deterministic hash of structure)
    # ==================================================================

    def record_tier_outcome(
        self,
        page_url: str,
        page_html: str,
        tier: str,
        success: bool,
        *,
        is_deterministic: bool,
    ) -> None:
        """Write the outcome of a tier choice back into the feedback store.

        This is the write side of the loop the router already reads from in
        ``determine_tier``. Without a caller, ``get_tier_stats`` always sees an
        empty store and the feedback branch is unreachable — the loop is built
        and disconnected. ``ApplicationsWorkflow`` calls this after each
        application attempt with the outcome it observed.

        ``is_deterministic`` is passed straight through to the service, which
        makes recording a no-op for seeded research runs so two identical runs
        cannot poison each other's store. It is required here — not defaulted —
        so a caller cannot silently drop determinism.
        """
        if self._feedback_service is None:
            return
        signature = self._make_page_signature(page_url, page_html)
        self._feedback_service.record_outcome(
            signature, tier, success, is_deterministic=is_deterministic
        )

    @staticmethod
    def _make_page_signature(url: str, page_html: str) -> str:
        """Derive a stable, anonymous signature from URL domain and HTML structure.

        The signature is reversible enough to be useful for grouping
        structurally‑similar pages, but contains NO PII or raw URLs.
        """
        # Extract domain (safe)
        domain = ""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
        except Exception:
            domain = "unknown"

        # Count structural elements — simple, fast, regex‑only (no BS4).
        form_count = len(re.findall(r'<\s*form\b', page_html, re.IGNORECASE))
        input_count = len(re.findall(r'<\s*input\b', page_html, re.IGNORECASE))
        # Basic fingerprint — can be extended later (e.g. presence of certain IDs).
        return f"{domain}|forms={form_count}|inputs={input_count}"

    # ==================================================================
    # EXISTING STATIC HEURISTICS (unchanged)
    # ==================================================================

    @staticmethod
    def _has_json_ld(html: str) -> bool:
        """True if *html* contains at least one ``application/ld+json`` script tag."""
        return 'application/ld+json' in html

    @staticmethod
    def _has_form(html: str) -> bool:
        """True if *html* contains both a ``<form`` and an ``<input`` element."""
        lower = html.lower()
        return '<form' in lower and '<input' in lower


__all__ = ["PageAnalysisRouter", "PageAnalysisTier"]
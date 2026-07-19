"""Lightweight, local‑only feedback service for page‑analysis tier selection.

Decoupled from the research module — always runs, independent of consent.
Uses EMA‑based success rates from a ``FeedbackRepositoryPort`` to influence
``PageAnalysisRouter`` decisions only after a minimum number of observations.

Deterministic‑run safety:  when ``is_deterministic=True`` is passed to
``record_outcome()``, no data is persisted — the store is strictly read‑only
for the duration of the run, guaranteeing that two seeded runs with the same
initial database produce identical tier recommendations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from auto_apply.domain.ports.feedback_repository_port import FeedbackRepositoryPort

logger = logging.getLogger(__name__)

# Minimum number of observations before a tier’s historical score influences
# the router.  Below this threshold the feedback is treated as “no data.”
_DEFAULT_MIN_SAMPLES: int = 5

# Maximum contribution weight from historical data (clamped to [0, 1]).
_DEFAULT_MAX_WEIGHT: float = 0.30


class PageFeedbackService:
    """Service that reads historical tier success rates and optionally records
    new outcomes.

    Args:
        repository: Backing store for tier performance data.
        min_samples: Observations required before using feedback.
        max_weight: Maximum weight that historical data can have when
            computing the combined score (the rest comes from static rules).
    """

    def __init__(
        self,
        repository: "FeedbackRepositoryPort",
        min_samples: int = _DEFAULT_MIN_SAMPLES,
        max_weight: float = _DEFAULT_MAX_WEIGHT,
    ) -> None:
        self._repo = repository
        self._min_samples = min_samples
        self._max_weight = max_weight

    # ------------------------------------------------------------------
    # QUERY INTERFACE (used by PageAnalysisRouter)
    # ------------------------------------------------------------------

    def get_tier_stats(
        self, page_signature: str
    ) -> dict[str, tuple[float, int]]:
        """Return historical (avg_success, count) for all tiers on a signature.

        Returns:
            Dict mapping tier name → (avg_success, count).  Empty dict
            when no data exists.
        """
        return self._repo.get_scores(page_signature)

    # ------------------------------------------------------------------
    # RECORDING INTERFACE (called after form evaluation)
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        page_signature: str,
        tier: str,
        success: bool,
        *,
        is_deterministic: bool = False,
    ) -> None:
        """Persist an outcome unless the session is deterministic.

        Args:
            page_signature: The opaque page signature.
            tier: ``PageAnalysisTier`` name that was used.
            success: Whether the tier produced a correct extraction.
            is_deterministic: When ``True`` (seeded research run), this
                method is a no‑op so that the store does not change.
        """
        if is_deterministic:
            logger.debug(
                "PageFeedbackService: deterministic run — outcome NOT recorded "
                "| signature=%s tier=%s success=%s",
                page_signature,
                tier,
                success,
            )
            return

        try:
            self._repo.record_outcome(page_signature, tier, success)
            logger.debug(
                "PageFeedbackService: recorded outcome | "
                "signature=%s tier=%s success=%s",
                page_signature,
                tier,
                success,
            )
        except Exception as exc:
            logger.warning(
                "PageFeedbackService: failed to record outcome | "
                "signature=%s tier=%s error=%s",
                page_signature,
                tier,
                exc,
            )


__all__ = ["PageFeedbackService"]
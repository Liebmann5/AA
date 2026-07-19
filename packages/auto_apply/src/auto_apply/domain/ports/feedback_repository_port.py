"""Protocol defining the contract for storing page-analysis feedback data.

This port allows the application layer (via PageFeedbackService) to read
and write per‑tier success statistics without importing any concrete adapter.

Implementations:
    PageFeedbackRepository (adapters/secondary/persistence/)
"""  # noqa: E501

from typing import Protocol, runtime_checkable


@runtime_checkable
class FeedbackRepositoryPort(Protocol):
    """Contract for a store that holds per‑(page_signature, tier) scoring."""

    def get_scores(
        self, page_signature: str
    ) -> dict[str, tuple[float, int]]:
        """Return a mapping of tier → (avg_success, effective_sample_count).

        Effective sample count is the number of observations contributing
        to the running average.  A nonexistent signature or tier returns
        an empty dict entry — callers treat missing keys as “no data”.

        Args:
            page_signature: The opaque signature of the page (e.g.
                ``"example.com|forms=1|inputs=5"``).

        Returns:
            Dict of tier name (e.g. ``"KNOWN_PLATFORM"``) → (avg, count).
        """
        ...

    def record_outcome(
        self,
        page_signature: str,
        tier: str,
        success: bool,
    ) -> None:
        """Update the running statistics for *page_signature* and *tier*.

        The underlying strategy (e.g. EMA) is an implementation detail.

        Args:
            page_signature: The opaque signature of the page.
            tier: The ``PageAnalysisTier`` name that was used.
            success: ``True`` if the tier produced a successful extraction
                (e.g. form was filled correctly), ``False`` otherwise.
        """
        ...


__all__ = ["FeedbackRepositoryPort"]
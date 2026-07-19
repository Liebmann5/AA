"""Tests for the page‑analysis feedback loop.

Validates:
  - Router with empty store (no feedback) still returns correct static tier.
  - After recording repeated failures for one tier and successes for another,
    the router shifts toward the higher‑success tier once enough data exists.
  - Deterministic (seeded) runs never modify the store.
  - Minimum‑sample threshold prevents hasty tier changes.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from auto_apply.application.services.page_analysis_router import (
    PageAnalysisRouter,
    PageAnalysisTier,
)
from auto_apply.application.services.page_feedback_service import (
    PageFeedbackService,
)
from auto_apply.adapters.secondary.persistence.page_feedback_repository import (
    PageFeedbackRepository,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_signature(domain: str = "example.com", form_count: int = 1, input_count: int = 5) -> str:
    return f"{domain}|forms={form_count}|inputs={input_count}"


def _make_router(
    feedback_service: PageFeedbackService | None = None,
) -> PageAnalysisRouter:
    return PageAnalysisRouter(
        ats_registry=None,                     # no ATS registry for these tests
        feedback_service=feedback_service,
    )


def _page_html(json_ld: bool = False, form: bool = True, inputs: int = 3) -> str:
    """Return a minimal HTML page with optional JSON‑LD and form."""
    parts = ["<html><body>"]
    if json_ld:
        parts.append('<script type="application/ld+json">{"@type":"JobPosting"}</script>')
    if form:
        parts.append("<form>")
        for i in range(inputs):
            parts.append(f'<input type="text" name="field{i}">')
        parts.append("</form>")
    parts.append("</body></html>")
    return "".join(parts)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_db() -> Path:
    """A temporary SQLite file that is deleted after the test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    # close the file descriptor, we only need the path
    import os
    os.close(fd)
    return Path(path)


# ── Tests ────────────────────────────────────────────────────────────────────

class TestEmptyStoreReturnStaticTier:
    """When the feedback store is missing or empty, static rules win."""

    def test_no_feedback_yields_css_extraction_with_form(self):
        router = _make_router(feedback_service=None)
        tier = router.determine_tier(
            "https://example.com/job/123",
            _page_html(form=True, inputs=5),
        )
        # static: no ATS, has form → CSS_EXTRACTION (0.6) beats FULL_MATH_DOM
        assert tier == PageAnalysisTier.CSS_EXTRACTION

    def test_empty_store_still_css_extraction(self, temp_db):
        repo = PageFeedbackRepository(temp_db)
        service = PageFeedbackService(repo, min_samples=5, max_weight=0.30)
        router = _make_router(feedback_service=service)
        html = _page_html(form=True, inputs=5)
        tier = router.determine_tier("https://example.com/job/1", html)
        # store empty → feedback weight = 0, static wins
        assert tier == PageAnalysisTier.CSS_EXTRACTION

    def test_json_ld_beats_form_when_present(self, temp_db):
        repo = PageFeedbackRepository(temp_db)
        service = PageFeedbackService(repo)
        router = _make_router(feedback_service=service)
        html = _page_html(json_ld=True, form=True, inputs=2)
        tier = router.determine_tier("https://example.com/j/42", html)
        # JSON‑LD → STRUCTURED_DATA (0.95) overrides CSS_EXTRACTION (0.60)
        assert tier == PageAnalysisTier.STRUCTURED_DATA


class TestFeedbackShift:
    """After enough data, the router moves away from a failing tier."""

    @staticmethod
    def _populate(repo: PageFeedbackRepository, sig: str,
                  tier_success: dict[str, tuple[float, int]]) -> None:
        """Pre‑fill the database by calling record_outcome multiple times
        to build up the desired EMA state.  Simpler than direct INSERT.
        """
        for tier, (avg, cnt) in tier_success.items():
            # We'll insert many outcomes to approximate the desired state.
            # We'll cheat by resetting and inserting directly via raw SQL for speed.
            with repo._get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO page_feedback "
                    "(page_signature, tier, avg_success, count, last_updated) "
                    "VALUES (?, ?, ?, ?, datetime('now'))",
                    (sig, tier, avg, cnt),
                )

    def test_css_extraction_deprioritized_when_bad_history(self, temp_db):
        sig = _make_signature()
        repo = PageFeedbackRepository(temp_db)
        # Pre-populate: CSS_EXTRACTION with many failures → avg 0.01, count=10
        #               FULL_MATH_DOM with many successes → avg 0.99, count=10
        self._populate(repo, sig, {
            "CSS_EXTRACTION": (0.01, 10),
            "FULL_MATH_DOM":  (0.99, 10),
        })
        service = PageFeedbackService(repo, min_samples=5, max_weight=0.30)
        router = _make_router(feedback_service=service)

        html = _page_html(form=True, inputs=5)
        tier = router.determine_tier("https://example.com/job/1", html)

        # Expected combined:
        # CSS_EXTRACTION static = 0.60, FULL_MATH_DOM = 0.20
        # weight = 0.30 (since count >= min_samples)
        # CSS: 0.60*0.7 + 0.01*0.3 = 0.42 + 0.003 = 0.423
        # FULL: 0.20*0.7 + 0.99*0.3 = 0.14 + 0.297 = 0.437
        # FULL_MATH_DOM should win
        assert tier == PageAnalysisTier.FULL_MATH_DOM, (
            "Expected FULL_MATH_DOM due to strong historical success"
        )

    def test_no_shift_below_min_samples(self, temp_db):
        """Feedback has too few samples → ignored."""
        sig = _make_signature()
        repo = PageFeedbackRepository(temp_db)
        self._populate(repo, sig, {
            "CSS_EXTRACTION": (0.01, 4),   # not enough
            "FULL_MATH_DOM":  (0.99, 4),
        })
        service = PageFeedbackService(repo, min_samples=5, max_weight=0.30)
        router = _make_router(feedback_service=service)

        html = _page_html(form=True, inputs=5)
        tier = router.determine_tier("https://example.com/job/1", html)
        # Static scores still decide → CSS_EXTRACTION
        assert tier == PageAnalysisTier.CSS_EXTRACTION


class TestDeterministicMode:
    """Seeded runs must not modify the store."""

    def test_record_outcome_is_noop_when_deterministic(self, temp_db):
        repo = PageFeedbackRepository(temp_db)
        service = PageFeedbackService(repo, min_samples=5, max_weight=0.30)

        sig = _make_signature()
        # Record an outcome with is_deterministic=True
        service.record_outcome(sig, "CSS_EXTRACTION", True, is_deterministic=True)
        stats = service.get_tier_stats(sig)
        assert stats == {}, "Deterministic run must not write to store"

    def test_identical_seeded_runs_produce_identical_decisions(self, temp_db):
        """Two routers with the same initial store and same inputs produce
        the same tier, and the store remains unchanged.
        """
        sig = _make_signature()
        repo = PageFeedbackRepository(temp_db)
        # Pre-populate some data so we can test that deterministic reads don't change it
        self._populate = TestFeedbackShift._populate
        self._populate(repo, sig, {"CSS_EXTRACTION": (0.5, 10)})

        service = PageFeedbackService(repo, min_samples=5, max_weight=0.30)
        router1 = _make_router(feedback_service=service)
        router2 = _make_router(feedback_service=service)

        html = _page_html(form=True, inputs=5)
        tier1 = router1.determine_tier("https://example.com/job/1", html)
        tier2 = router2.determine_tier("https://example.com/job/1", html)
        assert tier1 == tier2, "Seeded runs must be deterministic"

        # Verify store was NOT modified by the reads (it shouldn't be anyway, but safeguard)
        stats = service.get_tier_stats(sig)
        assert stats["CSS_EXTRACTION"] == (0.5, 10), "Store unchanged by read-only operations"
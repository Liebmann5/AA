"""Teeth pin for the GeographicPayDiscriminationDetector salary guard (R6).

Pre-fix, a posting with salary_max=0 and salary_min=None reached
``None / col_index`` and raised TypeError. These tests pin the guarded
behaviour and the still-firing genuine case.
"""

from auto_apply.domain.services.signal_detectors.base import DetectionContext
from auto_apply.domain.services.signal_detectors.extended_detectors import (
    GeographicPayDiscriminationDetector,
)


def test_zero_max_none_min_salary_does_not_crash() -> None:
    """TEETH: the exact pre-fix crash shape — falsy max, absent min."""
    ctx = DetectionContext(
        job_title="Software Engineer",
        job_description="We are hiring a software engineer.",
        metro_area="San Francisco-Oakland-Berkeley, CA",
        salary_max=0,
        salary_min=None,
    )
    assert GeographicPayDiscriminationDetector().detect(ctx) == []


def test_both_salary_fields_missing_returns_empty() -> None:
    """Coverage: the pre-existing early return for fully absent salary."""
    ctx = DetectionContext(
        metro_area="San Francisco-Oakland-Berkeley, CA",
        salary_max=None,
        salary_min=None,
    )
    assert GeographicPayDiscriminationDetector().detect(ctx) == []


def test_genuine_low_salary_still_fires_flag() -> None:
    """Characterization: a real below-market salary must still produce DISC-05."""
    ctx = DetectionContext(
        job_title="Software Engineer",
        job_description="We are hiring a software engineer.",
        metro_area="San Francisco-Oakland-Berkeley, CA",
        salary_min=20_000,
        salary_max=25_000,
    )
    signals = GeographicPayDiscriminationDetector().detect(ctx)
    assert any(s.signal_type == "DISC-05" for s in signals)

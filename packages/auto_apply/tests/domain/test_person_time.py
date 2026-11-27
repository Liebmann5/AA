"""Pins for how long AA waits for the person (WCAG 2.2 SC 2.2.1)."""

from __future__ import annotations

import pytest

from auto_apply.domain.models.profile import AccessibilityPreferences
from auto_apply.domain.services.person_time import TIME_LIMIT_SCALES, person_timeout


@pytest.mark.parametrize(("mode", "wait"), [
    ("1x", 300.0), ("3x", 900.0), ("10x", 3000.0), ("20x", 6000.0), ("off", None),
    (" OFF ", None),
])
def test_the_setting_scales_or_removes_the_limit(mode: str, wait: float | None) -> None:
    assert person_timeout(300.0, mode) == wait


def test_wcag_s_range_is_offered() -> None:
    """SC 2.2.1: turn off, or adjust to at least ten times the default."""
    assert None in TIME_LIMIT_SCALES.values()
    assert max(v for v in TIME_LIMIT_SCALES.values() if v is not None) >= 10


@pytest.mark.parametrize("mode", ["", "forever", None, 3, "x10"])
def test_an_unknown_value_is_the_standard_limit_never_no_limit(mode: object) -> None:
    assert person_timeout(300.0, mode) == 300.0


def test_no_base_limit_stays_no_limit() -> None:
    assert person_timeout(None, "1x") is None


def test_the_profile_offers_exactly_the_policy_s_values() -> None:
    field = AccessibilityPreferences.model_fields["time_limits"]
    allowed = set(field.annotation.__args__[0].__args__)  # Literal[...] | None
    assert allowed == set(TIME_LIMIT_SCALES)

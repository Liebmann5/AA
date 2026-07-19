"""Shared fixtures for infrastructure-layer tests.

This conftest provides fixtures that are reused across multiple test modules
in the infrastructure/ test directory.

Fixtures:
    mock_profile: A minimal, valid UserProfile instance suitable for
        tests that need a profile but don't care about the actual values.
        Uses `model_validate` to bypass full validation of derived fields.
"""

import pytest

from auto_apply.domain.models.profile import UserProfile


@pytest.fixture
def mock_profile() -> UserProfile:
    """Return a minimal valid UserProfile for use in infrastructure tests.

    This profile contains only the absolute minimum required fields to
    satisfy UserProfile validation. It is safe to use in tests that do not
    need specific profile data – the values are generic and won't affect
    the behaviour under test.

    The profile is validated via `model_validate` with the `extra='ignore'`
    behaviour (the default), so it won't raise on fields that are not present.

    Returns:
        UserProfile: A fully valid but minimal profile.
    """
    return UserProfile.model_validate({
        "profile_name": "infra-test-profile",
        "personal_info": {
            "first_name": "Test",
            "last_name": "User",
            "email": "test@example.com",
            "phone_number": "000-000-0000",
            "street_address": "123 Test St",
            "city": "Testville",
            "state": "TS",
            "zip_code": "00000",
            "country": "United States",
        },
        "links": {},
        "career_summary": "This is a test profile for infrastructure tests.",
        "search_preferences": {
            "desired_job_titles": ["Software Engineer"],
            "preferred_locations": ["Remote"],
            "skills": ["Python", "Testing"],
        },
        "politeness_settings": {
            "respect_robots_txt": True,
            "default_delay": 1.0,
        },
        "app_config": {
            "preferred_browser": "any",
            "run_headless": False,
            "daily_application_limit": 10,
            "enable_behavior_humanization": True,
        },
    })
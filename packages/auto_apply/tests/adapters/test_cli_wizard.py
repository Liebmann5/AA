"""Unit tests for adapters/primary/cli/wizard.py.

input() is monkeypatched so no real stdin is required.
Tests cover profile-derived defaults, schema label resolution, and graceful
fallback when no profile is provided.
"""

from unittest.mock import MagicMock, patch

import pytest

from auto_apply.adapters.primary.cli.wizard import CLIWizard


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _mock_profile(titles=("Data Engineer",), locations=("Boston",)):
    prefs = MagicMock()
    prefs.desired_job_titles = list(titles)
    prefs.preferred_locations = list(locations)
    profile = MagicMock()
    profile.search_preferences = prefs
    return profile


def _run_wizard(inputs: list[str], profile=None) -> dict:
    """Runs the wizard with a fixed sequence of mocked input() responses."""
    wizard = CLIWizard(profile=profile)
    with patch("builtins.input", side_effect=inputs):
        return wizard.run()


# ─────────────────────────────────────────────────────────────────────────────
# No-profile fallback
# ─────────────────────────────────────────────────────────────────────────────

def test_no_profile_uses_hardcoded_defaults():
    # Simulate user pressing Enter (accepting defaults) for all prompts.
    result = _run_wizard(["", "", "", "", ""])
    assert result["keywords"] == "Software Engineer"
    assert result["location"] == "Remote"
    assert result["max_results"] == 100


def test_no_profile_discovery_mode_strategy_default():
    result = _run_wizard(["", "", "", "", ""])
    assert result["mode"] == "discovery"
    assert result["strategy"] == "adaptive"


# ─────────────────────────────────────────────────────────────────────────────
# Profile-derived defaults
# ─────────────────────────────────────────────────────────────────────────────

def test_keywords_default_from_profile():
    profile = _mock_profile(titles=["ML Engineer", "Data Scientist"])
    # User presses Enter → accepts the profile default.
    result = _run_wizard(["", "", "", "", ""], profile=profile)
    assert result["keywords"] == "ML Engineer, Data Scientist"


def test_location_default_from_profile():
    profile = _mock_profile(locations=["Seattle"])
    result = _run_wizard(["", "", "", "", ""], profile=profile)
    assert result["location"] == "Seattle"


def test_user_can_override_profile_defaults():
    profile = _mock_profile(titles=["Data Engineer"], locations=["Boston"])
    result = _run_wizard(["", "Backend Engineer", "Austin", "", ""], profile=profile)
    assert result["keywords"] == "Backend Engineer"
    assert result["location"] == "Austin"


def test_empty_profile_titles_falls_back_to_hardcoded():
    profile = _mock_profile(titles=[])  # empty list
    result = _run_wizard(["", "", "", "", ""], profile=profile)
    assert result["keywords"] == "Software Engineer"


def test_empty_profile_locations_falls_back_to_hardcoded():
    profile = _mock_profile(locations=[])
    result = _run_wizard(["", "", "", "", ""], profile=profile)
    assert result["location"] == "Remote"


# ─────────────────────────────────────────────────────────────────────────────
# Schema label resolution
# ─────────────────────────────────────────────────────────────────────────────

def test_schema_label_returns_field_label():
    wizard = CLIWizard()
    label = wizard._schema_label("search_preferences.desired_job_titles", "FALLBACK")
    assert label == "Desired Job Titles"


def test_schema_label_returns_fallback_for_unknown_key():
    wizard = CLIWizard()
    label = wizard._schema_label("nonexistent.key", "My Fallback")
    assert label == "My Fallback"


def test_schema_label_prefers_schema_over_fallback_for_known_key():
    wizard = CLIWizard()
    label = wizard._schema_label("search_preferences.preferred_locations", "Location")
    assert label == "Preferred Locations"


# ─────────────────────────────────────────────────────────────────────────────
# Modes and strategy
# ─────────────────────────────────────────────────────────────────────────────

def test_strategy_1_is_adaptive():
    result = _run_wizard(["", "", "", "", "1"])
    assert result["strategy"] == "adaptive"


def test_strategy_2_is_stream():
    result = _run_wizard(["", "", "", "", "2"])
    assert result["strategy"] == "stream"


def test_strategy_3_is_collect_first():
    result = _run_wizard(["", "", "", "", "3"])
    assert result["strategy"] == "collect_first"


def test_strategy_unknown_falls_back_to_adaptive():
    result = _run_wizard(["", "", "", "", "9"])
    assert result["strategy"] == "adaptive"


def test_direct_links_mode():
    # Inputs: mode=2, link1, link2, ""(stop), ""(strategy default)
    result = _run_wizard(["2", "https://jobs.example.com/1", "https://jobs.example.com/2", "", ""])
    assert result["mode"] == "direct_links"
    assert "https://jobs.example.com/1" in result["links"]


def test_direct_links_empty_returns_empty_dict():
    result = _run_wizard(["2", ""])
    assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# max_results
# ─────────────────────────────────────────────────────────────────────────────

def test_max_results_from_user_input():
    result = _run_wizard(["", "", "", "50", ""])
    assert result["max_results"] == 50


def test_max_results_defaults_to_100_when_empty():
    result = _run_wizard(["", "", "", "", ""])
    assert result["max_results"] == 100


def test_max_results_defaults_to_100_on_bad_input():
    result = _run_wizard(["", "", "", "not-a-number", ""])
    assert result["max_results"] == 100

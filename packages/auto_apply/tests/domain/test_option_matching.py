"""Pins for choosing the option that means an answer (application step engine).

The matcher decides which option of a select, combobox or radio group AA
picks, so a wrong "best guess" is a wrong answer sent to an employer. Every
rung is pinned here, and so is every refusal: a tie, a placeholder, a phrase
that merely starts with the same word.
"""

from __future__ import annotations

import pytest

from auto_apply.domain.applications.option_matching import (
    NO_MATCH,
    is_decline,
    is_placeholder,
    match_option,
    polarity,
    same_value,
    shows_choice,
)

_COUNTRIES = ["Select...", "Canada", "Mexico", "United States of America"]
_STATES = ["-- Select --", "Arizona", "California", "Colorado", "Illinois"]


def _label(desired: object, options: list[str]) -> str | None:
    m = match_option(desired, options)  # type: ignore[arg-type]
    return options[m.index] if m.found else None


@pytest.mark.parametrize(
    ("desired", "options", "expected", "rung"),
    [
        ("Canada", _COUNTRIES, "Canada", "exact"),
        ("United States", _COUNTRIES, "United States of America", "alias"),
        ("USA", _COUNTRIES, "United States of America", "alias"),
        ("CA", _STATES, "California", "alias"),
        ("IL", _STATES, "Illinois", "alias"),
        ("Bachelor", ["Associate's", "Bachelor's Degree", "Master's Degree"], "Bachelor's Degree", "prefix"),
    ],
)
def test_each_rung_finds_the_option(desired: str, options: list[str], expected: str, rung: str) -> None:
    m = match_option(desired, options)
    assert m.found and options[m.index] == expected
    assert m.rung == rung


def test_a_pure_yes_matches_by_polarity_but_a_phrase_does_not() -> None:
    opts = ["Yes, I am authorized", "No, I am not authorized"]
    assert _label("Yes", opts) == "Yes, I am authorized"
    assert _label("No", opts) == "No, I am not authorized"
    # A phrase answer never picks an option merely because both start "No".
    assert _label("No preference", ["No, I will need sponsorship", "Yes"]) is None


def test_decline_matches_decline_in_any_wording() -> None:
    opts = ["Female", "Male", "I don't wish to answer"]
    assert _label("Decline to self-identify", opts) == "I don't wish to answer"
    assert _label("Prefer not to say", opts) == "I don't wish to answer"
    assert is_decline("I do not want to answer")
    assert not is_decline("No")


def test_decline_is_not_a_no() -> None:
    opts = ["Yes", "No", "Decline to answer"]
    assert _label("No", opts) == "No"
    assert polarity("Decline to answer") is False  # a no-family word...
    # ...but the polarity rung excludes decline options, so "No" stays "No".


def test_placeholders_are_never_chosen() -> None:
    assert is_placeholder("Select...")
    assert is_placeholder("-- Select --")
    assert is_placeholder("")
    assert not is_placeholder("Canada")
    assert match_option("Select...", _COUNTRIES) == NO_MATCH


def test_a_tie_is_no_match_not_a_guess() -> None:
    opts = ["Software Engineer II", "Software Engineer III"]
    assert not match_option("Software Engineer", opts).found


def test_overlap_needs_a_margin_over_the_runner_up() -> None:
    opts = ["Referral from an employee", "Job board (LinkedIn, Indeed)", "Company website"]
    assert _label("LinkedIn job board", opts) == "Job board (LinkedIn, Indeed)"
    assert not match_option("something unrelated entirely", opts).found


def test_several_wordings_are_tried_in_order() -> None:
    opts = ["Chicago, Illinois", "Chicago Heights, Illinois"]
    assert _label(("Chicago, IL", "Chicago, Illinois"), opts) == "Chicago, Illinois"


def test_read_back_compares_masked_numbers_by_digits() -> None:
    assert same_value("(555) 123-4567", "5551234567")
    assert same_value("+1 555 123 4567", "5551234567")
    assert not same_value("555", "556")
    assert same_value("Ada  Quill", "ada quill")


def test_a_custom_widget_shows_the_chosen_label() -> None:
    assert shows_choice("United States of America", "United States of America")
    assert shows_choice("Country: Canada ×", "Canada")
    assert not shows_choice("Select...", "Canada")

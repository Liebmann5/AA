"""Selection limits read from a multi-choice question's words (ADR-026)."""

from __future__ import annotations

import pytest

from auto_apply.domain.applications.selection_limits import selection_limit


@pytest.mark.parametrize(("text", "low", "high"), [
    ("Pick the best 2", 2, 2),
    ("Select up to three skills", 0, 3),
    ("Choose at least one", 1, 0),
    ("Choose one or more", 1, 0),
    ("Please select 2-3 options", 2, 3),
    ("Choose 2 to 4 areas", 2, 4),
    ("Pick your top 3 and then expand on your choices", 3, 3),
    ("Select one", 1, 1),
    ("Wählen Sie bis zu 3 Bereiche", 0, 3),
    ("Sélectionnez au moins deux", 2, 0),
    ("Elija exactamente 2", 2, 2),
    ("Selecione até 3", 0, 3),
    ("Select all that apply (up to 3)", 0, 3),
    ("Select all that apply, at least 2", 2, 0),
    ("Pick the best 2 from up to 5 options", 2, 2),
])
def test_limits_in_several_wordings_and_languages(text: str, low: int, high: int) -> None:
    lim = selection_limit(text)
    assert (lim.low, lim.high) == (low, high), lim


@pytest.mark.parametrize("text", [
    "Which of these apply? (select all that apply)",
    "Of these 5 tools, select all that apply",
    "Which 3 tools? Select all that apply",
    "Choose from these 5 tools; select all that apply",
    "How many years of experience do you have? 5",
    "Founded in 2010",
    "",
])
def test_no_limit_where_none_is_stated(text: str) -> None:
    assert not selection_limit(text).known


def test_the_limit_says_how_it_was_read() -> None:
    assert selection_limit("Select up to 3").evidence == "words(en):at most 3"
    assert selection_limit("Select up to 3").allows(3)
    assert not selection_limit("Select up to 3").allows(4)
    assert not selection_limit("Pick 2").allows(1)


def test_loosening_words_count_only_in_the_pages_languages() -> None:
    """'bis zu' (German 'up to') on a page AA reads as English never loosens
    the limit: it stays strict, and AA asks if an answer does not fit."""
    text = "Wählen Sie bis zu 3 Bereiche"
    assert selection_limit(text, ("de", "en")) == selection_limit(text)
    assert (selection_limit(text, ("en",)).low, selection_limit(text, ("en",)).high) == (3, 3)


def test_setting_words_count_in_every_language() -> None:
    assert selection_limit("Elija exactamente 2", ("en",)).high == 2

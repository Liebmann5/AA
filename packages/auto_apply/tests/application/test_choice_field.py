"""One rule for multiple-choice settings in the GUI and CLI (the suffix fix).

Before: "Suffix" was a free-text box; leaving it empty or typing "Jr" (the
profile requires "Jr.") made the whole Settings save fail.
"""

from __future__ import annotations

import pytest

from auto_apply.application.services.choice_field import (
    choice_index,
    choices_for,
    parse_choice,
)
from auto_apply.application.services.ui_schema import build_ui_schema
from auto_apply.domain.models.profile import PersonalInfo, UserProfile


def _field(key: str):
    return next(f for f in build_ui_schema(UserProfile, "en") if f.key == key)


def test_an_optional_choice_offers_none_first_and_stores_none() -> None:
    choices = choices_for(_field("personal_info.suffix"))
    assert choices[0].value is None and choices[0].label == "(none)"
    assert [c.value for c in choices[1:]] == ["Sr.", "Jr.", "II", "III", "IV", "V"]
    assert parse_choice(choices, "") is None
    assert parse_choice(choices, "none") is None


@pytest.mark.parametrize(("typed", "value"), [
    ("jr", "Jr."), ("JR.", "Jr."), ("3", "Jr."), ("iii", "III"), ("Sr", "Sr."),
])
def test_typed_answers_are_read_forgivingly(typed: str, value: str) -> None:
    assert parse_choice(choices_for(_field("personal_info.suffix")), typed) == value


@pytest.mark.parametrize("typed", ["Junior", "VI", "99", "I"])
def test_unknown_or_ambiguous_answers_are_refused_never_guessed(typed: str) -> None:
    with pytest.raises(ValueError, match="choice"):
        parse_choice(choices_for(_field("personal_info.suffix")), typed)


def test_a_stored_value_that_is_not_listed_shows_the_first_choice() -> None:
    choices = choices_for(_field("personal_info.suffix"))
    assert choice_index(choices, "Esq.") == 0 and choice_index(choices, "II") == 3


def test_every_choice_the_widget_offers_saves() -> None:
    """Whatever the person picks for the suffix, the profile accepts it."""
    base = UserProfile.model_json_schema()  # the model builds
    assert base
    for c in choices_for(_field("personal_info.suffix")):
        info = PersonalInfo.model_validate({
            "first_name": "Ada", "last_name": "Q", "email": "a@b.example",
            "phone_number": "5550100", "street_address": "1 Main St", "city": "Town",
            "state": "WA", "zip_code": "98000", "suffix": c.value})
        assert info.suffix == c.value

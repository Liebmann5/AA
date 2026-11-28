"""The one-use submit token (Phase 0, P0-4; AA_ENGINE_MATH.md §3, §3a).

TEETH: the module did not exist; each pin names what it guards.
"""

from __future__ import annotations

import pytest

from auto_apply.domain.services.submit_token import (
    AUTH_PERSON,
    AUTH_POLICY,
    ControlIdentity,
    TokenAlreadyUsed,
    TokenBook,
    values_changed,
)

SUBMIT = ControlIdentity(tag="button", type="submit", name="apply", id="go",
                         form_action="/apply", form_method="post")
VALUES = [("First name *", "identity", "Ada"), ("Email *", "email", "ada@example.org")]


def _mint(values=VALUES, control=SUBMIT, source=AUTH_PERSON):
    return TokenBook.mint(attempt_id="a1", values=values, control=control,
                          step_fingerprint="fp", auth_source=source)


def test_a_token_is_used_once() -> None:
    book = TokenBook()
    token = _mint()
    book.consume(token)
    with pytest.raises(TokenAlreadyUsed):
        book.consume(token)


def test_the_digest_binds_every_value() -> None:
    changed = [VALUES[0], ("Email *", "email", "ada@example.com")]
    assert _mint().values_digest != _mint(changed).values_digest
    assert _mint().values_digest == _mint(list(reversed(VALUES))).values_digest, \
        "question order does not matter"


def test_a_token_needs_an_armed_attempt_and_a_known_source() -> None:
    with pytest.raises(ValueError):
        TokenBook.mint(attempt_id="", values=VALUES, control=SUBMIT,
                       step_fingerprint="fp", auth_source=AUTH_PERSON)
    with pytest.raises(ValueError):
        _mint(source="someone")
    assert _mint(source=AUTH_POLICY).auth_source == AUTH_POLICY


def test_duplicate_question_keys_never_mint() -> None:
    with pytest.raises(ValueError):
        _mint([VALUES[0], VALUES[0]])


def test_the_target_is_compared_field_by_field() -> None:
    assert SUBMIT.mismatch(SUBMIT) == ""
    other_form = ControlIdentity(**{**SUBMIT.__dict__, "form_action": "/elsewhere"})
    assert SUBMIT.mismatch(other_form) == "form_action"
    assert not ControlIdentity().readable


def test_values_changed_uses_the_comparators_equivalence() -> None:
    approved = [("Phone", "digits", "(555) 123-4567"), ("Name", "identity", "Ada  Lovelace")]
    same = [("Phone", "digits", "555-123-4567"), ("Name", "identity", "ada lovelace")]
    assert values_changed(approved, same) == (), "a reformatting mask is not a change"
    edited = [("Phone", "digits", "555-123-4568"), ("Name", "identity", "Ada Lovelace")]
    assert values_changed(approved, edited) == ("Phone",)
    assert values_changed(approved, same[:1]) == ("Name",), "a vanished field is a change"

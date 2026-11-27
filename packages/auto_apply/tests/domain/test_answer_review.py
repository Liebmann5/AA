"""Which answers the person must see before they are sent (ADR-026)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from auto_apply.domain.applications import answer_review
from auto_apply.domain.applications.answer_review import (
    answer_class,
    needs_review,
    normal_timing,
    normal_trust,
)
from auto_apply.domain.applications.answers import Answer

NAME = Answer(text="Ada", source="profile:personal_info.first_name", confidence=0.95)
DECLARED = Answer(text="No", source="profile:legal_info.requires_sponsorship",
                  confidence=0.95, sensitive=True, review=True)
SAVED = Answer(text="Because…", source="saved", confidence=0.85, review=True)
MATCHED = Answer(text="Because…", source="saved:meaning", confidence=0.86, review=True)
DRAFT = Answer(text="I am…", source="generated", confidence=0.86, review=True)
UNSURE = Answer(text="Maybe", source="profile:x", confidence=0.6)
PERSON = Answer(text="Mine", source="human", confidence=0.5, review=True)
UNKNOWN = Answer(text="?", source="someplugin", confidence=0.99)


@pytest.mark.parametrize(("trust", "expected"), [
    ("never", {"NAME": False, "DECLARED": True, "SAVED": True, "MATCHED": True,
               "DRAFT": True}),
    ("own_words", {"NAME": False, "DECLARED": False, "SAVED": False, "MATCHED": True,
                   "DRAFT": True}),
    ("matched", {"NAME": False, "DECLARED": False, "SAVED": False, "MATCHED": False,
                 "DRAFT": True}),
    ("drafts", {"NAME": False, "DECLARED": False, "SAVED": False, "MATCHED": False,
                "DRAFT": False}),
])
def test_each_trust_level_widens_one_class(trust: str, expected: dict[str, bool]) -> None:
    got = {k: needs_review(globals()[k], trust) for k in expected}
    assert got == expected


@pytest.mark.parametrize("trust", ["never", "own_words", "matched", "drafts"])
def test_unsure_answers_are_always_reviewed_and_the_persons_never(trust: str) -> None:
    assert needs_review(UNSURE, trust) is True
    assert needs_review(PERSON, trust) is False


def test_an_unrecognised_source_is_treated_as_a_draft() -> None:
    assert answer_class(UNKNOWN) == "draft"
    assert needs_review(UNKNOWN, "matched") is True


@pytest.mark.parametrize("value", ["", None, "always", "NEVER ", 3])
def test_unknown_settings_fail_closed(value: object) -> None:
    assert normal_trust(value) == "never", "unknown reads as the strictest level"
    assert normal_timing(value) == "end"


def test_the_policy_is_independent_of_submission_and_of_how_people_are_asked() -> None:
    """The coupling ADR-026 forbids: this module may not read the submission
    setting, the interrupt policy, the gate transport, or any surface."""
    src = Path(answer_review.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert imported <= {"__future__", "auto_apply.domain.applications.answers"}, imported

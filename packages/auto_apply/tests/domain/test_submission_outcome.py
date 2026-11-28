"""Pins for the one outcome vocabulary (P0-2).

TEETH when written: the Literal had no UNKNOWN, and neither the vocabulary
table nor the click-failure classifier existed. Now regression guards; the
totality pin is the one that cannot silently rot.
"""

from __future__ import annotations

from typing import get_args

import pytest

from auto_apply.domain.models.application_evidence import (
    BLOCKING_HISTORY_STATUSES,
    BLOCKING_OUTCOMES,
    OUTCOME_VOCABULARY,
    ApplicationEvidence,
    history_status_for,
    outcome_for_click_failure,
)


def test_the_vocabulary_covers_every_outcome_literal():
    literal = set(get_args(ApplicationEvidence.model_fields["outcome"].annotation))
    assert set(OUTCOME_VOCABULARY) == literal


def test_unknown_is_a_first_class_outcome():
    literal = get_args(ApplicationEvidence.model_fields["outcome"].annotation)
    assert "UNKNOWN" in literal


def test_blocking_outcomes_are_exactly_the_cannot_rule_out_set():
    assert set(BLOCKING_OUTCOMES) == {
        "SUBMITTED",
        "PROBABLY_SUBMITTED",
        "AMBIGUOUS",
        "UNKNOWN",
    }


def test_blocking_history_statuses():
    assert set(BLOCKING_HISTORY_STATUSES) == {"APPLIED", "UNKNOWN"}


def test_history_status_mapping():
    assert history_status_for("SUBMITTED") == "APPLIED"
    assert history_status_for("AMBIGUOUS") == "UNKNOWN"
    assert history_status_for("SUBMISSION_GATE_BLOCKED") == "GATE_BLOCKED"
    assert history_status_for("something-unrecognised") == "UNKNOWN"


@pytest.mark.parametrize(
    "raised,rung,expected",
    [
        (True, None, "UNKNOWN"),       # an exception mid-ladder: cannot tell
        (True, "probe", "ERROR"),      # the rung is known: refused before dispatch
        (True, "none", "ERROR"),       # the rung is known: nothing fired
        (True, "keyboard", "UNKNOWN"), # the rung is known: it may have dispatched
        (False, "probe", "ERROR"),     # refused before any rung could dispatch
        (False, "none", "ERROR"),      # every rung refused to fire
        (False, "pointer", "UNKNOWN"), # the pointer rung may have dispatched
        (False, "keyboard", "UNKNOWN"),# focus + Enter may have dispatched
        (False, "native", "UNKNOWN"),
        (False, "js", "UNKNOWN"),
        (False, None, "UNKNOWN"),      # cannot tell — the safe answer
    ],
)
def test_click_failure_classification(raised, rung, expected):
    assert outcome_for_click_failure(raised=raised, rung=rung) == expected

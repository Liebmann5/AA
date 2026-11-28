"""The click rung must reach the workflow in production (P0-2, item 5).

InteractionExecutor raises ApplicationError on any failed click; before this
fix the ladder rung was discarded, so the workflow classified every failure
as UNKNOWN — including probe refusals where nothing was dispatched. These
pins drive the real executor with a fake page-action tool, and the workflow's
except branch is pinned by AST to read the rung off the error.
"""

from __future__ import annotations

import ast
import pathlib
from unittest.mock import MagicMock

import pytest

from auto_apply.adapters.secondary.interaction.human_like_adapter import (
    ClickFailedError,
    InteractionExecutor,
)
from auto_apply.application.services.page_action.result import ActionResult
from auto_apply.domain.models.application_evidence import outcome_for_click_failure


class _FakeTool:
    def __init__(self, result):
        self._result = result

    def click(self, element, irreversible=False, expect=None):
        return self._result


def _executor_with(result):
    return InteractionExecutor(MagicMock(), page_action=_FakeTool(result))


def test_a_probe_refusal_reaches_the_classifier_as_error():
    executor = _executor_with(
        ActionResult(False, reason="click target not reachable: occluded:div", rung="probe")
    )
    with pytest.raises(ClickFailedError) as excinfo:
        executor.click(MagicMock(), irreversible=True)
    assert excinfo.value.click_rung == "probe"
    assert outcome_for_click_failure(raised=True, rung=excinfo.value.click_rung) == "ERROR"


def test_a_keyboard_failure_reaches_the_classifier_as_unknown():
    executor = _executor_with(ActionResult(False, reason="x", rung="keyboard"))
    with pytest.raises(ClickFailedError) as excinfo:
        executor.click(MagicMock(), irreversible=True)
    assert excinfo.value.click_rung == "keyboard"
    assert outcome_for_click_failure(raised=True, rung=excinfo.value.click_rung) == "UNKNOWN"


def test_a_missing_tool_reports_the_none_rung_and_classifies_error():
    executor = InteractionExecutor(MagicMock(), page_action=None)
    with pytest.raises(ClickFailedError) as excinfo:
        executor.click(MagicMock(), irreversible=True)
    assert excinfo.value.click_rung == "none"
    assert outcome_for_click_failure(raised=True, rung="none") == "ERROR"


def test_the_workflow_reads_the_rung_off_the_exception():
    """AST pin: _submit_application's except branch must read exc.click_rung."""
    path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src" / "auto_apply" / "application" / "workflows" / "applications_workflow.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
            if any(isinstance(a, ast.Constant) and a.value == "click_rung" for a in node.args):
                found = True
    assert found, "the workflow's except branch must read exc.click_rung"

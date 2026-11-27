"""AST pin: exactly one repository write per application attempt (P0-2).

The measured double-write recorded APPLIED in _submit_application and then
FAILED in _record_application_outcome for the same attempt, in the same
second. This pin fails while two call sites exist and passes when one does.
"""

from __future__ import annotations

import ast
import pathlib

WORKFLOW = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "auto_apply" / "application" / "workflows" / "applications_workflow.py"
)


def _mark_applied_calls(tree) -> list:
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "mark_applied"
    ]


def test_mark_applied_is_called_exactly_once():
    tree = ast.parse(WORKFLOW.read_text(encoding="utf-8"))
    sites = _mark_applied_calls(tree)
    assert len(sites) == 1, (
        "mark_applied must be called exactly once per attempt — two call "
        "sites is the measured double-write"
    )


def test_the_single_write_lives_in_record_application_outcome():
    tree = ast.parse(WORKFLOW.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_record_application_outcome":
            inside = [
                sub for sub in ast.walk(node)
                if isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "mark_applied"
            ]
            assert len(inside) == 1
            return
    raise AssertionError("_record_application_outcome not found")

"""Pin: the ASP solver can locate the rules file via importlib.resources.

This pin passes post‑stage, and fails pre‑stage because the old parents[3]
path is wrong.
"""
from importlib import resources
from pathlib import Path

from auto_apply.adapters.secondary.reasoning.asp_adapter import ClingoFormSolver


def test_asp_rules_file_exists_via_importlib_resources():
    rules_path = resources.files("auto_apply.adapters.secondary.reasoning") / "rules" / "form_semantics.lp"
    assert rules_path.exists(), f"Rules file not found at {rules_path}"
    solver = ClingoFormSolver(rules_file_path=rules_path)
    assert solver.rules_file_path == rules_path

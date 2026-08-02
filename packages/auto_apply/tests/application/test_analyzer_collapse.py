
"""Pins for the analyzer collapse and the retired FSM stub (Stage 5c).

``webpage_analyzer`` and ``mathematical_web_analyzer`` each defined the same
five types — four exceptions and ``AnalyzerConfig`` — with identical bodies and
identical defaults. Duplicate exception classes are worse than they look:
``except PerceptionError`` bound to one module's class does not catch the other
module's, so a caller can be correct against one analyzer and quietly wrong
against the other. These pins hold one definition each and prove the collapse
changed no values.

They also retire ``domain/applications/fsm/universal.py``, which never existed:
``_instantiate_form_fsm`` imported it inside a ``try`` that logged at debug, so
the FSM was never once instantiated and ``self._fsm`` was assigned but never
read. Option (A) — no new FSM subsystem; the per-page loop already carries
Applications.
"""
import ast
import pathlib
from dataclasses import fields, is_dataclass

import pytest

from auto_apply.application.services import mathematical_web_analyzer as math_mod
from auto_apply.application.services import webpage_analyzer as web_mod
SRC = pathlib.Path(__file__).resolve().parent.parent.parent / "src" / "auto_apply"
WORKFLOW = SRC / "application" / "workflows" / "applications_workflow.py"

SHARED = (
    "WebpageAnalysisError",
    "PerceptionError",
    "ReasoningError",
    "AnalysisTimeoutError",
    "AnalyzerConfig",
)


# ─────────────────────────────────────────────────────────────────────────────
# ONE DEFINITION EACH
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", SHARED)
def test_each_shared_type_is_defined_exactly_once(name):
    definitions = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == name:
                definitions.append(str(path.relative_to(SRC)).replace("\\", "/"))

    assert definitions == ["application/services/analysis_contracts.py"], (
        f"{name} is defined in: {definitions}"
    )


@pytest.mark.parametrize("name", SHARED)
def test_both_analyzers_expose_the_same_class_object(name):
    """Identity, not similarity — the `except` hazard is now impossible."""
    assert getattr(web_mod, name) is getattr(math_mod, name)


def test_catching_one_modules_error_catches_the_others():
    """The concrete consequence, exercised rather than asserted structurally."""
    with pytest.raises(web_mod.PerceptionError):
        raise math_mod.PerceptionError("raised from the mathematical analyzer")


# ─────────────────────────────────────────────────────────────────────────────
# NOTHING CHANGED VALUE
# ─────────────────────────────────────────────────────────────────────────────


def test_the_analyzer_config_fields_and_defaults_are_unchanged():
    """Both duplicates carried these exact six fields and defaults."""
    from auto_apply.application.services.analysis_contracts import AnalyzerConfig

    assert is_dataclass(AnalyzerConfig)

    actual = {f.name: f.default for f in fields(AnalyzerConfig)}
    assert actual == {
        "enable_performance_logging": True,
        "extraction_timeout_seconds": 30.0,
        "reasoning_timeout_seconds": 60.0,
        "fallback_to_partial": False,
        "max_retries": 2,
        "retry_delay_seconds": 1.0,
    }


def test_the_analyzer_config_is_still_frozen():
    from auto_apply.application.services.analysis_contracts import AnalyzerConfig

    config = AnalyzerConfig()
    with pytest.raises(Exception):
        config.max_retries = 99


@pytest.mark.parametrize(
    "name", ["PerceptionError", "ReasoningError", "AnalysisTimeoutError"]
)
def test_the_exception_hierarchy_is_unchanged(name):
    from auto_apply.application.services import analysis_contracts

    error = getattr(analysis_contracts, name)
    assert issubclass(error, analysis_contracts.WebpageAnalysisError)
    assert issubclass(error, Exception)


# ─────────────────────────────────────────────────────────────────────────────
# THE RETIRED FSM
# ─────────────────────────────────────────────────────────────────────────────


def test_no_module_imports_the_fsm_that_never_existed():
    offenders = [
        str(path.relative_to(SRC))
        for path in sorted(SRC.rglob("*.py"))
        if "fsm.universal" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert offenders == [], f"the dead FSM import survives in: {offenders}"


def test_the_dead_instantiation_helper_is_gone():
    source = WORKFLOW.read_text(encoding="utf-8", errors="ignore")
    assert "_instantiate_form_fsm" not in source
    assert "self._fsm" not in source, (
        "an attribute that was assigned and never read survives"
    )


def test_the_fsm_package_still_holds_only_what_exists():
    """base.py and states.py are real; universal.py never was."""
    fsm_dir = SRC / "domain" / "applications" / "fsm"
    present = sorted(p.name for p in fsm_dir.glob("*.py"))
    assert "universal.py" not in present
    assert {"base.py", "states.py"} <= set(present)


# ─────────────────────────────────────────────────────────────────────────────
# THE STRATEGIC SYSTEM RE-PERCEIVES PER PAGE
# ─────────────────────────────────────────────────────────────────────────────


def _loop_body_calls() -> set[str]:
    """Names called inside the per-page `while True` loop of the apply flow."""
    tree = ast.parse(WORKFLOW.read_text(encoding="utf-8", errors="ignore"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.While):
            continue
        called = set()
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute):
                called.add(inner.func.attr)
        if "_navigate_multi_page_flow" in called:
            return called
    return set()


def test_perception_and_planning_happen_inside_the_per_page_loop():
    """Answers the multi-page question structurally: re-perceive, not plan-once.

    Perception (`_get_form_structure_with_iframe_fallback`) and planning
    (`_classify_all_fields`) both sit inside the same `while True` body that
    advances the wizard, so each page of a multi-step form is read and planned
    fresh after the DOM settles. If either were hoisted above the loop, this
    fails — which is the regression that would turn the strategic system into a
    plan-once executor without anyone noticing.
    """
    called = _loop_body_calls()

    assert called, "could not find the per-page loop"
    assert "_get_form_structure_with_iframe_fallback" in called
    assert "_classify_all_fields" in called
    assert "_fill_standard_fields" in called


def test_the_page_loop_is_bounded():
    """Re-perceiving per page is only safe because the walk has a ceiling."""
    source = WORKFLOW.read_text(encoding="utf-8", errors="ignore")
    assert "applications.max_pages" in source
    assert "_pages_navigated" in source

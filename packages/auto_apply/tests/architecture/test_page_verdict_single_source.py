"""Guard pins: the page verdict has one home and the retired copies stay retired.

GUARD, not teeth — this passes on the consolidating tree and fails on
regressions:

  * a retired decision point (PageClassifier, the detection strategies,
    EvasionManager, check_page_safety, is_challenge_present) reappearing
    anywhere in src/ — the predicate answered in two places again, which is
    the predicate-12 defect class;
  * a second ``assess_page`` definition;
  * the discovery strategy layer importing a retired classifier or
    detector;
  * any retired file still present — the files move to
    ``docs/old_retired_files/`` via retire.py, and this pin fails until
    they do, which is what enforces the apply-then-retire order.
"""

from __future__ import annotations

import ast
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _PKG_ROOT / "src" / "auto_apply"
_VERDICT_REL = "src/auto_apply/domain/services/page_assessment.py"
_SERP_STRATEGY = (
    _SRC_DIR
    / "adapters"
    / "secondary"
    / "discovery"
    / "strategies"
    / "serp_strategy.py"
)

_RETIRED_SRC = [
    "adapters/secondary/dom/classifier.py",
    "adapters/secondary/evasion/detection.py",
    "adapters/secondary/evasion/detection_config.json",
    "adapters/secondary/evasion/manager.py",
    "adapters/secondary/evasion/auditor.py",
    "domain/browser_state.py",
    "domain/ports/page_classification_port.py",
]

_RETIRED_CLASS_NAMES = {
    "PageClassifier",
    "EvasionManager",
    "DetectionStrategy",
    "DefaultDetectionStrategy",
    "CloudflareDetectionStrategy",
}

_RETIRED_FUNCTION_NAMES = {
    "is_challenge_present",
    "check_page_safety",
}


def _iter_src_files() -> list:
    return [
        p
        for p in sorted(_SRC_DIR.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


def test_retired_files_are_gone() -> None:
    still_present = [rel for rel in _RETIRED_SRC if (_SRC_DIR / rel).exists()]
    assert not still_present, (
        "These modules were retired by the page-verdict consolidation and "
        "must be moved out of src/ — run this change's retire.py commands "
        f"before running the suite: {still_present}"
    )


def test_no_regrowth_of_retired_decision_points() -> None:
    found: list[str] = []
    for path in _iter_src_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in _RETIRED_CLASS_NAMES:
                found.append(
                    f"{path.relative_to(_PKG_ROOT)}:{node.lineno} class {node.name}"
                )
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in _RETIRED_FUNCTION_NAMES
            ):
                found.append(
                    f"{path.relative_to(_PKG_ROOT)}:{node.lineno} def {node.name}"
                )
    assert not found, (
        "A retired page-verdict decision point reappeared — the answer to "
        f"'what is this page?' must live only in the one verdict: {found}"
    )


def test_exactly_one_assess_page_implementation() -> None:
    defs: list[str] = []
    for path in _iter_src_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "assess_page"
            ):
                defs.append(path.relative_to(_PKG_ROOT).as_posix())
    assert defs == [_VERDICT_REL], (
        f"The page verdict must have exactly one implementation, in "
        f"{_VERDICT_REL}. Found: {defs}."
    )


def test_serp_strategy_asks_the_one_verdict() -> None:
    tree = ast.parse(_SERP_STRATEGY.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
            imported_names |= {alias.name for alias in node.names}
    for corpse in (
        "auto_apply.adapters.secondary.dom.classifier",
        "auto_apply.adapters.secondary.evasion.detection",
        "auto_apply.adapters.secondary.evasion.manager",
    ):
        assert corpse not in imported_modules, (
            f"serp_strategy.py imports {corpse} again — discovery must ask "
            "the one page verdict, not a retired detector."
        )
    assert "assess_page" in imported_names, (
        "serp_strategy.py no longer imports assess_page — the block gate "
        "must ask the one page verdict."
    )

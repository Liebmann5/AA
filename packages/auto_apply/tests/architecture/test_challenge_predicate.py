"""Guard pin: exactly one implementation answers "is a challenge presented?".

GUARD, not teeth — it passes on the tree that introduced it and fails on
regressions:

  * a second ``assess_challenge`` appearing anywhere in src/ (the predicate
    being answered in two places again — predicate-12 class);
  * the application-attempt path regrowing its own answer: the substring
    list, the inline weighted mirror, a captcha hand-off enqueue, the
    title-substring login-wall list, or a URL where a checkpoint name
    belongs.

Scoped honestly: this pins the APPLICATION-ATTEMPT path, where the false
verdicts were measured. Discovery-side consumers (DefaultDetectionStrategy,
CloudflareDetectionStrategy, EvasionManager, PageClassifier,
MathFormUnderstandingService._detect_captcha) still carry their own answers;
migrating them to this predicate is a named follow-up, not asserted here.
"""

from __future__ import annotations

import ast
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _PKG_ROOT / "src" / "auto_apply"
_WORKFLOW = _SRC_DIR / "application" / "workflows" / "applications_workflow.py"
_PREDICATE_REL = "src/auto_apply/domain/services/challenge_assessment.py"


def _iter_src_files() -> list:
    return [
        p
        for p in sorted(_SRC_DIR.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


def test_exactly_one_challenge_predicate_implementation() -> None:
    defs: list[str] = []
    for path in _iter_src_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "assess_challenge"
            ):
                defs.append(path.relative_to(_PKG_ROOT).as_posix())
    assert defs == [_PREDICATE_REL], (
        "The challenge verdict must have exactly one implementation, in "
        f"{_PREDICATE_REL}. Found assess_challenge defined in: {defs}. "
        "A second answer to the same question is the predicate-12 defect."
    )


def test_applications_workflow_uses_only_the_one_predicate() -> None:
    src = _WORKFLOW.read_text(encoding="utf-8")

    # The deleted answers must not regrow.
    for corpse in (
        "captcha_indicators",      # the substring list
        "_p12",                    # the inline weighted mirror + dump
        "HANDLE_CAPTCHA",          # the hand-off enqueue (late, wrong page)
        "_LOGIN_WALL_INDICATORS",  # the title-substring login wall
        'f"submit_{',              # a URL where a checkpoint name belongs
        'f"redirect_{',
    ):
        assert corpse not in src, (
            f"{corpse!r} reappeared in applications_workflow.py — the "
            "application-attempt path must call the one predicate, not grow "
            "its own answer again."
        )

    # The one predicate must actually be imported and used.
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "auto_apply.domain.services.challenge_assessment"
        ):
            imported |= {alias.name for alias in node.names}
    assert {"assess_challenge", "assess_login_wall"} <= imported, (
        "applications_workflow.py no longer imports the one predicate from "
        "domain/services/challenge_assessment.py."
    )

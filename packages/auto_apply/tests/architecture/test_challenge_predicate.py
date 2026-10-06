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
verdicts were measured. The discovery side has since been consolidated:
serp_strategy and indeed ask the composed one verdict
(domain/services/page_assessment.py), which delegates to THIS module for
the challenge and login-wall answers, and the discovery-side copies
(DefaultDetectionStrategy, CloudflareDetectionStrategy, EvasionManager,
PageClassifier) are retired — test_page_verdict_single_source.py guards
that. The math-path copies (_detect_captcha/_detect_login_wall and their
unread fields) are removed; the application-attempt path now asks the
composed verdict too, and this file asserts it never reaches past the
verdict to the engine.
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

    # The application path must ask the ONE page verdict — and must not
    # reach past it to the challenge engine directly.
    tree = ast.parse(src)
    verdict_imports: set[str] = set()
    engine_imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "auto_apply.domain.services.page_assessment":
                verdict_imports |= {alias.name for alias in node.names}
            elif node.module == "auto_apply.domain.services.challenge_assessment":
                engine_imports |= {alias.name for alias in node.names}
    assert "assess_page" in verdict_imports, (
        "applications_workflow.py no longer imports assess_page from "
        "domain/services/page_assessment.py — the application path must ask "
        "the ONE page verdict."
    )
    assert not engine_imports, (
        "applications_workflow.py imports the challenge engine directly "
        f"({engine_imports}) — it must ask the composed verdict "
        "(page_assessment), which delegates to the engine."
    )

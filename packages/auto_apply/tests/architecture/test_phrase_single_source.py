"""Guard pins: outcome phrases have one home, and the math path has no
challenge/login answer of its own to disagree with the verdict.

GUARD, not teeth — passes on the consolidated tree, fails on regressions:

  * a sentinel outcome phrase literal appearing in any src module other
    than domain/services/page_phrases.py (a second phrase table regrowing);
  * the retired name ATS_CONFIRMATION_PATTERNS reappearing in src;
  * the math path re-growing a challenge or login answer
    (_detect_captcha/_detect_login_wall, is_captcha_present/is_login_wall,
    SERPStructure.captcha_detected) — it cannot disagree with the verdict
    because it has no answer.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PKG_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _PKG_ROOT / "src" / "auto_apply"
_PHRASES_FILE = _SRC_DIR / "domain" / "services" / "page_phrases.py"

#: One phrase per outcome table. If one of these legitimately needs to
#: appear elsewhere, that elsewhere is a second phrase table — fix it
#: instead of widening this pin.
_SENTINEL_PHRASES = [
    "thank you for applying",
    "no longer accepting",
    "you applied on",
    "application sent",
]


def _code_facts(path: Path) -> tuple[list[str], set[str]]:
    """(non-docstring string literals, identifiers) — comments and
    docstrings may name a retired symbol; only code may not."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    strings: list[str] = []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            strings.append(node.value.lower())
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
    return strings, names


def _iter_src_files() -> list:
    return [
        p
        for p in sorted(_SRC_DIR.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


@pytest.mark.parametrize("phrase", _SENTINEL_PHRASES)
def test_outcome_phrase_defined_once_in_src(phrase: str) -> None:
    hits = [
        path
        for path in _iter_src_files()
        if any(phrase in s for s in _code_facts(path)[0])
    ]
    assert hits == [_PHRASES_FILE], (
        f"{phrase!r} appears outside page_phrases.py: "
        f"{[str(p.relative_to(_PKG_ROOT)) for p in hits]}. Outcome phrases "
        "live in exactly one data module so a translator edits one place."
    )


def test_ats_confirmation_patterns_name_is_gone_from_src() -> None:
    hits = [
        path
        for path in _iter_src_files()
        if "ATS_CONFIRMATION_PATTERNS" in _code_facts(path)[1]
    ]
    assert not hits, (
        "ATS_CONFIRMATION_PATTERNS reappeared in "
        f"{[str(p.relative_to(_PKG_ROOT)) for p in hits]} — the phrase "
        "tables live in domain/services/page_phrases.py."
    )


def test_math_path_has_no_challenge_or_login_answer() -> None:
    seg = (_SRC_DIR / "domain" / "services" / "dom_segmentation.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(seg)
    for node in ast.walk(tree):
        assert not (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in ("_detect_captcha", "_detect_login_wall")
        ), (
            f"dom_segmentation regrew {node.name} — page identity is "
            "answered by page_assessment, not by the math path."
        )

    webpage = _code_facts(_SRC_DIR / "domain" / "models" / "math_webpage.py")[1]
    assert "is_captcha_present" not in webpage
    assert "is_login_wall" not in webpage

    port = _code_facts(_SRC_DIR / "domain" / "ports" / "page_understanding_port.py")[1]
    assert "captcha_detected" not in port

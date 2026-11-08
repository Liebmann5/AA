"""Import boundary (CT-NFR-001, CT-INV-105, Bible 1.3 rules 1 and 6).

The library imports only the standard library and itself, never AA, and only
with absolute imports.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pagecomp

# The installed package itself, wherever it lives (standalone src/ layout, or
# vendored inside AA's source tree).
SRC = Path(pagecomp.__file__).resolve().parent


def test_stdlib_only_absolute_imports_no_auto_apply():
    stdlib = set(sys.stdlib_module_names)
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"relative import in {path}"
                top = (node.module or "").split(".")[0]
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top in stdlib or top == "pagecomp", f"{path}: {alias.name}"
                continue
            else:
                continue
            assert top != "auto_apply", f"{path} imports AA"
            assert top in stdlib or top in ("pagecomp", "__future__"), f"{path}: {top}"


def test_tools_touch_no_clock_file_or_network():
    banned = {"time", "datetime", "socket", "urllib.request", "http", "random", "os", "subprocess"}
    for path in (SRC / "tools").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for n in names:
                assert n not in banned and n.split(".")[0] not in {"socket", "subprocess"}, f"{path}: {n}"

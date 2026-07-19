"""Architectural integrity tests.

These tests enforce invariants defined in the Architecture Bible and the
ADR records. They act as automated gates to prevent accidental degradation
of the hexagonal layering, single-source-of-truth, and other core design rules.
"""

import ast
import pathlib
import warnings
from typing import Optional

SRC_ROOT = pathlib.Path(__file__).resolve().parent.parent / "src" / "auto_apply"

# ----------------------------------------------------------------------
# Helper functions for the import-boundary test
# ----------------------------------------------------------------------
def _file_layer(py_file: pathlib.Path) -> str | None:
    """Return the architectural layer of *py_file*, or None if it is a root‑level file.

    ``adapters`` is split into ``adapters_primary`` and ``adapters_secondary``
    because hexagonal architecture treats them asymmetrically: primary
    (driving) adapters — CLI, GUI — exist specifically to call INTO the
    application layer's use cases, so that's not a boundary violation for
    them. Secondary (driven) adapters — persistence, browser, external APIs
    — implement ports that the application layer calls; if a secondary
    adapter reaches back UP into application, that's a real inversion of
    the intended dependency direction.
    """
    try:
        rel = py_file.relative_to(SRC_ROOT)
    except ValueError:
        return None
    parts = rel.parts
    if not parts:
        return None
    top = parts[0]
    if top == "adapters" and len(parts) > 1:
        if parts[1] == "primary":
            return "adapters_primary"
        if parts[1] == "secondary":
            return "adapters_secondary"
        return "adapters_secondary"  # unknown adapters/ subdir — default strict
    if top in ("domain", "application", "infrastructure"):
        return top
    return None  # files directly under auto_apply/ — treated as infrastructure


def _imported_layer(module_name: str) -> str | None:
    """Return the layer ('domain','application','adapters_primary',
    'adapters_secondary','infrastructure') if *module_name* begins with
    ``auto_apply.<layer>``, else None."""
    parts = module_name.split(".")
    if len(parts) < 2 or parts[0] != "auto_apply":
        return None
    layer = parts[1]
    if layer == "adapters" and len(parts) > 2:
        if parts[2] == "primary":
            return "adapters_primary"
        return "adapters_secondary"
    if layer in ("domain", "application", "infrastructure"):
        return layer
    return None


def _module_of_file(py_file: pathlib.Path) -> str | None:
    """Compute the fully‑qualified module name of *py_file* relative to SRC_ROOT."""
    try:
        rel = py_file.relative_to(SRC_ROOT)
    except ValueError:
        return None
    parts = list(rel.parts)
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    else:
        # Not a Python file — shouldn't happen.
        return None
    return "auto_apply." + ".".join(parts)


def _resolve_relative_import(py_file: pathlib.Path, node: ast.ImportFrom) -> str | None:
    """Resolve a relative import from *py_file* to an absolute module name."""
    if node.level == 0:
        # absolute — return node.module
        return node.module

    # Relative import
    file_mod = _module_of_file(py_file)
    if file_mod is None:
        return None
    parts = file_mod.split(".")
    # Remove the module name (last component)
    parts.pop()
    # Walk up 'level' levels
    if len(parts) < node.level:
        return None  # too many dots — invalid
    parts = parts[: -node.level] if node.level > 0 else parts
    if node.module:
        parts.append(node.module)
    return ".".join(parts) if parts else None


def _is_allowed(source_layer: str, imported_layer: str) -> bool:
    """Return True if *source_layer* is allowed to import *imported_layer*."""
    if source_layer == "domain":
        # domain must never import from application / adapters / infrastructure
        return imported_layer == "domain"
    if source_layer == "application":
        # application must never import from adapters / infrastructure
        return imported_layer in ("domain", "application")
    if source_layer == "adapters_secondary":
        # secondary (driven) adapters implement ports the application layer
        # calls — they must never reach back up into application or
        # infrastructure (that would invert the intended dependency
        # direction, and infrastructure -> adapters_secondary already runs
        # the other way via the composition root).
        return imported_layer in ("domain", "adapters_secondary")
    if source_layer == "adapters_primary":
        # primary (driving) adapters — CLI, GUI — exist specifically to call
        # into application-layer use cases; that is not a violation for them.
        return imported_layer in (
            "domain", "application", "adapters_primary", "infrastructure",
        )
    # infrastructure (or root) may import anything
    return True


# ----------------------------------------------------------------------
# Existing tests
# ----------------------------------------------------------------------
def test_single_session_plan_definition():
    """SessionPlan must be defined in exactly one source file.

    This guards against the duplicate definition found in BACKLOG-005
    (domain/models/session_plan.py and domain/models/session.py).
    """
    defining_files = []
    for py_file in SRC_ROOT.rglob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "class SessionPlan" in content:
            defining_files.append(str(py_file.relative_to(SRC_ROOT)))
    assert len(defining_files) == 1, (
        f"Expected exactly 1 file defining 'class SessionPlan', "
        f"but found {len(defining_files)}: {defining_files}"
    )


def test_old_research_infrastructure_removed():
    """Confirms no live code imports from the deprecated old research system."""
    violations = []
    for py_file in SRC_ROOT.rglob("*.py"):
        src = py_file.read_text(encoding="utf-8", errors="ignore")
        if (
            "application.services.research." in src
            or "services.research.collector" in src
        ):
            # Allow only the stubs themselves to reference the old paths
            if "application/services/research" not in str(py_file):
                violations.append(str(py_file))
    assert not violations, f"Stale imports from old research system: {violations}"


# ----------------------------------------------------------------------
# New test — Hexagonal import boundaries
# ----------------------------------------------------------------------
def test_hexagonal_import_boundaries():
    """Enforce import-direction rules: domain → domain only; application → domain only;
    adapters → domain only; infrastructure may import anything.

    This test is **expected to FAIL** right now because of two known violations:
      - application/services/session_controller.py imports a concrete adapter directly
      - application/services/mathematical_web_analyzer.py imports a concrete adapter directly

    These will be fixed in a follow-up task.  Once those two files are corrected the
    test should pass cleanly (no other violations are expected).

    Relative imports are resolved and TYPE_CHECKING blocks are **not** excluded —
    they represent real coupling at type‑check/IDE time.
    """
    violations: list[str] = []

    for py_file in SRC_ROOT.rglob("*.py"):
        layer = _file_layer(py_file)
        if layer is None:
            continue  # root‑level file — treated as infrastructure, no restrictions

        content = py_file.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(content, filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_layer = _imported_layer(alias.name)
                    if imported_layer is None:
                        continue
                    if not _is_allowed(layer, imported_layer):
                        violations.append(
                            f"{py_file.relative_to(SRC_ROOT)}:{node.lineno} "
                            f"import {alias.name}  (layer '{layer}' → '{imported_layer}')"
                        )

            elif isinstance(node, ast.ImportFrom):
                # Skip __future__ imports (they don't cross layer boundaries)
                if node.module == "__future__":
                    continue

                if node.level == 0:
                    base_module = node.module
                    imported_layer = _imported_layer(base_module)
                    if imported_layer is None:
                        continue
                    if not _is_allowed(layer, imported_layer):
                        violations.append(
                            f"{py_file.relative_to(SRC_ROOT)}:{node.lineno} "
                            f"from {node.module} import …  (layer '{layer}' → '{imported_layer}')"
                        )
                else:
                    resolved = _resolve_relative_import(py_file, node)
                    if resolved is None:
                        continue
                    imported_layer = _imported_layer(resolved)
                    if imported_layer is None:
                        continue
                    if not _is_allowed(layer, imported_layer):
                        violations.append(
                            f"{py_file.relative_to(SRC_ROOT)}:{node.lineno} "
                            f"relative import → {resolved}  (layer '{layer}' → '{imported_layer}')"
                        )

    assert not violations, (
        "Import boundary violations detected:\n" + "\n".join(violations)
    )
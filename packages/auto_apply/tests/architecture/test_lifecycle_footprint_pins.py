"""RATCHET pins for the lifecycle footprint: within the lifecycle-critical
file set, no NEW write-outside-the-authority site may appear.

Scope honesty: the full-tree census lives in AA_MASTER_TODO's measurements;
this pin covers the files the lifecycle feature owns or touches (the paths
authority, the entry point, the composition root, the one known outside
writer, the consent/purge path, and the new lifecycle modules). Widening
the set to the whole tree is turn-2/3 work, done with the tree visible —
each pre-existing site then gets an entry with a reason, per the exemption
precedent.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "auto_apply"

#: The lifecycle-critical file set, repo-relative to src/auto_apply.
LIFECYCLE_FILES: tuple[str, ...] = (
    "main.py",
    "domain/config.py",
    "infrastructure/composition_root.py",
    "adapters/secondary/browser/selenium_provider.py",
    "application/services/research_consent.py",
    "adapters/secondary/research/sqlite_consent_repository.py",
    "application/services/footprint_ledger.py",
    "application/services/instance_registry.py",
    "application/services/uninstall/__init__.py",
    "application/services/uninstall/model.py",
    "application/services/uninstall/scoping.py",
    "application/services/uninstall/guarded_delete.py",
    "application/services/uninstall/finisher.py",
    "application/services/uninstall/engine.py",
    "application/services/install/__init__.py",
    "application/services/install/bootstrap_pins.py",
    "application/services/install/manifest.py",
    "application/services/install/engine.py",
    "application/services/lifecycle_wording.py",
    "adapters/primary/cli/lifecycle_screen.py",
    "adapters/primary/gui/lifecycle_window.py",
)

#: Exact inventories. A new site fails; removing one fails until the map is
#: updated in the same change — the count moves on purpose, never by drift.
#: Exactly one legitimate site, declared (D11): install/engine.py's
#: default_root() computes the default install root's home — it cannot be
#: eliminated, only moved, so it is recorded with its reason and every
#: OTHER site fails.
EXPECTED_PATH_HOME: dict[str, int] = {"application/services/install/engine.py": 1}
EXPECTED_EXPANDUSER: dict[str, int] = {
    "main.py": 4,
    "adapters/primary/cli/lifecycle_screen.py": 1,
}
EXPECTED_ENVIRON_SETITEM: dict[str, int] = {"main.py": 4}
EXPECTED_ENVIRON_SETDEFAULT: dict[str, int] = {"domain/config.py": 2}
EXPECTED_MKDTEMP: dict[str, int] = {"application/services/uninstall/finisher.py": 1}


def _dotted(expr: ast.expr) -> str:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        base = _dotted(expr.value)
        return f"{base}.{expr.attr}" if base else expr.attr
    if isinstance(expr, ast.Call):
        return _dotted(expr.func)
    return ""


def _scan() -> dict[str, dict[str, int]]:
    found: dict[str, dict[str, int]] = {
        "home": {},
        "expanduser": {},
        "setitem": {},
        "setdefault": {},
        "mkdtemp": {},
    }
    for rel in LIFECYCLE_FILES:
        path = SRC / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _dotted(node.func)
                if name == "Path.home":
                    found["home"][rel] = found["home"].get(rel, 0) + 1
                elif name.endswith(".expanduser"):
                    found["expanduser"][rel] = found["expanduser"].get(rel, 0) + 1
                elif name == "os.environ.setdefault":
                    found["setdefault"][rel] = found["setdefault"].get(rel, 0) + 1
                elif name == "tempfile.mkdtemp":
                    found["mkdtemp"][rel] = found["mkdtemp"].get(rel, 0) + 1
            elif isinstance(node, ast.Subscript) and _dotted(node.value) == "os.environ":
                if isinstance(node.ctx, ast.Store):
                    found["setitem"][rel] = found["setitem"].get(rel, 0) + 1
    return found


def test_no_path_home_sites_in_lifecycle_files() -> None:
    """RATCHET: exactly one declared site (the default install root's home
    computation); any OTHER Path.home() in the set fails. RED before the
    lifecycle work: selenium_provider.py:523 had one (fixed, turn 1)."""
    assert _scan()["home"] == EXPECTED_PATH_HOME


def test_expanduser_inventory_is_exact() -> None:
    """RATCHET: user-input expansion only, exactly where known (three CLI
    handlers plus the uninstall helper)."""
    assert _scan()["expanduser"] == EXPECTED_EXPANDUSER


def test_environ_write_inventory_is_exact() -> None:
    """RATCHET: env mutation sites — pre-import path redirection and the two
    containment setdefaults — cannot grow silently."""
    scan = _scan()
    assert scan["setitem"] == EXPECTED_ENVIRON_SETITEM
    assert scan["setdefault"] == EXPECTED_ENVIRON_SETDEFAULT


def test_tempdir_staging_site_is_the_finisher_alone() -> None:
    """RATCHET: the OS temp dir is staging for the detached finisher only."""
    assert _scan()["mkdtemp"] == EXPECTED_MKDTEMP


def test_the_scan_is_not_passing_vacuously() -> None:
    """GUARD: the scan must find its known sites, or every ratchet above is
    green because the instrument broke."""
    scan = _scan()
    assert scan["setdefault"] == EXPECTED_ENVIRON_SETDEFAULT
    assert scan["setitem"] == EXPECTED_ENVIRON_SETITEM
    assert scan["expanduser"] == EXPECTED_EXPANDUSER
    assert scan["mkdtemp"] == EXPECTED_MKDTEMP

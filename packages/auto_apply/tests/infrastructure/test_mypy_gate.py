"""P1 mypy gate — type correctness enforced across src/ and tests/.

Two gates, deliberately split:
    test_mypy_src_passes    — the production tree (src/auto_apply)
    test_mypy_tests_passes  — the test tree (MagicMock-heavy; its own
                              population of findings, kept visible separately)

Both run mypy with the workspace-root pyproject.toml (strict=false,
ignore_missing_imports=true). To reproduce manually from packages/auto_apply:
    python -m mypy --config-file ../../pyproject.toml src/auto_apply
    python -m mypy --config-file ../../pyproject.toml tests

If mypy is not installed in the active interpreter, the failure says so with
an install hint instead of presenting as type errors (mirrors the ruff gate).

Also in this file: two structural pins guarding the P1 constructor promotion
itself, so a future refactor cannot silently reintroduce the monkey-patching
the stage removed.
"""
from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]  # <root>/packages/... -> <root>
_CONFIG = _REPO_ROOT / "pyproject.toml"
_SRC_DIR = _REPO_ROOT / "packages" / "auto_apply" / "src" / "auto_apply"
_TESTS_DIR = _REPO_ROOT / "packages" / "auto_apply" / "tests"


def _run_mypy(target: Path) -> subprocess.CompletedProcess:
    assert _CONFIG.is_file(), (
        f"workspace pyproject.toml not found at {_CONFIG} — the gate expects "
        f"the repo layout <root>/packages/auto_apply"
    )
    cmd = [
        sys.executable, "-m", "mypy",
        "--config-file", str(_CONFIG),
        "--explicit-package-bases",
        str(target),
    ]
    return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")


def _assert_clean(result: subprocess.CompletedProcess, label: str) -> None:
    if result.returncode == 0:
        return
    if "No module named mypy" in result.stderr:
        raise AssertionError(
            "mypy is not installed in this interpreter — the gate cannot run. "
            "Install it with: uv sync --group dev  (or: pip install mypy)\n"
            "stderr was:\n" + result.stderr
        )
    raise AssertionError(
        "mypy found type errors in " + label + ":\n"
        + result.stdout + "\n" + result.stderr
    )


# --------------------------------------------------------------------------
# The gates (teeth: red on the pre-fix tree with the port-contract errors)
# --------------------------------------------------------------------------

def test_mypy_src_passes() -> None:
    _assert_clean(_run_mypy(_SRC_DIR), "src/auto_apply")


def test_mypy_tests_passes() -> None:
    _assert_clean(_run_mypy(_TESTS_DIR), "tests/")


# --------------------------------------------------------------------------
# Structural pins for the P1 constructor promotion (teeth pre-stage)
# --------------------------------------------------------------------------

def test_session_plan_is_a_required_constructor_param() -> None:
    """session_plan must be a required AgentOrchestrator.__init__ parameter.

    Pre-stage it is absent from the signature entirely (it was monkey-patched
    onto the instance after construction) -> this fails. Post-stage it is
    present with NO default, which is what kills the _session_cap_reached
    None-trap structurally.
    """
    from auto_apply.application.agent.orchestrator import AgentOrchestrator

    params = inspect.signature(AgentOrchestrator.__init__).parameters
    assert "session_plan" in params, (
        "session_plan is not an __init__ parameter — it is still being "
        "monkey-patched after construction"
    )
    assert params["session_plan"].default is inspect.Parameter.empty, (
        "session_plan has a default value — the None branch of "
        "_session_cap_reached is armed again. It must be required."
    )


def test_no_post_construction_patching_in_composition_root() -> None:
    """composition_root must not assign orchestrator attributes after build."""
    import auto_apply

    cr = (
        Path(auto_apply.__file__).resolve().parent
        / "infrastructure"
        / "composition_root.py"
    )
    src = cr.read_text(encoding="utf-8")
    for forbidden in (
        "orchestrator.session_plan =",
        "orchestrator.behavior_parameters =",
        "orchestrator._workflows =",
    ):
        assert forbidden not in src, (
            "post-construction monkey-patching survived in "
            "composition_root.py: " + repr(forbidden) + ". Pass the value "
            "through the constructor instead."
        )

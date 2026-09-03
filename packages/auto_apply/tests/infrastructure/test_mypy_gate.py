"""P1 mypy gate — type correctness enforced across src/ and tests/.

Two gates, deliberately split, with deliberately DIFFERENT invocations:

    test_mypy_src_passes    — the production tree (src/auto_apply), run
                              WITHOUT --explicit-package-bases.
    test_mypy_tests_passes  — the test tree (tests/), run WITH it.

Why the invocations differ (this asymmetry is the fix for the blind-gate
defect; do not "unify" it):

    * ``--explicit-package-bases`` makes mypy name modules from the
      command-line path instead of discovering the package root.  Pointed
      at ``src/auto_apply`` it names modules ``src.auto_apply.*`` while
      every import in the code says ``auto_apply.*`` — every internal
      cross-module import goes unresolved, and under
      ``ignore_missing_imports`` the unresolved names are typed ``Any``.
      Measured on the same 260 files: WITH the flag, ``Success: no issues
      found in 260 source files``; WITHOUT it, 69 errors in 31 files.
      The gate was green for weeks because it could not see.  The
      blindness canary in this file exists to catch that class returning.

    * The tests/ tree needs the flag for the opposite reason: it contains
      seven ``conftest.py`` files and no package ``__init__.py`` at its
      root, so without explicit package bases mypy reports
      "Duplicate module named conftest".  The flag disambiguates them.

KNOWN WEAKNESS (tests/ gate): the flag is load-bearing there, and under it
test-module naming is synthetic and cross-module resolution of test helpers is weaker
than in src/.  It is green but shallow.  Do not read a green tests/ gate as the same strength
of guarantee as a green src/ gate.

To reproduce manually from packages/auto_apply:
    python -m mypy --config-file ../../pyproject.toml src/auto_apply
    python -m mypy --config-file ../../pyproject.toml --explicit-package-bases tests

If mypy is not installed in the active interpreter, the failure says so with an install
hint instead of presenting as type errors (mirrors the ruff gate).

Also in this file: two structural pins guarding the P1 constructor promotion itself, so a
future refactor cannot silently reintroduce the monkey-patching the stage removed, and
the blindness canary that keeps the gate sighted.
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]  # <root>/packages/... -> <root>
_CONFIG = _REPO_ROOT / "pyproject.toml"
_SRC_DIR = _REPO_ROOT / "packages" / "auto_apply" / "src" / "auto_apply"
_TESTS_DIR = _REPO_ROOT / "packages" / "auto_apply" / "tests"


def _run_mypy(target: Path, *, explicit_package_bases: bool) -> subprocess.CompletedProcess:
    """Run mypy over *target* with the workspace config.

    ``explicit_package_bases`` is required for the tests/ tree (seven
    conftest.py files collide without it) and is fatal to the src/ tree
    (it renames modules ``src.auto_apply.*``, orphaning every ``auto_apply.*``
    import into Any).  The asymmetry is deliberate — see the module docstring.
    """
    assert _CONFIG.is_file(), (
        f"workspace pyproject.toml not found at {_CONFIG} — the gate expects "
        f"the repo layout <root>/packages/auto_apply"
    )
    cmd = [
        sys.executable, "-m", "mypy",
        "--config-file", str(_CONFIG),
    ]
    if explicit_package_bases:
        cmd.append("--explicit-package-bases")
    cmd.append(str(target))
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
# The gates (teeth: red on the current tree with the 69 findings — that is
# the success condition of the sighting stage, not a regression)
# --------------------------------------------------------------------------

def test_mypy_src_passes() -> None:
    _assert_clean(_run_mypy(_SRC_DIR, explicit_package_bases=False), "src/auto_apply")


def test_mypy_tests_passes() -> None:
    _assert_clean(_run_mypy(_TESTS_DIR, explicit_package_bases=True), "tests/")


# --------------------------------------------------------------------------
# The blindness canary — the gate must not be able to slip back to silent
# green.  One pin, behavioural, because a structural check on the invocation
# would only re-assert what this file already says.
# --------------------------------------------------------------------------

def test_src_gate_resolves_internal_imports() -> None:
    """A deliberately wrong cross-module call must be reported by the src gate.

    The blind-gate failure mode: a bad invocation
    (``--explicit-package-bases`` on src/) names modules ``src.auto_apply.*``,
    every ``auto_apply.*`` import goes unresolved, and
    ``ignore_missing_imports`` types them ``Any`` — silencing every
    cross-module error while the gate reports green.  When that happens the canary's
    deliberate error below is invisible and this pin fails while
    ``test_mypy_src_passes`` still passes — exactly the false green this file exists to
    prevent.

    The probe goes through the gate's own invocation (`_run_mypy(_SRC_DIR, ...)`, not a
    synthetic path setup, so a regression of the gate's own command is what fails.
    """
    canary = _SRC_DIR / f"_type_gate_canary_{os.getpid()}.py"
    canary.write_text(
        "from auto_apply.domain.models.job import Job\n"
        "\n"
        "\n"
        "def _probe(job: Job) -> int:\n"
        "    return job.url\n",
        encoding="utf-8",
    )
    try:
        result = _run_mypy(_SRC_DIR, explicit_package_bases=False)
        output = result.stdout
        assert canary.stem in output and "Incompatible return value type" in output, (
            "the src gate did not report a deliberate cross-module type error "
            "— internal imports are resolving to Any (the blind-gate failure mode). "
            "Output was:\n" + result.stdout[:2000]
        )
    finally:
        canary.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# Structural pins for the P1 constructor promotion (kept verbatim from P1)
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

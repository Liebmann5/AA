"""GUARD pin — the CI workflow must keep every gate and the full OS matrix.

Pin label: GUARD, not teeth. This pin landed with the workflow it watches,
so it has never caught a missing gate. Its job is to fail when the next
person adds a gate locally and forgets to add it here, or trims an OS from
the matrix to make a red leg go away quietly. Both are instance #4 of the
root defect class — a gate that is green because it cannot see — expressed
in YAML instead of Python.

It parses the workflow as YAML (pyyaml is a core dependency), never as
substrings: RV-6 records that substring pins are how this project let gates
drift before.
"""
from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

_EXPECTED_OSES = {"ubuntu-latest", "windows-latest", "macos-latest"}
_EXPECTED_PYTHONS = {"3.10", "3.12"}
_PACKAGE_DIR = "packages/auto_apply"


def _load_workflow() -> dict:
    if not _WORKFLOW.is_file():
        pytest.fail(
            f"CI workflow is missing: {_WORKFLOW}. Without it the four gates "
            "run only when a human remembers — that has failed twice, "
            "expensively. Restore the file; do not weaken this pin."
        )
    with _WORKFLOW.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or "jobs" not in data:
        pytest.fail(f"{_WORKFLOW} is not a parseable GitHub Actions workflow.")
    return data


def _gates_job(data: dict) -> dict:
    jobs = data.get("jobs") or {}
    for job in jobs.values():
        strategy = (job or {}).get("strategy") or {}
        if isinstance(strategy.get("matrix"), dict) and "os" in strategy["matrix"]:
            return job
    pytest.fail("no job with an OS matrix found in ci.yml")
    raise AssertionError("unreachable")


def _run_steps(job: dict) -> list[dict]:
    return [
        step
        for step in (job.get("steps") or [])
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    ]


def test_matrix_covers_all_three_operating_systems() -> None:
    job = _gates_job(_load_workflow())
    oses = {str(o) for o in job["strategy"]["matrix"].get("os", [])}
    assert _EXPECTED_OSES <= oses, (
        f"matrix is missing operating systems: {sorted(_EXPECTED_OSES - oses)}. "
        "AA accommodates every user; CI does not get to choose which operating "
        "systems contributors are allowed to have."
    )


def test_matrix_exercises_the_python_floor_and_the_mypy_config_version() -> None:
    job = _gates_job(_load_workflow())
    pythons = {str(p) for p in job["strategy"]["matrix"].get("python", [])}
    assert _EXPECTED_PYTHONS <= pythons, (
        f"matrix is missing Python versions: {sorted(_EXPECTED_PYTHONS - pythons)}. "
        "3.10 is the requires-python floor and ruff is the only thing holding "
        "it; 3.12 is the mypy config's python_version. Both must be exercised."
    )


def test_fail_fast_is_disabled() -> None:
    job = _gates_job(_load_workflow())
    assert job["strategy"].get("fail-fast") is False, (
        "fail-fast must be disabled so one OS-specific failure does not hide "
        "the other legs' results."
    )


def test_all_four_gates_are_present_as_separately_named_steps() -> None:
    steps = _run_steps(_gates_job(_load_workflow()))
    gates = {
        "pytest suite": "pytest tests",
        "ruff F821": "ruff check src --select F821",
        "mypy src/": "mypy --config-file ../../pyproject.toml src/auto_apply",
        "mypy tests/": "--explicit-package-bases tests",
    }
    for gate, needle in gates.items():
        matching = [s for s in steps if needle in s["run"]]
        assert matching, (
            f"gate {gate!r} is missing from ci.yml (looked for {needle!r} in a "
            "step's run command). A gate that exists only locally is a gate "
            "that does not exist."
        )
        assert all(str(s.get("name", "")).strip() for s in matching), (
            f"gate {gate!r} has no step name — the failing gate must be "
            "identifiable from the run list without opening a log."
        )


def test_pytest_invocation_matches_the_canonical_local_command() -> None:
    steps = _run_steps(_gates_job(_load_workflow()))
    pytest_steps = [s for s in steps if "pytest" in s["run"]]
    assert len(pytest_steps) == 1, (
        f"expected exactly one pytest step, found {len(pytest_steps)}."
    )
    command = pytest_steps[0]["run"]
    assert "pytest tests -q -p no:cacheprovider" in command, (
        "the CI pytest invocation must match the documented local command "
        "argument-for-argument; anything else is a second invocation contract."
    )
    assert "-rs" in command, (
        "-rs is required so the per-job skip count is visible; a silent change "
        "in what CI exercises must show up in the log, not be absorbed."
    )


def test_mypy_invocations_are_asymmetric_by_design() -> None:
    steps = _run_steps(_gates_job(_load_workflow()))
    mypy_steps = [s for s in steps if "mypy" in s["run"]]
    assert len(mypy_steps) == 2, (
        f"expected exactly two mypy steps (src/ and tests/), found {len(mypy_steps)}. "
        "Do not 'tidy' the two invocations into one — the asymmetry is deliberate."
    )
    src_steps = [s for s in mypy_steps if "src/auto_apply" in s["run"]]
    tests_steps = [s for s in mypy_steps if "src/auto_apply" not in s["run"]]
    assert src_steps, "no mypy step targets src/auto_apply"
    assert tests_steps, "no mypy step targets tests/"
    assert "--explicit-package-bases" not in src_steps[0]["run"], (
        "src/ must run WITHOUT --explicit-package-bases — that flag renamed "
        "every module to src.auto_apply.* and blinded the gate for weeks."
    )
    assert "--explicit-package-bases" in tests_steps[0]["run"], (
        "tests/ must run WITH --explicit-package-bases; dropping it fails on "
        "'Duplicate module named conftest'."
    )
    for step in mypy_steps:
        assert "--config-file ../../pyproject.toml" in step["run"], (
            "both mypy invocations must use the workspace-root pyproject.toml."
        )


def test_uv_is_the_installer_never_pip() -> None:
    steps = _run_steps(_gates_job(_load_workflow()))
    assert any("uv sync" in s["run"] for s in steps), (
        "no 'uv sync' step found. hypothesis, mypy, ruff and pytest-mock are "
        "PEP 735 dependency groups; pip cannot install them and collection "
        "aborts rather than skips."
    )
    offenders = [s.get("name", "<unnamed>") for s in steps if "pip install" in s["run"]]
    assert not offenders, f"pip install found in CI step(s): {offenders}"


def test_every_gate_step_runs_from_the_package_directory() -> None:
    steps = _run_steps(_gates_job(_load_workflow()))
    gate_markers = ("pytest", "ruff", "mypy")
    gate_steps = [s for s in steps if any(m in s["run"] for m in gate_markers)]
    assert gate_steps, "no gate steps found"
    wrong = [
        s.get("name", "<unnamed>")
        for s in gate_steps
        if s.get("working-directory") != _PACKAGE_DIR
    ]
    assert not wrong, (
        f"gate steps must run from {_PACKAGE_DIR} (the canonical local command "
        f"runs there); offenders: {wrong}"
    )

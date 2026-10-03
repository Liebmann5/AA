"""GUARD pin — the release workflow keeps least privilege and attests exactly
what G1 names.

Landed with the workflow it watches, so GUARD, not teeth. Its job is to fail
when someone widens permissions to make an error go away, adds a pull_request
trigger, drops the version gate, or attests a file G1 did not name — the same
defect class as test_ci_workflow.py (a gate that is green because it cannot
see), expressed in YAML. Parsed as YAML (pyyaml is a core dependency), never
substring-matched.
"""
from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "release.yml"

#: Exactly the subjects G1 names: the built distribution and the two replay
#: result files. environment.json is deliberately NOT attested — it is not
#: part of the replay result (part A, item 7's ruling).
_EXPECTED_SUBJECTS = {
    "packages/auto_apply/dist/*",
    "packages/auto_apply/replay_out/replay.jsonl",
    "packages/auto_apply/replay_out/manifest.json",
}

#: uses: refs must be a version tag (vN...) or a full commit SHA — never a
#: branch name, which moves under the pin.
_ACTION_REF = re.compile(r"@(v\d[\w.\-]*|[0-9a-f]{40})$")


def _load() -> dict:
    if not _WORKFLOW.is_file():
        pytest.fail(
            f"release workflow is missing: {_WORKFLOW}. Without it, nothing "
            "ties a published result to the code that made it (item 10, B1)."
        )
    with _WORKFLOW.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or "jobs" not in data:
        pytest.fail(f"{_WORKFLOW} is not a parseable GitHub Actions workflow.")
    return data


def _trigger(data: dict) -> dict:
    # YAML 1.1 parses the bare key `on` as the boolean True.
    return data.get("on") or data.get(True) or {}


def _jobs(data: dict) -> dict:
    return data.get("jobs") or {}


def _run_steps(job: dict) -> list[dict]:
    return [
        s
        for s in job.get("steps") or []
        if isinstance(s, dict) and isinstance(s.get("run"), str)
    ]


def _attest_steps(job: dict) -> list[dict]:
    return [
        s
        for s in job.get("steps") or []
        if isinstance(s, dict) and "attest-build-provenance" in str(s.get("uses", ""))
    ]


def _needs(job: dict) -> set[str]:
    needs = job.get("needs") or []
    return {needs} if isinstance(needs, str) else set(needs)


def test_trigger_is_a_published_release_and_never_a_pull_request() -> None:
    """GUARD (G2): id-token: write must never be reachable from PR code."""
    trigger = _trigger(_load())
    assert set(trigger) == {"release"}, (
        f"release.yml triggers on {sorted(map(str, trigger))}; it must trigger "
        "ONLY on a published release — a pull_request trigger would hand the "
        "signing identity to fork code."
    )
    assert trigger["release"].get("types") == ["published"]


def test_top_level_permissions_are_empty_and_every_job_declares_its_own() -> None:
    data = _load()
    assert data.get("permissions") in (None, {}), (
        "top-level permissions must be empty; least privilege is per job"
    )
    for name, job in _jobs(data).items():
        assert isinstance(job.get("permissions"), dict) and job["permissions"], (
            f"job {name!r} declares no permissions block — permissions must "
            "be per job, explicit, and minimal"
        )


def test_least_privilege_per_job() -> None:
    """GUARD: id-token: write only where attesting; contents: write only
    where uploading to the release; nothing else holds either."""
    for name, job in _jobs(_load()).items():
        perms = job["permissions"]
        if _attest_steps(job):
            assert perms.get("id-token") == "write", name
            assert perms.get("attestations") == "write", name
        else:
            assert perms.get("id-token") != "write", (
                f"job {name!r} holds id-token: write without attesting anything"
            )
        uploads = any("gh release upload" in s["run"] for s in _run_steps(job))
        if uploads:
            assert perms.get("contents") == "write", name
        else:
            assert perms.get("contents") != "write", (
                f"job {name!r} holds contents: write without uploading to the release"
            )


def test_the_version_gate_exists_and_blocks_every_attesting_job() -> None:
    """GUARD (G4): the release fails BEFORE attesting when the tag and the
    package version disagree — the step must exist and every attesting job
    must declare needs: on it."""
    jobs = _jobs(_load())
    gate = None
    for name, job in jobs.items():
        for step in _run_steps(job):
            if "CITATION.cff" in step["run"] and "TAG_NAME" in step["run"]:
                gate = name
    assert gate is not None, (
        "no step compares the tag against pyproject and CITATION.cff — a "
        "release could publish on a version disagreement"
    )
    for name, job in jobs.items():
        if _attest_steps(job):
            assert gate in _needs(job), (
                f"job {name!r} attests without needs: {gate} — it must be "
                "impossible to attest after a failed version check"
            )


def test_the_replay_step_compares_against_the_committed_expected_digest() -> None:
    """GUARD: the attestation must sign bytes something checked."""
    compares = [
        s["run"]
        for job in _jobs(_load()).values()
        for s in _run_steps(job)
        if "tests/fixtures/replay/expected" in s["run"] and "replay_out" in s["run"]
    ]
    assert compares, (
        "no step compares the regenerated replay output against "
        "tests/fixtures/replay/expected — the attestation would sign bytes "
        "nothing checked"
    )


def test_attest_steps_cover_exactly_the_g1_subjects() -> None:
    """GUARD (G1): the attested subject set is exactly what was ruled on —
    no more (unruled claims), no less (an unsigned named claim)."""
    subjects = {
        str((s.get("with") or {}).get("subject-path"))
        for job in _jobs(_load()).values()
        for s in _attest_steps(job)
    }
    assert subjects == _EXPECTED_SUBJECTS, (
        f"attested subjects {sorted(subjects)} != G1's "
        f"{sorted(_EXPECTED_SUBJECTS)}"
    )


def test_actions_are_pinned_to_a_tag_or_sha_never_a_branch() -> None:
    """GUARD: a branch ref moves under the workflow; tags and SHAs do not."""
    offenders = []
    for name, job in _jobs(_load()).items():
        for step in job.get("steps") or []:
            uses = step.get("uses") if isinstance(step, dict) else None
            if uses and not _ACTION_REF.search(str(uses)):
                offenders.append(f"{name}: {uses}")
    assert not offenders, (
        f"actions referenced by a moving ref: {offenders}. Use a version tag "
        "or a full commit SHA."
    )


def test_the_build_writes_dist_where_the_attestation_looks() -> None:
    """TEETH (V9): bare `uv build` in a workspace member writes to the
    WORKSPACE ROOT's dist/ (measured, uv 0.8.17) — the attest glob and the
    upload glob would match nothing. RED against the first release.yml."""
    builds = [
        s["run"]
        for job in _jobs(_load()).values()
        for s in _run_steps(job)
        if "uv build" in s["run"]
    ]
    assert builds, "no uv build step found"
    assert all("--out-dir dist" in b for b in builds), (
        "uv build must be given --out-dir dist, or the attested path "
        "packages/auto_apply/dist/* is empty"
    )


def test_replay_outputs_are_regenerated_by_the_reader_not_uploaded() -> None:
    """GUARD (V10, ruled): the workflow does NOT upload replay outputs to
    the release. The reader regenerates them with --replay over the tagged
    corpus and verifies their own machine's bytes — strictly stronger than
    downloading ours, and the runbook says so."""
    uploads = [
        s["run"]
        for job in _jobs(_load()).values()
        for s in _run_steps(job)
        if "gh release upload" in s["run"]
    ]
    assert uploads, "no release-upload step found"
    assert all("replay_out" not in u for u in uploads), (
        "replay outputs must not be uploaded; the reader reproduces the "
        "attested digest on their own machine"
    )

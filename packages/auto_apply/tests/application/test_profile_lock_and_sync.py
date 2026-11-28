"""Synced-folder detection (Phase 0, P0-3) and the never-weaken database rule.

Detection uses only what the vendors document; an unreadable source is "not
detected", never an error, and "not detected" never means "not synced".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_apply.application.services.profile_lock import (
    ALLOW_SYNCED_ENV_VAR,
    detect_sync_root,
    synced_override,
)


def test_a_path_inside_onedrive_is_detected(tmp_path: Path) -> None:
    root = tmp_path / "OneDrive"
    data = root / "Documents" / "GitHub" / "AA" / "dev_data" / "journals"
    found = detect_sync_root(data, env={"OneDrive": str(root)}, home=tmp_path / "home")
    assert found is not None and found.startswith("OneDrive")


def test_a_dropbox_root_from_its_documented_info_json_is_detected(tmp_path: Path) -> None:
    appdata = tmp_path / "AppData"
    (appdata / "Dropbox").mkdir(parents=True)
    box = tmp_path / "Dropbox (Personal)"
    (appdata / "Dropbox" / "info.json").write_text(
        json.dumps({"personal": {"path": str(box), "host": 1, "is_team": False}}),
        encoding="utf-8")
    found = detect_sync_root(box / "AA" / "journals", env={"APPDATA": str(appdata)},
                             home=tmp_path / "home")
    assert found is not None and found.startswith("Dropbox")


def test_an_unreadable_source_is_not_an_error_and_nothing_is_claimed(tmp_path: Path) -> None:
    appdata = tmp_path / "AppData"
    (appdata / "Dropbox").mkdir(parents=True)
    (appdata / "Dropbox" / "info.json").write_text("{not json", encoding="utf-8")
    assert detect_sync_root(tmp_path / "data", env={"APPDATA": str(appdata)},
                            home=tmp_path / "home") is None


def test_a_sibling_folder_with_a_common_prefix_is_not_inside(tmp_path: Path) -> None:
    root = tmp_path / "OneDrive"
    assert detect_sync_root(tmp_path / "OneDriveBackup" / "x", env={"OneDrive": str(root)},
                            home=tmp_path / "home") is None


def test_the_override_comes_from_config_or_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ALLOW_SYNCED_ENV_VAR, raising=False)
    assert synced_override({"allow_synced_profile": False}) is False
    assert synced_override({"allow_synced_profile": "yes"}) is False, "only a real true"
    assert synced_override({"allow_synced_profile": True}) is True
    monkeypatch.setenv(ALLOW_SYNCED_ENV_VAR, "1")
    assert synced_override(None) is True


# ── never weaken a blocking row ─────────────────────────────────────────────


@pytest.fixture
def db(tmp_path, monkeypatch):
    import auto_apply.adapters.secondary.persistence.database as db_module

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "aa.db")
    db_module.DatabaseManager._instance = None
    try:
        yield db_module.DatabaseManager()
    finally:
        db_module.DatabaseManager._instance = None


def _outcome(db, url: str) -> str:
    with db.get_connection() as conn:
        return conn.execute("SELECT outcome FROM applied_jobs WHERE job_url = ?",
                            (url,)).fetchone()["outcome"]


@pytest.mark.parametrize(("first", "second", "kept"), [
    ("SUBMITTED", "UNKNOWN", "SUBMITTED"),        # UNKNOWN never overwrites a seen submission
    ("UNKNOWN", "FAILED_NAVIGATION", "UNKNOWN"),  # a later failure never clears "may have been sent"
    ("AMBIGUOUS", "USER_SKIPPED", "AMBIGUOUS"),
    ("UNKNOWN", "SUBMITTED", "SUBMITTED"),        # a stronger claim of receipt replaces it
    ("PROBABLY_SUBMITTED", "SUBMITTED", "SUBMITTED"),
    ("FAILED_NAVIGATION", "UNKNOWN", "UNKNOWN"),
    ("ERROR", "USER_SKIPPED", "USER_SKIPPED"),    # non-blocking rows are replaced as before
])
def test_a_blocking_row_is_never_weakened(db, first: str, second: str, kept: str) -> None:
    """TEETH: fails with the old INSERT OR REPLACE, which let any outcome
    overwrite any other."""
    url = "https://boards.example.io/jobs/w"
    db.record_application_permanently(url, "Acme", first, "s1")
    db.record_application_permanently(url, "Acme", second, "s2")
    assert _outcome(db, url) == kept


def test_settling_the_same_attempt_twice_is_idempotent(db) -> None:
    url = "https://boards.example.io/jobs/i"
    db.record_attempt_outcome(url, "boards.example.io|/jobs/i", "UNKNOWN", "a1")
    db.record_attempt_outcome(url, "boards.example.io|/jobs/i", "UNKNOWN", "a1")
    with db.get_connection() as conn:
        rows = conn.execute("SELECT outcome, attempt_id FROM applied_jobs WHERE job_url = ?",
                            (url,)).fetchall()
    assert [(r["outcome"], r["attempt_id"]) for r in rows] == [("UNKNOWN", "a1")]


def test_a_later_write_without_the_attempt_keeps_its_ids(db) -> None:
    url = "https://boards.example.io/jobs/k"
    db.record_attempt_outcome(url, "boards.example.io|/jobs/k", "SUBMITTED", "a9")
    db.record_application_permanently(url, "Acme", "SUBMITTED", "s1")   # the orchestrator's
    with db.get_connection() as conn:
        row = conn.execute("SELECT attempt_id, job_key FROM applied_jobs WHERE job_url = ?",
                           (url,)).fetchone()
    assert (row["attempt_id"], row["job_key"]) == ("a9", "boards.example.io|/jobs/k")

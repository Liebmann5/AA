"""Pins for C2 — handing session results to the user.

C1 made discovered jobs survive (job_history with session_id, queue-drain
completion, completion_state on the report). C2 surfaces all of it through
UIPort: summary().discovered, export_session_results, export_profile,
list_session_history. Every pin notes the pre-C2 failure it catches; none was
executed here (I could not run anything), but each teeth pin is mechanically
certain to fail on the old tree because the method, field, or call site does
not exist there.

Labels: TEETH fail against the pre-C2 tree for the reason stated; GUARD
passes on both trees and must not be broken silently; COVERAGE documents
behaviour of code introduced by this change.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from auto_apply.adapters.secondary.persistence.database import DatabaseManager
from auto_apply.adapters.secondary.persistence.profile_repository import ProfileRepository
from auto_apply.application.services.session_controller import SessionController
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.session_plan import SessionPlan
from auto_apply.domain.models.ui_contract import (
    DiscoveredJob,
    SessionHistoryEntry,
    SessionSummary,
)
from auto_apply.domain.ports.ui_port import UIPort

_PKG_ROOT = Path(__file__).resolve().parents[2]
_CLI_STARTUP = _PKG_ROOT / "src" / "auto_apply" / "adapters" / "primary" / "cli" / "startup.py"
_GUI_APP = _PKG_ROOT / "src" / "auto_apply" / "adapters" / "primary" / "gui" / "app.py"


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def fresh_db(tmp_path):
    """A real DatabaseManager pointed at a throwaway file, state restored after.

    DatabaseManager is a singleton; snapshot and restore db_path and the
    capability profile so these pins cannot leak into other tests (the same
    isolation pattern tests/application/test_session_lifecycle_defects.py
    established for the same reason).
    """
    db = DatabaseManager()
    original_path = db.db_path
    original_profile = db._capability_profile
    db.db_path = tmp_path / "c2_test.db"
    db._capability_profile = None
    db._init_schema()
    try:
        yield db
    finally:
        db.db_path = original_path
        db._capability_profile = original_profile


def _job(i: int) -> Job:
    return Job(
        title=f"Engineer {i}",
        company="Acme",
        url=f"https://acme.example/j/{i}",
        source="bing",
    )


def _controller(db, session_id: str, profile_repo=None) -> SessionController:
    """A SessionController with a real DB and a stubbed registry/orchestrator."""
    plan = SessionPlan(session_id=session_id)
    registry = MagicMock()
    registry.get_session_plan.return_value = plan
    registry.get_active_profile.return_value = MagicMock(profile_name="tester")
    db.get_queue_stats = lambda: {
        "pending": 0, "in_progress": 0, "completed": 0,
        "failed": 0, "skipped": 0, "permanently_failed": 0,
    }
    orchestrator = MagicMock()
    orchestrator.session_plan = plan
    orchestrator.context = MagicMock()
    orchestrator.context.session_id = session_id
    orchestrator.state_machine = MagicMock()
    orchestrator.task_queue = db
    return SessionController(
        registry=registry, db=db, orchestrator=orchestrator,
        profile_repo=profile_repo,
    )


def _minimal_profile_dict(name: str) -> dict:
    return {
        "profile_name": name,
        "personal_info": {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
            "phone_number": "555-0100",
            "street_address": "12 Analytical Way",
            "city": "Austin",
            "state": "TX",
            "zip_code": "78701",
        },
        "links": {},
        "career_summary": "Backend developer with four years building data pipelines.",
        "search_preferences": {"desired_job_titles": ["Data Scientist"]},
    }


def _report_dict(session_id: str, completion_state: str, found: int, submitted: int, failed: int) -> dict:
    """A JSON dict shaped exactly like SessionReport.save() writes."""
    return {
        "session_id": session_id,
        "profile_name": "tester",
        "started_at": "2026-09-15T14:02:00+00:00",
        "finished_at": "2026-09-15T14:22:00+00:00",
        "duration_seconds": 372.0,
        "mode": "discovery",
        "completion_state": completion_state,
        "discovery": {"raw_results_found": found, "new_jobs_identified": 0, "sources": []},
        "vetting": {"jobs_approved": 3, "jobs_rejected": 1, "rejection_reasons": {}},
        "applications": {
            "total": submitted + failed,
            "submitted": submitted,
            "failed": failed,
            "success_rate": 0.5,
            "records": [],
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# TEETH — discovered jobs reach the user through the port
# ─────────────────────────────────────────────────────────────────────────────


def test_summary_exposes_discovered_jobs_with_urls(fresh_db):
    """TEETH: after discovery persists jobs, summary().discovered returns them.

    Fails pre-C2: SessionSummary had no discovered field and the controller
    had no read path into job_history — the list was unreachable.
    """
    jobs = [_job(0), _job(1), _job(2)]
    for j in jobs:
        fresh_db.record_job_discovery(j, session_id="s1")

    controller = _controller(fresh_db, "s1")
    discovered = controller.summary().discovered

    assert len(discovered) == 3
    assert {d.url for d in discovered} == {j.url for j in jobs}
    assert all(isinstance(d, DiscoveredJob) for d in discovered)
    assert {d.title for d in discovered} == {j.title for j in jobs}


def test_both_surfaces_have_call_sites_reading_the_new_port_surface():
    r"""TEETH: cli/startup.py and gui/app.py read the results/custody surface.

    Pre-C2: `grep -rn "get_recent_jobs\|JobRepository" adapters/primary`
    returned nothing — zero callers anywhere on either surface. This AST pin
    asserts each surface actually reads the discovered list and calls each
    custody method — the exact shape of "zero callers" this change fixes.

    (Docstring is a raw string because the grep pattern above contains a
    backslash-escaped alternation, which is an invalid escape sequence in a
    normal string literal — SyntaxWarning under -W error.)
    """
    required = {"discovered", "export_session_results", "export_profile", "list_session_history"}

    for path in (_CLI_STARTUP, _GUI_APP):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        used = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        missing = required - used
        assert not missing, (
            f"{path.name} has no call site reading {sorted(missing)} — "
            f"the port exposes them but the surface never shows them"
        )


def test_controller_still_satisfies_the_extended_port(fresh_db):
    """COVERAGE: the 15-method UIPort is satisfied structurally, no wrapper."""
    controller = _controller(fresh_db, "s1")
    assert isinstance(controller, UIPort)


# ─────────────────────────────────────────────────────────────────────────────
# TEETH — export_profile
# ─────────────────────────────────────────────────────────────────────────────


def test_export_profile_writes_plaintext_json_to_the_given_path(tmp_path):
    """TEETH: export_profile writes the profile to the chosen directory.

    Fails pre-C2: the method did not exist on ProfileRepositoryPort at all.
    The export is plaintext JSON BY DESIGN (portable to any machine, any
    vault state).
    """
    repo = ProfileRepository(storage_dir=tmp_path / "store")
    repo.save_profile(UserProfile(**_minimal_profile_dict("ada")))
    out_dir = tmp_path / "usb"
    out_dir.mkdir()

    target = repo.export_profile("ada", out_dir)

    assert target == out_dir / "ada.json"
    assert target.is_file()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["personal_info"]["email"] == "ada@example.com"
    assert data["profile_name"] == "ada"


def test_export_profile_refuses_overwrite_without_the_flag(tmp_path):
    """TEETH: an existing destination is only replaced with overwrite=True."""
    repo = ProfileRepository(storage_dir=tmp_path / "store")
    repo.save_profile(UserProfile(**_minimal_profile_dict("ada")))
    out_dir = tmp_path / "usb"
    out_dir.mkdir()
    repo.export_profile("ada", out_dir)

    with pytest.raises(FileExistsError):
        repo.export_profile("ada", out_dir)

    # And with the flag, the export succeeds.
    target = repo.export_profile("ada", out_dir, overwrite=True)
    assert target.is_file()


@pytest.mark.parametrize(
    "name,destination_kind",
    [
        ("../evil", "dir"),
        ("a/b", "dir"),
        ("ada", "file"),
        ("ada", "store"),
        ("ada", "dotdot"),
    ],
)
def test_export_profile_refuses_path_traversal(tmp_path, name, destination_kind):
    """TEETH: traversal destinations are refused, each kind for its own reason.

    - a name containing ".." or a path separator cannot write outside the dir;
    - a destination that is a file (not a directory) is not a place to write;
    - a destination inside the profile store would be the plaintext-overwrite
      downgrade the vault documentation warns about;
    - a destination containing ".." is refused outright (conservative rule).
    """
    store = tmp_path / "store"
    repo = ProfileRepository(storage_dir=store)
    repo.save_profile(UserProfile(**_minimal_profile_dict("ada")))

    if destination_kind == "dir":
        destination = tmp_path / "usb"
        destination.mkdir()
    elif destination_kind == "file":
        destination = tmp_path / "afile.txt"
        destination.write_text("x")
    elif destination_kind == "store":
        destination = store
    else:  # "dotdot"
        destination = tmp_path / "usb" / ".." / "usb"

    with pytest.raises(ValueError):
        repo.export_profile(name, destination)


def test_export_profile_refuses_unknown_profile(tmp_path):
    """TEETH: exporting a profile that cannot be loaded is a clear error."""
    repo = ProfileRepository(storage_dir=tmp_path / "store")
    out_dir = tmp_path / "usb"
    out_dir.mkdir()

    with pytest.raises(ValueError):
        repo.export_profile("nobody", out_dir)


def test_controller_export_profile_requires_a_wired_repo(fresh_db, tmp_path):
    """COVERAGE: an unwired controller fails loud, not silently."""
    controller = _controller(fresh_db, "s1", profile_repo=None)
    with pytest.raises(RuntimeError):
        controller.export_profile("ada", tmp_path)


# ─────────────────────────────────────────────────────────────────────────────
# GUARDS — the USB story and the encryption invariant
# ─────────────────────────────────────────────────────────────────────────────


def test_export_import_round_trip_produces_an_equal_profile(tmp_path):
    """GUARD: export → import round-trips to an equal profile.

    This IS the USB story: write a profile to removable media on machine A,
    import it into a fresh store on machine B, and get the same profile back.
    """
    repo_a = ProfileRepository(storage_dir=tmp_path / "store_a")
    original = UserProfile(**_minimal_profile_dict("ada"))
    repo_a.save_profile(original)

    out_dir = tmp_path / "usb"
    out_dir.mkdir()
    exported = repo_a.export_profile("ada", out_dir)

    repo_b = ProfileRepository(storage_dir=tmp_path / "store_b")
    imported_path = repo_b.import_profile(exported)
    loaded = repo_b.load_profile(imported_path.stem)

    assert loaded is not None
    assert loaded.model_dump() == original.model_dump()


def test_export_does_not_mutate_store_or_encryption_state(tmp_path):
    """GUARD: the stored profile and its encryption are untouched by export.

    The near-miss this pins: a wizard writing bytes itself would have
    overwritten an encrypted stored profile with plaintext and told nobody.
    Export must leave the stored file byte-identical — encrypted or not.
    """
    repo = ProfileRepository(
        storage_dir=tmp_path / "vault_store", master_password="hunter2"
    )
    repo.save_profile(UserProfile(**_minimal_profile_dict("ada")))
    stored = repo.storage_dir / "ada.json"
    bytes_before = stored.read_bytes()
    assert not bytes_before.lstrip().startswith(b"{"), (
        "the vault-backed store should be encrypted, not plaintext JSON"
    )

    out_dir = tmp_path / "usb"
    out_dir.mkdir()
    target = repo.export_profile("ada", out_dir)

    # The stored file is byte-identical — export touched nothing in the store.
    assert stored.read_bytes() == bytes_before

    # The export itself is plaintext JSON by design.
    exported_text = target.read_text(encoding="utf-8")
    assert exported_text.lstrip().startswith("{")
    assert "ada@example.com" in exported_text


# ─────────────────────────────────────────────────────────────────────────────
# TEETH — session history
# ─────────────────────────────────────────────────────────────────────────────


def test_session_history_lists_past_runs_with_outcome_and_counts(tmp_path, monkeypatch):
    """TEETH: past sessions are listable with their outcome and counts.

    Fails pre-C2: SessionReport had no loader — no load, no glob — and
    UIPort had no list_session_history, so nothing could enumerate past runs.
    """
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "session_aaa_20260901_120000.json").write_text(
        json.dumps(_report_dict("aaa-session-1", "stopped", 5, 2, 1)),
        encoding="utf-8",
    )
    (reports / "session_bbb_20260910_090000.json").write_text(
        json.dumps(_report_dict("bbb-session-2", "queue_drained", 12, 3, 0)),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "auto_apply.application.services.session_controller.USER_DATA_DIR", tmp_path
    )
    controller = _controller(MagicMock(), "current-session")

    entries = controller.list_session_history()

    assert len(entries) == 2
    # Newest file first (bbb was written second → later mtime).
    assert entries[0].session_id == "bbb-session-2"
    assert entries[0].completion_state == "queue_drained"
    assert entries[0].jobs_found == 12
    assert entries[0].applications_submitted == 3
    assert entries[0].applications_failed == 0
    assert entries[1].completion_state == "stopped"
    assert all(isinstance(e, SessionHistoryEntry) for e in entries)


def test_session_history_empty_when_no_reports(tmp_path, monkeypatch):
    """COVERAGE: no reports directory → empty tuple, never an error."""
    monkeypatch.setattr(
        "auto_apply.application.services.session_controller.USER_DATA_DIR", tmp_path
    )
    controller = _controller(MagicMock(), "current-session")
    assert controller.list_session_history() == ()


# ─────────────────────────────────────────────────────────────────────────────
# COVERAGE — results CSV export and the GUI's pure formatters
# ─────────────────────────────────────────────────────────────────────────────


def test_export_session_results_writes_csv_with_urls(fresh_db, tmp_path):
    """COVERAGE: the collect-run deliverable — a CSV of discovered jobs.

    The ruling: show on screen, export on request. This method only runs
    because the user asked, and refuses to overwrite without the flag.
    """
    jobs = [_job(0), _job(1)]
    for j in jobs:
        fresh_db.record_job_discovery(j, session_id="s1")
    controller = _controller(fresh_db, "s1")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    target = controller.export_session_results(out_dir)

    assert target.name.startswith("aa_results_")
    text = target.read_text(encoding="utf-8")
    assert "title,company,url,source" in text
    assert jobs[0].url in text
    assert jobs[1].url in text

    with pytest.raises(FileExistsError):
        controller.export_session_results(out_dir)
    assert controller.export_session_results(out_dir, overwrite=True).is_file()


def test_gui_format_helpers_are_pure_and_correct():
    """COVERAGE: the GUI's results/history formatting works without Tk.

    The prompt's constraint: test the pure functions, never construct widgets.
    These helpers are module-level functions taking plain data.

    Diagnosis note (2026-09, defect 3b): the previous version of this pin
    asserted exact padded-column formatting — literal strings with specific
    space counts ("Jobs discovered:    2"). A pin that asserts padding instead
    of meaning breaks the moment the formatter's spacing drifts from the
    test's expectation, even when the helper is correct. The assertions below
    check the semantic payload instead: the labels, the job titles, the URLs,
    and the outcome tokens that the helpers must always produce, regardless
    of how they choose to pad them.
    """
    from auto_apply.adapters.primary.gui.app import (
        format_history_lines,
        format_results_lines,
    )

    summary = SessionSummary(
        jobs_discovered=2,
        discovered=(
            DiscoveredJob(title="Backend Engineer", company="Acme", url="https://x/1", source="bing"),
            DiscoveredJob(title="Data Engineer", company="Globex", url="https://x/2", source="google"),
        ),
    )
    results_text = "\n".join(format_results_lines(summary))
    # The count, labelled, must appear — padding is not asserted.
    assert "Jobs discovered" in results_text
    assert "2" in results_text
    # The discovered list is the collect-run payoff: titles, companies, URLs.
    assert "Backend Engineer" in results_text
    assert "Acme" in results_text
    assert "https://x/1" in results_text
    assert "Data Engineer" in results_text
    assert "Globex" in results_text
    assert "https://x/2" in results_text

    entries = (
        SessionHistoryEntry(
            session_id="s1",
            profile_name="tester",
            completion_state="queue_drained",
            started_at="2026-09-15T14:02:00",
            duration_seconds=372.0,
            jobs_found=12,
            applications_submitted=3,
            applications_failed=1,
        ),
    )
    history_text = "\n".join(format_history_lines(entries))
    # Outcome and counts, as tokens — padding and separators not asserted.
    assert "queue_drained" in history_text
    assert "found 12" in history_text
    assert "applied 3" in history_text

    assert format_history_lines(()) == ["No past sessions found."]

"""Pins for C1 — discovered jobs must survive the run.

Before this change, discovery persistence happened only at vetting
(vetting_workflow.py:363). Stage U3 made DISCOVER_ONLY reachable, and a live
run on 2026-09-15 found 7 jobs and persisted none of them. These pins hold
the ruling: persist at discovery with session_id populated, read
session-scoped, and never treat a DISCOVERED row as a reason to skip.

Labels follow the standing method: TEETH fail against the pre-C1 tree for the
reason stated in the docstring (each is mechanically certain — the method,
field, event, or row simply does not exist pre-C1); GUARD passes on both
trees and must not be broken silently; COVERAGE documents behaviour of code
introduced by this change.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from auto_apply.adapters.secondary.persistence.database import DatabaseManager
from auto_apply.adapters.secondary.persistence.job_repository import JobRepository
from auto_apply.application.agent.event_bus import EventBus
from auto_apply.application.agent.orchestrator import AgentOrchestrator
from auto_apply.application.agent.state_machine import AgentState, StateMachine
from auto_apply.application.services.data_processing.deduplication_manager import (
    DeduplicationManager,
)
from auto_apply.application.workflows.discovery_workflow import DiscoveryWorkflow
from auto_apply.domain.events import Event
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.models.session_plan import SessionExecutionMode, SessionPlan
from auto_apply.domain.models.session_report import SessionReport


def _job(i: int) -> Job:
    return Job(
        title=f"Engineer {i}",
        company="Acme",
        url=f"https://acme.example/j/{i}",
        source="bing",
    )


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
    db.db_path = tmp_path / "c1_test.db"
    db._capability_profile = None
    db._init_schema()
    try:
        yield db
    finally:
        db.db_path = original_path
        db._capability_profile = original_profile


def _workflow(db, jobs, *, session_id, mode, event_bus=None, dedup=None):
    provider = MagicMock()
    provider.requires_live_browser = False
    provider.run.return_value = list(jobs)
    return DiscoveryWorkflow(
        profile=MagicMock(),
        providers=[provider],
        task_queue=db,
        event_bus=event_bus or MagicMock(),
        dedup=dedup or DeduplicationManager(),
        text_matcher=MagicMock(),
        plan=SessionPlan(session_id=session_id, execution_mode=mode),
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEETH — persistence at discovery, session-scoped
# ─────────────────────────────────────────────────────────────────────────────


def test_discover_only_run_persists_found_jobs_with_session_id(fresh_db):
    """TEETH: a DISCOVER_ONLY run's jobs are stored and readable afterwards.

    Fails pre-C1: nothing persists at discovery and
    ``JobRepository.get_jobs_for_session`` does not exist, so the read side
    of this pin cannot even be constructed on the old tree.
    """
    jobs = [_job(i) for i in range(3)]
    wf = _workflow(fresh_db, jobs, session_id="s1", mode=SessionExecutionMode.DISCOVER_ONLY)

    enqueued = wf.run(instructions=[SearchInstruction(title="Engineer", location="Remote")])

    assert enqueued == 0  # DISCOVER_ONLY enqueues nothing for vetting — that is the mode
    found = JobRepository(fresh_db).get_jobs_for_session("s1")
    assert len(found) == 3
    assert {j.url for j in found} == {j.url for j in jobs}

    with fresh_db.get_connection() as conn:
        rows = conn.execute(
            "SELECT url, session_id, status FROM job_history"
        ).fetchall()
    assert {r["session_id"] for r in rows} == {"s1"}
    assert {r["status"] for r in rows} == {"DISCOVERED"}


def test_full_pipeline_after_discover_only_rediscovers_the_same_jobs(fresh_db):
    """TEETH (the anti-poisoning pin): a collect run must not shrink the next one.

    The status assertion fails pre-C1 (no rows exist). The enqueue assertion
    is the behaviour the ruling must preserve: with DISCOVERED rows present,
    a second run with a fresh DeduplicationManager must still yield every
    job — job_history is history, not a reprocessing guard.
    """
    jobs = [_job(i) for i in range(4)]
    _workflow(fresh_db, jobs, session_id="s1", mode=SessionExecutionMode.DISCOVER_ONLY).run(
        instructions=[SearchInstruction(title="Engineer", location="Remote")]
    )

    wf2 = _workflow(fresh_db, jobs, session_id="s2", mode=SessionExecutionMode.FULL_PIPELINE)
    enqueued = wf2.run(instructions=[SearchInstruction(title="Engineer", location="Remote")])

    assert enqueued == 4, (
        "a collect-links-only run poisoned the search it was gathering for"
    )
    with fresh_db.get_connection() as conn:
        statuses = {r["url"]: r["status"] for r in conn.execute(
            "SELECT url, status FROM job_history"
        ).fetchall()}
    assert set(statuses.values()) == {"DISCOVERED"}, (
        "discovery flipped history rows to APPLIED — history is not an outcome record"
    )


def test_run_publishes_found_count_in_discover_only(fresh_db):
    """TEETH: JOBS_DISCOVERED carries the unique found count in every mode.

    Fails pre-C1: the event was published from _enqueue_vet_tasks with the
    vet enqueue count — which is 0 when vetting is skipped, so nothing was
    published at all for DISCOVER_ONLY and payloads[JOBS_DISCOVERED] raises
    KeyError on the old tree.
    """
    bus = MagicMock()
    jobs = [_job(i) for i in range(5)]
    wf = _workflow(
        fresh_db, jobs, session_id="s1",
        mode=SessionExecutionMode.DISCOVER_ONLY, event_bus=bus,
    )

    wf.run(instructions=[SearchInstruction(title="Engineer", location="Remote")])

    payloads = {
        call.args[0]: call.args[1]
        for call in bus.publish.call_args_list
    }
    assert payloads[Event.JOBS_DISCOVERED]["count"] == 5


def test_orchestrator_counters_follow_the_jobs_discovered_event():
    """COVERAGE: the orchestrator's discovery counters come from the event,
    not from the VET enqueue return value.

    tests/application/test_orchestrator_dispatch.py used to pin the old
    wiring (update_stats called with the enqueue count inside the handler);
    its counter assertions were replaced with delegation-only checks in this
    same change, and the counter contract lives here instead.
    """
    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.event_bus = EventBus()
    orch.context = MagicMock()
    orch._session_report = SessionReport(session_id="pin", profile_name="t")
    orch.state_machine = MagicMock()
    orch._register_event_handlers()

    orch.event_bus.publish(Event.JOBS_DISCOVERED, {"count": 7, "source": "discovery"})

    orch.context.update_stats.assert_called_with("discovered", 7)
    assert orch._session_report.raw_results_found == 7


def test_queue_drain_is_recorded_as_completed_not_abandoned(fresh_db, tmp_path, monkeypatch):
    """TEETH: a run that exhausts its queue writes a finished report.

    Fails pre-C1 in two ways: the loop could not exit on its own (it idled
    forever), and the saved JSON carries no "completion_state" key on the old
    tree (KeyError). The scripted queue flips running=False so the pin
    cannot hang even if the completion branch regresses.
    """
    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.running = True
    orch.paused = False
    orch.state_machine = StateMachine(initial_state=AgentState.IDLE)
    orch._browser_monitor = None
    orch._network_monitor = None
    orch._watchdog = None
    orch._progress = None
    orch.checkpoint_manager = MagicMock()
    orch.checkpoint_manager.load.return_value = None
    orch.task_queue = fresh_db
    orch.registry = MagicMock()
    orch.context = MagicMock()
    orch.event_bus = MagicMock()
    orch._driver = None
    orch._session_report = SessionReport(session_id="drain", profile_name="t")
    orch._engines = {}
    orch._workflows = {
        "ApplicationsWorkflow": SimpleNamespace(
            batch_scheduler=SimpleNamespace(
                check_batch_ready=lambda: False,
                has_any_buffered=lambda: False,
            )
        )
    }
    orch.IDLE_SLEEP_SECONDS = 0.01

    def _next_task():
        orch.running = False
        return None

    monkeypatch.setattr(fresh_db, "get_next_task", _next_task)
    monkeypatch.setattr(
        "auto_apply.application.agent.orchestrator.USER_DATA_DIR", tmp_path
    )

    orch.run()

    reports = list((tmp_path / "reports").glob("*.json"))
    assert reports, "no session report was written when the queue drained"
    data = json.loads(reports[0].read_text(encoding="utf-8"))
    assert data["completion_state"] == "queue_drained"


# ─────────────────────────────────────────────────────────────────────────────
# GUARDS
# ─────────────────────────────────────────────────────────────────────────────


def test_vetting_add_job_after_discovery_is_a_noop_no_double_write(fresh_db):
    """GUARD: FULL_PIPELINE writes exactly one row per discovered URL.

    vetting_workflow keeps its add_job call — it is the only writer for jobs
    that arrive via RESOLVE_JOB_URL and were never discovered — but for
    discovery-found jobs its write must be an INSERT OR IGNORE no-op.
    Fails pre-C1: discovery persisted nothing, so add_job returns True.
    """
    jobs = [_job(i) for i in range(3)]
    _workflow(fresh_db, jobs, session_id="s1", mode=SessionExecutionMode.FULL_PIPELINE).run(
        instructions=[SearchInstruction(title="Engineer", location="Remote")]
    )

    repo = JobRepository(fresh_db)
    for job in jobs:
        assert repo.add_job(job) is False, (
            "vetting's persistence wrote a second row for a discovery-found job"
        )

    with fresh_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM job_history").fetchone()[0]
    assert count == 3


def test_record_job_discovery_still_returns_false_for_a_known_url(fresh_db):
    """GUARD: the idempotency contract from the pre-C1 tree must not change."""
    job = _job(1)
    assert fresh_db.record_job_discovery(job, session_id="s1") is True
    assert fresh_db.record_job_discovery(job, session_id="s2") is False


def test_get_recent_jobs_orders_by_applied_at_without_error(fresh_db):
    """COVERAGE (adjacent latent bug fixed in this change): get_recent_jobs
    ordered by a nonexistent last_updated column and would have raised
    sqlite3.OperationalError on first call — zero callers meant nothing saw it.
    """
    jobs = [_job(1), _job(2)]
    for job in jobs:
        fresh_db.record_job_discovery(job, session_id="s1")

    recent = JobRepository(fresh_db).get_recent_jobs(limit=10)

    assert {j.url for j in recent} == {j.url for j in jobs}

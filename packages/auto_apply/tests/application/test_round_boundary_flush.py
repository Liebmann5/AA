"""S8g pins — round-completion batch flush (R-2 ruling).

Pin labels (honest, per standing method):
  A  TEETH — ordering: the previous round's batch must be processed BEFORE
     the next DISCOVER task is dispatched. Pre-S8g the only flush ran at
     queue-empty, i.e. AFTER all dispatches; the ordering assertion fails on
     the old tree. (The call-count assertion alone is NOT teeth: the old
     queue-empty flush also fires once — do not rely on it.)
  B  BEHAVIOUR-PRESERVING — the queue-empty flush still drains the final
     round (a single-search session behaves identically on both trees).
  C  BEHAVIOUR-PRESERVING — an empty buffer never triggers a flush.
  D  COVERAGE-adjacent — the static-mode invariant the stage relies on
     (no browser -> APPLY never enters the queue). Possibly redundant with
     existing capability-gate coverage; included because S8g's safety
     argument depends on it, and existing coverage could not be verified
     from the supplied tree.

The loop-driving pins build a partial AgentOrchestrator (the documented
pattern from tests/application/test_orchestrator_dispatch.py) and run the
REAL run() loop with a scripted task queue. _dispatch_task and _process_batch
are mocked: the flush trigger in the loop is the unit under test, not
dispatch, not the apply machinery.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from auto_apply.application.agent.orchestrator import AgentOrchestrator
from auto_apply.application.agent.state_machine import AgentState, StateMachine
from auto_apply.domain.models.capability_profile import ResolvedCapabilityProfile
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.task_priority import TaskPriority
from auto_apply.domain.models.work_unit import TaskType, WorkUnit


def _discover_unit(name: str) -> WorkUnit:
    return WorkUnit(
        priority=TaskPriority.DISCOVER,
        task_type=TaskType.DISCOVER,
        payload={"query": name, "location": "Remote"},
        source="test",
    )


def _job() -> Job:
    return Job(
        title="Engineer",
        company="Acme",
        url="https://acme.example/1",
        source="test",
    )


class _FakeScheduler:
    """Minimal CompanyBatchScheduler stand-in. Always below threshold (the
    R-2 premise) and records every flush call."""

    def __init__(self) -> None:
        self._batches: dict[str, list[Job]] = {}
        self.flushed: list[dict[str, list[Job]]] = []

    def check_batch_ready(self) -> bool:
        return False

    def has_any_buffered(self) -> bool:
        return bool(self._batches)

    def flush_all_batches(self) -> dict[str, list[Job]]:
        self.flushed.append(dict(self._batches))
        out, self._batches = self._batches, {}
        return out


def _build_orchestrator(scheduler: _FakeScheduler, scripted_queue: list, events: list):
    """Partial orchestrator: only the attributes run() touches are injected."""
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
    orch.task_queue = MagicMock()
    orch.registry = MagicMock()
    orch.registry.discovery_requires_live_browser.return_value = False
    orch.context = MagicMock()
    orch.event_bus = MagicMock()
    orch._driver = None
    orch._session_report = MagicMock()
    orch._engines = {}
    orch._workflows = {
        "ApplicationsWorkflow": SimpleNamespace(batch_scheduler=scheduler),
    }
    orch.IDLE_SLEEP_SECONDS = 0.01  # instance override of the class constant

    def _next_task():
        if scripted_queue:
            return scripted_queue.pop(0)
        orch.running = False
        return None

    orch.task_queue.get_next_task.side_effect = _next_task

    def _dispatch(task):
        events.append(("dispatch", task.id))

    orch._dispatch_task = MagicMock(side_effect=_dispatch)
    orch._process_batch = MagicMock(
        side_effect=lambda company_key, jobs, sched: events.append(("batch", company_key))
    )
    return orch


# --------------------------------------------------------------------------
# Pin A (TEETH): round-boundary flush fires BEFORE the next discovery dispatch
# --------------------------------------------------------------------------

def test_round_boundary_flush_fires_before_next_discovery_dispatch():
    scheduler = _FakeScheduler()
    events: list = []
    wu1, wu2 = _discover_unit("q1"), _discover_unit("q2")
    orch = _build_orchestrator(scheduler, [wu1, wu2], events)

    # Simulate round 1's vet/apply buffering between the two searches.
    def _dispatch_buffering(task):
        events.append(("dispatch", task.id))
        if task is wu1:
            scheduler._batches["acme"] = [_job()]

    orch._dispatch_task.side_effect = _dispatch_buffering

    orch.run()

    batch_events = [e for e in events if e[0] == "batch"]
    assert batch_events == [("batch", "acme")], (
        f"expected exactly one flush of 'acme', got {batch_events}"
    )
    assert events.index(("batch", "acme")) < events.index(("dispatch", wu2.id)), (
        f"the previous round's applications must drain BEFORE the next "
        f"DISCOVER is dispatched; got order {events}. Pre-S8g the only flush "
        f"ran at queue-empty — after every dispatch."
    )


# --------------------------------------------------------------------------
# Pin B (BEHAVIOUR-PRESERVING): queue-empty flush still drains the final round
# --------------------------------------------------------------------------

def test_queue_empty_flush_still_drains_final_round():
    scheduler = _FakeScheduler()
    events: list = []
    wu1 = _discover_unit("q1")
    orch = _build_orchestrator(scheduler, [wu1], events)

    def _dispatch_buffering(task):
        events.append(("dispatch", task.id))
        scheduler._batches["acme"] = [_job()]

    orch._dispatch_task.side_effect = _dispatch_buffering

    orch.run()

    assert [e for e in events if e[0] == "batch"] == [("batch", "acme")], (
        "a single-search session must still flush its buffered applications "
        "when the queue empties — identical on both trees"
    )


# --------------------------------------------------------------------------
# Pin C (BEHAVIOUR-PRESERVING): empty buffer never triggers a flush
# --------------------------------------------------------------------------

def test_no_flush_when_buffer_empty():
    scheduler = _FakeScheduler()
    events: list = []
    wu1, wu2 = _discover_unit("q1"), _discover_unit("q2")
    orch = _build_orchestrator(scheduler, [wu1, wu2], events)

    orch.run()

    assert scheduler.flushed == []
    orch._process_batch.assert_not_called()


# --------------------------------------------------------------------------
# Pin D (COVERAGE-adjacent): the static-mode invariant the stage relies on
# --------------------------------------------------------------------------

def test_static_mode_capability_profile_never_allows_apply_tasks():
    """S8g's static-mode safety argument: without a browser, APPLY tasks are
    rejected at queue insertion, so the batch buffer is provably empty and the
    round-boundary flush is a no-op. This pins the contract the stage relies
    on; the DatabaseManager enforcement of it is pre-existing."""
    profile = ResolvedCapabilityProfile(has_browser=False)
    assert profile.can_run_task("apply") is False
    assert "apply" not in profile.allowed_task_types
    assert ResolvedCapabilityProfile(has_browser=True).can_run_task("apply") is True

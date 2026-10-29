"""Pins for the session-owned query budget and cross-task engine rotation.

New-surface pins. Mutations caught: the budget reverting to a per-task cap;
the rotation restarting at every task boundary; the budget counting planned
but never-sent instructions; generic sessions being truncated under the cap.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from auto_apply.application.workflows.discovery_workflow import DiscoveryWorkflow
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.models.session_plan import SessionPlan
from auto_apply.domain.services.search_planner import (
    PlannedQuery,
    PlannedSearch,
)


def _pq(engine: str, platform: str = "jobvite") -> PlannedQuery:
    return PlannedQuery(
        engine=engine,
        platform=platform,
        title="Engineer",
        location="Remote",
        workplace_type="remote",
        raw_query_string='site:jobs.jobvite.com ("Engineer")',
        surface_template="web",
        date_range=None,
        max_results=30,
    )


class _RecordingPlanner:
    def __init__(self, engines_per_call: list[str]) -> None:
        self.calls: list[dict] = []
        self._engines_per_call = engines_per_call

    def plan(self, **kwargs) -> PlannedSearch:
        self.calls.append(kwargs)
        queries = tuple(_pq(engine) for engine in self._engines_per_call)
        return PlannedSearch(queries=queries, notes=(), dropped_targets=())


def _engine(name: str) -> MagicMock:
    provider = MagicMock()
    provider.name = name
    provider.requires_live_browser = False
    provider.run.return_value = []
    return provider


def _workflow(planner, plan: SessionPlan) -> DiscoveryWorkflow:
    return DiscoveryWorkflow(
        profile=MagicMock(),
        providers=[_engine("google"), _engine("bing")],
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        dedup=MagicMock(),
        text_matcher=MagicMock(),
        plan=plan,
        search_planner=planner,
    )


def _plan(cap: int) -> SessionPlan:
    return SessionPlan(
        session_id="budget-pin",
        max_queries_per_session=cap,
        use_ats_site_search=True,
        ats_platforms=("jobvite",),
        active_providers=("google", "bing"),
        max_concurrency=1,
    )


def _instruction() -> SearchInstruction:
    return SearchInstruction(title="Engineer", location="Remote")


def test_the_budget_is_shared_across_discover_tasks():
    """The second task is planned with what the first left, not a fresh cap."""
    planner = _RecordingPlanner(["google", "bing"])
    workflow = _workflow(planner, _plan(cap=5))
    workflow.run(instructions=[_instruction()])
    workflow.run(instructions=[_instruction()])
    assert planner.calls[0]["budget"] == 5
    assert planner.calls[1]["budget"] == 3


def test_engine_rotation_continues_across_a_task_boundary():
    """No engine gets two consecutive planned queries across tasks."""
    planner = _RecordingPlanner(["google"])
    workflow = _workflow(planner, _plan(cap=10))
    workflow.run(instructions=[_instruction()])
    workflow.run(instructions=[_instruction()])
    assert planner.calls[0]["engines"] == ("google", "bing")
    assert planner.calls[1]["engines"] == ("bing", "google")


def test_rotation_resumes_after_the_last_engine_used():
    """Two queries ending on bing: the next task starts on google."""
    planner = _RecordingPlanner(["google", "bing"])
    workflow = _workflow(planner, _plan(cap=10))
    workflow.run(instructions=[_instruction()])
    workflow.run(instructions=[_instruction()])
    assert planner.calls[1]["engines"] == ("google", "bing")


def test_an_exhausted_budget_never_reaches_the_planner_or_a_provider():
    planner = _RecordingPlanner(["google", "bing"])
    workflow = _workflow(planner, _plan(cap=2))
    workflow.run(instructions=[_instruction()])
    second = workflow.run(instructions=[_instruction()])
    assert len(planner.calls) == 1
    assert second == 0


def test_generic_queries_count_toward_the_budget_but_are_not_truncated_under_it():
    """Default path: the counter runs, nothing is cut below the cap."""
    plan = SessionPlan(session_id="budget-generic", max_queries_per_session=5)
    workflow = DiscoveryWorkflow(
        profile=MagicMock(),
        providers=[_engine("google")],
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        dedup=MagicMock(),
        text_matcher=MagicMock(),
        plan=plan,
    )
    for _ in range(3):
        workflow.run(instructions=[_instruction()])
    assert workflow._queries_sent_this_session == 3

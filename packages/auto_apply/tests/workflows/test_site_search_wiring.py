"""Wiring pins for ATS-targeted search inside DiscoveryWorkflow.

Label honesty: the planner integration did not exist before this change.
Pins marked GUARD protect the default path (site search OFF) — those run
against behavior that must not change. Pins marked NEW SURFACE cover the new
behavior and name the mutation each catches.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from auto_apply.application.workflows.discovery_workflow import (
    DiscoveryWorkflow,
    _DiscoveryStats,
)
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.models.session_plan import SearchPair, SessionPlan
from auto_apply.domain.models.work_unit import TaskType
from auto_apply.domain.services.search_planner import (
    PlannedQuery,
    PlannedSearch,
    PlannerNote,
)


def _planned_query(**overrides) -> PlannedQuery:
    kwargs: dict = {
        "engine": "google",
        "platform": "greenhouse",
        "title": "Engineer",
        "location": "Remote",
        "workplace_type": "remote",
        "raw_query_string": 'site:boards.greenhouse.io ("Engineer")',
        "surface_template": "web",
        "date_range": None,
        "max_results": 30,
    }
    kwargs.update(overrides)
    return PlannedQuery(**kwargs)


class _FakePlanner:
    """Records plan() calls and returns canned output."""

    def __init__(self, queries=(), notes=()):
        self._queries = tuple(queries)
        self._notes = tuple(notes)
        self.calls: list[dict] = []

    def plan(self, **kwargs) -> PlannedSearch:
        self.calls.append(kwargs)
        return PlannedSearch(queries=self._queries, notes=self._notes)


def _profile(titles=("Engineer",), locations=("Remote",)):
    profile = MagicMock()
    profile.search_preferences.desired_job_titles = list(titles)
    profile.search_preferences.preferred_locations = list(locations)
    profile.search_preferences.workplace_types = ["remote"]
    return profile


def _plan(**overrides) -> SessionPlan:
    kwargs: dict = {"session_id": "site-search-wiring", "max_concurrency": 1}
    kwargs.update(overrides)
    return SessionPlan(**kwargs)


def _workflow(plan, planner=None, providers=(), profile=None) -> DiscoveryWorkflow:
    return DiscoveryWorkflow(
        profile=profile if profile is not None else _profile(),
        providers=list(providers),
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        dedup=MagicMock(),
        text_matcher=MagicMock(),
        plan=plan,
        search_planner=planner,
    )


def test_default_path_is_untouched_when_site_search_is_off() -> None:
    """GUARD — with the flag off, overrides pass through unchanged and the
    planner is never consulted, even when one is injected.

    Mutation caught: consulting the planner when the flag is off.
    """
    planner = _FakePlanner(queries=[_planned_query()])
    workflow = _workflow(plan=_plan(), planner=planner)
    base = [SearchInstruction(title="Engineer", location="Remote")]
    out = workflow._build_search_instructions(override_instructions=base)
    assert out == base
    assert planner.calls == []


def test_generic_overrides_expand_through_the_planner() -> None:
    """NEW SURFACE — a seeded (title, location) task becomes planner output
    when site search is engaged.

    Mutation caught: running the generic query alongside (or instead of) the
    planned queries, or passing the wrong bases/platforms to the planner.
    """
    planner = _FakePlanner(
        queries=[_planned_query(), _planned_query(engine="bing")]
    )
    workflow = _workflow(
        plan=_plan(use_ats_site_search=True, ats_platforms=("greenhouse",)),
        planner=planner,
    )
    out = workflow._build_search_instructions(
        override_instructions=[SearchInstruction(title="Engineer", location="Remote")]
    )
    assert len(planner.calls) == 1
    assert planner.calls[0]["bases"] == (("Engineer", "Remote", "remote"),)
    assert planner.calls[0]["platforms"] == ("greenhouse",)
    assert [i.raw_query_string for i in out] == [
        'site:boards.greenhouse.io ("Engineer")'
    ] * 2
    assert {i.engine for i in out} == {"google", "bing"}


def test_verbatim_overrides_pass_through_even_when_site_search_is_on() -> None:
    """NEW SURFACE — a raw_query_string override is a verbatim power-user
    query; the planner must never rewrite it.

    Mutation caught: expanding or replacing verbatim overrides.
    """
    planner = _FakePlanner(queries=[_planned_query()])
    workflow = _workflow(
        plan=_plan(use_ats_site_search=True, ats_platforms=("greenhouse",)),
        planner=planner,
    )
    verbatim = SearchInstruction(
        title="Custom", raw_query_string="site:jobs.lever.co engineer"
    )
    out = workflow._build_search_instructions(override_instructions=[verbatim])
    assert out == [verbatim]
    assert planner.calls == []


def test_search_pairs_override_the_profile_matrix() -> None:
    """NEW SURFACE — plan-declared pairs take precedence over the profile
    matrix when no user override exists.

    Mutation caught: reading the profile first, or ignoring search_pairs.
    """
    plan = _plan(
        search_pairs=(
            SearchPair(title="Direct", location="Austin", workplace_type="hybrid"),
        )
    )
    workflow = _workflow(
        plan=plan, profile=_profile(titles=("Wrong",), locations=("Nowhere",))
    )
    out = workflow._build_search_instructions()
    assert [(i.title, i.location, i.workplace_type) for i in out] == [
        ("Direct", "Austin", "hybrid")
    ]


def test_engine_bound_instructions_reach_only_their_engine() -> None:
    """NEW SURFACE — engine routing in the fan-out; None still broadcasts.

    Mutation caught: matching on the provider class name instead of .name,
    or treating a None engine as bound.
    """
    p_google = MagicMock()
    p_google.name = "google"
    p_google.run.return_value = []
    p_bing = MagicMock()
    p_bing.name = "bing"
    p_bing.run.return_value = []
    workflow = _workflow(plan=_plan(), providers=(p_google, p_bing))
    google_only = SearchInstruction(title="E", raw_query_string="q", engine="google")
    broadcast = SearchInstruction(title="E2", raw_query_string="q2")
    bing_only = SearchInstruction(title="E3", raw_query_string="q3", engine="bing")
    workflow._execute_serp_discovery(
        [google_only, broadcast, bing_only], [p_google, p_bing]
    )
    assert [c.args[0] for c in p_google.run.call_args_list] == [
        google_only,
        broadcast,
    ]
    assert [c.args[0] for c in p_bing.run.call_args_list] == [broadcast, bing_only]


def test_jobs_carry_search_provenance() -> None:
    """NEW SURFACE — every found job states the engine form, platform and
    query that produced it.

    Mutation caught: dropping any of the three stamps.
    """
    job = Job(
        title="T", company="C", url="https://x.example/1", source="google"
    )
    provider = MagicMock()
    provider.name = "google"
    provider.run.return_value = [job]
    workflow = _workflow(plan=_plan(), providers=(provider,))
    instruction = SearchInstruction(
        title="E",
        raw_query_string='site:boards.greenhouse.io ("E")',
        engine="google",
        platform="greenhouse",
        surface_template="web",
    )
    found = workflow._execute_serp_discovery([instruction], [provider])
    assert found[0].metadata["search_query"] == 'site:boards.greenhouse.io ("E")'
    assert found[0].metadata["target_platform"] == "greenhouse"
    assert found[0].metadata["engine_form"] == "web"


def test_no_planner_degrades_to_the_normal_path() -> None:
    """NEW SURFACE — flag on but no planner wired: overrides pass through,
    nothing raises.

    Mutation caught: raising when the planner is absent.
    """
    workflow = _workflow(
        plan=_plan(use_ats_site_search=True, ats_platforms=("greenhouse",)),
        planner=None,
    )
    out = workflow._build_search_instructions(
        override_instructions=[SearchInstruction(title="Engineer", location="Remote")]
    )
    assert [i.title for i in out] == ["Engineer"]
    assert out[0].raw_query_string is None


def test_site_search_on_without_platforms_falls_back_and_warns_once(caplog) -> None:
    """NEW SURFACE — the flag with no platforms warns once per workflow, then
    runs the normal matrix.

    Mutation caught: warning per call, or silently producing nothing.
    """
    workflow = _workflow(
        plan=_plan(use_ats_site_search=True, ats_platforms=()),
        planner=_FakePlanner(),
    )
    with caplog.at_level(logging.WARNING):
        first = workflow._build_search_instructions()
        second = workflow._build_search_instructions()
    warnings = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and "use_ats_site_search" in r.getMessage()
    ]
    assert len(warnings) == 1
    assert first and second


def test_planner_notes_reach_the_log(caplog) -> None:
    """NEW SURFACE — exclusions the planner reports are visible in the log.

    Mutation caught: swallowing planner notes.
    """
    planner = _FakePlanner(
        queries=[_planned_query()],
        notes=[
            PlannerNote("warning", "budget reached"),
            PlannerNote("info", "skipped x"),
        ],
    )
    workflow = _workflow(
        plan=_plan(use_ats_site_search=True, ats_platforms=("greenhouse",)),
        planner=planner,
    )
    with caplog.at_level(logging.INFO):
        workflow._build_search_instructions(
            override_instructions=[SearchInstruction(title="E", location="")]
        )
    messages = [r.getMessage() for r in caplog.records]
    assert any("budget reached" in m for m in messages)
    assert any("skipped x" in m for m in messages)


def _off_shape_workflow(registry, plan=None) -> DiscoveryWorkflow:
    return DiscoveryWorkflow(
        profile=_profile(),
        providers=[],
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        dedup=MagicMock(),
        text_matcher=MagicMock(),
        ats_registry=registry,
        plan=plan if plan is not None else _plan(),
    )


def _hit(url: str, platform: str = "jobvite") -> Job:
    job = Job(title="Engineer", company="Acme", url=url, source="google")
    job.metadata["target_platform"] = platform
    return job


def test_a_terminal_hit_is_dropped_and_never_followed():
    """A success/confirm page is never routed anywhere — mining included."""
    registry = MagicMock()
    registry.is_terminal_page.return_value = True
    workflow = _off_shape_workflow(registry)
    kept, counts = workflow._handle_off_shape_hits(
        [_hit("https://jobs.jobvite.com/acme/job/1/apply/success")]
    )
    assert kept == []
    assert counts == {"dropped": 0, "terminal": 1, "mined": 0}
    registry.match.assert_not_called()
    workflow._task_queue.queue_task.assert_not_called()


def test_an_off_shape_hit_is_dropped_and_counted_by_default():
    """A board URL with mining off: dropped, counted, never enqueued."""
    registry = MagicMock()
    registry.is_terminal_page.return_value = False
    registry.match.return_value = None
    workflow = _off_shape_workflow(registry)
    kept, counts = workflow._handle_off_shape_hits(
        [_hit("https://jobs.jobvite.com/acme")]
    )
    assert kept == []
    assert counts == {"dropped": 1, "terminal": 0, "mined": 0}
    workflow._task_queue.queue_task.assert_not_called()


def test_an_off_shape_hit_routes_to_company_mining_when_enabled():
    """A board URL with mining on becomes a DISCOVER_COMPANY task."""
    registry = MagicMock()
    registry.is_terminal_page.return_value = False
    registry.match.return_value = None
    plan = _plan(enable_company_page_mining=True)
    workflow = _off_shape_workflow(registry, plan=plan)
    kept, counts = workflow._handle_off_shape_hits(
        [_hit("https://jobs.jobvite.com/acme")]
    )
    assert kept == []
    assert counts == {"dropped": 0, "terminal": 0, "mined": 1}
    workflow._task_queue.queue_task.assert_called_once()
    task = workflow._task_queue.queue_task.call_args.args[0]
    assert task.task_type == TaskType.DISCOVER_COMPANY
    assert task.payload["careers_url"] == "https://jobs.jobvite.com/acme"


def test_an_on_shape_posting_is_kept():
    """A URL matching the targeted platform's posting shape passes through."""
    registry = MagicMock()
    registry.is_terminal_page.return_value = False
    registry.match.return_value = MagicMock(name="jobvite")
    registry.match.return_value.name = "jobvite"
    workflow = _off_shape_workflow(registry)
    hit = _hit("https://jobs.jobvite.com/acme/job/123")
    kept, counts = workflow._handle_off_shape_hits([hit])
    assert kept == [hit]
    assert counts == {"dropped": 0, "terminal": 0, "mined": 0}


def test_unstamped_jobs_pass_untouched():
    """The default path never stamps target_platform — it is never filtered."""
    registry = MagicMock()
    workflow = _off_shape_workflow(registry)
    job = Job(title="Engineer", company="Acme", url="https://acme.example/1", source="bing")
    kept, counts = workflow._handle_off_shape_hits([job])
    assert kept == [job]
    assert counts == {"dropped": 0, "terminal": 0, "mined": 0}
    registry.is_terminal_page.assert_not_called()


def test_off_shape_counts_reach_the_completion_summary():
    """The discovery report names what was dropped and why."""
    workflow = _off_shape_workflow(MagicMock())
    stats = _DiscoveryStats(
        off_shape_dropped=2, terminal_dropped=1, routed_to_mining=1
    )
    workflow._emit_completion_summary(stats)
    payload = workflow._event_bus.publish.call_args.args[1]
    assert payload["off_shape_dropped"] == 2
    assert payload["terminal_dropped"] == 1
    assert payload["routed_to_mining"] == 1

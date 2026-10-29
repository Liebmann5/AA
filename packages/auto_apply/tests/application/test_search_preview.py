"""Pins for the plan preview (application/services/search_preview.py).

Label honesty: the preview is new surface; every pin is mutation-checked and
its docstring names the mutation it catches. The workflow-parity pin is the
one that matters most: the preview must equal what the session will do.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

from auto_apply.application.services.search_preview import (
    plan_updates_for_request,
    preview_search_plan,
)
from auto_apply.application.workflows.discovery_workflow import DiscoveryWorkflow
from auto_apply.domain.models.session_plan import SessionPlan
from auto_apply.domain.models.ui_contract import (
    EntryPoint,
    SearchPlanPreview,
    SessionRequest,
    format_search_plan_preview,
)
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.services.search_planner import PlannedQuery, PlannedSearch


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
    """Records plan() calls and returns canned output (the site-search
    wiring tests' pattern — kept local so the modules stay independent)."""

    def __init__(self, queries_per_call) -> None:
        self._queries = tuple(queries_per_call)
        self.calls: list[dict] = []

    def plan(self, **kwargs) -> PlannedSearch:
        self.calls.append(kwargs)
        return PlannedSearch(queries=self._queries, notes=(), dropped_targets=())


def _profile() -> MagicMock:
    profile = MagicMock()
    profile.search_preferences.desired_job_titles = ["Engineer", "Analyst"]
    profile.search_preferences.preferred_locations = ["Remote"]
    profile.search_preferences.workplace_types = ["remote"]
    return profile


def _plan(**overrides) -> SessionPlan:
    kwargs: dict = {
        "session_id": "preview-pin",
        "max_concurrency": 1,
        "active_providers": ("google", "bing"),
        "max_queries_per_session": 10,
    }
    kwargs.update(overrides)
    return SessionPlan(**kwargs)


def test_preview_module_is_offline() -> None:
    """TEETH: the preview must never touch a browser or the network.

    Mutation caught: any import of a browser or network library in the
    preview module."""
    import auto_apply.application.services.search_preview as mod

    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    banned = ("selenium", "playwright", "requests", "urllib", "socket", "httpx")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(banned), alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(banned), node.module


def test_generic_preview_lists_every_base() -> None:
    """TEETH: with targeting off, the preview shows the broadcast the
    session will run — one line per (title, location), engine=ALL.

    Mutation caught: showing nothing when site search is off, or inventing
    engine bindings the workflow would not make."""
    preview = preview_search_plan(
        _profile(),
        _plan(),
        planner=None,
        request=SessionRequest(entry=EntryPoint.SEARCH),
    )
    assert preview.site_search is False
    assert preview.planned_count == 2
    assert [q.query for q in preview.queries] == [
        "Engineer jobs in Remote",
        "Analyst jobs in Remote",
    ]
    assert all(q.engine == "" for q in preview.queries)
    assert preview.budget == 10


def test_site_search_preview_lists_planner_queries() -> None:
    """TEETH: with targeting on, the preview lists the planner's own output
    with engine, platform and form.

    Mutation caught: dropping the engine/platform/form, or reordering."""
    planner = _RecordingPlanner([_pq("google"), _pq("bing")])
    preview = preview_search_plan(
        _profile(),
        _plan(use_ats_site_search=True, ats_platforms=("jobvite",)),
        planner,
        SessionRequest(
            entry=EntryPoint.SEARCH,
            keywords=("Engineer",),
            location="Remote",
            platforms=("jobvite",),
        ),
    )
    assert preview.site_search is True
    assert [q.engine for q in preview.queries] == ["google", "bing"]
    assert all(q.platform == "jobvite" for q in preview.queries)
    assert all(q.form == "web" for q in preview.queries)
    assert planner.calls[0]["platforms"] == ("jobvite",)


def test_preview_matches_the_workflows_own_planning() -> None:
    """TEETH (the parity pin): the preview equals what the session will do —
    same per-base planner calls, same budget sequence, same engine rotation,
    same queries in the same order.

    Mutation caught: the preview re-implementing the workflow's budget or
    rotation instead of mirroring it."""
    plan = _plan(use_ats_site_search=True, ats_platforms=("jobvite",))
    planner_wf = _RecordingPlanner([_pq("google"), _pq("bing")])
    workflow = DiscoveryWorkflow(
        profile=_profile(),
        providers=[],
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        dedup=MagicMock(),
        text_matcher=MagicMock(),
        plan=plan,
        search_planner=planner_wf,
    )
    wf_out_1 = workflow._build_search_instructions(
        override_instructions=[SearchInstruction(title="Engineer", location="Remote")]
    )
    # The fan-out's own accounting, simulated: the session counts what it sent.
    workflow._queries_sent_this_session = len(wf_out_1)
    wf_out_2 = workflow._build_search_instructions(
        override_instructions=[SearchInstruction(title="Analyst", location="Remote")]
    )

    planner_pv = _RecordingPlanner([_pq("google"), _pq("bing")])
    preview = preview_search_plan(
        _profile(),
        plan,
        planner_pv,
        SessionRequest(
            entry=EntryPoint.SEARCH,
            keywords=("Engineer", "Analyst"),
            location="Remote",
            platforms=("jobvite",),
        ),
    )

    assert [q.query for q in preview.queries] == [
        i.raw_query_string for i in [*wf_out_1, *wf_out_2]
    ]
    assert [c["budget"] for c in planner_wf.calls] == [
        c["budget"] for c in planner_pv.calls
    ]
    assert [c["engines"] for c in planner_wf.calls] == [
        c["engines"] for c in planner_pv.calls
    ]
    assert [c["bases"] for c in planner_wf.calls] == [
        c["bases"] for c in planner_pv.calls
    ]


def test_budget_truncation_names_dropped_bases() -> None:
    """TEETH: when the session budget runs out, later bases are named as
    dropped and the planner is not called again.

    Mutation caught: an extra planner call past budget, or a silent drop."""
    planner = _RecordingPlanner([_pq("google")])
    preview = preview_search_plan(
        _profile(),
        _plan(use_ats_site_search=True, ats_platforms=("jobvite",),
              max_queries_per_session=1),
        planner,
        SessionRequest(
            entry=EntryPoint.SEARCH,
            keywords=("Engineer", "Analyst", "Clerk"),
            location="Remote",
            platforms=("jobvite",),
        ),
    )
    assert len(planner.calls) == 1
    assert preview.planned_count == 1
    assert preview.dropped == ("Analyst — Remote", "Clerk — Remote")


def test_engine_rotation_carries_across_bases() -> None:
    """TEETH: the engine after a call's last bound engine leads the next
    call, exactly as the session rotates.

    Mutation caught: restarting the rotation at every base."""
    planner = _RecordingPlanner([_pq("google")])
    preview_search_plan(
        _profile(),
        _plan(use_ats_site_search=True, ats_platforms=("jobvite",)),
        planner,
        SessionRequest(
            entry=EntryPoint.SEARCH,
            keywords=("Engineer", "Analyst"),
            location="Remote",
            platforms=("jobvite",),
        ),
    )
    assert planner.calls[0]["engines"] == ("google", "bing")
    assert planner.calls[1]["engines"] == ("bing", "google")


def test_admin_lock_overrides_request_platforms() -> None:
    """TEETH: an admin lock beats the request — and a request-shaped object
    that is not a real policy cannot fake a lock.

    Mutation caught: reading the lock without the isinstance guard (a
    MagicMock policy would then fabricate one)."""
    from auto_apply.domain.models.policy import AdminPolicy

    planner = _RecordingPlanner([_pq("google")])
    preview = preview_search_plan(
        _profile(),
        _plan(),
        planner,
        SessionRequest(
            entry=EntryPoint.SEARCH,
            keywords=("Engineer",),
            platforms=("jobvite",),
        ),
        admin_policy=AdminPolicy(search_platforms=["greenhouse"]),
    )
    assert planner.calls[0]["platforms"] == ("greenhouse",)
    assert preview.locked_platforms == ("greenhouse",)


def test_missing_planner_falls_back_to_generic_with_reason() -> None:
    """TEETH: targeting engaged but no planner — the preview shows the
    generic search and names the reason, never raises.

    Mutation caught: raising, or showing an empty preview with no reason."""
    preview = preview_search_plan(
        _profile(),
        _plan(use_ats_site_search=True, ats_platforms=("jobvite",)),
        None,
        SessionRequest(
            entry=EntryPoint.SEARCH,
            keywords=("Engineer",),
            platforms=("jobvite",),
        ),
    )
    assert preview.site_search is False
    assert preview.reason_key == "searchplan.preview.reason_no_planner"
    assert preview.planned_count == 1


def test_formatter_renders_all_sections_and_translates() -> None:
    """TEETH: the shared formatter fills every placeholder and renders
    blocked content deterministically for a given locale.

    Mutation caught: an unfilled placeholder, a missing section, or a line
    that does not come from the locale."""
    templates = {
        "searchplan.preview.title": "TITLE",
        "searchplan.preview.mode_targeted": "TARGETED",
        "searchplan.preview.budget": "{planned} of {budget}",
        "searchplan.preview.note_prefix": "NOTE",
        "searchplan.preview.dropped": "DROPPED {targets}",
        "searchplan.preview.admin_lock": "LOCKED {platforms}",
        "searchplan.preview.reason_no_planner": "REASON",
    }
    preview = SearchPlanPreview(
        site_search=True,
        queries=(
            __import__("auto_apply.domain.models.ui_contract", fromlist=["PlannedQueryView"]).PlannedQueryView(
                engine="google", platform="jobvite", form="web", query="q"
            ),
        ),
        notes=("n1",),
        dropped=("x",),
        budget=10,
        planned_count=1,
        reason_key="searchplan.preview.reason_no_planner",
        locked_platforms=("greenhouse",),
    )
    lines = format_search_plan_preview(preview, translate=templates.get)
    text = "\n".join(lines)
    assert "TITLE" in text and "TARGETED" in text
    assert "1 of 10" in text
    assert "NOTE n1" in text
    assert "DROPPED x" in text
    assert "LOCKED greenhouse" in text
    assert "REASON" in text
    assert "{" not in text


def test_factory_builds_offline(minimal_valid_profile) -> None:
    """TEETH: the composition-root factory produces a preview with no
    browser and no network.

    Mutation caught: the factory requiring a driver or raising on a plain
    profile."""
    from auto_apply.infrastructure.composition_root import build_search_plan_preview

    preview = build_search_plan_preview(
        minimal_valid_profile, SessionRequest(entry=EntryPoint.SEARCH)
    )
    assert preview.planned_count >= 1
    assert preview.site_search is False

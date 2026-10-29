"""The plan preview: what a session will search, computed before it starts.

One builder computes the preview from the same inputs the session runs with
— the session plan after the request and any admin lock are applied, and
the same planner the workflow uses — so the preview cannot drift from the
run. The parity pin proves it against the workflow itself. Offline by
construction: no browser, no network.

The plan-update rule lives here exactly once (plan_updates_for_request):
SessionController applies it to the live session plan, the preview applies
it to a copy. The platform rule is a tri-state: None inherits the
profile/config default, () turns targeting off for the session, and a named
list targets exactly those platforms. An admin lock wins over the request,
exactly as it wins over the profile in the registry merge.
"""

from __future__ import annotations

from typing import Any

from auto_apply.domain.models.session_plan import SessionPlan
from auto_apply.domain.models.ui_contract import (
    PlannedQueryView,
    SearchPlanPreview,
    SessionRequest,
)

__all__ = ["plan_updates_for_request", "preview_search_plan"]


def plan_updates_for_request(
    request: SessionRequest, admin_policy: Any
) -> dict[str, Any]:
    """The plan updates a SessionRequest implies — the ONE computation.

    Anything that is not a list/tuple is treated as "no lock": a partial
    double (a MagicMock in tests, an unwired registry) must not be able to
    turn a request into a plan error.
    """
    updates: dict[str, Any] = {"execution_mode": request.execution_mode}
    if isinstance(request.max_results, int) and request.max_results > 0:
        updates["max_results_per_query"] = request.max_results
    if request.providers:
        updates["active_providers"] = request.providers
    if request.platforms is not None:
        locked = getattr(admin_policy, "search_platforms", None)
        if isinstance(locked, (list, tuple)):
            updates["ats_platforms"] = tuple(locked)
            updates["use_ats_site_search"] = bool(locked)
        else:
            updates["ats_platforms"] = tuple(request.platforms)
            updates["use_ats_site_search"] = bool(request.platforms)
    return updates


def _request_bases(profile: Any, request: SessionRequest) -> list[tuple[str, str]]:
    """The (title, location) pairs the session will search.

    The request wins; an empty request falls back to the profile's saved
    titles and locations — the same fallback the task seeder uses, so the
    preview shows the same bases the session would run.
    """
    prefs = getattr(profile, "search_preferences", None)
    titles = list(request.keywords) or list(
        getattr(prefs, "desired_job_titles", None) or []
    )
    if request.location:
        locations = [request.location]
    else:
        locations = list(getattr(prefs, "preferred_locations", None) or [])
    if not locations:
        locations = ["Remote"]
    return [(title, location) for title in titles for location in locations]


def preview_search_plan(
    profile: Any,
    plan: SessionPlan,
    planner: Any,
    request: SessionRequest,
    admin_policy: Any = None,
) -> SearchPlanPreview:
    """Build the preview from the same inputs the session runs with.

    With targeting engaged, each base is planned exactly the way the
    workflow plans it: one planner call per base, the session budget
    decrementing, engines rotating innermost. Without it, the preview shows
    the generic broadcast every enabled engine receives. A missing planner
    degrades to the generic view with the reason named — never an exception.
    """
    updates = plan_updates_for_request(request, admin_policy)
    effective = plan.model_copy(update=updates)

    engines = tuple(effective.active_providers)
    budget = int(effective.max_queries_per_session)
    locked = getattr(admin_policy, "search_platforms", None)
    locked_platforms = tuple(locked) if isinstance(locked, (list, tuple)) else ()

    site_engaged = bool(effective.use_ats_site_search and effective.ats_platforms)
    reason_key = ""
    if site_engaged and planner is None:
        site_engaged = False
        reason_key = "searchplan.preview.reason_no_planner"

    queries: list[PlannedQueryView] = []
    notes: list[str] = []
    dropped: list[str] = []
    bases = _request_bases(profile, request)

    if site_engaged:
        remaining = budget
        offset = 0
        for title, location in bases:
            if remaining <= 0:
                dropped.append(f"{title} — {location}")
                continue
            call_engines = engines
            if call_engines and offset:
                off = offset % len(call_engines)
                call_engines = call_engines[off:] + call_engines[:off]
            planned = planner.plan(
                bases=((title, location, "remote"),),
                engines=call_engines,
                platforms=tuple(effective.ats_platforms),
                date_range=effective.date_range,
                max_results=effective.max_results_per_query,
                budget=remaining,
            )
            notes.extend(note.message for note in planned.notes)
            for query in planned.queries:
                queries.append(
                    PlannedQueryView(
                        engine=query.engine or "",
                        platform=query.platform,
                        form=query.surface_template or "",
                        query=query.raw_query_string,
                        date_range=query.date_range,
                        max_results=query.max_results,
                    )
                )
            dropped.extend(planned.dropped_targets)
            remaining -= len(planned.queries)
            if engines:
                bound = [q.engine for q in planned.queries if q.engine]
                if bound and bound[-1] in engines:
                    offset = (engines.index(bound[-1]) + 1) % len(engines)
    else:
        for title, location in bases[:budget]:
            queries.append(
                PlannedQueryView(
                    engine="",
                    query=f"{title} jobs in {location}",
                    max_results=effective.max_results_per_query,
                )
            )
        for title, location in bases[budget:]:
            dropped.append(f"{title} — {location}")

    return SearchPlanPreview(
        site_search=site_engaged,
        queries=tuple(queries),
        notes=tuple(dict.fromkeys(notes)),
        dropped=tuple(dropped),
        engines=engines,
        budget=budget,
        planned_count=len(queries),
        reason_key=reason_key,
        locked_platforms=locked_platforms,
    )

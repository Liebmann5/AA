"""Pins for the automated site-restricted search planner.

Label honesty: the planner did not exist before this change, so no pin here
could have been run against the old tree. Every pin covers new behaviour and
its docstring names the mutation it catches. The pins marked GUARD protect a
property the feature depends on from future edits.
"""

from __future__ import annotations

import pytest

from auto_apply.domain.models.search_query import QueryRequest
from auto_apply.domain.models.search_surface import (
    SearchSurfaceSpec,
    VerificationStatus,
)
from auto_apply.domain.services.query_composer import compose
from auto_apply.domain.services.search_planner import (
    AUTOMATION_STATUSES,
    PlatformTarget,
    SearchPlanner,
)


def _engine_spec(
    name: str,
    *,
    site_template: str | None = "web",
    with_site_operator: bool = True,
    with_location_field: bool = False,
) -> SearchSurfaceSpec:
    """A minimal valid engine spec: a jobs form and a web form."""
    operators = [
        {
            "name": "phrase",
            "label": "Exact words",
            "explanation": "x",
            "syntax": '"{value}"',
            "status": "vendor",
        },
    ]
    if with_site_operator:
        operators.append(
            {
                "name": "site",
                "label": "Only this site",
                "explanation": "x",
                "syntax": "site:{value}",
                "status": "vendor",
            }
        )
    web_params: list[dict] = [{"name": "q", "source": "query"}]
    if with_location_field:
        web_params.append({"name": "l", "source": "location"})
    data: dict = {
        "name": name,
        "display_name": name.title(),
        "kind": "engine",
        "homepage": f"https://{name}.example",
        "text_query": {
            "or_token": "OR",
            "subject_group": "({content})",
            "phrase_quote": '"',
            "exclude_prefix": "-",
        },
        "urls": {
            "jobs": {
                "base": f"https://{name}.example/jobs",
                "parameters": [{"name": "q", "source": "query"}],
            },
            "web": {
                "base": f"https://{name}.example/search",
                "parameters": web_params,
            },
        },
        "default_url": "web",
        "automation_url": "jobs",
        "operators": operators,
    }
    if site_template is not None:
        data["site_template"] = site_template
    return SearchSurfaceSpec.model_validate(data)


def _target(
    name: str, status: str = "measured", restriction: str | None = None
) -> PlatformTarget:
    return PlatformTarget(
        name=name,
        restriction=(
            restriction if restriction is not None else f"boards.{name}.example"
        ),
        status=status,
    )


def _planner(**overrides) -> SearchPlanner:
    kwargs: dict = {
        "engine_specs": {
            "engone": _engine_spec("engone"),
            "engtwo": _engine_spec("engtwo"),
        },
        "platform_targets": {},
        "is_terminal": None,
        "strategy_name": "per_platform",
    }
    kwargs.update(overrides)
    return SearchPlanner(**kwargs)


def _plan(planner: SearchPlanner, **overrides):
    kwargs: dict = {
        "bases": (("Engineer", "", "remote"),),
        "engines": ("engone", "engtwo"),
        "platforms": (),
        "date_range": None,
        "max_results": 30,
        "budget": 50,
    }
    kwargs.update(overrides)
    return planner.plan(**kwargs)


def test_only_measured_or_vendor_platforms_are_planned() -> None:
    """NEW SURFACE — the automation verification gate.

    Mutation caught: widening AUTOMATION_STATUSES (e.g. adding third_party or
    unverified), or dropping the status check entirely.
    """
    planner = _planner(
        platform_targets={
            "measuredco": _target("measuredco", "measured"),
            "vendorco": _target("vendorco", "vendor"),
            "thirdco": _target("thirdco", "third_party"),
            "unknownco": _target("unknownco", "unverified"),
        }
    )
    out = _plan(
        planner,
        engines=("engone",),
        platforms=("measuredco", "vendorco", "thirdco", "unknownco"),
    )
    assert [q.platform for q in out.queries] == ["measuredco", "vendorco"]
    notes = " ".join(n.message for n in out.notes)
    assert "thirdco" in notes and "unknownco" in notes
    assert set(AUTOMATION_STATUSES) == {
        VerificationStatus.MEASURED,
        VerificationStatus.VENDOR,
    }


def test_engine_without_a_site_operator_gets_no_site_queries() -> None:
    """NEW SURFACE — refusal-both in automation.

    Mutation caught: emitting a degraded, restriction-less query instead of
    skipping the engine.
    """
    planner = _planner(
        engine_specs={"plain": _engine_spec("plain", with_site_operator=False)},
        platform_targets={"measuredco": _target("measuredco")},
    )
    out = _plan(planner, engines=("plain",), platforms=("measuredco",))
    assert out.queries == ()
    assert any("not planned" in n.message for n in out.notes)


def test_engine_without_a_site_template_gets_no_site_queries() -> None:
    """NEW SURFACE — an engine must declare which form carries site queries.

    Mutation caught: defaulting site queries to the automation (jobs) form.
    """
    planner = _planner(
        engine_specs={"engone": _engine_spec("engone", site_template=None)},
        platform_targets={"measuredco": _target("measuredco")},
    )
    out = _plan(planner, engines=("engone",), platforms=("measuredco",))
    assert out.queries == ()
    assert any("no form for site-restricted" in n.message for n in out.notes)


def test_queries_are_composed_through_the_catalog_composer() -> None:
    """NEW SURFACE (differential) — the planner's text equals compose()'s
    output for the same inputs, byte for byte.

    Mutation caught: hand-formatting a site: clause anywhere in the planner.
    """
    spec = _engine_spec("engone")
    planner = _planner(
        engine_specs={"engone": spec},
        platform_targets={
            "greenhouse": _target("greenhouse", restriction="boards.greenhouse.io")
        },
    )
    out = _plan(
        planner,
        bases=(("Software Engineer", "", "remote"),),
        engines=("engone",),
        platforms=("greenhouse",),
    )
    expected = compose(
        QueryRequest(
            surface="engone",
            site="boards.greenhouse.io",
            phrases=("Software Engineer",),
        ),
        spec,
    ).bar_text
    assert [q.raw_query_string for q in out.queries] == [expected]


def test_the_planner_formats_no_site_clause_itself() -> None:
    """GUARD — composition is single-sourced in the catalog composer.

    Mutation caught: any hand-built site: clause appearing in the planner
    module, or the compose import disappearing.
    """
    import inspect

    import auto_apply.domain.services.search_planner as planner_module

    source = inspect.getsource(planner_module)
    assert "site:{" not in source
    assert '"site:" +' not in source
    assert "'site:' +" not in source
    assert callable(getattr(planner_module, "compose", None))


def test_engines_rotate_innermost_platforms_outermost() -> None:
    """NEW SURFACE — no engine host receives consecutive queries while
    another enabled target remains.

    Mutation caught: swapping the loop nesting (engine-outer).
    """
    planner = _planner(
        platform_targets={
            "greenhouse": _target("greenhouse"),
            "lever": _target("lever"),
        }
    )
    out = _plan(planner, platforms=("greenhouse", "lever"))
    assert [(q.platform, q.engine) for q in out.queries] == [
        ("greenhouse", "engone"),
        ("greenhouse", "engtwo"),
        ("lever", "engone"),
        ("lever", "engtwo"),
    ]


def test_budget_truncates_and_reports_dropped_targets() -> None:
    """NEW SURFACE — the budget is a hard cap, never exceeded, never silent.

    Mutation caught: an off-by-one (>= vs >), or dropping without a note.
    """
    planner = _planner(
        platform_targets={
            "greenhouse": _target("greenhouse"),
            "lever": _target("lever"),
        }
    )
    out = _plan(planner, platforms=("greenhouse", "lever"), budget=3)
    assert len(out.queries) == 3
    assert len(out.dropped_targets) == 1
    assert any("budget" in n.message.lower() for n in out.notes)


def test_planning_is_deterministic() -> None:
    """NEW SURFACE — same inputs, same plan, twice.

    Mutation caught: introducing unordered iteration (sets) or chance into
    planning.
    """
    planner = _planner(
        platform_targets={
            "greenhouse": _target("greenhouse"),
            "lever": _target("lever"),
        }
    )
    first = _plan(planner, platforms=("greenhouse", "lever"))
    second = _plan(planner, platforms=("greenhouse", "lever"))
    assert first == second


def test_location_is_appended_only_when_the_engine_form_lacks_a_location_field() -> None:
    """NEW SURFACE — location handling follows the engine form's fields.

    Mutation caught: always appending (duplicating the location into engines
    that carry it in the URL) or never appending (dropping it on web forms).
    """
    planner = _planner(
        engine_specs={
            "withloc": _engine_spec("withloc", with_location_field=True),
            "withoutloc": _engine_spec("withoutloc"),
        },
        platform_targets={"greenhouse": _target("greenhouse")},
    )
    out = _plan(
        planner,
        bases=(("Engineer", "Austin", "remote"),),
        engines=("withloc", "withoutloc"),
        platforms=("greenhouse",),
    )
    by_engine = {q.engine: q for q in out.queries}
    assert "Austin" not in by_engine["withloc"].raw_query_string
    assert by_engine["withloc"].location == "Austin"
    assert by_engine["withoutloc"].raw_query_string.endswith("Austin")


def test_terminal_restrictions_are_never_planned() -> None:
    """NEW SURFACE — a success/confirm page shape is never a search target.

    Mutation caught: dropping the is_terminal check.
    """
    planner = _planner(
        platform_targets={
            "doneco": _target(
                "doneco", restriction="boards.example.com/apply/success"
            )
        },
        is_terminal=lambda url: "success" in url,
    )
    out = _plan(planner, engines=("engone",), platforms=("doneco",))
    assert out.queries == ()
    assert any("terminal" in n.message for n in out.notes)


def test_an_unknown_strategy_falls_back_to_per_platform_with_a_warning() -> None:
    """NEW SURFACE — a bad strategy name degrades, loudly.

    Mutation caught: raising on an unknown strategy, or using it silently.
    """
    planner = _planner(
        strategy_name="grouped_or",
        platform_targets={"greenhouse": _target("greenhouse")},
    )
    out = _plan(planner, platforms=("greenhouse",))
    assert [q.platform for q in out.queries] == ["greenhouse", "greenhouse"]
    assert any("Unknown site-search strategy" in n.message for n in out.notes)


def test_a_multi_platform_group_is_refused_to_per_platform() -> None:
    """NEW SURFACE — grouped composition is refused loudly until the
    composer supports it.

    Mutation caught: silently splitting a multi-platform group, or blindly
    trusting a strategy's groups.
    """

    class GroupAll:
        name = "group_all"

        def group(self, platforms):
            return [tuple(platforms)]

    planner = _planner(
        strategies=[GroupAll()],
        strategy_name="group_all",
        platform_targets={
            "greenhouse": _target("greenhouse"),
            "lever": _target("lever"),
        },
        engine_specs={"engone": _engine_spec("engone")},
    )
    out = _plan(planner, engines=("engone",), platforms=("greenhouse", "lever"))
    assert [q.platform for q in out.queries] == ["greenhouse", "lever"]
    assert any("multi-platform group" in n.message for n in out.notes)


def test_an_unknown_platform_is_skipped_with_a_warning() -> None:
    """NEW SURFACE.

    Mutation caught: planning a platform with no descriptor (an invented
    restriction).
    """
    out = _plan(_planner(), engines=("engone",), platforms=("nosuchco",))
    assert out.queries == ()
    assert any("nosuchco" in n.message for n in out.notes)


def test_an_engine_missing_from_the_catalog_is_skipped() -> None:
    """NEW SURFACE.

    Mutation caught: planning on an engine with no catalog entry.
    """
    planner = _planner(platform_targets={"greenhouse": _target("greenhouse")})
    out = _plan(planner, engines=("noengine",), platforms=("greenhouse",))
    assert out.queries == ()
    assert any("noengine" in n.message for n in out.notes)


def test_nothing_to_target_plans_nothing_without_raising() -> None:
    """NEW SURFACE — degradation: empty inputs produce an empty plan, not an
    exception.

    Mutation caught: indexing into an empty list, or treating empty input as
    an error.
    """
    planner = _planner(platform_targets={"greenhouse": _target("greenhouse")})
    assert _plan(planner, engines=(), platforms=("greenhouse",)).queries == ()
    assert _plan(planner, platforms=()).queries == ()
    assert _plan(planner, bases=()).queries == ()


def test_date_range_and_result_cap_are_carried_onto_every_query() -> None:
    """NEW SURFACE.

    Mutation caught: dropping date_range/max_results when converting planner
    output.
    """
    planner = _planner(platform_targets={"greenhouse": _target("greenhouse")})
    out = _plan(
        planner,
        engines=("engone",),
        platforms=("greenhouse",),
        date_range="week",
        max_results=15,
    )
    assert out.queries
    for query in out.queries:
        assert query.date_range == "week"
        assert query.max_results == 15
        assert query.engine == "engone"
        assert query.surface_template == "web"


def test_engines_and_platforms_preserve_the_caller_order() -> None:
    """GUARD — planning order follows the caller's order, not dict/set order.

    Mutation caught: iterating a set of targets or re-sorting them.
    """
    planner = _planner(
        platform_targets={
            "zeta": _target("zeta"),
            "alpha": _target("alpha"),
        }
    )
    out = _plan(
        planner,
        engines=("engtwo", "engone"),
        platforms=("zeta", "alpha"),
    )
    assert [(q.platform, q.engine) for q in out.queries] == [
        ("zeta", "engtwo"),
        ("zeta", "engone"),
        ("alpha", "engtwo"),
        ("alpha", "engone"),
    ]

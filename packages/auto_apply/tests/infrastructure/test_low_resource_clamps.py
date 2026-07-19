"""The low-resource clamps must reach the code they are supposed to clamp.

The Worst-Case-User Contract, unenforced
----------------------------------------
``registry._merge_config()`` computes a low-resource override block::

    if is_low_resource:
        low_resource_overrides = {
            "max_applications_per_session": min(..., 25),
            "max_discovery_results_per_query": min(..., 15),
            "min_action_delay_ms": max(..., 800),
            "discovery_strategy": "static_fetch",
            "enable_fingerprint_spoofing": False,
        }
        merged.update(low_resource_overrides)

Two of those five have no runtime reader at all:
``max_discovery_results_per_query`` and ``min_action_delay_ms``. They are
computed on every low-resource startup, merged into the effective config, and
never consulted. On a 2GB machine AA decides to mine 15 results instead of 30,
then mines 30.

Five names, one concept
-----------------------
The result-per-query cap exists under five different names:

1. ``max_discovery_results_per_query`` — flat YAML key + registry fallback
2. ``discovery.max_pages_per_query``   — nested YAML key
3. ``SessionPlan.max_results_per_query`` — reads ``disc["max_results_per_query"]``,
   a key the ``discovery`` section does not contain, so it is permanently the
   hardcoded 30 and is read by nobody
4. ``ExecutionMode.max_discovery_results_per_query`` — a fourth default of 30
5. ``JobSearchPreferences.max_search_results`` — what ``serp_strategy.py:147``
   actually reads, via ``getattr(self.prefs, "max_search_results", 30)``

Only #5 reaches the miner. ``max_search_results`` **is not a field on
JobSearchPreferences**, so the getattr default fires on every run and
``MAX_TOTAL_JOBS`` is 30 on every machine, forever — independent of the YAML,
the user's settings, the admin policy, and the low-resource clamp.

``getattr`` with a default is what makes this silent. A plain attribute access
would have raised ``AttributeError`` on the first run three years ago.

This is §14: a capability profile that is computed but does not alter component
construction or execution is not integrated. It is the single most important
line of code for the machine AA exists to serve, and it is dead.
"""

from __future__ import annotations

import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "auto_apply"


def _config_readers(key: str) -> list[str]:
    """Files that read `key` out of a config mapping, excluding the registry."""
    out: list[str] = []
    for py in SRC.rglob("*.py"):
        if py.name == "registry.py":
            continue  # where the key is defined and clamped, not consumed
        for i, ln in enumerate(
            py.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if re.search(rf"""["']{re.escape(key)}["']""", ln) and "get" in ln.lower():
                out.append(f"{py.relative_to(SRC).as_posix()}:{i}")
    return out


def test_serp_strategy_result_cap_is_a_real_field() -> None:
    """The SERP result cap must be a resolved value, not a phantom getattr default.

    Structural replacement for the original (which required a max_search_results
    field on JobSearchPreferences). The cap is now a typed policy value carried on
    SearchInstruction and injected into the strategy, so it can honour the
    low-resource clamp. This asserts the fix is in place:

      * SearchInstruction has a typed ``max_results`` field (the carrier), and
      * serp_strategy no longer reads the phantom ``getattr(self.prefs,
        'max_search_results', ...)`` that fired 30 on every machine.

    Teeth (must FAIL pre-fix): before this stage SearchInstruction has no
    max_results field, and serp_strategy still contains the getattr.
    """
    from auto_apply.domain.models.search_instruction import (  # noqa: PLC0415
        SearchInstruction,
    )

    assert "max_results" in SearchInstruction.model_fields, (
        "SearchInstruction has no max_results field, so the per-query result cap "
        "has no typed carrier from the session plan down to the scraper."
    )
    serp_src = (
        SRC / "adapters" / "secondary" / "discovery" / "strategies"
        / "serp_strategy.py"
    ).read_text(encoding="utf-8")
    assert 'getattr(self.prefs, "max_search_results"' not in serp_src, (
        "serp_strategy still reads getattr(self.prefs, 'max_search_results', 30) "
        "— a phantom field, so MAX_TOTAL_JOBS is 30 on every machine regardless of "
        "the low-resource clamp. Inject the resolved cap instead."
    )


def test_low_resource_result_clamp_reaches_a_consumer() -> None:
    """min(x, 15) on a 2GB machine must actually cap something.

    Behavioral replacement for the string-grep original (which looked for a
    ``.get("max_discovery_results_per_query")`` reader — the pre-typed-config
    pattern). The clamped value now flows typed: merged config -> SessionPlan
    .max_results_per_query -> SearchInstruction.max_results -> the scraper. This
    proves the clamp reaches the plan value a consumer reads, and that the
    workflow threads it onto the instruction.

    Teeth (must FAIL pre-fix): before this stage the workflow never sets
    SearchInstruction.max_results from the plan, so the clamp reaches nothing.
    """
    import auto_apply.infrastructure.registry as reg  # noqa: PLC0415
    from auto_apply.domain.models.session_plan import SessionPlan  # noqa: PLC0415
    from auto_apply.domain.models.timing import BehaviorParameters  # noqa: PLC0415

    low = reg.CapabilitiesRegistry._merge_config(
        runtime_defaults=dict(reg._RUNTIME_DEFAULTS),
        user_settings={}, admin_policy=None, is_low_resource=True,
    )
    assert low["max_discovery_results_per_query"] == 15, low
    plan = SessionPlan.from_config(
        session_id="t", config=low, behavior=BehaviorParameters.from_config(low),
    )
    assert plan.max_results_per_query == 15, (
        "the low-resource clamp did not reach SessionPlan.max_results_per_query."
    )
    wf_src = (
        SRC / "application" / "workflows" / "discovery_workflow.py"
    ).read_text(encoding="utf-8")
    assert "max_results=self._plan.max_results_per_query" in wf_src, (
        "the workflow never threads plan.max_results_per_query onto "
        "SearchInstruction, so the clamped cap is computed and discarded."
    )


def test_low_resource_delay_floor_reaches_a_consumer() -> None:
    """max(x, 800) on a 2GB machine must actually slow something down."""
    readers = _config_readers("min_action_delay_ms")
    assert readers, (
        "registry._merge_config() raises min_action_delay_ms to a floor of 800ms "
        "in low-resource mode, and nothing reads it. The floor is computed and "
        "discarded, so a slow machine is driven at the same rate as a fast one."
    )

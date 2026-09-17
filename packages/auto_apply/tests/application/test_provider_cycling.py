"""Provider-order cycling: seeded, reproducible, lossless.

Discovery shuffles which SERP provider (Google/Bing/Indeed) is tried first each
search, so runs are not always Google-first (a CAPTCHA magnet). With a session
seed the shuffle is reproducible; without one it is non-deterministic. These pins
prove reproducibility, per-search variation, and that no provider is lost or the
input mutated.

Turn 2 (stage U3) adds the fan-out filter pins: the session plan's
active_providers now constrains which engines run at all.
"""
from __future__ import annotations

import random
from unittest.mock import MagicMock

from auto_apply.application.workflows.discovery_workflow import DiscoveryWorkflow
from auto_apply.domain.models.session_plan import SessionPlan


def _workflow(rng):
    return DiscoveryWorkflow(
        profile=MagicMock(),
        providers=[],
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        dedup=MagicMock(),
        text_matcher=MagicMock(),
        provider_order_rng=rng,
    )


def _workflow_with(providers, plan=None, rng=None):
    return DiscoveryWorkflow(
        profile=MagicMock(),
        providers=list(providers),
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        dedup=MagicMock(),
        text_matcher=MagicMock(),
        plan=plan,
        provider_order_rng=rng,
    )


def _provider(name):
    p = MagicMock()
    p.name = name
    return p


def _names(providers):
    return [p.name for p in providers]


_PROVIDERS = [_provider("Google"), _provider("Bing"), _provider("Indeed")]


def test_same_seed_is_reproducible():
    a = _names(_workflow(random.Random(42))._order_providers(_PROVIDERS))
    b = _names(_workflow(random.Random(42))._order_providers(_PROVIDERS))
    assert a == b


def test_order_contains_all_providers():
    ordered = _workflow(random.Random(3))._order_providers(_PROVIDERS)
    assert sorted(_names(ordered)) == sorted(_names(_PROVIDERS))


def test_input_list_is_not_mutated():
    before = _names(_PROVIDERS)
    _workflow(random.Random(9))._order_providers(_PROVIDERS)
    assert _names(_PROVIDERS) == before


def test_stream_advances_across_searches():
    """Successive searches get different orders (reproducibly) from one RNG."""
    w = _workflow(random.Random(42))
    orders = [tuple(_names(w._order_providers(_PROVIDERS))) for _ in range(6)]
    assert len(set(orders)) > 1, "provider order never varied across searches"


def test_single_provider_is_returned_unshuffled():
    only = [_provider("Only")]
    assert _names(_workflow(random.Random(1))._order_providers(only)) == ["Only"]


def test_empty_provider_list_is_safe():
    assert _workflow(random.Random(1))._order_providers([]) == []


def test_default_rng_when_none_still_orders_losslessly():
    # No injected rng -> a fresh unseeded Random; order still contains all providers.
    wf = DiscoveryWorkflow(
        profile=MagicMock(), providers=[], task_queue=MagicMock(),
        event_bus=MagicMock(), dedup=MagicMock(), text_matcher=MagicMock(),
    )
    ordered = wf._order_providers(_PROVIDERS)
    assert sorted(_names(ordered)) == sorted(_names(_PROVIDERS))


# ─────────────────────────────────────────────────────────────────────────────
# Turn 2 (stage U3): the plan's active_providers filters the fan-out
# ─────────────────────────────────────────────────────────────────────────────

def test_plan_active_providers_filters_the_fan_out():
    """TEETH: a plan naming one engine fans out to that engine only.

    Fails pre-turn-2 — _initialize_sources ignored the plan entirely and
    returned every provider it was given, so a SessionRequest naming one
    engine would have run all three anyway."""
    providers = [_provider("Google"), _provider("Bing"), _provider("Indeed")]
    plan = SessionPlan(session_id="pin", active_providers=("bing",))
    wf = _workflow_with(providers, plan=plan)
    assert _names(wf._initialize_sources()) == ["Bing"]


def test_default_plan_fans_out_to_every_provider():
    """GUARD: the default plan vocabulary runs every engine — the menu's
    default choice must not narrow what a user already had."""
    providers = [_provider("Google"), _provider("Bing"), _provider("Indeed")]
    wf = _workflow_with(providers)
    assert _names(wf._initialize_sources()) == ["Google", "Bing", "Indeed"]

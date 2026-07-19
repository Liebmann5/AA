"""The feedback loop must stay closed and must not fabricate a plan.

Context
-------
``test_feedback_loop_closure.py`` pins that ``record_outcome`` has a caller and
that ``plan.is_deterministic`` reaches a consumer. Those go green once the loop
is wired. They do not, however, guard the shape of the wiring — and the natural
mistake is the one ``DiscoveryWorkflow`` already made::

    if plan:
        self._plan = plan
    else:
        self._plan = SessionPlan(session_id="discovery-fallback")  # fail-open

A defaulted or fabricated plan means a caller that forgets to inject one gets a
silently non-deterministic run — the same fail-open shape as the cooldown
default and every getattr stand-in in this audit. ``ApplicationsWorkflow.plan``
must be required, so a missing plan raises at construction instead of inventing
determinism state.

These tests also verify the write path honours the determinism flag end to end:
``PageAnalysisRouter.record_tier_outcome`` must pass ``is_deterministic``
straight through to the feedback service (which drops the write on seeded runs),
never swallow or default it.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from auto_apply.application.services.page_analysis_router import PageAnalysisRouter
from auto_apply.application.workflows.applications_workflow import ApplicationsWorkflow


def test_applications_workflow_plan_is_required() -> None:
    param = inspect.signature(ApplicationsWorkflow.__init__).parameters.get("plan")
    assert param is not None, (
        "ApplicationsWorkflow does not accept a plan. It needs one to pass "
        "plan.is_deterministic into the feedback loop."
    )
    assert param.default is inspect.Parameter.empty, (
        "ApplicationsWorkflow.plan has a default. A caller that omits it would "
        "get a fabricated or non-deterministic plan silently — the fail-open "
        "shape DiscoveryWorkflow fell into. Make plan required so a missing "
        "injection raises at construction."
    )
    assert param.kind is inspect.Parameter.KEYWORD_ONLY, (
        "plan should be keyword-only so it is injected explicitly by name."
    )


def test_router_passes_determinism_through() -> None:
    """A deterministic run must reach the service with is_deterministic=True."""
    service = MagicMock()
    router = PageAnalysisRouter.__new__(PageAnalysisRouter)
    router._feedback_service = service
    router._ats_registry = None

    router.record_tier_outcome(
        "https://example.com/apply",
        "<html><form></form></html>",
        "CSS_EXTRACTION",
        True,
        is_deterministic=True,
    )
    assert service.record_outcome.called, "router did not reach the feedback service"
    _, kwargs = service.record_outcome.call_args
    assert kwargs.get("is_deterministic") is True, (
        "router.record_tier_outcome dropped or altered is_deterministic. On a "
        "seeded run this would let the store be written and break reproducibility."
    )


def test_router_write_is_a_noop_without_a_service() -> None:
    """Low-resource path: no feedback service means no crash, no write."""
    router = PageAnalysisRouter.__new__(PageAnalysisRouter)
    router._feedback_service = None
    router._ats_registry = None
    # Must not raise.
    router.record_tier_outcome("u", "<html></html>", "FULL_MATH_DOM", False, is_deterministic=False)

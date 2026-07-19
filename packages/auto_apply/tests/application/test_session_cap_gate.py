"""The session application cap is a promise, and RESEARCH_AUDIT is the only exit.

``test_application_caps.py`` pins *that* a gate exists (an AST comparison of a
running count against ``max_applications_per_session``). This file pins how the
gate behaves, so the enforcement cannot later be quietly turned into a sentinel
or lose its one legitimate exemption:

1. The cap is enforced. When the submitted count reaches
   ``max_applications_per_session`` the orchestrator reports the cap as reached
   and stops applying. Applications are irreversible; over-applying cannot be
   undone.

2. ``0`` means zero. "Unlimited" is never expressed as a magic cap value —
   a cap of 0 applies to nothing. This is what stops a future refactor from
   reintroducing ``0 == unlimited``, which would silently uncap every session
   whose cap was left at the default-cleared value.

3. RESEARCH_AUDIT is exempt, and it is the *only* exemption. Uncapped volume is
   the explicit, granted purpose of a research-audit session — a mode, not a
   number. A researcher gets unlimited applications by being granted the mode,
   never by setting the cap to a sentinel.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from auto_apply.application.agent.orchestrator import AgentOrchestrator
from auto_apply.domain.models.session_plan import SessionExecutionMode, SessionPlan


def _orch(mode: SessionExecutionMode, cap: int, submitted: int) -> AgentOrchestrator:
    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.session_plan = SessionPlan(
        session_id="cap-test",
        execution_mode=mode,
        max_applications_per_session=cap,
    )
    orch.context = MagicMock()
    orch.context.stats.applications_submitted = submitted
    return orch


def test_cap_not_reached_below_limit() -> None:
    assert _orch(SessionExecutionMode.FULL_PIPELINE, 50, 49)._session_cap_reached() is False


def test_cap_reached_at_limit() -> None:
    assert _orch(SessionExecutionMode.FULL_PIPELINE, 50, 50)._session_cap_reached() is True


def test_cap_reached_above_limit() -> None:
    assert _orch(SessionExecutionMode.FULL_PIPELINE, 50, 99)._session_cap_reached() is True


def test_zero_cap_means_zero_not_unlimited() -> None:
    """A cap of 0 must stop immediately — 0 is not a sentinel for unlimited."""
    assert _orch(SessionExecutionMode.FULL_PIPELINE, 0, 0)._session_cap_reached() is True


def test_research_audit_is_exempt_from_the_cap() -> None:
    """Research audits are uncapped by their granted mode, at any count."""
    assert _orch(SessionExecutionMode.RESEARCH_AUDIT, 50, 10_000)._session_cap_reached() is False


def test_research_audit_ignores_a_zero_cap_too() -> None:
    """The exemption is the mode, independent of the cap value."""
    assert _orch(SessionExecutionMode.RESEARCH_AUDIT, 0, 10_000)._session_cap_reached() is False


def test_missing_plan_fails_closed() -> None:
    """No plan wired is a bug; refuse to apply rather than invent an unbounded cap."""
    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.session_plan = None
    orch.context = MagicMock()
    orch.context.stats.applications_submitted = 0
    assert orch._session_cap_reached() is True

"""Behavioral pins for the three previously-unheard published events.

``tests/architecture/test_event_wiring.py`` asserts these events have a
subscriber. This file asserts the subscribers DO something: a handler that
merely exists is the same defect wearing a subscription.

    * CAPTCHA_REQUIRES_MANUAL_SOLVE — the terminal-hang fix: the escalation
      must have a release path, and must never leave the session paused.
    * PROVIDER_TIMED_OUT — the orchestrator must record and reschedule.
    * REDIRECT_TO_LIST_DETECTED — the orchestrator must enqueue a
      DISCOVER_COMPANY WorkUnit.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from auto_apply.application.agent.context import ExecutionContext
from auto_apply.application.agent.event_bus import EventBus
from auto_apply.application.agent.orchestrator import AgentOrchestrator
from auto_apply.application.agent.state_machine import AgentState, StateMachine
from auto_apply.domain.events import Event
from auto_apply.domain.models.work_unit import TaskType


def _make_orchestrator() -> AgentOrchestrator:
    """Partial orchestrator: only what the event handlers touch.

    State is advanced to RUNNING so the pre-HITL restore target in the
    release-path pins is RUNNING rather than IDLE. ``_driver`` is set to None
    to mirror what the real ``__init__`` does at construction — the resolver
    path in _handle_captcha passes it to the resolver.
    """
    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.event_bus = EventBus()
    orch.state_machine = StateMachine(initial_state=AgentState.IDLE)
    orch.state_machine.transition_to(AgentState.INITIALIZING)
    orch.state_machine.transition_to(AgentState.RUNNING)
    orch.context = ExecutionContext(profile=MagicMock(), session_id="test")
    orch.task_queue = MagicMock()
    orch._captcha_resolver = None
    orch._driver = None
    orch._approval_gate = None
    orch._seen_redirect_urls = set()
    orch.paused = False
    orch.running = True
    orch._register_event_handlers()
    return orch


# ─────────────────────────────────────────────────────────────────────────────
# Wiring: all three events have exactly one subscriber
# ─────────────────────────────────────────────────────────────────────────────


def test_all_three_events_have_a_subscriber():
    orch = _make_orchestrator()
    assert orch.event_bus.subscriber_count(Event.CAPTCHA_REQUIRES_MANUAL_SOLVE) == 1
    assert orch.event_bus.subscriber_count(Event.PROVIDER_TIMED_OUT) == 1
    assert orch.event_bus.subscriber_count(Event.REDIRECT_TO_LIST_DETECTED) == 1


# ─────────────────────────────────────────────────────────────────────────────
# CAPTCHA — the terminal-hang fix
# ─────────────────────────────────────────────────────────────────────────────


def test_captcha_escalation_records_and_prompts_with_manual_solve_checkpoint():
    orch = _make_orchestrator()
    calls = []

    def gate(question, options, checkpoint=None, timeout=300.0):
        calls.append((question, list(options), checkpoint))
        return "solved"

    orch.set_approval_gate(gate)
    task = SimpleNamespace(
        id="task-1",
        payload={
            "challenge_url": "https://example.com/challenge",
            "challenge_type": "recaptcha",
        },
    )

    orch._handle_captcha(task)

    assert calls, "the HITL gate was never called — the prompt path is broken"
    _, options, checkpoint = calls[0]
    assert checkpoint == "CAPTCHA_REQUIRES_MANUAL_SOLVE"
    assert "solved" in options
    assert "stop" in options
    assert orch.context.stats.captchas_escalated == 1
    assert orch.paused is False, "the old unrecoverable pause() survived"


def test_captcha_gate_granted_restores_running_state():
    """The release path, asserted end to end: AWAITING_HUMAN during the gate,
    RUNNING after it. The current code cannot reach this state at all — which
    is the bug, and these teeth."""
    orch = _make_orchestrator()
    states_during_gate = []

    def gate(question, options, checkpoint=None, timeout=300.0):
        orch.event_bus.publish(Event.HUMAN_APPROVAL_REQUESTED, {
            "context_id": "c1",
            "checkpoint": checkpoint,
            "question": question,
            "options": options,
        })
        states_during_gate.append(orch.state_machine.current_state)
        orch.event_bus.publish(Event.HUMAN_APPROVAL_GRANTED, {
            "context_id": "c1",
            "choice": "solved",
        })
        return "solved"

    orch.set_approval_gate(gate)
    orch._handle_captcha(SimpleNamespace(id="t2", payload={}))

    assert states_during_gate == [AgentState.AWAITING_HUMAN]
    assert orch.state_machine.current_state == AgentState.RUNNING


def test_captcha_gate_timeout_does_not_stick_in_awaiting_human():
    """A gate that returns without a grant (the 300 s timeout path) must not
    leave the state machine stalled in AWAITING_HUMAN."""
    orch = _make_orchestrator()

    def gate(question, options, checkpoint=None, timeout=300.0):
        orch.event_bus.publish(Event.HUMAN_APPROVAL_REQUESTED, {
            "context_id": "c2",
            "checkpoint": checkpoint,
            "question": question,
            "options": options,
        })
        # No GRANTED publish — simulates request_approval's timeout return.
        return "skip"

    orch.set_approval_gate(gate)
    orch._handle_captcha(SimpleNamespace(id="t3", payload={}))

    assert orch.state_machine.current_state == AgentState.RUNNING, (
        "the gate returned without a grant and nothing resumed the session — "
        "the timeout path re-introduces the stall"
    )


def test_captcha_without_wired_gate_records_and_continues_without_pause():
    """THE teeth: the current code pauses forever here; the fix must not."""
    orch = _make_orchestrator()  # no gate wired
    orch._handle_captcha(SimpleNamespace(
        id="t4",
        payload={
            "challenge_url": "https://example.com/c",
            "challenge_type": "hcaptcha",
        },
    ))
    assert orch.paused is False
    assert orch.state_machine.current_state != AgentState.PAUSED
    assert orch.context.stats.captchas_escalated == 1


def test_captcha_resolver_success_does_not_escalate():
    orch = _make_orchestrator()
    orch._captcha_resolver = MagicMock()
    orch._captcha_resolver.resolve.return_value = True
    gate = MagicMock()
    orch.set_approval_gate(gate)

    orch._handle_captcha(SimpleNamespace(id="t5", payload={}))

    gate.assert_not_called()
    assert orch.state_machine.current_state == AgentState.RUNNING
    assert orch.context.stats.captchas_escalated == 0


def test_captcha_resolver_failure_escalates_to_gate():
    orch = _make_orchestrator()
    orch._captcha_resolver = MagicMock()
    orch._captcha_resolver.resolve.return_value = False
    gate = MagicMock(return_value="solved")
    orch.set_approval_gate(gate)

    orch._handle_captcha(SimpleNamespace(id="t6", payload={}))

    gate.assert_called_once()
    assert orch.context.stats.captchas_escalated == 1


# ─────────────────────────────────────────────────────────────────────────────
# PROVIDER_TIMED_OUT
# ─────────────────────────────────────────────────────────────────────────────


def test_provider_timeout_records_and_reschedules_matching_task():
    orch = _make_orchestrator()
    orch.context.current_work_unit = SimpleNamespace(id="worker-9")
    orch.task_queue.reschedule_for_retry.return_value = True

    orch.event_bus.publish(Event.PROVIDER_TIMED_OUT, {
        "worker_id": "worker-9",
        "provider_name": "google",
        "last_action": "harvesting serp",
    })

    assert orch.context.stats.provider_timeouts == 1
    orch.task_queue.reschedule_for_retry.assert_called_once()
    task_id, error_msg = orch.task_queue.reschedule_for_retry.call_args[0]
    assert task_id == "worker-9"
    assert "google" in error_msg


def test_provider_timeout_without_matching_task_records_only():
    orch = _make_orchestrator()
    orch.context.current_work_unit = SimpleNamespace(id="other-task")

    orch.event_bus.publish(Event.PROVIDER_TIMED_OUT, {
        "worker_id": "worker-9",
        "provider_name": "bing",
        "last_action": "harvesting",
    })

    assert orch.context.stats.provider_timeouts == 1
    orch.task_queue.reschedule_for_retry.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# REDIRECT_TO_LIST_DETECTED
# ─────────────────────────────────────────────────────────────────────────────


def test_redirect_to_list_enqueues_company_discovery():
    orch = _make_orchestrator()

    orch.event_bus.publish(Event.REDIRECT_TO_LIST_DETECTED, {
        "url": "https://acme.example.com/careers",
        "job_title": "Software Engineer",
    })

    orch.task_queue.queue_task.assert_called_once()
    unit = orch.task_queue.queue_task.call_args[0][0]
    assert unit.task_type == TaskType.DISCOVER_COMPANY
    assert unit.payload["careers_url"] == "https://acme.example.com/careers"


def test_redirect_to_list_does_not_enqueue_same_url_twice():
    orch = _make_orchestrator()
    payload = {"url": "https://acme.example.com/careers", "job_title": "X"}

    orch.event_bus.publish(Event.REDIRECT_TO_LIST_DETECTED, payload)
    orch.event_bus.publish(Event.REDIRECT_TO_LIST_DETECTED, payload)

    assert orch.task_queue.queue_task.call_count == 1


def test_redirect_to_list_without_url_does_not_enqueue():
    orch = _make_orchestrator()

    orch.event_bus.publish(Event.REDIRECT_TO_LIST_DETECTED, {"job_title": "X"})

    orch.task_queue.queue_task.assert_not_called()

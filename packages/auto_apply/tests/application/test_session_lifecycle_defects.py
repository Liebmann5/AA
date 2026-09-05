"""Teeth pins for the two defects the live run proved: the subscription race
and the ghost CAPTCHA task.

1. SUBSCRIPTION RACE — a dashboard that binds AFTER the orchestrator
   published HUMAN_APPROVAL_REQUESTED must still render the open gate,
   because gate state is readable (SessionController.get_pending_approvals),
   not a one-shot broadcast. A static wiring pin cannot catch ordering;
   these behavioral pins are what catches it.

2. GHOST CAPTCHA TASK — a HANDLE_CAPTCHA task restored from a dead session
   references a page that provably no longer exists (the driver is closed in
   teardown). discard_stale_reactive_tasks() must mark it SKIPPED with a
   recorded reason before any dispatch, and must leave URL-addressable tasks
   untouched.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from auto_apply.adapters.primary.cli.dashboard import CLIDashboard
from auto_apply.adapters.secondary.persistence.database import DatabaseManager
from auto_apply.application.agent.event_bus import EventBus
from auto_apply.application.services.session_controller import SessionController
from auto_apply.domain.models.task_priority import TaskPriority
from auto_apply.domain.models.work_unit import TaskType, WorkUnit


def _make_controller() -> SessionController:
    """Partial SessionController: only what the gate/recovery paths touch."""
    sc = SessionController.__new__(SessionController)
    sc.registry = MagicMock()
    sc.db = MagicMock()
    sc.orchestrator = MagicMock()
    sc.orchestrator.event_bus = EventBus()
    sc._agent_thread = None
    sc._pending_approvals = {}
    sc._approvals_lock = threading.Lock()
    return sc


def _wait_for_open_gate(sc: SessionController, timeout_s: float = 5.0) -> list[dict]:
    """Poll until a gate is open (or time out), returning the pending list."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        pending = sc.get_pending_approvals()
        if pending:
            return pending
        time.sleep(0.01)
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Defect 1 — the subscription race
# ─────────────────────────────────────────────────────────────────────────────


def test_late_subscriber_sees_already_open_gate():
    """A gate opened before any UI subscribed must still be renderable.

    This is the race the live log showed: 'HITL gate open' preceded the
    dashboard's subscribe line, and the session waited 3.5 minutes on an
    invisible prompt. With readable gate state, a late bind renders anyway.
    """
    sc = _make_controller()
    outcomes: list[str] = []
    t = threading.Thread(
        target=lambda: outcomes.append(
            sc.request_approval(
                "A CAPTCHA is blocking the current page. Solve it in the "
                "browser window, then choose how to continue.",
                ["solved", "skip", "stop"],
                checkpoint="CAPTCHA_REQUIRES_MANUAL_SOLVE",
                timeout=5.0,
            )
        ),
        daemon=True,
    )
    t.start()

    pending = _wait_for_open_gate(sc)
    assert pending, "gate never opened"
    assert len(pending) == 1

    payload = pending[0]
    assert payload["checkpoint"] == "CAPTCHA_REQUIRES_MANUAL_SOLVE"
    assert "CAPTCHA" in payload["question"]
    assert "solved" in payload["options"]
    assert "stop" in payload["options"]
    assert payload["context_id"]

    # The gate is still open and answerable from the same readable state.
    assert sc.provide_approval(payload["context_id"], "solved") is True
    t.join(timeout=6.0)
    assert outcomes == ["solved"]


def test_gate_removed_from_pending_after_answer():
    """After an answer, a late bind must render nothing — no ghost prompt."""
    sc = _make_controller()
    outcomes: list[str] = []
    t = threading.Thread(
        target=lambda: outcomes.append(
            sc.request_approval("Approve?", ["yes"], timeout=5.0)
        ),
        daemon=True,
    )
    t.start()

    pending = _wait_for_open_gate(sc)
    assert pending, "gate never opened"

    assert sc.provide_approval(pending[0]["context_id"], "yes") is True
    t.join(timeout=6.0)

    assert sc.get_pending_approvals() == []
    assert outcomes == ["yes"]


def test_cli_dashboard_seeds_pending_gate_on_late_bind():
    """The real race path: a CLIDashboard constructed after the gate opened
    must have the pending payload seeded at construction — not after the
    next publish that may never come."""
    sc = _make_controller()
    t = threading.Thread(
        target=lambda: sc.request_approval(
            "Solve the CAPTCHA?", ["solved"], timeout=5.0
        ),
        daemon=True,
    )
    t.start()
    pending = _wait_for_open_gate(sc)
    assert pending, "gate never opened"

    # Dashboard binds NOW — after the publish. The old code heard nothing.
    dash = CLIDashboard(sc)

    assert dash._pending_approval is not None
    assert dash._pending_approval["question"] == "Solve the CAPTCHA?"
    assert dash._pending_approval["context_id"] == pending[0]["context_id"]

    sc.provide_approval(pending[0]["context_id"], "solved")
    t.join(timeout=6.0)


# ─────────────────────────────────────────────────────────────────────────────
# Defect 2 — the ghost CAPTCHA task
# ─────────────────────────────────────────────────────────────────────────────


def _temp_db(tmp_path) -> DatabaseManager:
    """A real DatabaseManager pointed at a throwaway database file.

    DatabaseManager is a singleton. Two pieces of shared state must be
    isolated for these tests:

    - ``db_path`` is overridden to a throwaway file (restored by the caller).
    - ``_capability_profile`` is SAVED and CLEARED. An earlier test (e.g. the
      static-mode suite) may leave a STATIC_ASSISTED profile on the shared
      instance, whose allowed task types exclude handle_captcha — that made
      ``queue_task`` reject the ghost task this fixture needs to seed.
      Clearing it bypasses the gate exactly as in a no-profile startup; the
      caller restores the previous value in finally.
    """
    db = DatabaseManager()
    db.db_path = tmp_path / "stale_task_test.db"
    db._capability_profile = None
    db._init_schema()
    return db


def test_stale_captcha_task_is_discarded_at_startup(tmp_path):
    """The exact live defect: a restored HANDLE_CAPTCHA task must be marked
    SKIPPED with a recorded reason — never dispatched into a fresh browser."""
    db = _temp_db(tmp_path)
    original_path = db.db_path
    original_profile = db._capability_profile
    try:
        ghost = WorkUnit(
            priority=1,
            task_type=TaskType.HANDLE_CAPTCHA,
            payload={"challenge_url": "https://linkedin.example/expired_jd_redirect",
                     "challenge_type": "recaptcha"},
            source="applications_workflow",
            context_data={"return_state": "applying"},
        )
        db.queue_task(ghost)

        discarded = db.discard_stale_reactive_tasks()

        assert discarded == 1
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT status, error_message FROM work_queue WHERE id = ?",
                (ghost.id,),
            ).fetchone()
        assert row["status"] == "SKIPPED"
        assert "outlived its session" in row["error_message"]

        # The ghost must not be dispatchable.
        assert db.get_next_task() is None
    finally:
        db.db_path = original_path
        db._capability_profile = original_profile


def test_normal_tasks_survive_the_discard(tmp_path):
    """URL-addressable tasks re-navigate fine — they must survive untouched."""
    db = _temp_db(tmp_path)
    original_path = db.db_path
    original_profile = db._capability_profile
    try:
        ghost = WorkUnit(
            priority=1,
            task_type=TaskType.HANDLE_CAPTCHA,
            payload={"challenge_url": "https://example.com/challenge"},
            source="applications_workflow",
        )
        healthy = WorkUnit(
            priority=TaskPriority.DISCOVER,
            task_type=TaskType.DISCOVER,
            payload={"query": "python engineer", "location": "Remote"},
            source="user_discovery_input",
        )
        db.queue_task(ghost)
        db.queue_task(healthy)

        discarded = db.discard_stale_reactive_tasks()

        assert discarded == 1
        with db.get_connection() as conn:
            healthy_row = conn.execute(
                "SELECT status FROM work_queue WHERE id = ?", (healthy.id,),
            ).fetchone()
        assert healthy_row["status"] in ("PENDING", "IN_PROGRESS")

        # The healthy task must be the one dispatched next.
        next_task = db.get_next_task()
        assert next_task is not None
        assert next_task.id == healthy.id
    finally:
        db.db_path = original_path
        db._capability_profile = original_profile


def test_startup_recovery_calls_the_discard():
    """_perform_startup_recovery must invoke the discard — wiring, not hope."""
    sc = _make_controller()
    sc.db.recover_interrupted_tasks.return_value = 0
    sc.db.discard_stale_reactive_tasks.return_value = 1

    sc._perform_startup_recovery()

    sc.db.recover_interrupted_tasks.assert_called_once()
    sc.db.discard_stale_reactive_tasks.assert_called_once()

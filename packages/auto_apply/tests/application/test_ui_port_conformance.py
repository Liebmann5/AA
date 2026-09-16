"""Conformance pins for SessionController satisfying UIPort (A2), plus the
stage E1 autonomy pins (the control, the state, and the record).

Labels are honest, per the standing method:
  TEETH — verified to fail against the pre-A2 tree for the reason stated.
  GUARD — passes on both trees; freezes behavior the merge must not break.

Construction note: every pin mocks the network pre-check
(controller._check_network_connectivity) because the real check issues
urllib requests with 5-second timeouts — pins must be deterministic.
"""

from __future__ import annotations

import ast
import inspect
import logging
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import SimpleNamespace, UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints
from unittest.mock import MagicMock, call, patch

import pytest
from pydantic import BaseModel, ValidationError

from auto_apply.application.agent.context import SessionStatistics
from auto_apply.application.agent.event_bus import EventBus
from auto_apply.application.agent.state_machine import AgentState
from auto_apply.application.services import session_controller as sc_module
from auto_apply.application.services.autonomy import (
    apply_autonomy,
    autonomy_enabled_for_profile,
)
from auto_apply.application.services.session_controller import (
    _EVENT_KIND_MAP,
    _LEGACY_ENTRY_TO_EXECUTION_MODE,
    _OUTCOME_KIND_MAP,
    _STREAM_TEXT_RENDERERS,
    AnsweredBy,
    SessionController,
)
from auto_apply.application.workflows.discovery_workflow import DiscoveryWorkflow
from auto_apply.domain.events import Event
from auto_apply.domain.models.application_evidence import ApplicationEvidence
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.session_plan import (
    SessionExecutionMode,
    SessionPlan,
)
from auto_apply.domain.models.ui_contract import (
    ActivityKind,
    ApprovalRequest,
    EntryPoint,
    QueueSnapshot,
    SessionEventRecord,
    SessionRequest,
    SessionSnapshot,
    SessionSummary,
    SessionViewState,
    SubmittedApplication,
    entry_point_from_label,
    view_state_from_agent_state,
)
from auto_apply.domain.models.work_unit import TaskType
from auto_apply.domain.ports.interrupt_policy_port import (
    Checkpoint,
    ProfileBasedInterruptPolicy,
)
from auto_apply.domain.ports.ui_port import UIPort

_UI_CONTRACT_MODULE = "auto_apply.domain.models.ui_contract"

_EXPECTED_PORT_METHODS = {
    "initialize_session", "start", "stop", "pause", "resume",
    "provide_approval", "snapshot", "summary", "queue_snapshot",
    "pending_approvals", "is_running", "recent_events",
    "export_session_results", "export_profile", "list_session_history",
    # E1: the autonomy read and write. The port went from 15 methods to 17;
    # the controller must satisfy the wider surface structurally, no wrapper.
    "autonomy", "set_autonomy",
}


def _queue_stats() -> dict:
    return {
        "pending": 0, "in_progress": 0, "completed": 0,
        "failed": 0, "skipped": 0, "permanently_failed": 0,
    }


def _controller(
    plan: SessionPlan | None = None,
    profile=None,
) -> SessionController:
    plan = plan or SessionPlan(session_id="pin-test")
    registry = MagicMock()
    registry.get_session_plan.return_value = plan
    registry.get_active_profile.return_value = (
        profile if profile is not None else MagicMock()
    )
    db = MagicMock()
    db.get_queue_stats.return_value = _queue_stats()
    orchestrator = MagicMock()
    orchestrator.session_plan = plan
    orchestrator.context = MagicMock()
    orchestrator.context.session_id = "pin-test"
    orchestrator.context.stats = SessionStatistics()
    orchestrator.state_machine = MagicMock()
    orchestrator.task_queue = db
    controller = SessionController(
        registry=registry, db=db, orchestrator=orchestrator
    )
    controller._check_network_connectivity = lambda: True  # deterministic pins
    return controller


def _queued(controller: SessionController):
    return [
        call.args[0]
        for call in controller.db.queue_task.call_args_list
    ]


# ─────────────────────────────────────────────────────────────────────────────
# TEETH
# ─────────────────────────────────────────────────────────────────────────────

def test_controller_satisfies_ui_port() -> None:
    """TEETH: pre-A2 the controller lacks snapshot/summary/queue_snapshot/
    recent_events, so isinstance was False. Now it must satisfy the port
    structurally — no wrapper class involved."""
    controller = _controller()
    assert isinstance(controller, UIPort)
    # And the typed methods return typed data, not dicts.
    assert isinstance(controller.snapshot(), SessionSnapshot)
    assert isinstance(controller.summary(), SessionSummary)


def test_discover_only_carries_mode_end_to_end() -> None:
    """TEETH: execution_mode was a constant (session_plan.py:171 reads a
    config section nothing writes). A SessionRequest must set it on the
    live plan AND on every seeded task."""
    controller = _controller()
    controller.start_session(
        SessionRequest(
            entry=EntryPoint.SEARCH,
            execution_mode=SessionExecutionMode.DISCOVER_ONLY,
            keywords=("python",),
        )
    )
    assert (
        controller.orchestrator.session_plan.execution_mode
        is SessionExecutionMode.DISCOVER_ONLY
    )
    for task in _queued(controller):
        assert task.context_data["execution_mode"] == "discover_only"


def test_no_apply_can_be_queued_in_discover_only() -> None:
    """TEETH (the alpha safety guarantee): in DISCOVER_ONLY, no APPLY task
    may be queued. Clause 1: link tasks derive next_task=VET and
    skip_vetting=False. Clause 2: the mode itself cannot apply. Clause 3:
    the downstream vetting gate skips enqueueing entirely."""
    controller = _controller()
    controller.start_session(
        SessionRequest(
            entry=EntryPoint.DIRECT_URLS,
            execution_mode=SessionExecutionMode.DISCOVER_ONLY,
            urls=("https://example.com/j/1",),
        )
    )
    tasks = _queued(controller)
    assert tasks, "expected one RESOLVE_JOB_URL task"
    task = tasks[0]
    assert task.task_type is TaskType.RESOLVE_JOB_URL
    assert task.payload["next_task"] == "VET"
    assert task.payload["skip_vetting"] is False
    mode = controller.orchestrator.session_plan.execution_mode
    assert mode is SessionExecutionMode.DISCOVER_ONLY
    assert mode.includes_application is False
    # Clause 3 — the structural gate downstream: vetting enqueues nothing.
    workflow = DiscoveryWorkflow(
        profile=MagicMock(),
        providers=[],
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        dedup=MagicMock(),
        text_matcher=MagicMock(),
    )
    job = Job(title="Eng", company="Acme", url="https://x", source="t")
    assert workflow._enqueue_vet_tasks([job], mode) == 0
    assert workflow._enqueue_vet_tasks(
        [job], SessionExecutionMode.FULL_PIPELINE
    ) == 1


def test_search_entry_discover_only_queues_only_discover_tasks() -> None:
    """TEETH (alpha-safety, search path): a DISCOVER_ONLY search queues
    DISCOVER tasks and nothing else — no VET, no APPLY can ever be
    produced downstream of this request. This is AA's only structural
    no-submit guarantee, and the alpha usability study cannot ethically
    run without it (there is no --dry-run flag; verified by grep)."""
    controller = _controller()
    controller.start_session(
        SessionRequest(
            entry=EntryPoint.SEARCH,
            execution_mode=SessionExecutionMode.DISCOVER_ONLY,
            keywords=("python",),
        )
    )
    tasks = _queued(controller)
    assert tasks, "expected DISCOVER tasks to be seeded"
    assert {t.task_type for t in tasks} == {TaskType.DISCOVER}


def test_providers_thread_into_the_rebuilt_plan() -> None:
    """TEETH: providers=("bing",) reaches the live plan (fails pre-turn-2 —
    SessionRequest had no providers field, so nothing could thread it)."""
    controller = _controller()
    controller.start_session(
        SessionRequest(entry=EntryPoint.SEARCH, providers=("bing",))
    )
    assert controller.orchestrator.session_plan.active_providers == ("bing",)


def test_empty_providers_leaves_plan_default_untouched() -> None:
    """GUARD: providers=() means "not declared" — the plan default stands."""
    controller = _controller()
    controller.start_session(SessionRequest(entry=EntryPoint.SEARCH))
    assert controller.orchestrator.session_plan.active_providers == (
        "google", "bing", "indeed",
    )


def test_rebuilt_plan_reaches_plan_holding_workflows() -> None:
    """TEETH: without the refresh, workflows keep the boot plan and
    request-scoped values (mode, cap, providers) never reach them.

    Pre-turn-2 this is exactly why the wizard's max_results reached the
    plan but never the scraper — the workflow read max_results_per_query
    from the stale boot plan it was built with."""
    controller = _controller()
    sentinel = SimpleNamespace(_plan=controller.orchestrator.session_plan)
    controller.orchestrator._workflows = {"DiscoveryWorkflow": sentinel}
    controller.start_session(
        SessionRequest(
            entry=EntryPoint.SEARCH,
            providers=("bing",),
            max_results=7,
        )
    )
    assert sentinel._plan.active_providers == ("bing",)
    assert sentinel._plan.max_results_per_query == 7


def test_seed_priority_preserved_for_both_url_modes() -> None:
    """GUARD (behavior-preserving): the legacy pair produced priority 1
    (direct) and 3 (vet); the merged seeder must not lose that. Passes on
    both trees — pinned so the collapse cannot regress it."""
    controller = _controller()
    controller.start_session(
        SessionRequest(
            entry=EntryPoint.DIRECT_URLS,
            execution_mode=SessionExecutionMode.APPLY_ONLY,
            urls=("https://a.example/1", "https://a.example/2"),
        )
    )
    controller.start_session(
        SessionRequest(
            entry=EntryPoint.VET_URLS,
            execution_mode=SessionExecutionMode.FULL_PIPELINE,
            urls=("https://v.example/1",),
        )
    )
    tasks = _queued(controller)
    assert [t.priority for t in tasks] == [1, 1, 3]
    apply_task = tasks[0]
    vet_task = tasks[2]
    assert apply_task.payload["next_task"] == "APPLY"
    assert apply_task.payload["skip_vetting"] is True
    assert apply_task.source == "user_direct_input"
    assert vet_task.payload["next_task"] == "VET"
    assert vet_task.payload["skip_vetting"] is False
    assert vet_task.source == "user_vet_input"


def test_timeout_records_answered_by_timeout() -> None:
    """TEETH: a 300 s gate timeout previously returned "skip" with only a
    log line. The machine's answer must be in the evidence record."""
    controller = _controller()
    choice = controller.request_approval(
        "Approve?", ["submit"], timeout=0.01
    )
    assert choice == "skip"
    evidence = controller.approval_evidence()
    assert len(evidence) == 1
    assert evidence[0].answered_by is AnsweredBy.TIMEOUT
    assert evidence[0].choice == "skip"


def test_get_stats_does_not_touch_private_report() -> None:
    """TEETH: session_controller.py must contain no attribute access to
    _session_report — the projection is event-fed. (Prose mentions in
    docstrings are fine; the scan checks Attribute nodes.)"""
    src = Path(sc_module.__file__).read_text(encoding="utf-8")
    offenders = [
        node.lineno
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Attribute) and node.attr == "_session_report"
    ]
    assert not offenders, (
        f"session_controller.py still touches _session_report at "
        f"line(s) {offenders}"
    )


def test_direct_links_mode_no_longer_raises() -> None:
    """TEETH (the translate ruling): {"mode": "direct_links"} raised
    ValueError at session_controller.py:188 — the CLI paste-links path
    could not start. The shim maps it to DIRECT_URLS."""
    controller = _controller()
    count = controller.initialize_session({
        "mode": "direct_links",
        "links": ["https://x.example/1", "https://x.example/2"],
    })
    assert count == 2
    tasks = _queued(controller)
    assert all(t.task_type is TaskType.RESOLVE_JOB_URL for t in tasks)
    assert all(t.payload["next_task"] == "APPLY" for t in tasks)


def test_max_results_reaches_plan() -> None:
    """TEETH: the CLI wizard's max_results was collected and discarded.
    It must now reach the live session plan."""
    controller = _controller()
    controller.start_session(
        SessionRequest(
            entry=EntryPoint.SEARCH,
            keywords=("python",),
            max_results=7,
        )
    )
    assert controller.orchestrator.session_plan.max_results_per_query == 7


def test_dict_and_private_shim_agree_on_execution_mode_for_every_label() -> None:
    """TEETH (rewritten after the spy version broke itself): legacy 'vet'
    resolved to two different execution modes depending on the door —
    the dict shim read the table, the private shim hardcoded
    FULL_PIPELINE. One label, two answers.

    The first version of this pin spied on SessionRequest construction
    with patch.object — which replaced the module global that
    initialize_session's isinstance guard reads, so the pin could not
    run at all (TypeError at session_controller.py:553). The production
    guard is correct; the spy was wrong. This version needs no patching:
    every seeded WorkUnit already carries context_data["execution_mode"],
    so the task IS the evidence. Note the stamp is written from
    request.execution_mode.value at seed time, so this asserts the mode
    as the rest of the system will actually consume it, not merely as it
    was constructed — a stronger claim than the spy's.

    'company' is a genuine exception, pinned at the plan rather than the
    task, and said plainly: _seed_company_urls carries no context_data
    stamp, so the task cannot report its mode. For that row the dict
    path is the only mode answer, and it is asserted on
    orchestrator.session_plan instead.

    What this pin catches, and what it cannot:
      * a door drifting from the table fails the agreement assertion
        (shim stamp != dict stamp);
      * a WRONG TABLE ROW it cannot catch by itself: `expected` is read
        from the table the shim consumes, so both doors stamping the
        same wrong value would pass here. Semantic correctness of the
        rows is pinned with LITERALS in
        test_legacy_dict_shim_still_queues_what_it_queued below — that
        is where the F-8 class is actually caught.
    """
    stamped_cases = [
        ("discovery", "_seed_discovery_tasks", "python"),
        ("direct", "_seed_direct_apply_tasks", "https://x.example/1"),
        ("vet", "_seed_vet_tasks", "https://x.example/1"),
    ]
    for label, shim_name, raw in stamped_cases:
        entry = entry_point_from_label(label)
        expected = _LEGACY_ENTRY_TO_EXECUTION_MODE[entry].value

        # Door 1: the dict shim — read the mode stamped on every seeded task.
        dict_controller = _controller()
        dict_controller.initialize_session({"mode": label, "input": raw})
        dict_stamps = {
            task.context_data["execution_mode"]
            for task in _queued(dict_controller)
        }

        # Door 2: the legacy private shim — the same stamp, from the same table.
        shim_controller = _controller()
        getattr(shim_controller, shim_name)(raw)
        shim_stamps = {
            task.context_data["execution_mode"]
            for task in _queued(shim_controller)
        }

        assert shim_stamps == dict_stamps, (
            f"{label!r}: private shim stamped {shim_stamps}, "
            f"dict path stamped {dict_stamps} — two doors, two answers"
        )
        assert dict_stamps == shim_stamps == {expected}, (
            f"{label!r}: stamps {dict_stamps} do not equal the table row "
            f"{expected!r} — the doors may agree, but on the wrong answer"
        )

    # 'company' — pinned at the plan, not the task (see docstring): the
    # company seeder carries no context_data stamp, so the task cannot
    # report its mode. The dict path must still land on the table row.
    company_controller = _controller()
    company_controller.initialize_session({
        "mode": "company", "input": "https://x.example/1",
    })
    assert (
        company_controller.orchestrator.session_plan.execution_mode
        is _LEGACY_ENTRY_TO_EXECUTION_MODE[EntryPoint.COMPANY_PAGES]
    )


# ─────────────────────────────────────────────────────────────────────────────
# GUARDS
# ─────────────────────────────────────────────────────────────────────────────

def test_legacy_dict_shim_still_queues_what_it_queued() -> None:
    """GUARD: initialize_session({"mode": "discovery", "input": "X"}) and
    the "direct"/"vet" shapes must keep working — the 1,200 tests and both
    wizards depend on the dict path (removed at stage U3, not now).

    This pin also carries the F-8 fix: the mode each label produces is
    asserted against string LITERALS, not against the mapping table the
    shim reads. "vet" must produce "vet_and_apply" — vet-then-apply is
    the legacy semantic (the original docstring: 'Newline-separated job
    URLs to vet before applying'), and it is pinned independently of
    _LEGACY_ENTRY_TO_EXECUTION_MODE, so a wrong table row fails here
    rather than passing through the agreement check above.
    """
    controller = _controller()
    count = controller.initialize_session({"mode": "discovery", "input": "X"})
    assert count == 1
    task = _queued(controller)[0]
    assert task.task_type is TaskType.DISCOVER
    assert task.payload["query"] == "X"
    assert task.context_data["execution_mode"] == "full_pipeline"

    controller2 = _controller()
    controller2.initialize_session({"mode": "direct", "input": "https://d/1"})
    direct_task = _queued(controller2)[0]
    assert direct_task.priority == 1
    assert direct_task.payload["next_task"] == "APPLY"
    assert direct_task.context_data["execution_mode"] == "apply_only"

    controller3 = _controller()
    controller3.initialize_session({"mode": "vet", "input": "https://v/1"})
    vet_task = _queued(controller3)[0]
    assert vet_task.priority == 3
    assert vet_task.payload["next_task"] == "VET"
    assert vet_task.context_data["execution_mode"] == "vet_and_apply", (
        "legacy 'vet' must mean vet-then-apply — the original mode "
        "docstring ('Newline-separated job URLs to vet before applying'), "
        "asserted independently of the mapping table. If this reads "
        "'vet_only', the table row is wrong — and the agreement pin above "
        "cannot see it, because its expectation comes from the same table."
    )
    assert SessionExecutionMode("vet_and_apply").includes_application is True


def test_strategy_key_warns_but_continues(caplog) -> None:
    """GUARD (fail kind for users, fail loud for maintainers): the unread
    'strategy' key must warn, never crash."""
    controller = _controller()
    with caplog.at_level(logging.WARNING):
        count = controller.initialize_session({
            "mode": "discovery", "input": "X", "strategy": "adaptive",
        })
    assert count == 1
    assert any("strategy" in r.getMessage() for r in caplog.records)


def test_snapshot_and_summary_are_null_objects_when_idle() -> None:
    """GUARD (the A1 ruling): before any session, the views are zeroed
    first-class values — never None, never an exception."""
    controller = _controller()
    snap = controller.snapshot()
    assert snap.state.name == "NO_SESSION"
    assert snap.jobs_discovered == 0
    summary = controller.summary()
    assert summary.state.name == "NO_SESSION"
    assert summary.applications_submitted == 0
    assert summary.submitted == ()


def test_summary_projects_from_event_feed() -> None:
    """GUARD (projection shape — the teeth for the redesign are in
    test_get_stats_does_not_touch_private_report): an event with an
    evidence_outcome payload must land in the typed summary and the
    legacy get_stats() projection without any private report access."""
    controller = _controller()
    controller._on_application_outcome({
        "job_url": "https://acme.example/j/1",
        "job_title": "Engineer",
        "company": "Acme",
        "ats": "greenhouse",
        "pages_navigated": 1,
        "fields_filled": 3,
        "used_gpt4all": False,
        "evidence_outcome": "SUBMITTED",
        "evidence_confidence": 0.95,
    })
    summary = controller.summary()
    assert summary.applications_submitted == 1
    assert summary.submitted[0].url == "https://acme.example/j/1"
    assert summary.submitted[0].company == "Acme"
    legacy = controller.get_stats()
    assert legacy["applications_submitted"] == 1
    assert legacy["submitted_job_urls"] == ["https://acme.example/j/1"]
    events = controller.recent_events()
    assert events, "the stream must record the outcome too"


def test_answer_approval_records_human_and_rejects_out_of_band() -> None:
    """GUARD (evidence integrity): a human answer is recorded as HUMAN;
    a choice outside the gate's options does not unblock and is not recorded."""
    controller = _controller()
    context_id = "pin-ctx"
    gate = threading.Event()
    payload = {
        "context_id": context_id,
        "checkpoint": "TEST",
        "question": "ok?",
        "options": ["submit", "skip"],
    }
    controller._pending_approvals[context_id] = (gate, [], payload)

    assert controller.answer_approval(context_id, "submit", AnsweredBy.HUMAN)
    assert gate.is_set()
    evidence = controller.approval_evidence()
    assert evidence[0].answered_by is AnsweredBy.HUMAN
    assert evidence[0].choice == "submit"

    bad_id = "pin-ctx-2"
    gate2 = threading.Event()
    controller._pending_approvals[bad_id] = (
        gate2, [], {**payload, "context_id": bad_id, "options": ["submit"]}
    )
    assert not controller.answer_approval(bad_id, "nonsense", AnsweredBy.HUMAN)
    assert not gate2.is_set()
    assert len(controller.approval_evidence()) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Type machinery (the checker the teeth pins rely on)
# ─────────────────────────────────────────────────────────────────────────────

def _is_data_type(t: object) -> bool:
    """True iff t is a builtin scalar, Path, an Enum, a frozen ui_contract
    DTO, or a tuple/Optional of those. Any and every container other than
    tuple are data-shape violations."""
    if t is Any:
        return False
    if t is None or t is type(None):
        return True
    if t in (int, bool, str, float):
        return True
    if t is Path:
        return True
    if isinstance(t, type):
        if issubclass(t, Enum):
            return True
        if issubclass(t, BaseModel) and t.__module__ == _UI_CONTRACT_MODULE:
            return True
        return False
    origin = get_origin(t)
    if origin is tuple:
        return all(a is Ellipsis or _is_data_type(a) for a in get_args(t))
    if origin is Union or origin is UnionType:
        return all(_is_data_type(a) for a in get_args(t))
    return False


def _check_callable(fn: Any) -> bool:
    """True iff every parameter and the return of fn is annotated and
    resolves to a data type per _is_data_type. Unannotated parameters or
    returns fail."""
    try:
        sig = inspect.signature(fn)
        hints = get_type_hints(fn)
    except Exception:
        return False
    for p in sig.parameters.values():
        if p.name == "self":
            continue
        if p.name not in hints:
            return False
        if not _is_data_type(hints[p.name]):
            return False
    if "return" not in hints:
        return False
    return _is_data_type(hints["return"])


def _port_methods(port: Any) -> dict[str, Any]:
    return {
        name: member
        for name, member in vars(port).items()
        if not name.startswith("_") and callable(member)
    }


# ─────────────────────────────────────────────────────────────────────────────
# TEETH
# ─────────────────────────────────────────────────────────────────────────────

def test_unknown_entry_point_rejected() -> None:
    """TEETH (boundary moved earlier): today an unknown mode fails at
    session_controller.py:188 only AFTER initialize_session has been
    entered and the network check run. The typed boundary fails at
    construction, before anything is seeded."""
    with pytest.raises(ValidationError):
        SessionRequest(entry="banana")  # type: ignore[arg-type]


def test_unknown_execution_mode_rejected() -> None:
    """TEETH: execution_mode has no live reader today — it is read from
    config["session"]["execution_mode"] (session_plan.py:171-176) and no
    session: section exists in runtime_defaults.yaml — so nothing today
    could even reject a bad value. The DTO rejects it at construction."""
    with pytest.raises(ValidationError):
        SessionRequest(
            entry=EntryPoint.SEARCH,
            execution_mode="sideways",  # type: ignore[arg-type]
        )


def test_session_request_is_frozen() -> None:
    """TEETH: the dict was mutable by construction; the DTO rejects
    assignment."""
    request = SessionRequest(entry=EntryPoint.SEARCH, keywords=("python",))
    with pytest.raises(ValidationError):
        request.keywords = ("java",)  # type: ignore[misc]


def test_ui_port_type_hints_are_data_only() -> None:
    """TEETH: every method on UIPort resolves to frozen DTOs from
    ui_contract, enums, Path, or builtins — no live objects. The
    discrimination proof that this check has teeth is in
    test_type_checker_rejects_session_controller_today."""
    methods = _port_methods(UIPort)
    assert set(methods) == _EXPECTED_PORT_METHODS, (
        f"the port drifted from the declared surface: "
        f"missing={sorted(_EXPECTED_PORT_METHODS - set(methods))} "
        f"extra={sorted(set(methods) - _EXPECTED_PORT_METHODS)}"
    )
    bad = sorted(n for n, fn in methods.items() if not _check_callable(fn))
    assert not bad, f"port methods carrying non-data types: {bad}"


def test_type_checker_rejects_session_controller_today() -> None:
    """TEETH: the checker must flag the contract this port replaces.

    Run against the CURRENT SessionController: initialize_session takes
    dict[str, Any] (session_controller.py:170), get_stats returns
    dict[str, Any] (:482), get_pending_approvals returns list[dict] (:522).
    If any of those PASSED, the checker would be too loose to have teeth,
    and a green UIPort result would mean nothing."""
    for name in ("initialize_session", "get_stats", "get_pending_approvals"):
        fn = getattr(SessionController, name)
        assert not _check_callable(fn), (
            f"SessionController.{name} passed the data-type check — the "
            f"checker cannot distinguish the broken dict contract from "
            f"the typed port."
        )


def test_providers_defaults_to_empty_tuple() -> None:
    """TEETH: providers did not exist before stage U3 turn 2; () means
    "not declared — use the SessionPlan's active_providers default"."""
    assert SessionRequest(entry=EntryPoint.SEARCH).providers == ()


def test_providers_accepts_an_explicit_subset() -> None:
    """TEETH: a declared engine subset is preserved (the kwarg did not
    exist before stage U3 turn 2)."""
    request = SessionRequest(entry=EntryPoint.SEARCH, providers=("bing",))
    assert request.providers == ("bing",)


def test_session_event_record_kind_must_be_activity_kind() -> None:
    """TEETH: kind accepts only ActivityKind, never the raw internal Event.

    Fails against the pre-D1 tree for the structural reason that
    ActivityKind did not exist there and ``kind: Event`` accepted any of
    the 47 internal names. On the current tree, an Event member must be
    rejected and every ActivityKind member accepted."""
    with pytest.raises(ValidationError):
        SessionEventRecord(kind="SESSION_STARTED", text="t")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        SessionEventRecord(kind="JOB_VETTED_FAIL", text="t")  # type: ignore[arg-type]
    for kind in ActivityKind:
        record = SessionEventRecord(kind=kind, text="t")
        assert record.kind is kind


# ─────────────────────────────────────────────────────────────────────────────
# GUARDS
# ─────────────────────────────────────────────────────────────────────────────

def test_all_execution_modes_representable() -> None:
    """GUARD: seven of eight SessionExecutionMode members are unreachable
    today (no session: section in runtime_defaults.yaml). Pinned so a
    future narrowing of the DTO to the four used entries is caught."""
    for mode in SessionExecutionMode:
        request = SessionRequest(entry=EntryPoint.SEARCH, execution_mode=mode)
        assert request.execution_mode is mode


def test_entry_point_has_exactly_the_four_seeders() -> None:
    """GUARD: membership. The four members correspond to the four seeders
    at session_controller.py:275 (SEARCH), :322 (DIRECT_URLS), :359
    (VET_URLS), :395 (COMPANY_PAGES)."""
    assert set(EntryPoint) == {
        EntryPoint.SEARCH,
        EntryPoint.DIRECT_URLS,
        EntryPoint.VET_URLS,
        EntryPoint.COMPANY_PAGES,
    }


def test_from_label_maps_legacy_labels_and_rejects_unknown() -> None:
    """GUARD (alias table): 'direct_links' from cli/wizard.py:47 is not in
    the controller's dispatch table and raises ValueError today;
    'discovery'/'direct' from gui/wizard.py do work. The alias table is
    the single place that answers 'what does this label mean'."""
    assert entry_point_from_label("discovery") is EntryPoint.SEARCH
    assert entry_point_from_label("direct") is EntryPoint.DIRECT_URLS
    assert entry_point_from_label("direct_links") is EntryPoint.DIRECT_URLS
    assert entry_point_from_label("vet") is EntryPoint.VET_URLS
    assert entry_point_from_label("company") is EntryPoint.COMPANY_PAGES
    with pytest.raises(ValueError):
        entry_point_from_label("banana")


def test_every_agent_state_maps_to_a_view_state() -> None:
    """GUARD (totality): fails the day someone adds an AgentState member
    without updating _AGENT_STATE_TO_VIEW_STATE."""
    for state in AgentState:
        mapped = view_state_from_agent_state(state.name)
        assert isinstance(mapped, SessionViewState)


def test_null_snapshot_is_valid_and_zeroed() -> None:
    """GUARD: pins the null-object ruling — the no-session view is a
    first-class value, not None and not an exception."""
    snap = SessionSnapshot()
    assert snap.state is SessionViewState.NO_SESSION
    assert snap.jobs_discovered == 0
    assert snap.jobs_vetted == 0
    assert snap.applications_submitted == 0
    assert snap.applications_failed == 0
    assert snap.queue_pending == 0
    assert snap.pending_approvals == 0
    assert snap.duration_seconds == 0.0
    assert snap.current_task == ""


def test_session_request_fields_do_not_shadow_profile() -> None:
    """GUARD: the one-source-per-value ruling. Adding salary floor,
    skills, daily limits or identity fields to SessionRequest fails this
    pin. ``providers`` is admitted because which engines THIS run uses is
    session-scoped, not a property of the person."""
    assert set(SessionRequest.model_fields) == {
        "entry", "execution_mode", "keywords", "location",
        "max_results", "urls", "providers",
    }


def test_all_dtos_are_frozen() -> None:
    """GUARD: every DTO in the module is ConfigDict(frozen=True) and
    rejects assignment."""
    instances: list[BaseModel] = [
        SessionRequest(entry=EntryPoint.SEARCH),
        SessionSnapshot(),
        SessionSummary(),
        QueueSnapshot(),
        ApprovalRequest(
            context_id="c", checkpoint="cp", question="q", options=("a",)
        ),
        SubmittedApplication(
            url="https://example.com/j/1", company="Acme", outcome="SUBMITTED"
        ),
        SessionEventRecord(
            kind=ActivityKind.INFO, text="t", level="INFO",
            at=datetime.now(timezone.utc),
        ),
    ]
    for instance in instances:
        field_name = next(iter(type(instance).model_fields))
        with pytest.raises(ValidationError):
            setattr(instance, field_name, getattr(instance, field_name))


def test_seed_priority_preserves_the_legacy_1_vs_3_split() -> None:
    """GUARD: the merged seeder must not lose pasted-apply-URLs jumping
    ahead of vet-URLs (session_controller.py:322 vs :359). The split is
    derived from execution_mode, as required by the prompt."""
    apply_first = SessionRequest(
        entry=EntryPoint.DIRECT_URLS,
        execution_mode=SessionExecutionMode.APPLY_ONLY,
        urls=("https://example.com/j/1",),
    )
    assert apply_first.seed_priority == 1
    vet_first = SessionRequest(
        entry=EntryPoint.VET_URLS,
        execution_mode=SessionExecutionMode.FULL_PIPELINE,
        urls=("https://example.com/j/1",),
    )
    assert vet_first.seed_priority == 3


def test_activity_kind_membership_is_exactly_the_ui_vocabulary() -> None:
    """GUARD: the projected feed vocabulary is exactly these ten kinds.

    This pin exists so a member cannot be added to ActivityKind without a
    deliberate edit of this pin — a UI adapter may switch on this set
    exhaustively and a future silent expansion would otherwise widen the
    port's surface without anyone deciding to."""
    assert set(ActivityKind) == {
        ActivityKind.FOUND,
        ActivityKind.VETTED,
        ActivityKind.REJECTED,
        ActivityKind.APPLIED,
        ActivityKind.SKIPPED,
        ActivityKind.BLOCKED,
        ActivityKind.REFUSED,
        ActivityKind.FAILED,
        ActivityKind.INFO,
        ActivityKind.WAITING,
    }


# ═════════════════════════════════════════════════════════════════════════════
# Activity projection (D1)
#
# Pin labels are honest per the standing method:
#   TEETH — each fails against the pre-D1 tree by construction: the enum,
#   the maps, and the handlers it asserts on did not exist there. I have not
#   verified the red run by execution; each pin states its mechanism so the
#   failure is auditable by eye.
#   GUARD — passes on both trees; freezes an ordering or null-object ruling.
# ═════════════════════════════════════════════════════════════════════════════

_STREAM_ONLY_EVENTS: tuple[Event, ...] = (
    Event.DISCOVERY_COMPLETE,
    Event.CAPTCHA_REQUIRES_MANUAL_SOLVE,
    Event.PROVIDER_TIMED_OUT,
    Event.PROVIDER_BENCHED,
    Event.TASK_PERMANENTLY_FAILED,
    Event.TASK_SKIPPED_DUPLICATE,
    Event.BROWSER_DEGRADED,
    Event.BROWSER_UNHEALTHY,
    Event.BROWSER_DEAD,
    Event.NETWORK_UNHEALTHY,
    Event.NETWORK_RESTORED,
    Event.REDIRECT_TO_LIST_DETECTED,
)

_SPECIAL_EVENTS: tuple[Event, ...] = (
    Event.JOBS_DISCOVERED,
    Event.JOB_VETTED_PASS,
    Event.JOB_VETTED_FAIL,
    Event.APPLICATION_SUBMITTED,
    Event.APPLICATION_FAILED,
)

_HITL_EVENTS: tuple[Event, ...] = (
    Event.HUMAN_APPROVAL_REQUESTED,
    Event.HUMAN_APPROVAL_GRANTED,
)


def _projection_controller() -> tuple[SessionController, EventBus]:
    """A controller with a REAL EventBus so subscriptions and publishes are live."""
    plan = SessionPlan(session_id="projection-test")
    registry = MagicMock()
    registry.get_session_plan.return_value = plan
    registry.get_active_profile.return_value = MagicMock()
    db = MagicMock()
    db.get_queue_stats.return_value = _queue_stats()
    bus = EventBus()
    orchestrator = MagicMock()
    orchestrator.session_plan = plan
    orchestrator.context = MagicMock()
    orchestrator.context.session_id = "projection-test"
    orchestrator.context.stats = SessionStatistics()
    orchestrator.state_machine = MagicMock()
    orchestrator.task_queue = db
    orchestrator.event_bus = bus
    controller = SessionController(
        registry=registry, db=db, orchestrator=orchestrator
    )
    controller._check_network_connectivity = lambda: True
    return controller, bus


def _fat_payload() -> dict:
    """One payload covering every key any renderer reads, plus sentinel
    PII-shaped values in unknown keys (see test_projection_drops_payload_pii)."""
    return {
        "job_title": "Software Engineer",
        "company": "Acme Corp",
        "url": "https://acme.example/jobs/1",
        "job_url": "https://acme.example/jobs/1",
        "count": 7,
        "source": "bing",
        "reason": "title_mismatch: Low Relevance Score (0.31)",
        "task_type": "APPLY",
        "error": "TimeoutError: page load",
        "provider": "Google",
        "provider_name": "Google",
        "last_action": "harvesting serp",
        "yield_ratio": 0.11,
        "bytes_ratio": 0.22,
        "baseline_samples": 4,
        "response_ms": 2100.0,
        "consecutive_failures": 3,
        "downtime_seconds": 61.0,
        "latency_ms": 42.0,
        "captcha_type": "recaptcha",
        "task_id": "abc123",
        "enqueued": 5,
        "raw_found": 9,
        "evidence_outcome": "ERROR",
        "evidence_confidence": 0.4,
        # Sentinel PII-shaped values in keys no renderer is allowed to read.
        "applicant_email": "SENTINEL_EMAIL@example.com",
        "email": "SENTINEL_EMAIL@example.com",
        "phone": "SENTINEL-PHONE-555",
        "full_name": "SENTINEL-NAME-JANE",
        "street_address": "SENTINEL-ADDRESS-1-MAIN-ST",
    }


def test_subscription_set_matches_kind_map__teeth() -> None:
    """TEETH: the live subscription set equals _EVENT_KIND_MAP minus HITL.

    Fails today because _EVENT_KIND_MAP did not exist and the bus set was
    10 not 17. The set is derived from the LIVE bus (subscriber_count per
    Event member), never from a hardcoded copy of the subscriptions — a
    subscribe line added without a kind-map row fails here, not in prose."""
    controller, bus = _projection_controller()
    live = {m for m in Event if bus.subscriber_count(m) > 0}
    expected = set(_EVENT_KIND_MAP) - set(_HITL_EVENTS)
    assert live == expected, (
        f"live subscription set and _EVENT_KIND_MAP disagree — "
        f"subscribed-but-unmapped: {sorted(live - expected)}; "
        f"mapped-but-not-subscribed: {sorted(expected - live)}"
    )
    assert live == set(_STREAM_ONLY_EVENTS) | set(_SPECIAL_EVENTS), (
        "the stream-only/special partition in this file drifted from the "
        "live subscriptions — update _STREAM_ONLY_EVENTS / _SPECIAL_EVENTS"
    )


def test_every_stream_event_has_a_renderer__teeth() -> None:
    """TEETH: every stream-only subscription has a text renderer.

    Fails today because _STREAM_TEXT_RENDERERS did not exist. Renderer
    keys must equal the stream-only subscription set exactly — a renderer
    with no subscription is dead code; a subscription with no renderer
    would fall through to the unmapped-warning path in production."""
    assert set(_STREAM_TEXT_RENDERERS) == set(_STREAM_ONLY_EVENTS), (
        f"renderer keys {sorted(set(_STREAM_TEXT_RENDERERS))} != "
        f"stream-only subscriptions {sorted(_STREAM_ONLY_EVENTS)}"
    )
    assert set(_STREAM_TEXT_RENDERERS) <= set(_EVENT_KIND_MAP), (
        "a renderer exists for an event with no kind mapping — the "
        "kind map and renderer table must not drift apart"
    )


def test_every_subscribed_event_maps_to_a_kind_and_renders__teeth() -> None:
    """TEETH: every subscribed event produces a record with its mapped kind
    and a non-empty sentence that is not a payload key-dump.

    Fails today: _record_event did not exist, and the 7 newly-subscribed
    events (browser/network/dedup/redirect) produced no record at all."""
    controller, _bus = _projection_controller()
    payload = _fat_payload()

    for event in _STREAM_ONLY_EVENTS:
        controller._record_event(event, payload)
    controller._on_discovery_event(payload)
    controller._on_vetting_event({**payload, "reason": "all_filters_passed"})
    controller._on_vetting_event(payload)
    controller._on_application_outcome({**payload, "evidence_outcome": "SUBMITTED"})
    controller._on_application_outcome({**payload, "evidence_outcome": "ERROR"})
    controller.request_approval("Approve this?", ["submit"], timeout=0.01)
    controller._record_approval_answer("pin-ctx", "submit", AnsweredBy.HUMAN)

    events = controller.recent_events()
    assert events, "no feed records were produced at all"
    for event in set(_EVENT_KIND_MAP):
        expected_kind = _EVENT_KIND_MAP[event]
        matches = [r for r in events if r.kind is expected_kind and r.text]
        assert matches, (
            f"{event.name} mapped to {expected_kind.name} produced no record; "
            f"expected kinds present: {sorted({r.kind.name for r in events})}"
        )
        assert not any("['" in r.text for r in matches), (
            f"{event.name}'s record looks like a payload key-dump, not a "
            f"sentence: {matches[-1].text!r}"
        )


def test_every_outcome_literal_maps_to_a_kind__teeth() -> None:
    """TEETH: every ApplicationEvidence outcome literal is covered.

    Fails today because _OUTCOME_KIND_MAP did not exist. The literal set is
    read from the model's annotation, not retyped here — a new outcome
    added to ApplicationEvidence fails here until its kind is decided."""
    outcome_literals = set(
        get_args(ApplicationEvidence.model_fields["outcome"].annotation)
    )
    assert outcome_literals == set(_OUTCOME_KIND_MAP), (
        f"unmapped outcomes: {sorted(outcome_literals - set(_OUTCOME_KIND_MAP))}; "
        f"map entries for outcomes that no longer exist: "
        f"{sorted(set(_OUTCOME_KIND_MAP) - outcome_literals)}"
    )


def test_every_activity_kind_is_reachable__teeth() -> None:
    """TEETH: no kind is unreachable vocabulary.

    Fails today because neither map nor ActivityKind existed. A kind no
    event can ever produce is dead vocabulary a UI would switch on in vain."""
    reachable = set(_EVENT_KIND_MAP.values()) | set(_OUTCOME_KIND_MAP.values())
    assert reachable == set(ActivityKind), (
        f"unreachable kinds: {sorted(set(ActivityKind) - reachable)}"
    )


def test_browser_health_event_reaches_recent_events__teeth() -> None:
    """TEETH: a browser-health event published on the bus lands in the feed.

    Fails today — BROWSER_UNHEALTHY was not subscribed by the controller,
    so recent_events() returned empty even though the orchestrator saw the
    same event. This is the live-run gap: the browser died while the feed
    showed nothing."""
    controller, bus = _projection_controller()
    assert controller.recent_events() == ()
    bus.publish(Event.BROWSER_UNHEALTHY, {
        "consecutive_failures": 3,
        "metrics": {},
        "last_error": "timeout",
    })
    events = controller.recent_events()
    assert events, "BROWSER_UNHEALTHY produced no feed record"
    assert events[-1].kind is ActivityKind.BLOCKED
    assert events[-1].text


def test_blocked_and_refused_render_distinctly__teeth() -> None:
    """TEETH (the live-run loss): a CAPTCHA block and a gate refusal are
    different kinds, not one undifferentiated "failed" record.

    Fails today: both landed under Event.APPLICATION_FAILED with no kind
    refinement. This is the scenario the projection exists for — seven
    CAPTCHA_BLOCKED applications the person could not distinguish from a
    broken run."""
    controller, _bus = _projection_controller()
    controller._on_application_outcome(
        {**_fat_payload(), "evidence_outcome": "CAPTCHA_BLOCKED"}
    )
    controller._on_application_outcome(
        {**_fat_payload(), "evidence_outcome": "SUBMISSION_GATE_BLOCKED"}
    )
    controller._on_application_outcome(
        {**_fat_payload(), "evidence_outcome": "SUBMITTED"}
    )
    kinds = [r.kind for r in controller.recent_events()]
    assert ActivityKind.BLOCKED in kinds
    assert ActivityKind.REFUSED in kinds
    assert ActivityKind.APPLIED in kinds


def test_recent_events_records_are_port_legal__teeth() -> None:
    """TEETH: every record the projection produces is a port-legal DTO.

    Fails today because the projection path did not exist. kind must be an
    ActivityKind member (never the raw Event), and every record must
    round-trip through its own frozen schema."""
    controller, _bus = _projection_controller()
    controller._record_event(Event.BROWSER_UNHEALTHY, _fat_payload())
    controller._on_application_outcome(
        {**_fat_payload(), "evidence_outcome": "SUBMITTED"}
    )
    for record in controller.recent_events():
        assert isinstance(record.kind, ActivityKind), (
            f"record kind {record.kind!r} is not an ActivityKind — the raw "
            f"internal Event must never cross the port"
        )
        SessionEventRecord(**record.model_dump())


def test_projection_drops_payload_pii__teeth() -> None:
    """TEETH: sentinel PII-shaped values in unknown payload keys never
    appear in rendered text; whitelisted job data always does.

    Fails today because the whitelist renderers did not exist. The
    sentinel strings are unique enough that any appearance in any record
    is a leak, not a coincidence."""
    controller, _bus = _projection_controller()
    payload = _fat_payload()
    sentinels = (
        "SENTINEL_EMAIL@example.com",
        "SENTINEL-PHONE-555",
        "SENTINEL-NAME-JANE",
        "SENTINEL-ADDRESS-1-MAIN-ST",
    )

    for event in _STREAM_ONLY_EVENTS:
        controller._record_event(event, payload)
    controller._on_vetting_event(payload)
    controller._on_application_outcome(
        {**payload, "evidence_outcome": "SUBMITTED"}
    )

    events = controller.recent_events()
    assert events, "no records produced — the pin would pass vacuously"
    all_text = "\n".join(r.text for r in events)
    for sentinel in sentinels:
        assert sentinel not in all_text, (
            f"payload value {sentinel!r} leaked into the feed — a renderer "
            f"is interpolating keys it was not written to read"
        )
    job_records = [
        r for r in events
        if r.kind in (ActivityKind.APPLIED, ActivityKind.REJECTED)
    ]
    assert job_records, "no job records produced"
    assert all("Software Engineer" in r.text for r in job_records), (
        "whitelisted job title did not survive rendering"
    )


def test_recent_events_empty_before_session__guard() -> None:
    """GUARD: before any session, the stream is an empty tuple — the
    null-object ruling — never None and never an exception."""
    controller, _bus = _projection_controller()
    assert controller.recent_events() == ()
    assert controller.recent_events(limit=0) == ()


def test_recent_events_order_and_limit__guard() -> None:
    """GUARD: records arrive oldest-first; limit returns the newest window,
    oldest of the window first. (The port documents oldest-first; D1 does
    not flip it.)"""
    controller, _bus = _projection_controller()
    controller._record_stream(ActivityKind.FOUND, "first")
    controller._record_stream(ActivityKind.VETTED, "second")
    controller._record_stream(ActivityKind.APPLIED, "third")

    kinds = [r.kind for r in controller.recent_events()]
    assert kinds == [ActivityKind.FOUND, ActivityKind.VETTED, ActivityKind.APPLIED]

    window = [r.kind for r in controller.recent_events(limit=2)]
    assert window == [ActivityKind.VETTED, ActivityKind.APPLIED]


# ═════════════════════════════════════════════════════════════════════════════
# Autonomy (stage E1) — the control, the state, and the record
#
# The backend honoured the choice before this stage; E1 adds the CONTROL (a
# switch both surfaces can reach, through the port and a shared
# application-layer write), the VISIBILITY (state shown at startup, before a
# run, on the dashboard and in results), and the RECORD (a session run with
# autonomy on is labelled, and every submission it makes is stamped POLICY
# rather than passing as human).
#
# Pin labels follow the standing method:
#   TEETH — fail against the pre-E1 tree by construction (the method, field,
#           or stamp does not exist there).
#   GUARD — passes on both trees; freezes a property the change must not
#           break, stated so the next reader does not delete it.
# ═════════════════════════════════════════════════════════════════════════════

_PKG_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_SRC = (
    _PKG_ROOT / "src" / "auto_apply" / "application" / "workflows" / "applications_workflow.py"
)


def _autonomy_profile(checkpoints) -> SimpleNamespace:
    """A minimal profile-shaped object: only what the autonomy write touches."""
    return SimpleNamespace(
        app_config=SimpleNamespace(human_review_checkpoints=checkpoints)
    )


def _autonomy_controller(checkpoints=None, repo=None):
    """A SessionController with mocked registry/db/orchestrator whose active
    profile carries the given checkpoint list.

    Kept separate from _controller() above so a change to the shared helper
    cannot silently alter what the autonomy pins assert.
    """
    plan = SessionPlan(session_id="autonomy-pin")
    profile = _autonomy_profile(checkpoints)
    registry = MagicMock()
    registry.get_session_plan.return_value = plan
    registry.get_active_profile.return_value = profile
    db = MagicMock()
    db.get_queue_stats.return_value = _queue_stats()
    orchestrator = MagicMock()
    orchestrator.session_plan = plan
    orchestrator.context = MagicMock()
    orchestrator.context.session_id = "autonomy-pin"
    orchestrator.context.stats = SessionStatistics()
    orchestrator.state_machine = MagicMock()
    orchestrator.task_queue = db
    controller = SessionController(
        registry=registry, db=db, orchestrator=orchestrator, profile_repo=repo
    )
    controller._check_network_connectivity = lambda: True
    return controller, profile


class TestApplyAutonomy:
    """The shared write both surfaces and the port method delegate to."""

    def test_enable_with_zero_acknowledgements_refuses__teeth(self) -> None:
        """TEETH: enabling with no acknowledgements must change nothing —
        the two-warning rule is enforced by the write itself, not trusted
        to the surfaces."""
        profile, repo = _autonomy_profile(None), MagicMock()
        assert apply_autonomy(profile, repo, True, ()) is False
        repo.save_profile.assert_not_called()
        assert profile.app_config.human_review_checkpoints is None

    def test_enable_with_one_acknowledgement_refuses__teeth(self) -> None:
        """TEETH: one acknowledgement is not two — refuse."""
        profile, repo = _autonomy_profile(None), MagicMock()
        assert apply_autonomy(profile, repo, True, ("yes",)) is False
        repo.save_profile.assert_not_called()
        assert profile.app_config.human_review_checkpoints is None

    def test_enable_with_two_applies_and_persists__teeth(self) -> None:
        """TEETH: two acknowledgements write the autonomous checkpoint set
        and persist through the repository."""
        profile, repo = _autonomy_profile(None), MagicMock()
        assert apply_autonomy(profile, repo, True, ("a", "b")) is True
        assert set(profile.app_config.human_review_checkpoints) == {
            "ON_SUSPICIOUS_REDIRECT"
        }
        assert "BEFORE_FORM_SUBMIT" not in profile.app_config.human_review_checkpoints
        repo.save_profile.assert_called_once_with(profile)

    def test_disable_restores_review_defaults__guard(self) -> None:
        """GUARD: disabling needs no acknowledgements and restores review."""
        profile, repo = _autonomy_profile(["ON_SUSPICIOUS_REDIRECT"]), MagicMock()
        assert apply_autonomy(profile, repo, False, ()) is True
        assert set(profile.app_config.human_review_checkpoints) == {
            "BEFORE_FORM_SUBMIT", "ON_SUSPICIOUS_REDIRECT"
        }
        repo.save_profile.assert_called_once_with(profile)

    def test_apply_raises_without_repository__teeth(self) -> None:
        """TEETH: an in-memory-only write would vanish on restart — refuse loudly."""
        with pytest.raises(RuntimeError):
            apply_autonomy(_autonomy_profile(None), None, True, ("a", "b"))


class TestIsAutonomousParse:
    """One answer to 'is this autonomous?' — parse and fallback included."""

    @pytest.mark.parametrize(
        "checkpoints",
        [
            None,
            [],
            ["NONSENSE"],
            ["before_form_submit"],
            ["BEFORE_FORM_SUBMIT"],
            ["BEFORE_FORM_SUBMIT", "ON_SUSPICIOUS_REDIRECT"],
        ],
    )
    def test_not_autonomous__teeth(self, checkpoints) -> None:
        """TEETH: empty, unknown, or review-containing lists are NOT
        autonomous. The unknown case is the fallback the whole change leans
        on: a typo must fall back to review, never to autonomy."""
        assert ProfileBasedInterruptPolicy.is_autonomous(checkpoints) is False

    def test_autonomous_when_review_checkpoint_absent__teeth(self) -> None:
        assert ProfileBasedInterruptPolicy.is_autonomous(["ON_SUSPICIOUS_REDIRECT"]) is True

    @pytest.mark.parametrize(
        "checkpoints",
        [None, [], ["NONSENSE"], ["ON_SUSPICIOUS_REDIRECT"], ["BEFORE_FORM_SUBMIT"]],
    )
    def test_is_autonomous_agrees_with_the_instance__teeth(self, checkpoints) -> None:
        """TEETH: the classmethod and a constructed policy must always agree,
        including through the empty/fallback path."""
        policy = ProfileBasedInterruptPolicy(checkpoints)
        pauses = policy.should_pause(Checkpoint.BEFORE_FORM_SUBMIT, None)
        assert pauses is (not ProfileBasedInterruptPolicy.is_autonomous(checkpoints))


class TestControllerAutonomy:
    """The session's frozen answer, the port, and the typed labels."""

    def test_controller_satisfies_the_widened_port__guard(self) -> None:
        controller, _ = _autonomy_controller()
        assert isinstance(controller, UIPort)

    def test_autonomy_reflects_construction_checkpoints__teeth(self) -> None:
        controller, _ = _autonomy_controller(checkpoints=["ON_SUSPICIOUS_REDIRECT"])
        assert controller.autonomy() is True

    def test_autonomy_defaults_off__guard(self) -> None:
        controller, _ = _autonomy_controller(checkpoints=None)
        assert controller.autonomy() is False

    def test_autonomy_is_frozen_for_the_controller_lifetime__teeth(self) -> None:
        """TEETH: set_autonomy writes the profile but the current session's
        answer must NOT move — a mid-run flip is exactly the failure the
        maintainer's condition forbids."""
        controller, profile = _autonomy_controller(checkpoints=None, repo=MagicMock())
        assert controller.autonomy() is False
        assert controller.set_autonomy(True, ("a", "b")) is True
        assert profile.app_config.human_review_checkpoints == ["ON_SUSPICIOUS_REDIRECT"]
        assert controller.autonomy() is False, (
            "the session's autonomy answer moved mid-run — the guarantee "
            "is that a session's policy cannot change after composition"
        )

    def test_set_autonomy_refuses_with_one_acknowledgement__teeth(self) -> None:
        controller, profile = _autonomy_controller(checkpoints=None, repo=MagicMock())
        assert controller.set_autonomy(True, ("one",)) is False
        assert profile.app_config.human_review_checkpoints is None

    def test_set_autonomy_raises_without_repo__teeth(self) -> None:
        controller, _ = _autonomy_controller(checkpoints=None, repo=None)
        with pytest.raises(RuntimeError):
            controller.set_autonomy(True, ("a", "b"))

    def test_snapshot_and_summary_carry_autonomy__teeth(self) -> None:
        """TEETH: the session's automation intensity is visible in the typed views."""
        controller, _ = _autonomy_controller(checkpoints=["ON_SUSPICIOUS_REDIRECT"])
        assert controller.snapshot().autonomy_enabled is True
        assert controller.summary().autonomy_enabled is True

    def test_null_views_default_to_review__guard(self) -> None:
        assert SessionSnapshot().autonomy_enabled is False
        assert SessionSummary().autonomy_enabled is False


class TestPolicyStamp:
    """A machine-authorised submission is labelled, never passed as human."""

    def test_submission_in_autonomous_session_stamps_policy__teeth(self) -> None:
        """TEETH: with autonomy on, the policy authorises submissions, and
        that machine decision must be labelled in the evidence record."""
        controller, _ = _autonomy_controller(checkpoints=["ON_SUSPICIOUS_REDIRECT"])
        controller._on_application_outcome({
            "job_url": "https://example.test/j/1",
            "job_title": "Engineer",
            "company": "Acme",
            "evidence_outcome": "SUBMITTED",
            "evidence_confidence": 0.9,
        })
        answers = controller.approval_evidence()
        assert len(answers) == 1
        assert answers[0].answered_by is AnsweredBy.POLICY
        assert answers[0].checkpoint == "BEFORE_FORM_SUBMIT"
        assert answers[0].choice == "submit"
        assert any(
            "authorized by policy" in r.text
            for r in controller.recent_events()
        ), "the stream must note the policy authorisation visibly"

    def test_review_session_submission_does_not_stamp_policy__guard(self) -> None:
        """GUARD: with autonomy off, a submission is a human/gate answer,
        not a policy answer — nothing may be mislabeled."""
        controller, _ = _autonomy_controller(checkpoints=None)
        controller._on_application_outcome({
            "job_url": "https://example.test/j/1",
            "job_title": "Engineer",
            "company": "Acme",
            "evidence_outcome": "SUBMITTED",
            "evidence_confidence": 0.9,
        })
        assert controller.approval_evidence() == ()

    def test_blocked_outcome_in_autonomous_session_stamps_nothing__guard(self) -> None:
        controller, _ = _autonomy_controller(checkpoints=["ON_SUSPICIOUS_REDIRECT"])
        controller._on_application_outcome({
            "job_url": "https://example.test/j/1",
            "job_title": "Engineer",
            "company": "Acme",
            "evidence_outcome": "CAPTCHA_BLOCKED",
            "evidence_confidence": 0.4,
        })
        assert controller.approval_evidence() == ()


def _workflow_for(checkpoints):
    """An ApplicationsWorkflow with only what _authorize_submission touches."""
    from auto_apply.application.workflows.applications_workflow import (
        ApplicationsWorkflow,
    )

    return ApplicationsWorkflow(
        profile=MagicMock(),
        browser=MagicMock(),
        perception_port=None,
        interaction_port=MagicMock(),
        webpage_analyzer=None,
        field_classifier=None,
        semantic_filler=None,
        text_matcher=MagicMock(),
        file_handler=None,
        interruption_handler=None,
        dom_observer=None,
        ats_registry=None,
        job_repo=MagicMock(),
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        interrupt_policy=ProfileBasedInterruptPolicy(checkpoints),
        text_generation_port=None,
        plan=SessionPlan(session_id="autonomy-pin"),
    )


class TestAuthoriserHonoursTheSwitch:
    """The fail-closed authoriser still answers the switch end-to-end."""

    def test_autonomy_on_authorises_without_any_gate__guard(self) -> None:
        """GUARD (existing authoriser behavior, pinned from the autonomy angle):
        no pause configured → authorized, no gate consulted."""
        wf = _workflow_for(["ON_SUSPICIOUS_REDIRECT"])
        authorized, outcome, _detail = wf._authorize_submission(
            MagicMock(url="https://x", title="t", company="c")
        )
        assert authorized is True
        assert outcome == ""

    def test_autonomy_off_blocks_without_a_gate__guard(self) -> None:
        """GUARD: with review required and no gate wired, refusal — the
        fail-closed authoriser must still refuse every ambiguous path it
        refuses today."""
        wf = _workflow_for(None)
        authorized, outcome, _detail = wf._authorize_submission(
            MagicMock(url="https://x", title="t", company="c")
        )
        assert authorized is False
        assert outcome == "SUBMISSION_GATE_BLOCKED"

    def test_the_policy_object_never_changes_during_authorisation__guard(self) -> None:
        """GUARD: the policy the workflow authorises with is the object it was
        constructed with — the composition-time freeze, at runtime."""
        wf = _workflow_for(None)
        policy_before = wf._interrupt_policy
        wf._authorize_submission(MagicMock(url="https://x", title="t", company="c"))
        assert wf._interrupt_policy is policy_before


class _PolicyAssignmentVisitor(ast.NodeVisitor):
    """Finds assignments to self._interrupt_policy outside __init__."""

    def __init__(self) -> None:
        self.scope = "<module>"
        self.bad: list[int] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        prev = self.scope
        self.scope = node.name
        self.generic_visit(node)
        self.scope = prev

    def _check_targets(self, targets, lineno: int) -> None:
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "_interrupt_policy"
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and self.scope != "__init__"
            ):
                self.bad.append(lineno)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._check_targets(node.targets, node.lineno)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._check_targets([node.target], node.lineno)
        self.generic_visit(node)


def test_interrupt_policy_assigned_only_in_init__guard() -> None:
    """GUARD (AST): _interrupt_policy may be assigned only in __init__ — any
    mid-run flip path added later fails here."""
    tree = ast.parse(_WORKFLOW_SRC.read_text(encoding="utf-8"))
    visitor = _PolicyAssignmentVisitor()
    visitor.visit(tree)
    assert visitor.bad == [], (
        f"self._interrupt_policy assigned outside __init__ at lines {visitor.bad}"
    )


def test_workflow_never_rebuilds_its_policy__guard() -> None:
    """GUARD (AST): the workflow never constructs a new policy after composition."""
    source = _WORKFLOW_SRC.read_text(encoding="utf-8")
    assert "ProfileBasedInterruptPolicy(" not in source


def test_authoriser_never_reads_the_profile__guard() -> None:
    """GUARD (AST): _authorize_submission consults only the injected policy —
    no self._profile read, so there is no late read to subvert."""
    tree = ast.parse(_WORKFLOW_SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_authorize_submission":
            offenders = [
                inner.lineno
                for inner in ast.walk(node)
                if isinstance(inner, ast.Attribute)
                and isinstance(inner.value, ast.Name)
                and inner.value.id == "self"
                and inner.attr == "_profile"
            ]
            assert not offenders, (
                f"_authorize_submission reads self._profile at lines {offenders}"
            )
            return
    raise AssertionError("_authorize_submission not found in applications_workflow.py")


class TestCLIControl:
    """The CLI asks (two different warnings to enable) and applies pre-build."""

    def _startup(self, profile, repo):
        from auto_apply.adapters.primary.cli.startup import CLIStartup

        return CLIStartup(profile_repo_factory=lambda **kw: repo)

    def test_enable_flow_asks_two_different_questions_and_applies__teeth(self, capsys) -> None:
        """TEETH: the enable path must ask exactly two differently-worded
        confirmations and apply only when both are confirmed."""
        profile, repo = _autonomy_profile(None), MagicMock()
        startup = self._startup(profile, repo)
        prompts: list[str] = []
        answers = iter(["y", "YES", "YES"])

        def _input(prompt: str = "") -> str:
            prompts.append(prompt)
            return next(answers)

        with patch("builtins.input", _input):
            startup._ask_autonomy(profile)

        yes_prompts = [p for p in prompts if "YES" in p]
        assert len(yes_prompts) == 2, f"expected two YES confirmations, got {yes_prompts}"
        assert yes_prompts[0] != yes_prompts[1], (
            "the two warnings must say different things — two identically-worded "
            "confirmations are one confirmation with an extra click"
        )
        out = capsys.readouterr().out
        assert "WARNING 1 of 2" in out and "WARNING 2 of 2" in out, (
            "enabling must show two warnings, not one"
        )
        assert "real name and email" in out, (
            "the second warning must name a consequence the first did not"
        )
        assert set(profile.app_config.human_review_checkpoints) == {"ON_SUSPICIOUS_REDIRECT"}
        repo.save_profile.assert_called_once_with(profile)

    def test_declining_leaves_autonomy_off__guard(self) -> None:
        profile, repo = _autonomy_profile(None), MagicMock()
        startup = self._startup(profile, repo)
        with patch("builtins.input", lambda prompt="": "n"):
            startup._ask_autonomy(profile)
        assert profile.app_config.human_review_checkpoints is None
        repo.save_profile.assert_not_called()

    def test_one_yes_then_decline_does_not_apply__guard(self) -> None:
        profile, repo = _autonomy_profile(None), MagicMock()
        startup = self._startup(profile, repo)
        answers = iter(["y", "YES", "no"])
        with patch("builtins.input", lambda prompt="": next(answers)):
            startup._ask_autonomy(profile)
        assert profile.app_config.human_review_checkpoints is None
        repo.save_profile.assert_not_called()

    def test_turning_off_needs_one_confirmation__guard(self) -> None:
        profile, repo = _autonomy_profile(["ON_SUSPICIOUS_REDIRECT"]), MagicMock()
        startup = self._startup(profile, repo)
        with patch("builtins.input", lambda prompt="": "y"):
            startup._ask_autonomy(profile)
        assert set(profile.app_config.human_review_checkpoints) == {
            "BEFORE_FORM_SUBMIT", "ON_SUSPICIOUS_REDIRECT"
        }


class TestGUISurface:
    """The GUI shows the state and names a fully automated session."""

    def test_state_text_differs_by_state__teeth(self) -> None:
        from auto_apply.adapters.primary.gui.wizard import autonomy_state_text

        assert autonomy_state_text(True) != autonomy_state_text(False)

    def test_state_text_names_the_behaviour__teeth(self) -> None:
        from auto_apply.adapters.primary.gui.wizard import autonomy_state_text

        assert "without asking" in autonomy_state_text(True)
        assert "ask before" in autonomy_state_text(False)

    def test_results_lines_show_autonomy__teeth(self) -> None:
        from auto_apply.adapters.primary.gui.app import format_results_lines

        lines = format_results_lines(SessionSummary(autonomy_enabled=True))
        assert any("Autonomy" in line for line in lines)

    def test_results_lines_quiet_when_off__guard(self) -> None:
        from auto_apply.adapters.primary.gui.app import format_results_lines

        lines = format_results_lines(SessionSummary(autonomy_enabled=False))
        assert not any("Autonomy" in line for line in lines)

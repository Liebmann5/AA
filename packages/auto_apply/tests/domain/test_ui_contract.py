"""Pins for the UI contract types and the UIPort driving port.

Labels are honest, per the standing method:
  TEETH — verified to fail against the pre-change tree for the reason
          stated (the untyped dict had none of this structure). The
          discrimination proof for the type checker is in
          test_type_checker_rejects_session_controller_today.
  GUARD — passes on both trees; freezes a ruling a future edit must not
          quietly break.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

import pytest
from pydantic import BaseModel, ValidationError

from auto_apply.application.agent.state_machine import AgentState
from auto_apply.application.services.session_controller import SessionController
from auto_apply.domain.models.session_plan import SessionExecutionMode
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
from auto_apply.domain.ports.ui_port import UIPort

_UI_CONTRACT_MODULE = "auto_apply.domain.models.ui_contract"

_EXPECTED_PORT_METHODS = {
    "initialize_session", "start", "stop", "pause", "resume",
    "provide_approval", "snapshot", "summary", "queue_snapshot",
    "pending_approvals", "is_running", "recent_events",
    # C2 (2026-09-15) grew the port from 12 to 15. Each earns its place:
    #   export_session_results — a DISCOVER_ONLY run's output is otherwise
    #                            unreachable; it is the mode's deliverable.
    #   export_profile         — import_profile had no counterpart, so the USB
    #                            story only ever ran one way.
    #   list_session_history   — SessionReport.save() had no reader at all.
    "export_session_results", "export_profile", "list_session_history",
    # E1 (2026-09-16) grew the port from 15 to 17:
    #   autonomy     — the read a user could never otherwise make ("is THIS
    #                  session going to submit without asking?").
    #   set_autonomy — the write: the control both surfaces use to change the
    #                  choice, guarded by two acknowledgements.
    "autonomy", "set_autonomy",
}


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
    # Order matters, and not for style. On Python 3.9/3.10
    # `isinstance(tuple[str, ...], type)` is True — it only became False in
    # 3.11 (gh-88790). Checking isinstance first sent every parameterised
    # generic into the class branch, where it failed both issubclass tests and
    # returned False without ever reaching the tuple check. That rejected all
    # four tuple[...] methods on UIPort under 3.10, which is the requires-python
    # floor, while passing on 3.12. Testing the origin first is correct on every
    # version: get_origin() is None for a plain class, so real classes still
    # reach the isinstance branch below.
    origin = get_origin(t)
    if origin is tuple:
        return all(a is Ellipsis or _is_data_type(a) for a in get_args(t))
    if origin is Union or origin is UnionType:
        return all(_is_data_type(a) for a in get_args(t))
    if origin is not None:
        return False        # any other container is a data-shape violation
    if isinstance(t, type):
        if issubclass(t, Enum):
            return True
        if issubclass(t, BaseModel) and t.__module__ == _UI_CONTRACT_MODULE:
            return True
        return False
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

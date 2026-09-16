"""Pins for D2: both dashboards render the port's activity stream.

The AST pins read cli/dashboard.py, gui/dashboard.py and gui/app.py as text —
they never import Tk, never construct a widget, and need no display. The CLI
behavioral pins exercise display-free logic only (the prompt handler is
input()/print(), the diff helper is pure).

Pin labels are honest:
  TEETH — each fails against the pre-D2 tree by construction (zero call
          sites, zero formatter, two subscriptions). I have not verified the
          red runs by execution; the mechanism is stated in each docstring.
  GUARD — passes on both trees; freezes the HITL prompt and the empty-stream
          null-object behavior the dashboards must not lose.
"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path
from unittest.mock import MagicMock

from auto_apply.domain.models.ui_contract import (
    ACTIVITY_MARKS,
    ActivityKind,
    ApprovalRequest,
    SessionEventRecord,
    activity_new,
    format_activity_line,
)

_PKG_ROOT = Path(__file__).resolve().parents[2]
_CLI_DASH = _PKG_ROOT / "src" / "auto_apply" / "adapters" / "primary" / "cli" / "dashboard.py"
_GUI_DASH = _PKG_ROOT / "src" / "auto_apply" / "adapters" / "primary" / "gui" / "dashboard.py"
_GUI_APP = _PKG_ROOT / "src" / "auto_apply" / "adapters" / "primary" / "gui" / "app.py"


def _call_names(path: Path) -> set[str]:
    """Names invoked in call position anywhere in the file (attr or bare)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names


def _import_modules(path: Path) -> set[str]:
    """Dotted module names imported anywhere in the file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def _record(kind: ActivityKind, text: str = "Blocked by CAPTCHA: Engineer @ Acme") -> SessionEventRecord:
    return SessionEventRecord(kind=kind, text=text)


# ─────────────────────────────────────────────────────────────────────────────
# TEETH
# ─────────────────────────────────────────────────────────────────────────────

def test_gui_surface_reads_the_stream__teeth() -> None:
    """TEETH: gui/app.py reads recent_events() and feeds it to the panel.

    Fails today: zero call sites anywhere under adapters/primary. Asserted by
    AST, not by a grep of intent — a call site that is later deleted fails
    here, not silently."""
    calls = _call_names(_GUI_APP)
    assert "recent_events" in calls, (
        "gui/app.py never calls controller.recent_events() — the GUI surface "
        "has no path from the port's stream to the screen"
    )
    assert "feed_activity" in calls, (
        "gui/app.py reads the stream but never hands it to the dashboard — "
        "feed_activity() is the writer path, call it"
    )


def test_cli_surface_reads_the_stream__teeth() -> None:
    """TEETH: cli/dashboard.py reads recent_events().

    Fails today: the CLI subscribes to one Event and has no stream call site."""
    calls = _call_names(_CLI_DASH)
    assert "recent_events" in calls, (
        "cli/dashboard.py never calls controller.recent_events() — the CLI "
        "surface has no activity output at all"
    )


def test_gui_log_message_has_a_caller__teeth() -> None:
    """TEETH: Dashboard.log_message is invoked somewhere.

    Fails today: the Activity panel's writer has zero callers. The caller
    lives in feed_activity() (self.log_message) — a second writer path is
    exactly what this pin forbids by only requiring one."""
    assert "log_message" in _call_names(_GUI_DASH), (
        "Dashboard.log_message has zero callers — the panel is a widget with "
        "a write method nobody calls"
    )


def test_both_surfaces_use_the_one_formatter__teeth() -> None:
    """TEETH: cli and gui both call ui_contract.format_activity_line.

    Two surfaces wording the same record two ways is the drift this arc
    exists to remove, so both must import and call the ONE formatter rather
    than composing their own line. Fails today: neither dashboard imports
    format_activity_line."""
    for path in (_CLI_DASH, _GUI_DASH):
        assert "format_activity_line" in _call_names(path), (
            f"{path.name} does not call format_activity_line — if it "
            f"formats records itself, the two surfaces will drift"
        )
        assert "auto_apply.domain.models.ui_contract" in _import_modules(path), (
            f"{path.name} must import the shared formatter from ui_contract"
        )


def test_formatter_output_matches_one_source__teeth() -> None:
    """TEETH: one record renders as timestamp + mark + text, mark from the
    shared map — never a literal retyped here.

    Fails today because format_activity_line does not exist. The mark is
    read from ACTIVITY_MARKS, so a mark change updates this pin's
    expectation instead of breaking it — the pin compares against the
    single source, not a second literal."""
    record = _record(ActivityKind.BLOCKED)
    line = format_activity_line(record)
    assert line == (
        f"{record.at:%H:%M:%S} {ACTIVITY_MARKS[ActivityKind.BLOCKED]} {record.text}"
    )
    assert record.text in line, "the record's text must appear verbatim"
    for kind in ActivityKind:
        # Every kind has a mark — a kind added to the enum without a mark
        # fails here (KeyError), which is the point.
        format_activity_line(_record(kind, text="x"))


def test_activity_new_diffs_and_replays_on_wrap__teeth() -> None:
    """TEETH: the diff helper returns only new records, and replays the
    window when the last-displayed record has fallen out (deque wrapped).

    Index-based diffing starves forever once the bounded deque wraps; this
    helper diffs by record identity. Fails today because activity_new does
    not exist."""
    a = _record(ActivityKind.FOUND, "a")
    b = _record(ActivityKind.VETTED, "b")
    c = _record(ActivityKind.APPLIED, "c")
    records = (a, b, c)

    assert activity_new(records, a) == (b, c)
    assert activity_new(records, c) == ()
    assert activity_new(records, None) == records

    # last_displayed fell out of the window (deque wrapped or new session):
    # the whole current window replays — a bounded replay, never silence.
    stale = _record(ActivityKind.FOUND, "stale")
    assert activity_new(records, stale) == records


def test_no_direct_bus_subscription_remains__teeth() -> None:
    """TEETH: neither dashboard subscribes to the bus or imports domain.events.

    Fails today: both dashboards call event_bus.subscribe and import
    domain.events.Event. U4's import ban (adapters may import only the port
    and domain.models.*) is satisfied by construction — the poll, not a
    subscription, is the only seam."""
    for path in (_CLI_DASH, _GUI_DASH):
        assert "subscribe" not in _call_names(path), (
            f"{path.name} still calls .subscribe() on the event bus — the "
            f"port's poll is the only seam an adapter may use"
        )
        assert "auto_apply.domain.events" not in _import_modules(path), (
            f"{path.name} imports domain.events — that import is the coupling "
            f"the port exists to remove"
        )


# ─────────────────────────────────────────────────────────────────────────────
# GUARDS
# ─────────────────────────────────────────────────────────────────────────────

def test_cli_gate_prompt_still_opens_and_releases__guard(
    monkeypatch, capsys
) -> None:
    """GUARD: the HITL prompt opens, blocks on input, and releases the gate.

    Whatever the mechanism (subscription before, port poll now), a gate must
    still reach a human and release with their choice. Display-free: the
    handler is input()/print(), monkeypatched."""
    from auto_apply.adapters.primary.cli.dashboard import CLIDashboard

    controller = MagicMock()
    approval = ApprovalRequest(
        context_id="ctx-1",
        checkpoint="CAPTCHA_REQUIRES_MANUAL_SOLVE",
        question="A CAPTCHA is blocking the page. Continue?",
        options=("solved", "skip"),
    )
    dashboard = CLIDashboard(controller)

    monkeypatch.setattr(builtins, "input", lambda _prompt="": "1")
    dashboard._handle_approval_prompt(approval)

    out = capsys.readouterr().out
    assert "Approval Required" in out, "the prompt never opened"
    controller.provide_approval.assert_called_once_with("ctx-1", "solved")


def test_gui_gate_check_is_wired_in_the_poll__guard() -> None:
    """GUARD (structural, no Tk): the GUI polls pending gates and the modal
    still calls provide_approval with the gate's context id."""
    app_calls = _call_names(_GUI_APP)
    assert "pending_approvals" in app_calls, (
        "gui/app.py does not poll controller.pending_approvals() — a gate "
        "would never reach the GUI user"
    )
    assert "show_approval" in app_calls, (
        "gui/app.py polls gates but never shows the modal"
    )
    dash_calls = _call_names(_GUI_DASH)
    assert "provide_approval" in dash_calls, (
        "the GUI modal no longer calls provide_approval — the gate would "
        "open but never release"
    )


def test_empty_stream_is_safe__guard(capsys) -> None:
    """GUARD: a dashboard with no session yet renders an empty stream rather
    than raising — the null-object ruling."""
    from auto_apply.adapters.primary.cli.dashboard import CLIDashboard

    controller = MagicMock()
    controller.recent_events.return_value = ()
    dashboard = CLIDashboard(controller)
    dashboard._poll_activity()
    assert capsys.readouterr().out == "", (
        "an empty stream produced output — it should be a no-op"
    )
    assert activity_new((), None) == (), (
        "activity_new must return an empty tuple for an empty window"
    )

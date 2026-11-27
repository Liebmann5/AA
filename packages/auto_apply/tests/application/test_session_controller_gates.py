"""Pins for the one choke point every question to the person passes through
(``SessionController.request_approval``): the gate contract ``hitl_gate``
relies on, the person's time-limit setting (WCAG 2.2 SC 2.2.1), stopping
releases every open question, and the person's typed or private answers.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import pytest

from auto_apply.application.services.session_controller import (
    AnsweredBy,
    SessionController,
)

from .test_ui_port_conformance import _controller


def _with_limits(mode: str) -> SessionController:
    controller = _controller()

    def effective(key: str, default: Any = None) -> Any:
        return {"time_limits": mode} if key == "accessibility" else default

    controller.registry.get_effective_config.side_effect = effective  # type: ignore[attr-defined]
    return controller


def _open(controller: SessionController, **kw: Any) -> tuple[threading.Thread, list[str]]:
    out: list[str] = []
    t = threading.Thread(target=lambda: out.append(controller.request_approval(**kw)),
                         daemon=True)
    t.start()
    for _ in range(200):
        if controller.pending_approvals():
            break
        time.sleep(0.01)
    return t, out


def test_the_gate_keeps_its_promise_to_return_within_its_timeout() -> None:
    """The contract hitl_gate rests on: no thread is ever abandoned because
    the gate itself returns when its time is up."""
    controller = _controller()
    started = time.monotonic()
    assert controller.request_approval("Q?", ["done"], timeout=0.05) == "skip"
    assert time.monotonic() - started < 2.0


@pytest.mark.parametrize(("mode", "wait"), [("1x", 10.0), ("3x", 30.0), ("10x", 100.0),
                                            ("off", None)])
def test_the_person_s_setting_scales_every_question(mode: str, wait: float | None) -> None:
    controller = _with_limits(mode)
    t, out = _open(controller, question="Q?", options=["done"], checkpoint="X", timeout=10.0)
    pending = controller.pending_approvals()
    assert pending and pending[0].wait_s == wait
    assert controller.provide_approval(pending[0].context_id, "done")
    t.join(2)
    assert out == ["done"]


def test_stopping_releases_a_question_with_no_time_limit() -> None:
    controller = _with_limits("off")
    t, out = _open(controller, question="Q?", options=["done"], checkpoint="X", timeout=10.0)
    assert controller.pending_approvals()[0].wait_s is None
    controller.stop()
    t.join(2)
    assert not t.is_alive() and out == ["skip"]
    evidence = controller.approval_evidence()
    assert evidence[-1].answered_by is AnsweredBy.STOPPED and evidence[-1].choice == "skip"


def test_a_typed_answer_is_the_person_s_words_and_an_empty_one_is_refused() -> None:
    controller = _controller()
    t, out = _open(controller, question="City?", options=["skip"], checkpoint="FORM",
                   timeout=10.0, kind="text", private=True)
    req = controller.pending_approvals()[0]
    assert req.kind == "text" and req.private and req.options == ("skip",)
    assert not controller.provide_approval(req.context_id, "   ")
    assert controller.provide_approval(req.context_id, "Springfield")
    t.join(2)
    assert out == ["Springfield"]


def test_a_private_answer_is_never_logged_or_kept_as_evidence(
        caplog: pytest.LogCaptureFixture) -> None:
    controller = _controller()
    with caplog.at_level(logging.DEBUG):
        t, out = _open(controller, question="Gender?", options=["Female", "Male"],
                       checkpoint="FORM", timeout=10.0, private=True)
        req = controller.pending_approvals()[0]
        assert controller.provide_approval(req.context_id, "Female")
        t.join(2)
    assert out == ["Female"]
    assert "Female'" not in caplog.text and "choice='Female'" not in caplog.text
    assert controller.approval_evidence()[-1].choice == "answered"


def test_an_ordinary_answer_is_still_recorded_as_given() -> None:
    controller = _controller()
    t, out = _open(controller, question="Submit?", options=["submit"], checkpoint="X",
                   timeout=10.0)
    req = controller.pending_approvals()[0]
    assert req.kind == "choice" and not req.private
    assert controller.provide_approval(req.context_id, "submit")
    t.join(2)
    assert controller.approval_evidence()[-1].choice == "submit"

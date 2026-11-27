"""Pins for asking the person through the approval gate (``hitl_gate``).

Round-3 review findings these hold: no worker thread is ever started (an
abandoned one reading the terminal would swallow the person's next answer),
so a gate that cannot promise to return — one without a ``timeout`` — is
not asked at all; a gate that raises ``TypeError`` inside is asked once; the
person's typed answers are taken only from a gate that says it takes them;
nothing an exception says reaches the log.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import pytest

from auto_apply.application.services.hitl_gate import (
    accepts_timeout,
    ask_gate,
    ask_text,
    can_ask_text,
)


def test_a_gate_that_takes_a_timeout_is_given_it() -> None:
    seen: dict[str, Any] = {}

    def gate(question: str, options: list[str], *, checkpoint: str, timeout: float) -> str:
        seen.update(checkpoint=checkpoint, timeout=timeout)
        return "done"

    assert ask_gate(gate, "q", ["done", "skip"], checkpoint="X", timeout=12.0) == "done"
    assert seen == {"checkpoint": "X", "timeout": 12.0}


def test_no_time_limit_is_passed_through_as_none() -> None:
    seen: dict[str, Any] = {}

    def gate(question: str, options: list[str], *, checkpoint: str,
             timeout: float | None) -> str:
        seen["timeout"] = timeout
        return "done"

    assert ask_gate(gate, "q", ["done", "skip"], checkpoint="X", timeout=None) == "done"
    assert seen == {"timeout": None}


def test_a_gate_that_raises_type_error_inside_is_asked_once() -> None:
    calls: list[int] = []

    def gate(question: str, options: list[str], **kw: Any) -> str:
        calls.append(1)
        raise TypeError("a bug inside the gate")

    assert ask_gate(gate, "q", ["done", "skip"], checkpoint="X", timeout=1.0) == "skip"
    assert calls == [1]


def test_a_gate_without_a_timeout_is_never_asked_and_no_thread_is_left() -> None:
    """Round-3 (ChatGPT, MAJOR): the old fallback ran such a gate on a worker
    thread and abandoned it on timeout — still blocked on stdin, it would read
    the person's next answer. Now the gate is not called at all."""
    calls: list[int] = []
    release = threading.Event()

    def legacy(question: str, options: list[str], *, checkpoint: str) -> str:
        calls.append(1)
        release.wait(10)            # a prompt nobody answers
        return "done"

    assert not accepts_timeout(legacy)
    before = threading.active_count()
    started = time.monotonic()
    assert ask_gate(legacy, "q", ["done", "skip"], checkpoint="X", timeout=0.2) == "skip"
    assert time.monotonic() - started < 0.5
    assert calls == [] and threading.active_count() == before
    release.set()


@pytest.mark.parametrize("answer", [None, 3, "maybe", ""])
def test_an_answer_that_was_not_offered_is_a_skip(answer: Any) -> None:
    assert ask_gate(lambda *a, **k: answer, "q", ["done", "skip"], checkpoint="X",
                    timeout=1.0) == "skip"


def test_no_gate_is_a_skip() -> None:
    assert ask_gate(None, "q", ["done", "skip"], checkpoint="X", timeout=1.0) == "skip"
    assert ask_text(None, "q", checkpoint="X", timeout=1.0) is None


def test_what_an_exception_says_never_reaches_the_log(caplog: pytest.LogCaptureFixture) -> None:
    def gate(*a: Any, **k: Any) -> str:
        raise RuntimeError("Ada Quill, 555-123-4567")

    with caplog.at_level(logging.DEBUG):
        assert ask_gate(gate, "q", ["done", "skip"], checkpoint="X", timeout=1.0) == "skip"
    assert "RuntimeError" in caplog.text
    assert "Ada" not in caplog.text and "555" not in caplog.text


def test_a_typed_answer_is_taken_only_from_a_gate_that_takes_one() -> None:
    def choice_only(question: str, options: list[str], *, checkpoint: str,
                    timeout: float | None) -> str:
        return "typed words"

    seen: dict[str, Any] = {}

    def full(question: str, options: list[str], *, checkpoint: str, timeout: float | None,
             kind: str = "choice", private: bool = False) -> str:
        seen.update(kind=kind, private=private, options=options)
        return "Springfield"

    assert not can_ask_text(choice_only)
    assert ask_text(choice_only, "City?", checkpoint="X", timeout=1.0) is None
    assert can_ask_text(full)
    assert ask_text(full, "City?", checkpoint="X", timeout=1.0) == "Springfield"
    assert seen == {"kind": "text", "private": True, "options": ["skip"]}


@pytest.mark.parametrize("answer", ["skip", "", "   ", None, 7])
def test_a_skipped_or_empty_typed_answer_is_none(answer: Any) -> None:
    assert ask_text(lambda *a, **k: answer, "q", checkpoint="X", timeout=1.0) is None


def test_private_is_passed_to_a_gate_that_takes_it() -> None:
    seen: dict[str, Any] = {}

    def gate(question: str, options: list[str], *, checkpoint: str, timeout: float | None,
             private: bool = False) -> str:
        seen["private"] = private
        return "Female"

    assert ask_gate(gate, "Gender", ["Female", "Male", "skip"], checkpoint="X", timeout=1.0,
                    private=True) == "Female"
    assert seen == {"private": True}

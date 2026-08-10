"""S8i pins — logging honesty.

Pin labels (honest, per standing method):
  A  TEETH — a 32-char hex task ID containing 10-digit runs must survive the
     PII filter verbatim. Pre-stage the phone pattern matches the digit run
     (no boundary anchors) and the ID is destroyed -> fails.
  B  TEETH — a phone redaction must produce exactly "[PHONE REDACTED]", not
     cascade-mangled output. Pre-stage the field-value pattern re-matches the
     placeholder's own label word ("PHONE REDACTED]") -> "[PHONE [VALUE
     REDACTED]" -> fails.
  C  TEETH (source-level) — main.py must pass console_level/debug_mode into
     setup_logging. Pre-stage the call is bare -> the substrings are absent
     -> fails. (The runtime contract it wires is pinned by E.)
  F  TEETH — after setup_logging(), the selenium remote_connection logger is
     at WARNING. Pre-stage it is never configured (NOTSET) -> fails.
  D  BEHAVIOUR-PRESERVING — a phone number and an email in ordinary prose
     are still redacted, on both trees.
  E  BEHAVIOUR-PRESERVING — setup_logging(console_level=DEBUG) leaves a
     console handler at DEBUG. The parameters already exist pre-stage, so
     this passes on both trees; it documents the contract C wires in main.

The two setup_logging pins snapshot and restore root-logger state and
redirect LOG_DIR to a tmp path, so they leave no residue in the suite.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

import auto_apply
import auto_apply.infrastructure.logging_setup as logging_setup
from auto_apply.infrastructure.log_filter import PIIRedactingFilter

_MAIN_PY = Path(auto_apply.__file__).resolve().parent / "main.py"


@pytest.fixture
def _preserve_logging(monkeypatch, tmp_path):
    """Snapshot root logger state and redirect the log directory."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    selenium_logger = logging.getLogger(
        "selenium.webdriver.remote.remote_connection"
    )
    saved_selenium_level = selenium_logger.level
    monkeypatch.setattr(logging_setup, "LOG_DIR", tmp_path)
    yield
    root.handlers.clear()
    for handler in saved_handlers:
        root.addHandler(handler)
    root.setLevel(saved_level)
    selenium_logger.setLevel(saved_selenium_level)


# --------------------------------------------------------------------------
# Pin A (TEETH): hex task IDs survive the phone pattern
# --------------------------------------------------------------------------

def test_hex_task_id_is_not_destroyed() -> None:
    task_id = "ff1234567890abcdef1234567890abcdef"  # two 10-digit runs
    line = f"Dispatching | type=DISCOVER id={task_id}"
    out = PIIRedactingFilter()._scrub(line)
    assert out == line, (
        f"task ID was mangled by the phone pattern: {out!r}. A 10-digit run "
        f"inside a hex string is not a phone number."
    )


# --------------------------------------------------------------------------
# Pin B (TEETH): phone redaction is not cascade-mangled
# --------------------------------------------------------------------------

def test_phone_redaction_is_not_cascade_mangled() -> None:
    out = PIIRedactingFilter()._scrub("call 555-123-4567 now")
    assert out == "call [PHONE REDACTED] now", (
        f"cascade-mangled output: {out!r} — the field-value pattern "
        f"re-matched the redactor's own placeholder"
    )


# --------------------------------------------------------------------------
# Pin C (TEETH, source-level): --debug reaches setup_logging in main.py
# --------------------------------------------------------------------------

def test_debug_flag_reaches_setup_logging_call() -> None:
    src = _MAIN_PY.read_text(encoding="utf-8")
    assert "console_level=" in src, (
        "setup_logging() is called bare in main.py — --debug cannot reach "
        "the console handler level"
    )
    assert "debug_mode=" in src, (
        "debug_mode is never passed to setup_logging in main.py — the PII "
        "console-filter exemption for debug runs is dead"
    )


# --------------------------------------------------------------------------
# Pin F (TEETH): selenium remote_connection muted after setup
# --------------------------------------------------------------------------

def test_selenium_remote_connection_muted_after_setup(_preserve_logging) -> None:
    logging_setup.setup_logging()
    level = logging.getLogger(
        "selenium.webdriver.remote.remote_connection"
    ).level
    assert level == logging.WARNING, (
        f"selenium remote_connection logger level is {level}, expected "
        f"WARNING — its DEBUG wire chatter is the dominant app.log volume"
    )


# --------------------------------------------------------------------------
# Pin D (BEHAVIOUR-PRESERVING): prose phone/email still redacted
# --------------------------------------------------------------------------

def test_phone_and_email_in_prose_still_redacted() -> None:
    f = PIIRedactingFilter()
    phone_out = f._scrub("reach me at 555-123-4567 please")
    email_out = f._scrub("write to jane@example.com soon")
    assert "555-123-4567" not in phone_out
    assert "jane@example.com" not in email_out
    assert "[EMAIL REDACTED]" in email_out


# --------------------------------------------------------------------------
# Pin E (BEHAVIOUR-PRESERVING): console_level parameter works as documented
# --------------------------------------------------------------------------

def test_setup_logging_debug_console_level(_preserve_logging) -> None:
    logging_setup.setup_logging(
        console_level=logging.DEBUG, debug_mode=True
    )
    root = logging.getLogger()
    console_handlers = [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
    ]
    assert any(h.level == logging.DEBUG for h in console_handlers), (
        "no console handler at DEBUG after setup_logging(console_level=DEBUG)"
    )

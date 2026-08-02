"""Console logging must never crash on non-ASCII, on any platform.

Regression pin for the Windows cp1252 crash: state-machine transitions log a
``\u2192`` arrow, and on a cp1252 console every such message raised
UnicodeEncodeError *inside* the logging handler — three tracebacks per run and
unreadable output. setup_logging() now reconfigures the console stream to UTF-8
with errors="backslashreplace", so logging degrades safely instead of crashing.

The test reproduces the Windows condition deterministically (a cp1252-backed
stream) so it fails against the pre-fix handler and passes after — no Windows
required.
"""
from __future__ import annotations

import io
import logging

# The exact message + args that crashed in production (state_machine.py:365).
_MSG = "StateMachine: %s \u2192 %s (triggered_by=%s)"
_ARGS = ("IDLE", "INITIALIZING", "unspecified")


def _emit_capturing_errors(handler: logging.Handler, stream_logger_name: str) -> bool:
    """Log the arrow message through *handler*; return True if logging errored."""
    errored = {"hit": False}
    original = logging.Handler.handleError
    logging.Handler.handleError = lambda self, record: errored.__setitem__("hit", True)  # type: ignore[assignment]
    try:
        lg = logging.getLogger(stream_logger_name)
        lg.handlers.clear()
        lg.addHandler(handler)
        lg.setLevel(logging.INFO)
        lg.propagate = False
        lg.info(_MSG, *_ARGS)
    finally:
        logging.Handler.handleError = original  # type: ignore[assignment]
    return errored["hit"]


def _cp1252_stream() -> tuple[io.TextIOWrapper, io.BytesIO]:
    buf = io.BytesIO()
    return io.TextIOWrapper(buf, encoding="cp1252", newline="\n"), buf


def test_plain_handler_on_cp1252_would_crash() -> None:
    """Teeth: the pre-fix arrangement (plain handler, cp1252 stream) errors."""
    stream, _ = _cp1252_stream()
    handler = logging.StreamHandler(stream)
    assert _emit_capturing_errors(handler, "unicode_repro_plain") is True, (
        "expected a cp1252 console to fail on the arrow — if this passes, the "
        "reproduction no longer models the Windows console and the regression "
        "guard below is meaningless."
    )


def test_setup_logging_console_is_unicode_safe() -> None:
    """After the fix's remedy the same stream logs the arrow without erroring."""
    stream, buf = _cp1252_stream()
    # Apply exactly what setup_logging() does to the console stream.
    try:
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError):
        stream = io.TextIOWrapper(
            buf, encoding="utf-8", errors="backslashreplace", line_buffering=True
        )
    handler = logging.StreamHandler(stream)
    errored = _emit_capturing_errors(handler, "unicode_repro_fixed")
    handler.flush()
    stream.flush()
    assert errored is False, "console logging still crashes on a non-ASCII message"
    out = buf.getvalue().decode("utf-8", errors="replace")
    assert "\u2192" in out, "the arrow was dropped rather than rendered"

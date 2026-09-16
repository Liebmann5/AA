"""Configures the application-wide logging system.

This module sets up handlers for console output (human-readable) and file
output (JSON structured).  A PII redacting filter is installed on all file
handlers and (in non-debug mode) console handlers after setup.

Two separate concerns are handled here, and both matter:

- The console LOG handler writes to **stderr**, not stdout: the interactive
  profile wizard and the live dashboard own stdout, and the console stream
  is a duplicate of what is already written unconditionally to
  ``dev_data/logs/app.log``. Splitting the streams keeps prompts and
  dashboard out of shell redirection (``python -m auto_apply > run.log``).

- Both ``sys.stdout`` and ``sys.stderr`` are made UTF-8-safe with
  ``errors="backslashreplace"``. The stderr protection keeps logging from
  crashing on non-ASCII log messages; the stdout protection keeps the CLI's
  OWN ``print()`` output — box-drawing characters, check marks, arrows —
  from raising UnicodeEncodeError on Windows consoles or redirected output.
  The stdout assignment is NOT a logging concern and must not be removed on
  the grounds that logging no longer uses stdout: it protects ``print()``.
  (A dedicated console-encoding configuration call is the better long-term
  home for that concern; it lives here because that is where it already was.)
"""

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone

from auto_apply.domain.config import LOG_DIR


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON strings for machine parsing."""

    def format(self, record: logging.LogRecord) -> str:
        """Formats a log record into a JSON string.

        Args:
            record (logging.LogRecord): The log record object containing metadata
                about the event (level, message, timestamp, etc.).

        Returns:
            str: A valid JSON string representing the log event.
        """
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),  # noqa: E501
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def _utf8_safe_stream(stream):
    """Return a UTF-8, never-crash text stream equivalent to *stream*.

    Reconfigures the stream in place when it supports ``reconfigure``;
    otherwise wraps its binary buffer in a new ``io.TextIOWrapper``. Never
    raises: a stream that can be neither reconfigured nor wrapped is returned
    unchanged, so logging and ``print()`` degrade rather than crash on any
    platform. Callers must assign the result back to ``sys.stdout`` or
    ``sys.stderr`` for ``print()`` to benefit — ``print()`` looks those names
    up on every call, so a wrapper held only in a local variable does nothing.
    """
    try:
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        return stream
    except (AttributeError, ValueError):
        pass

    try:
        import io  # noqa: PLC0415

        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            return io.TextIOWrapper(
                buffer,
                encoding="utf-8",
                errors="backslashreplace",
                line_buffering=True,
            )
    except Exception:
        pass
    return stream


def setup_logging(
    console_level: int = logging.INFO,
    json_file: bool = True,
    debug_mode: bool = False,
) -> None:
    """Initializes the root logger with console and file handlers.

    Args:
        console_level (int): Minimum level for console output.
        json_file (bool): Whether to use JSON formatting for the file log.
        debug_mode (bool): If True, PII filtering is disabled on the console
            handler so developers can see real data.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "app.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture everything

    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # 0. UTF-8 protection for the CLI's OWN print() output — NOT for logging.
    #    The CLI user interface (profile wizard, dashboard frames, results
    #    block) prints box-drawing and check-mark characters that cp1252
    #    cannot encode; on Windows consoles or redirected stdout, print()
    #    raises UnicodeEncodeError without this. print() resolves sys.stdout
    #    by name on every call, so the result MUST be assigned back to
    #    sys.stdout to take effect.
    #
    #    DO NOT remove this assignment on the grounds that "logging no longer
    #    uses stdout". It does not exist for logging. That exact reasoning is
    #    what caused the Windows UnicodeEncodeError regression in the CLI's
    #    HITL approval prompt — the print("─" * 52) line — and it must not be
    #    repeated by a future reader.
    sys.stdout = _utf8_safe_stream(sys.stdout)

    # 1. Console Handler — writes to stderr, so interactive prompts and the
    #    live dashboard keep stdout for themselves (logs already persist to
    #    app.log regardless).
    #    Force a UTF-8, never-crash console stream. Python's default console
    #    encoding is platform-dependent (cp1252 on Windows, cp437 on some
    #    consoles); a single non-ASCII character in ANY log message — an arrow,
    #    a bullet, an em dash — otherwise raises UnicodeEncodeError *inside* the
    #    logging handler and spews a traceback per message. Reconfigure the
    #    stream to UTF-8 with errors="backslashreplace" so logging degrades to a
    #    readable escape (e.g. \u2192) instead of crashing, on any platform and
    #    for any message content. This is a reliability/auditability fix, not a
    #    behavioural one — the app never depended on the crash.
    console_stream = _utf8_safe_stream(sys.stderr)
    console_handler = logging.StreamHandler(console_stream)
    console_handler.setLevel(console_level)
    console_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # 2. File Handler — use RotatingFileHandler for cross-platform rotation.
    #    Size-based rotation works on Windows (where TimedRotatingFileHandler
    #    cannot rename open files) and on Linux/macOS.
    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_file,
        maxBytes=5 * 1024 * 1024,   # 5 MB per file
        backupCount=5,               # Keep 5 rotated files → max 30 MB total
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)

    if json_file:
        file_handler.setFormatter(JSONFormatter())
    else:
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(message)s")
        )

    root_logger.addHandler(file_handler)

    # Quiet noisy third-party connection-pool chatter. Selenium drives
    # ChromeDriver over urllib3 with a maxsize=1 pool; even with command
    # dispatch serialized, a transient overlap can still emit
    # "Connection pool is full, discarding connection: localhost" at WARNING.
    # That message is benign (urllib3 simply opens a fresh connection), so we
    # raise its threshold to ERROR to keep the console signal clean while still
    # surfacing genuine pool errors.
    logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

    # Selenium logs every WebDriver command round trip at DEBUG via
    # remote_connection — measured at 96-98% of app.log bytes (137-300 KB/s
    # sustained, ~26 MB in a 112 s session). That is the largest single
    # log-volume source and the worst offender for USB flash endurance.
    # WARNING keeps genuine driver errors visible.
    logging.getLogger("selenium.webdriver.remote.remote_connection").setLevel(
        logging.WARNING
    )

    # ── PII Scrubbing ──────────────────────────────────────────────────────
    try:
        from auto_apply.infrastructure.log_filter import install_pii_filter  # noqa: PLC0415
        install_pii_filter(debug_mode=debug_mode)
    except Exception:
        # Degrade gracefully — logging works without PII filter if the module
        # is unavailable (worst-case environment).
        pass

    logging.info("Logging initialized. Writing logs to %s", log_file)

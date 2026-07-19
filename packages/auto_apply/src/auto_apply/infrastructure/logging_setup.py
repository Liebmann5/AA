"""Configures the application-wide logging system.

This module sets up handlers for both console output (human-readable) and
file output (JSON structured).  A PII redacting filter is installed on all
file handlers and (in non-debug mode) console handlers after setup.
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

    # 1. Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
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

    # ── PII Scrubbing ──────────────────────────────────────────────────────
    try:
        from auto_apply.infrastructure.log_filter import install_pii_filter  # noqa: PLC0415
        install_pii_filter(debug_mode=debug_mode)
    except Exception:
        # Degrade gracefully — logging works without PII filter if the module
        # is unavailable (worst-case environment).
        pass

    logging.info("Logging initialized. Writing logs to %s", log_file)
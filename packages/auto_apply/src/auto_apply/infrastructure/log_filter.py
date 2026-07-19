"""PII-scrubbing log filter for AutoApply.

Automatically redacts email addresses, phone numbers, and common name
patterns from log messages before they are written to file or console.

Architecture: This is infrastructure — it wires into the logging system
at startup. It imports nothing from domain, application, or adapters.

The filter uses lightweight regex rather than NLP to keep startup fast
and to avoid loading SpaCy before the logging system is ready.
"""

from __future__ import annotations

import logging
import re


# ── Redaction Patterns ───────────────────────────────────────────────────────

_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

_PHONE_PATTERN = re.compile(
    r"""
    (?:\+?1[\s\-.]?)?               # Optional country code
    (?:\(?\d{3}\)?[\s\-.]?)         # Area code
    \d{3}[\s\-.]?\d{4}             # Local number
    """,
    re.VERBOSE,
)

# Common sensitive field labels — redact the VALUE that follows them
_FIELD_VALUE_PATTERN = re.compile(
    r"""
    (?P<label>
        \b(?:email|phone|mobile|ssn|social.security|password|passwd|
            first.name|last.name|full.name|date.of.birth|dob|
            address|street|salary.expect|cover.letter)\b
    )
    (?P<sep>[\s→:=|]+)
    (?P<value>[^\s|→\n]{3,80})   # The value that follows the label
    """,
    re.IGNORECASE | re.VERBOSE,
)


class PIIRedactingFilter(logging.Filter):
    """Scrubs PII from log records before they are emitted.

    Applied to file handlers only — console output is not scrubbed so
    developers can see real data during development with --debug.
    In production (AA_DEBUG=0, default), apply to console too.

    Usage in setup_logging():
        pii_filter = PIIRedactingFilter(redact_console=not debug_mode)
        file_handler.addFilter(pii_filter)
        if not debug_mode:
            console_handler.addFilter(pii_filter)
    """

    REDACTED_EMAIL = "[EMAIL REDACTED]"
    REDACTED_PHONE = "[PHONE REDACTED]"
    REDACTED_VALUE = "[VALUE REDACTED]"

    def __init__(self, redact_console: bool = False) -> None:
        super().__init__()
        self.redact_console = redact_console

    def filter(self, record: logging.LogRecord) -> bool:
        """Mutates record.msg and record.args to remove PII.

        Always returns True (never drops messages — only scrubs them).
        """
        try:
            # Render the full message first so we can scrub it as one string
            original_msg = record.getMessage()
            scrubbed = self._scrub(original_msg)

            if scrubbed != original_msg:
                # Replace msg with the pre-rendered scrubbed version
                record.msg = scrubbed
                record.args = ()  # Already rendered — clear args to avoid double-format

        except Exception:
            pass  # Never let a filter crash the logging system

        return True

    def _scrub(self, text: str) -> str:
        """Apply all PII redaction patterns to a string."""
        text = _EMAIL_PATTERN.sub(self.REDACTED_EMAIL, text)
        text = _PHONE_PATTERN.sub(self.REDACTED_PHONE, text)
        text = _FIELD_VALUE_PATTERN.sub(
            lambda m: f"{m.group('label')}{m.group('sep')}{self.REDACTED_VALUE}",
            text,
        )
        return text


def install_pii_filter(debug_mode: bool = False) -> None:
    """Install the PII filter on all existing log handlers.

    Call this after setup_logging() completes.

    Args:
        debug_mode: If True, console handler is NOT filtered (so developers
                    can see real data). File handler is ALWAYS filtered.
    """
    pii_filter = PIIRedactingFilter(redact_console=not debug_mode)
    root = logging.getLogger()

    for handler in root.handlers:
        is_file = isinstance(handler, (
            logging.FileHandler,
            logging.handlers.TimedRotatingFileHandler,
            logging.handlers.RotatingFileHandler,
        ))
        is_console = isinstance(handler, logging.StreamHandler) and not is_file

        if is_file:
            handler.addFilter(pii_filter)  # Always filter file logs
        elif is_console and not debug_mode:
            handler.addFilter(pii_filter)  # Filter console in non-debug mode

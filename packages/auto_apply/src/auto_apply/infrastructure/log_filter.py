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
import logging.handlers
import re


# ── Redaction Patterns ───────────────────────────────────────────────────────

_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

_PHONE_PATTERN = re.compile(
    # (?<!\w) / (?!\w) — NOT \b. A letter-to-digit transition is not a word
    # boundary (both are \w), so \b would still match a 10-digit run inside
    # a 32-char hex task ID. The lookarounds are what actually protect IDs.
    r"""
    (?<!\w)(?:\+?1[\s\-.]?)?               # Optional country code
    (?:\(?\d{3}\)?[\s\-.]?)         # Area code
    \d{3}[\s\-.]?\d{4}(?!\w)             # Local number
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


# Inert sentinel tokens used during multi-pattern redaction. They contain
# no label vocabulary, so the field-value pattern can never re-match a region
# that was already redacted. (The previous one-phase pipeline let redaction
# placeholders like "[PHONE REDACTED]" re-trigger the phone/email label
# words, mangling output into shapes like "[PHONE [VALUE REDACTED]".)
_SENTINEL_EMAIL = "\x00AA1\x00"
_SENTINEL_PHONE = "\x00AA2\x00"
_SENTINEL_VALUE = "\x00AA3\x00"


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
        """Apply all PII redaction patterns to a string.

        Two-phase: patterns substitute inert sentinel tokens first, then the
        sentinels are mapped to the human-readable placeholders. The sentinels
        contain no label vocabulary, so the field-value pattern can never
        re-match a region that was already redacted (the cascade).
        """
        text = _EMAIL_PATTERN.sub(_SENTINEL_EMAIL, text)
        text = _PHONE_PATTERN.sub(_SENTINEL_PHONE, text)
        text = _FIELD_VALUE_PATTERN.sub(
            lambda m: f"{m.group('label')}{m.group('sep')}{_SENTINEL_VALUE}",
            text,
        )
        return (
            text.replace(_SENTINEL_EMAIL, self.REDACTED_EMAIL)
            .replace(_SENTINEL_PHONE, self.REDACTED_PHONE)
            .replace(_SENTINEL_VALUE, self.REDACTED_VALUE)
        )


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

"""What a document field's value is: a file, or prose.

Pure — the standard library only. Kept apart from the profile model so code
that only needs this answer (the application engine's answer sources) does
not import pydantic and AA's configuration, which creates AA's data folders
when it is imported. ``auto_apply.domain.models.profile`` re-exports both
names, so existing imports are unchanged.
"""

from __future__ import annotations

from pathlib import Path

DOCUMENT_FILE_SUFFIXES: frozenset[str] = frozenset({".pdf", ".doc", ".docx", ".txt"})
"""Suffixes that mark a document field's value as a file path rather than prose."""


def is_document_path(value: str | None) -> bool:
    """True when a document field's value names a file rather than prose.

    This is the SINGLE predicate for the question "does this value name a
    file?" — defined here once and used by the settings writer, the model
    validator, and the applications engine, so the rule cannot drift between
    the places that write a cover letter and the place that attaches it.

    Shape check only — never touches the filesystem. A value like
    ``"resume.pdf"`` or ``"documents/cover.docx"`` returns True; a sentence,
    a URL, or any prose returns False. A value containing ``"://"`` is a link,
    not a local file (AA cannot upload a URL as a file), and a value with a
    newline is prose even if it happens to end in a document suffix. Whether
    the named file actually exists is decided by the resolved accessors
    (``get_resolved_resume_path`` / ``get_resolved_cover_letter_path``), not
    here.

    Args:
        value: The stored document value, or None.

    Returns:
        True if the value has the shape of a file path.
    """
    if not value or not value.strip():
        return False
    text = value.strip()
    if "\n" in text or "://" in text:
        return False
    return Path(text).suffix.lower() in DOCUMENT_FILE_SUFFIXES


__all__ = ["DOCUMENT_FILE_SUFFIXES", "is_document_path"]

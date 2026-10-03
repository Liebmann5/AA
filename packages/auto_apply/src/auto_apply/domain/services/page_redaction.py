"""Clean a page before AA keeps a copy of it (item 6).

A copy is kept only after this runs, and only its output is ever written:
the raw page never touches disk. Current practice for research that keeps
web pages (data-donation studies, The Markup's Citizen Browser) removes the
participant's own identifiers and anything that is not needed for the
research question before storage; AA does it at the moment of capture.

What is removed, and why:

* scripts, noscript blocks, frames, objects and embeds — they carry no text
  a detector reads, and logged-in pages put the user's identity and session
  state inside inline script data;
* event-handler attributes — code, not content;
* every form value, every hidden input and every textarea's text — a form
  can be pre-filled with the user's details, and hidden fields carry
  session and anti-forgery tokens;
* meta tags whose name speaks of tokens, sessions, CSRF or nonces;
* the user's OWN details, given by the caller (name, email, phone, address
  from the profile): each occurrence becomes "[redacted]". A phone number
  matches with any separators between its digits. Details match whatever
  their letter case; single NAMES (a first or last name on its own) match
  only as written, because a name that is also a word ("Will", "May")
  would otherwise wipe that word from every page. A name written in a
  different case ("NICK") therefore survives in a copy — the residual risk,
  stated rather than hidden.

What is kept: the page's text and its structure — what a detector, a
replay and a human reviewer need.

Deterministic, pure, standard library only. Returns the cleaned page and a
count per rule, so a copy says what was taken out of it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from auto_apply.domain.services.html_elements import remove_paired

__all__ = ["REDACTED", "redact_page"]

REDACTED = "[redacted]"

#: Elements removed with everything inside them: (rule, tag names). Each is
#: removed open-tag-to-matching-close-tag by remove_paired (html_elements), which pairs the
#: tags in one linear pass; an open tag with no close is then removed on its
#: own by _LONE. A lazy ``<script.*?</script>`` regex would rescan to the end
#: of the page from every unclosed open tag — quadratic, and a page with
#: thousands of them would hang the vetting step that reads it.
_PAIRED: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("script", ("script",)),
    ("noscript", ("noscript",)),
    ("frame", ("iframe", "frame")),
    ("embed", ("object",)),
)
_LONE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("script", re.compile(r"<script\b[^<>]*>", re.I)),
    ("noscript", re.compile(r"<noscript\b[^<>]*>", re.I)),
    ("frame", re.compile(r"<i?frame\b[^<>]*>", re.I)),
    ("embed", re.compile(r"<(?:object|embed)\b[^<>]*>", re.I)),
)


_HIDDEN_INPUT = re.compile(
    r"<input\b[^<>]*?\btype\s*=\s*[\"']?hidden[\"']?[^<>]*>", re.I
)
_VALUE_ATTR = re.compile(
    r"(<(?:input|option|button)\b[^<>]*?)\s(?:value|data-value)\s*=\s*"
    r"(\"[^\"]*\"|'[^']*'|[^\s>]+)",
    re.I | re.S,
)
_META = re.compile(r"<meta\b[^<>]*>", re.I)
_TOKEN_NAME = re.compile(
    r"\b(?:name|property)\s*=\s*[\"'][^\"']*(?:token|csrf|xsrf|session|nonce)", re.I
)
_HANDLER = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)


def _value_pattern(value: str, ignore_case: bool = True) -> re.Pattern[str] | None:
    """A pattern for one of the user's own values, or None if too short to
    match safely (fewer than 3 meaningful characters would redact words)."""
    value = value.strip()
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 7 and len(digits) >= len(re.sub(r"\s", "", value)) - 4:
        # A phone number: its digits with any separators between them.
        return re.compile(r"(?<!\d)" + r"[\s().+-]*".join(digits) + r"(?!\d)")
    if len(value) < 3:
        return None
    flags = re.I if ignore_case else 0
    return re.compile(r"(?<!\w)" + re.escape(value) + r"(?!\w)", flags)


def redact_page(
    html: str, own_values: Iterable[str] = (), own_names: Iterable[str] = ()
) -> tuple[str, tuple[tuple[str, int], ...]]:
    """The page with everything above removed, and what was removed.

    Args:
        html: The page as read.
        own_values: The user's own details to remove wherever they appear,
            in any letter case (full name, email, phone, street address).
        own_names: Single names to remove where they appear as written.

    Returns:
        (cleaned page, ((rule, count), ...)) with zero counts left out.
    """
    counts: dict[str, int] = {}

    def sub(rule: str, pattern: re.Pattern[str], repl: str, text: str) -> str:
        text, n = pattern.subn(repl, text)
        if n:
            counts[rule] = counts.get(rule, 0) + n
        return text

    for rule, tags in _PAIRED:
        for tag in tags:
            html, n = remove_paired(html, tag)
            if n:
                counts[rule] = counts.get(rule, 0) + n
    for rule, pattern in _LONE:
        html = sub(rule, pattern, "", html)
    html = sub("event_handler", _HANDLER, "", html)
    html = sub("hidden_input", _HIDDEN_INPUT, "", html)
    html = sub("form_value", _VALUE_ATTR, r"\1", html)
    html, n = remove_paired(html, "textarea", keep_tags=True)
    if n:
        counts["textarea_text"] = n
    token_metas = 0

    def drop_token_meta(match: re.Match[str]) -> str:
        nonlocal token_metas
        if _TOKEN_NAME.search(match.group(0)):
            token_metas += 1
            return ""
        return match.group(0)

    html = _META.sub(drop_token_meta, html)
    if token_metas:
        counts["token_meta"] = token_metas

    candidates = [_value_pattern(v) for v in own_values if v] + [
        _value_pattern(n, ignore_case=False) for n in own_names if n
    ]
    patterns = [p for p in candidates if p]
    # Longest first, so a full name is replaced before a part of it.
    patterns.sort(key=lambda p: -len(p.pattern))
    for pattern in patterns:
        html = sub("own_details", pattern, REDACTED, html)

    return html, tuple(sorted(counts.items()))

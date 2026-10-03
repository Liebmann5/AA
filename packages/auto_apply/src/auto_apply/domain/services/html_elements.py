"""Linear-time element scanning shared by page cleaning and text extraction.

Both domain/services/page_redaction.py (item 6) and
domain/services/text_extraction.py (item 7) remove whole elements — a
script and everything inside it — from page source. A lazy
``<tag.*?</tag>`` regex rescans to the end of the page from every unclosed
open tag, which is quadratic and hung on hostile pages (measured in item 6);
remove_paired pairs open and close tags in one pass instead.

Pure, standard library only.
"""

from __future__ import annotations

import re

__all__ = ["remove_paired"]


def remove_paired(html: str, tag: str, keep_tags: bool = False) -> tuple[str, int]:
    """Remove every ``<tag …>…</tag>`` span, pairing each open tag with the
    first close tag after it. Linear in the page size. With ``keep_tags``
    only what is BETWEEN the tags goes (a textarea stays, its text does not)."""
    opens = [m.start() for m in re.finditer(rf"<{tag}\b", html, re.I)]
    closes = [(m.start(), m.end()) for m in re.finditer(rf"</{tag}\s*>", html, re.I)]
    if not opens or not closes:
        return html, 0
    kept: list[str] = []
    pos = 0
    removed = 0
    ci = 0
    for start in opens:
        if start < pos:
            continue  # inside a span already removed
        while ci < len(closes) and closes[ci][0] < start:
            ci += 1
        if ci == len(closes):
            break
        if keep_tags:
            open_end = html.find(">", start, closes[ci][0])
            if open_end == -1:
                continue  # an open tag that never ends before the close: leave it
            kept.append(html[pos : open_end + 1])
            kept.append(html[closes[ci][0] : closes[ci][1]])
        else:
            kept.append(html[pos:start])
        pos = closes[ci][1]
        removed += 1
    kept.append(html[pos:])
    return "".join(kept), removed

"""Page text without a browser — the extraction step of a replay (item 7).

A live run reads a job page's text from the browser (``innerText``, through
PerceptionPort.get_page_text). A replay has no browser: it re-reads a kept
page copy, so it needs its own way from page source to text. This is it.

Why AA's own code and not a parser library. The point of a replay is that
the same corpus gives the same bytes on every machine AA runs on. CPython's
``html.parser`` has changed behaviour in patch releases (comment and script
handling), and the CI interpreters are not pinned to a patch release; a
third-party parser adds its own version to the result. This module is part
of AA, so its behaviour changes only when AA's does — and the replay
manifest names the AA version.

What it does, in order:
  1. keep only the <body> when there is one (``innerText`` of the body is
     what a live run reads);
  2. remove comments, and every script, style, noscript, template, svg and
     head element with its content;
  3. turn block-level tags and <br> into line breaks and table cells into
     spaces, and drop every other tag;
  4. decode character references (``&amp;``, ``&#8212;``) with
     ``html.unescape``, whose table is the fixed HTML5 list;
  5. normalise whitespace: no-break spaces become spaces, runs of spaces
     and tabs collapse, lines are stripped, and blank lines collapse to one.

It is NOT ``innerText``: it cannot see CSS, so text a stylesheet hides is
kept. Replayed detections can therefore differ from the live ones on the
same page; the replay manifest says which extraction produced its text.

Linear in the page size (see html_elements). Pure, standard library only.
"""

from __future__ import annotations

import html as _html
import re

from auto_apply.domain.services.html_elements import remove_paired

__all__ = ["EXTRACTION_METHOD", "visible_text"]

#: Named in every replay manifest, so a reader knows how the text was made.
#: Change the suffix whenever the output of visible_text() changes.
EXTRACTION_METHOD = "aa-static-text/1"

_BODY_OPEN = re.compile(r"<body\b[^<>]*>", re.I)
_BODY_CLOSE = re.compile(r"</body\s*>", re.I)
_HIDDEN_ELEMENTS = ("script", "style", "noscript", "template", "svg", "head")
_LONE_HIDDEN = re.compile(
    r"<(?:script|style|noscript|template|svg|head)\b[^<>]*>", re.I
)
_BLOCK = re.compile(
    r"</?(?:address|article|aside|blockquote|br|dd|details|dialog|div|dl|dt|"
    r"fieldset|figcaption|figure|footer|form|h[1-6]|header|hr|li|main|nav|"
    r"ol|p|pre|section|summary|table|tbody|tfoot|thead|tr|ul)\b[^<>]*>",
    re.I,
)
_CELL = re.compile(r"</?(?:td|th)\b[^<>]*>", re.I)
_TAG = re.compile(r"</?[A-Za-z!][^<>]*>")
_SPACES = re.compile(r"[ \t\f\v ]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def _drop_comments(page: str) -> str:
    """Remove ``<!-- ... -->`` comments in one pass; an unclosed comment runs
    to the end of the page, as a browser treats it. (A lazy regex would
    rescan to the end from every unclosed ``<!--``: quadratic.)"""
    out: list[str] = []
    pos = 0
    while True:
        start = page.find("<!--", pos)
        if start == -1:
            out.append(page[pos:])
            return " ".join(out)
        out.append(page[pos:start])
        end = page.find("-->", start + 4)
        if end == -1:
            return " ".join(out)
        pos = end + 3


def visible_text(page: str) -> str:
    """The human-visible text of a page source, deterministically.

    Args:
        page: Page source (a kept page copy, or any HTML).

    Returns:
        The text, with single line breaks between blocks, at most one blank
        line in a row, no leading or trailing whitespace. "" for an empty or
        text-free page. Never raises for any str input.
    """
    opened = _BODY_OPEN.search(page)
    if opened is not None:
        closes = list(_BODY_CLOSE.finditer(page, opened.end()))
        end = closes[-1].start() if closes else len(page)
        page = page[opened.end() : end]
    page = _drop_comments(page)
    for tag in _HIDDEN_ELEMENTS:
        page, _ = remove_paired(page, tag)
    page = _LONE_HIDDEN.sub(" ", page)
    page = _BLOCK.sub("\n", page)
    page = _CELL.sub(" ", page)
    page = _TAG.sub("", page)
    page = _html.unescape(page)
    page = page.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACES.sub(" ", line).strip() for line in page.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()

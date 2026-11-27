"""StructuredPostingPort over pagecomp's structured-data tool (JSON-LD ``JobPosting``).

pagecomp is vendored and uses the standard library only, so this reader is
available on every machine AA runs on: the baseline tier, not an
enhancement. It reads the HTML it is given; it never drives the browser.
"""
from __future__ import annotations

import logging
import re
import urllib.parse

from auto_apply.domain.ports.structured_posting_port import StructuredPosting

logger = logging.getLogger(__name__)

_DIGITS = re.compile(r"\d{4,}")


def _ids_in(url: str) -> set[str]:
    """Long digit runs in an address: job ids in its path or query."""
    try:
        parts = urllib.parse.urlsplit(url or "")
    except ValueError:
        return set()
    return set(_DIGITS.findall(parts.path)) | set(_DIGITS.findall(parts.query))


class PagecompPostingReader:
    """Reads a posting's own JSON-LD ``JobPosting`` with pagecomp."""

    def read(self, html: str, url: str) -> StructuredPosting | None:
        if not html:
            return None
        try:
            from pagecomp import Analyzer, Ok, observe_html  # noqa: PLC0415

            result = Analyzer(observe_html(html, url=url or "")).get("structured").result
        except Exception as exc:  # noqa: BLE001 - a reader fault reads nothing
            logger.debug("PagecompPostingReader: read failed: %s", exc)
            return None
        if not isinstance(result, Ok):
            return None
        postings = [p for p in result.value.postings if (p.title or "").strip()]
        posting = self._this_pages(postings, url)
        if posting is None:
            return None
        return StructuredPosting(
            title=posting.title.strip(),
            company=(posting.organization or "").strip(),
            locations=tuple(loc.strip() for loc in posting.locations if loc.strip()),
            remote=bool(posting.remote),
            identifier=(posting.identifier or "").strip(),
            date_posted=(posting.date_posted or "").strip(),
            valid_through=(posting.valid_through or "").strip(),
            source="json-ld",
        )

    @staticmethod
    def _this_pages(postings: list, url: str):
        """The page's own posting: the only one, or the one whose url or
        identifier matches a job id in the page's address. An embedded board
        can list several; guessing among them would put another job's facts
        on this one, so an unresolvable choice reads nothing."""
        if len(postings) == 1:
            return postings[0]
        if not postings:
            return None
        ids = _ids_in(url)
        if not ids:
            return None
        matching = [
            p for p in postings
            if ids & (_ids_in(p.url) | set(_DIGITS.findall(p.identifier or "")))
        ]
        return matching[0] if len(matching) == 1 else None

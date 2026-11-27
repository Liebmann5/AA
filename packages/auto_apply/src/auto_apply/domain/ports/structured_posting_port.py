"""What a job posting says about itself: the StructuredPostingPort.

Not to be confused with domain.models.page_copy.PostingFacts, the facts the
*listing* showed, kept with a page copy for replay.

A results page describes a posting second-hand. Its title is truncated or
decorated ("Job Application for Senior Software Engineer, Backend ...") and
an engine's card never names the employer. The posting page usually states
all of it first-hand, as schema.org ``JobPosting`` structured data, which
job boards and applicant-tracking systems publish for search engines.

Vetting reads these facts after it lands on the posting and before any
filter judges the job, so the filters, the research record and the
application all work from the posting's own words.

The read is offline: it takes the page's HTML and address, never the
browser, and never touches the network.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class StructuredPosting:
    """The facts one posting declares about itself.

    Every field is "" or empty when the posting does not state it. Nothing
    here is inferred.

    Attributes:
        title: The job title.
        company: The hiring organisation's name.
        locations: Each stated job location, as written.
        remote: True when the posting declares the job remote
            (``jobLocationType: TELECOMMUTE``); False otherwise.
        identifier: The posting's own identifier, when stated.
        date_posted: As stated (ISO 8601 by the standard), or "".
        valid_through: As stated, or "".
        source: Where the facts came from (``"json-ld"``).
    """

    title: str = ""
    company: str = ""
    locations: tuple[str, ...] = ()
    remote: bool = False
    identifier: str = ""
    date_posted: str = ""
    valid_through: str = ""
    source: str = ""

    @property
    def location(self) -> str:
        """The stated locations joined for display ("" when none)."""
        return "; ".join(self.locations)


@runtime_checkable
class StructuredPostingPort(Protocol):
    """Reads the facts a posting page declares about itself."""

    def read(self, html: str, url: str) -> StructuredPosting | None:
        """The facts of the ONE posting on this page.

        Returns None when the page declares no posting, or several postings
        none of which can be told to be this page's. Never raises.
        """
        ...

"""Domain types for verified page advance (pagination).

These types are pure data: no browser, no I/O. The advancer adapter
(adapters/secondary/navigation/page_advancer.py) produces AdvanceOutcome;
the SERP strategy consumes it and records the method/stop reason as
pagination evidence.
"""
from __future__ import annotations

from dataclasses import dataclass


class AdvanceMethod:
    """How a results page was reached. Stored on the research record."""

    TEMPLATE = "url-template"
    REL_NEXT = "rel-next"
    STRUCTURAL = "structural-next"
    NUMBERED = "numbered"
    LOAD_MORE = "load-more"
    SCROLL_GROWTH = "scroll-growth"


class StopReason:
    """Why advancing stopped. Stored on the research record."""

    NO_NEXT = "no-next-control"
    NO_CHANGE = "no-change"
    NO_BROWSER = "no-browser"
    ERROR = "error"


@dataclass(frozen=True)
class UrlPageTemplate:
    """A page number carried in the URL as pure data.

    value(page) = first + step * (page - 1), page 1-based. For Google:
    param="start", first=0, step=10 -> page 2 is start=10.
    """

    param: str
    first: int
    step: int


@dataclass(frozen=True)
class AdvanceOutcome:
    """The result of one advance attempt.

    ``advanced`` is only ever True together with ``verified``: the advancer
    never claims a page it could not prove changed. On failure,
    ``stop_reason`` carries a StopReason value and ``detail`` a diagnostic.
    """

    advanced: bool
    method: str = ""
    verified: bool = False
    stop_reason: str = ""
    detail: str = ""

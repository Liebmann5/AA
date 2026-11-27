"""Did a search engine keep a query's ``site:`` restriction?

An engine can answer a site-restricted query as if the restriction were not
there, silently. Measured on 2026-11-08:

* in AA's own browser, Google answered six of seven platform searches
  (``site:jobs.ashbyhq.com ("Software Engineer")`` and five more) with the
  same unrestricted page, ZipRecruiter's "Full Time Software Engineer Jobs in
  Los Angeles, CA" first, while ``site:boards.greenhouse.io`` was kept;
* in the owner's browser, typing the same queries, Google kept all seven,
  and Bing returned one identical Greenhouse list for every ``site:`` value.

A page of results with none on the restricted site is therefore not "no
jobs": it is a different search than the one AA asked for. This module
judges that, from the hosts of the results a page reader found. Pure: no
browser, no network.

Google documents that ``site:example.com`` includes every subdomain
(Search Central, "site: search operator"), so a result host matches when it
equals the restricted host or is a subdomain of it.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

#: ``site:`` operands of a query, skipping excluded ones (``-site:``).
_SITE = re.compile(r"(?<![-\w])site:([^\s()\"]+)", re.IGNORECASE)

#: Fewer results than this cannot show that the restriction was dropped: a
#: page with one or two stray links may be a "no results" page with
#: suggestions. Below it the verdict is "unknown", never "dropped".
MIN_RESULTS_TO_JUDGE = 3


def restriction_of(query: str) -> str:
    """The first included ``site:`` operand of *query*, lower-case ("" if none)."""
    match = _SITE.search(query or "")
    return match.group(1).strip().strip("/").lower() if match else ""


def restriction_host(restriction: str) -> str:
    """The host part of a restriction (``bamboohr.com/careers`` → ``bamboohr.com``)."""
    return (restriction or "").split("/", 1)[0].strip().lower().removeprefix("www.")


def host_within(host: str, restriction: str) -> bool:
    """True when *host* is the restricted host or a subdomain of it."""
    host = (host or "").strip().lower().strip(".").removeprefix("www.")
    target = restriction_host(restriction)
    return bool(host and target) and (host == target or host.endswith("." + target))


@dataclass(frozen=True)
class RestrictionCheck:
    """One results page judged against one ``site:`` restriction.

    Attributes:
        restriction: The restriction asked for ("" when the query had none).
        results: How many results the page reader found.
        on_site: How many of them are on the restricted host.
    """

    restriction: str
    results: int
    on_site: int

    @property
    def dropped(self) -> bool:
        """The engine answered without the restriction: enough results to
        judge, and none of them on the restricted site."""
        return bool(self.restriction) and self.results >= MIN_RESULTS_TO_JUDGE and self.on_site == 0

    @property
    def state(self) -> str:
        """``kept``, ``dropped`` or ``unknown`` (no restriction, or too few
        results to tell)."""
        if not self.restriction or self.results < MIN_RESULTS_TO_JUDGE:
            return "unknown" if self.on_site == 0 else "kept"
        return "dropped" if self.on_site == 0 else "kept"

    def describe(self) -> str:
        return f"{self.on_site} of {self.results} results on {self.restriction}"


def check_restriction(restriction: str, result_hosts: Iterable[str]) -> RestrictionCheck:
    """Judge a page's result hosts against *restriction*."""
    hosts = [h for h in result_hosts if h]
    on_site = sum(1 for h in hosts if host_within(h, restriction))
    return RestrictionCheck(restriction=restriction, results=len(hosts), on_site=on_site)

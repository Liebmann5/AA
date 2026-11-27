"""Where an opaque route really went: the host a results page shows, and the
arrival check that confirms it.

A search engine can hide a result's destination behind its own route
(Google's ``/goto?url=<token>``, measured on 2026-11-08 in an owner's
everyday Chrome as well as under automation). The results page still shows
the destination next to the link (``jobs.jobvite.com › brahma › job``), and
Discovery keeps such a hit on that shown destination (owner ruling
2026-11-04: opaque routes count; the visit is the resolution).

What a page shows is a claim, not a fact: the route can lead somewhere else
(a changed redirect, an expired token, an interstitial, a page that moved).
So the claim is checked twice:

* ``shown_host`` reads the shown destination's host strictly, so a string
  such as ``evil.com/jobs.jobvite.com`` is read as ``evil.com``;
* ``judge_arrival`` checks, after the browser followed the route, that the
  page it LANDED on is a posting of the platform the search targeted, on
  the platform's own hosts or embedded on the employer's careers site.

Both are pure: no network, no browser. The caller supplies the landed
address and the platform registry.
"""
from __future__ import annotations

import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

#: The separators engines print between a breadcrumb's host and its path.
_CRUMB_SEPARATORS = ("›", "»")


def url_host(url: str) -> str:
    """The lower-case host of a URL ("" when there is none or it is malformed)."""
    try:
        return (urllib.parse.urlsplit((url or "").strip()).hostname or "").lower().strip(".")
    except ValueError:
        return ""


def shown_host(shown: str) -> str:
    """The host of a destination as a results page shows it.

    Accepts what the page prints: ``jobs.jobvite.com``, ``jobs.jobvite.com/acme``,
    ``https://jobs.jobvite.com › acme › job``. Returns "" when no host can be
    read. Parsed as a URL authority, so a path, a port, user info or a
    trailing dot never becomes part of the host: ``evil.com/jobs.jobvite.com``
    is ``evil.com`` and ``jobs.jobvite.com@evil.com`` is ``evil.com``. A
    name without a dot is not a host.
    """
    text = (shown or "").strip()
    for sep in _CRUMB_SEPARATORS:
        text = text.split(sep, 1)[0]
    text = text.strip()
    if not text or any(ch.isspace() for ch in text):
        return ""
    if "://" not in text:
        text = "//" + text
    host = url_host(text)
    # A shown destination is a public host name: it has a dot ("https:"
    # alone, a word or a scheme is not one).
    return host if "." in host else ""


@dataclass(frozen=True)
class ArrivalVerdict:
    """Where an opaque route landed, judged.

    Attributes:
        problem: Why the landing is NOT a posting of the target platform
            (worded for the log and the job's record); "" when confirmed.
        embedded: Evidence that the landing is the platform's posting
            embedded on the employer's own site (``gh_jid=8301214``, or the
            platform's application frame); "" for a landing on the
            platform's own hosts, and for a rejection.
    """

    problem: str = ""
    embedded: str = ""

    @property
    def confirmed(self) -> bool:
        return not self.problem


def judge_arrival(
    route_url: str,
    landed_url: str,
    target_platform: str,
    registry: Any,
    page_resources: Callable[[], Sequence[str]] | None = None,
) -> ArrivalVerdict:
    """Judge the landing of an opaque route against ``target_platform``.

    Confirmed when the landed page is a posting on the platform's hosts, or
    the platform's posting embedded on the employer's own site (the
    descriptor's ``embedding`` evidence: a job-id parameter, or a frame of
    the platform's application form, read from ``page_resources`` — called
    only when the landed host is not the platform's).

    Rejected, with the reason, when:

    * the landed address is unknown;
    * the browser is still on the route's own host (the route did not
      resolve: an interstitial, a block, a dead token);
    * no platform registry is available to confirm anything;
    * the landed host belongs to another platform or to none, with no
      embedding evidence;
    * the landed page is a terminal page (a closed or removed posting, a
      confirmation);
    * the landed page is on the platform but is not a posting (a company's
      list of openings, a search page).

    ``registry`` is the ATS registry (``platform_for_host``,
    ``embedded_posting``, ``is_terminal_page``, ``match``). A fault in any
    of them is a rejection, never a pass.
    """
    landed_host = url_host(landed_url)
    if not landed_host:
        return ArrivalVerdict("ArrivalCheck: the landed address is unknown")
    route_host = url_host(route_url)
    if route_host and landed_host == route_host:
        return ArrivalVerdict(
            f"ArrivalCheck: the route did not resolve (still on {landed_host})"
        )
    if registry is None:
        return ArrivalVerdict("ArrivalCheck: no platform registry to confirm the landing")
    try:
        platform = registry.platform_for_host(landed_host)
    except Exception:  # noqa: BLE001 - a registry fault is a rejection
        platform = None
    if platform != target_platform:
        try:
            resources = list(page_resources()) if page_resources is not None else []
        except Exception:  # noqa: BLE001 - unreadable page: no evidence
            resources = []
        try:
            evidence = str(
                registry.embedded_posting(target_platform, landed_url, resources) or ""
            )
        except Exception:  # noqa: BLE001
            evidence = ""
        if evidence:
            return ArrivalVerdict(embedded=evidence)
        return ArrivalVerdict(
            f"ArrivalCheck: landed off platform ({landed_host}; "
            f"expected {target_platform})"
        )
    try:
        terminal = registry.is_terminal_page(landed_url) is True
    except Exception:  # noqa: BLE001
        terminal = False
    if terminal:
        return ArrivalVerdict(
            f"ArrivalCheck: landed on a terminal {target_platform} page "
            "(the posting is closed or removed, or a confirmation page)"
        )
    try:
        descriptor = registry.match(landed_url)
    except Exception:  # noqa: BLE001
        descriptor = None
    if descriptor is None or getattr(descriptor, "name", None) != target_platform:
        return ArrivalVerdict(
            f"ArrivalCheck: landed on a {target_platform} page that is not a posting"
        )
    return ArrivalVerdict()


def arrival_problem(
    route_url: str,
    landed_url: str,
    target_platform: str,
    registry: Any,
    page_resources: Callable[[], Sequence[str]] | None = None,
) -> str:
    """``judge_arrival(...).problem``: the rejection reason, or "" when confirmed."""
    return judge_arrival(
        route_url, landed_url, target_platform, registry, page_resources
    ).problem


class _ResourceCollector(HTMLParser):
    """Collects the ``src`` of every frame and script on a page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("iframe", "frame", "script") and len(self.urls) < _MAX_RESOURCES:
            for name, value in attrs:
                if name == "src" and value:
                    self.urls.append(value.strip())


#: A page lists far fewer frames and scripts than this; the cap bounds the
#: work on a hostile or broken page.
_MAX_RESOURCES = 500


def page_resource_urls(html: str, base_url: str = "") -> list[str]:
    """The absolute addresses of the frames and scripts a page loads.

    Read from the page's HTML with the standard library parser (no browser,
    no network): the evidence ``judge_arrival`` needs to recognise a
    platform's application form embedded in an employer's page. Never raises.
    """
    if not html:
        return []
    collector = _ResourceCollector()
    try:
        collector.feed(html)
        collector.close()
    except Exception:  # noqa: BLE001 - a broken page yields what was read
        pass
    out: list[str] = []
    for url in collector.urls:
        try:
            out.append(urllib.parse.urljoin(base_url, url) if base_url else url)
        except ValueError:
            continue
    return out

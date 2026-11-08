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
* ``arrival_problem`` checks, after the browser followed the route, that the
  page it LANDED on is a posting of the platform the search targeted.

Both are pure: no network, no browser. The caller supplies the landed
address and the platform registry.
"""
from __future__ import annotations

import urllib.parse
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


def arrival_problem(
    route_url: str,
    landed_url: str,
    target_platform: str,
    registry: Any,
) -> str:
    """Why the landing of an opaque route is NOT a posting of ``target_platform``.

    Returns "" when the landing is confirmed. Every other answer is a
    rejection reason, worded for the log and the job's record:

    * the landed address is unknown;
    * the browser is still on the route's own host (the route did not
      resolve: an interstitial, a block, a dead token);
    * no platform registry is available to confirm anything;
    * the landed host belongs to another platform, or to none;
    * the landed page is a terminal page (a closed or removed posting, a
      confirmation);
    * the landed page is on the platform but is not a posting (a company's
      list of openings, a search page).

    ``registry`` is the ATS registry: ``platform_for_host``,
    ``is_terminal_page`` and ``match`` are read; a fault in any of them is a
    rejection, never a pass.
    """
    landed_host = url_host(landed_url)
    if not landed_host:
        return "ArrivalCheck: the landed address is unknown"
    route_host = url_host(route_url)
    if route_host and landed_host == route_host:
        return f"ArrivalCheck: the route did not resolve (still on {landed_host})"
    if registry is None:
        return "ArrivalCheck: no platform registry to confirm the landing"
    try:
        platform = registry.platform_for_host(landed_host)
    except Exception:  # noqa: BLE001 - a registry fault is a rejection
        platform = None
    if platform != target_platform:
        return (
            f"ArrivalCheck: landed off platform ({landed_host}; "
            f"expected {target_platform})"
        )
    try:
        terminal = registry.is_terminal_page(landed_url) is True
    except Exception:  # noqa: BLE001
        terminal = False
    if terminal:
        return (
            f"ArrivalCheck: landed on a terminal {target_platform} page "
            "(the posting is closed or removed, or a confirmation page)"
        )
    try:
        descriptor = registry.match(landed_url)
    except Exception:  # noqa: BLE001
        descriptor = None
    if descriptor is None or getattr(descriptor, "name", None) != target_platform:
        return f"ArrivalCheck: landed on a {target_platform} page that is not a posting"
    return ""

"""Arrival: did the navigation land on the surface it asked for?

Ported unchanged in rule from AA ``navigation_landing.check_landing``
(owner run 2026-11-02: ``bing.com/jobs?q=`` landed on ``/?form=REDIRERR``
and was logged as success). A landing is on surface when it keeps the
requested site (registrable domain), path (trailing slash and case
ignored) and has no error token in its query. The pure function is public
(``check_landing``) because AA's ``ResilientDriver.confirm_arrival`` calls
it outside any page analysis; the tool reads the observation's
``requested_url``.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pagecomp.links import site
from pagecomp.registry import ToolSpec
from pagecomp.results import Abstain, Ok

ERROR_QUERY_TOKENS = frozenset({"redirerr", "error", "err", "notfound", "not_found", "404"})
SAME_SURFACE, NO_PAGE, DIFFERENT_SITE, HOME_PAGE, DIFFERENT_PATH, ERROR_REDIRECT = (
    "same-surface", "no-page", "different-site", "home-page", "different-path", "error-redirect")


@dataclass(frozen=True)
class Landing:
    requested: str
    landed: str
    on_surface: bool
    reason: str


def check_landing(requested: str, landed: str) -> Landing:
    try:
        want = urllib.parse.urlparse(requested or "")
        got = urllib.parse.urlparse(landed or "")
    except ValueError:
        return Landing(requested, landed, False, NO_PAGE)
    if got.scheme not in ("http", "https") or not got.netloc:
        return Landing(requested, landed, False, NO_PAGE)
    if site(want.hostname or "") != site(got.hostname or ""):
        return Landing(requested, landed, False, DIFFERENT_SITE)
    toks: set[str] = set()
    for k, v in urllib.parse.parse_qsl(got.query, keep_blank_values=True):
        toks.add(k.lower())
        toks.add(v.lower())
    if toks & ERROR_QUERY_TOKENS:
        return Landing(requested, landed, False, ERROR_REDIRECT)
    wp, gp = want.path.rstrip("/").lower(), got.path.rstrip("/").lower()
    if wp != gp:
        return Landing(requested, landed, False, HOME_PAGE if gp == "" and wp != "" else DIFFERENT_PATH)
    return Landing(requested, landed, True, SAME_SURFACE)


def _run(q: Any, params: Mapping[str, Any]) -> Ok[Landing] | Abstain:
    if not q.obs.requested_url:
        return Abstain("no-requested-url")
    landing = check_landing(q.obs.requested_url, q.obs.url)
    return Ok(landing, confidence=1.0)


TOOL = ToolSpec(id="arrival", ct_id="CT-T-016/A", version="0.1.0", run=_run,
                summary="requested vs landed surface")

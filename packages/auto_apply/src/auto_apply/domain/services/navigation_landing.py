"""Did a navigation land on the surface it asked for?

A browser ``get`` that returns without error is not a successful navigation:
the site may redirect somewhere else. Measured on the owner's live run of
2026-11-02 (environment ``owner``): ``https://www.bing.com/jobs?q=...``
redirected to Bing's home page, ``https://www.bing.com/?form=REDIRERR``, and
the navigator logged "successful and validated"; S1's reader then took the
home page's news cards for job records. Observed again in environment
``cloud`` on 2026-11-03: the same address answers 404 and lands on
``/?form=REDIRERR``.

The rule: a landing is on the requested surface only when it keeps the
requested site (the same registrable domain), the requested path (trailing
slash and case ignored) and carries no error marker in its query. A home
page reached from a non-home request is a different surface. Pure; never
raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlparse

#: Query values or keys that name an error redirect (Bing: ``form=REDIRERR``).
#: Whole tokens, lowercased.
_ERROR_QUERY_TOKENS: frozenset[str] = frozenset(
    {"redirerr", "error", "err", "notfound", "not_found", "404"}
)

#: Second-level labels under which the registrable domain takes three labels
#: (``example.co.uk``). A small table, not a public-suffix list: enough to keep
#: ``jobs.example.co.uk`` and ``www.example.co.uk`` on one site.
_SHORT_SLDS: frozenset[str] = frozenset({"co", "com", "org", "net", "ac", "gov", "edu"})


@dataclass(frozen=True)
class Landing:
    """Where a navigation ended, and whether that is the requested surface.

    ``reason`` is an enumerated string: ``same-surface``, ``no-page``,
    ``different-site``, ``home-page``, ``different-path`` or
    ``error-redirect``.
    """

    requested: str
    landed: str
    on_surface: bool
    reason: str


def _site(host: str) -> str:
    labels = [part for part in host.lower().split(".") if part]
    if len(labels) >= 3 and labels[-2] in _SHORT_SLDS and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _path(path: str) -> str:
    return path.rstrip("/").lower()


def check_landing(requested: str, landed: str) -> Landing:
    """Compare the landed URL with the requested one (see module docstring)."""
    try:
        want = urlparse(requested or "")
        got = urlparse(landed or "")
    except ValueError:
        return Landing(requested, landed, False, "no-page")
    if got.scheme not in ("http", "https") or not got.netloc:
        return Landing(requested, landed, False, "no-page")
    if _site(want.netloc) != _site(got.netloc):
        return Landing(requested, landed, False, "different-site")
    tokens = set()
    for key, value in parse_qsl(got.query, keep_blank_values=True):
        tokens.add(key.lower())
        tokens.add(value.lower())
    if tokens & _ERROR_QUERY_TOKENS:
        return Landing(requested, landed, False, "error-redirect")
    want_path, got_path = _path(want.path), _path(got.path)
    if want_path != got_path:
        if got_path == "" and want_path != "":
            return Landing(requested, landed, False, "home-page")
        return Landing(requested, landed, False, "different-path")
    return Landing(requested, landed, True, "same-surface")

"""Byte-identity pin: the catalog-driven engine URL builders produce exactly
the bytes the hardcoded builders produced before the move.

GUARD (regression), not teeth: the expected strings are the pre-change
outputs, written by hand from the pre-move code. This pin passes on the old
tree's OUTPUT and must keep passing on the new one. The mutations it exists
to catch: any drift between the catalog and what automation sends (a catalog
edit changing hl, the parameter order, or a date code), and any refactor
reintroducing a second source of URL truth.
"""
from __future__ import annotations

import pytest

from auto_apply.adapters.secondary.discovery.strategies.engine_strategies import (
    BingSearchStrategy,
    GoogleSearchStrategy,
    IndeedSearchStrategy,
)
from auto_apply.domain.models.search_instruction import SearchInstruction

_GOOGLE_BASE = (
    "https://www.google.com/search?q=Engineer+jobs+in+Remote"
    "&ibp=htl%3Bjobs&hl=en&gl=us&start=0"
)
_BING_BASE = "https://www.bing.com/jobs?q=Engineer+jobs+in+Remote"
_INDEED_BASE = "https://www.indeed.com/jobs?q=Engineer+jobs+in+Remote&l=Remote"

_CASES = [
    ("google", None, _GOOGLE_BASE),
    ("google", "hour", _GOOGLE_BASE + "&tbs=qdr%3Ah"),
    ("google", "day", _GOOGLE_BASE + "&tbs=qdr%3Ad"),
    ("google", "week", _GOOGLE_BASE + "&tbs=qdr%3Aw"),
    ("google", "month", _GOOGLE_BASE + "&tbs=qdr%3Am"),
    ("google", "year", _GOOGLE_BASE + "&tbs=qdr%3Ay"),
    ("bing", None, _BING_BASE),
    ("bing", "hour", _BING_BASE + "&filters=ex1%3A%22h%22"),
    ("bing", "day", _BING_BASE + "&filters=ex1%3A%22d%22"),
    ("bing", "week", _BING_BASE + "&filters=ex1%3A%22w%22"),
    ("bing", "month", _BING_BASE + "&filters=ex1%3A%22m%22"),
    ("bing", "year", _BING_BASE + "&filters=ex1%3A%22y%22"),
    ("indeed", None, _INDEED_BASE),
    ("indeed", "hour", _INDEED_BASE + "&fromage=1"),
    ("indeed", "day", _INDEED_BASE + "&fromage=1"),
    ("indeed", "week", _INDEED_BASE + "&fromage=7"),
    ("indeed", "month", _INDEED_BASE + "&fromage=30"),
    ("indeed", "year", _INDEED_BASE + "&fromage=365"),
]

_RAW = 'site:jobs.lever.co "software engineer"'
_RAW_Q = "site%3Ajobs.lever.co+%22software+engineer%22"

_RAW_CASES = [
    ("google", f"https://www.google.com/search?q={_RAW_Q}&ibp=htl%3Bjobs&hl=en&gl=us&start=0"),
    ("bing", f"https://www.bing.com/jobs?q={_RAW_Q}"),
    ("indeed", f"https://www.indeed.com/jobs?q={_RAW_Q}&l=Remote"),
]

_STRATEGIES = {
    "google": GoogleSearchStrategy,
    "bing": BingSearchStrategy,
    "indeed": IndeedSearchStrategy,
}


def _instruction(date_range=None, raw=None):
    return SearchInstruction(
        title="Engineer",
        location="Remote",
        raw_query_string=raw,
        date_range=date_range,
    )


@pytest.mark.parametrize("engine,date_range,expected", _CASES)
def test_engine_urls_are_byte_identical(engine, date_range, expected):
    strategy = _STRATEGIES[engine]()
    assert strategy.build_search_url(_instruction(date_range=date_range)) == expected


@pytest.mark.parametrize("engine,expected", _RAW_CASES)
def test_raw_query_urls_are_byte_identical(engine, expected):
    strategy = _STRATEGIES[engine]()
    assert strategy.build_search_url(_instruction(raw=_RAW)) == expected


def test_an_unknown_date_range_is_omitted_never_invented():
    """Automation omits an unknown date_range (the pre-catalog behaviour),
    never invents a code for it. Mutation caught: the composer writing a
    parameter for a code it does not know."""
    from auto_apply.adapters.secondary.discovery.search_surface_registry import (
        load_surface_bundled,
    )
    from auto_apply.domain.services.query_composer import build_automation_url

    url = build_automation_url(
        load_surface_bundled("google"),
        query="Engineer jobs in Remote",
        location="Remote",
        date_range="bogus",
    )
    assert "tbs" not in url

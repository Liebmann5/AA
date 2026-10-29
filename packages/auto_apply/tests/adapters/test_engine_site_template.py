"""Pins for engine-bound URL forms (SearchInstruction.surface_template).

Label honesty: surface_template did not exist before this change, so these
pins cover new surface; each docstring names the mutation caught. The
default-form pin (test_the_default_form_is_unaffected) is a GUARD for the
pre-existing byte contract.
"""

from __future__ import annotations

import pytest

from auto_apply.adapters.secondary.discovery.strategies.engine_strategies import (
    BingSearchStrategy,
    GoogleSearchStrategy,
    IndeedSearchStrategy,
)
from auto_apply.domain.models.search_instruction import SearchInstruction


def test_google_site_query_uses_the_web_form() -> None:
    """NEW SURFACE — a site-restricted Google query goes to web results, not
    the jobs vertical.

    Mutation caught: routing site queries to automation_url (jobs), whose
    cards carry no followable URL.
    """
    instruction = SearchInstruction(
        title="Engineer",
        raw_query_string='site:boards.greenhouse.io ("Engineer")',
        surface_template="web",
    )
    url = GoogleSearchStrategy().build_search_url(instruction)
    assert url == (
        "https://www.google.com/search?q="
        "site%3Aboards.greenhouse.io+%28%22Engineer%22%29"
    )
    assert "ibp=htl" not in url


def test_date_range_maps_on_the_web_form() -> None:
    """NEW SURFACE — the web form carries the date parameter.

    Mutation caught: dropping date_range when a non-default template is used.
    """
    instruction = SearchInstruction(
        title="Engineer",
        raw_query_string="site:x.example engineer",
        surface_template="web",
        date_range="week",
    )
    url = GoogleSearchStrategy().build_search_url(instruction)
    assert "tbs=qdr%3Aw" in url


def test_the_default_form_is_unaffected() -> None:
    """GUARD — an instruction with no surface_template produces exactly the
    automation URL it always did.

    Mutation caught: changing the template=None default path.
    """
    instruction = SearchInstruction(
        title="Engineer", location="Remote", date_range="day"
    )
    url = GoogleSearchStrategy().build_search_url(instruction)
    assert url == (
        "https://www.google.com/search?q=Engineer+jobs+in+Remote"
        "&ibp=htl%3Bjobs&hl=en&gl=us&start=0&tbs=qdr%3Ad"
    )


def test_an_unknown_template_raises() -> None:
    """NEW SURFACE — a template name the surface does not declare is a
    configuration error, never a silent fallback.

    Mutation caught: falling back to the default form on a bad name.
    """
    with pytest.raises(ValueError, match="no URL template"):
        GoogleSearchStrategy().build_search_url(
            SearchInstruction(title="E", surface_template="nope")
        )


def test_bing_site_query_uses_its_web_form() -> None:
    """NEW SURFACE — Bing's declared site form is its web search.

    Mutation caught: sending site queries to the Bing jobs vertical.
    """
    instruction = SearchInstruction(
        title="E",
        raw_query_string="site:jobs.lever.co engineer",
        surface_template="web",
    )
    url = BingSearchStrategy().build_search_url(instruction)
    assert url == "https://www.bing.com/search?q=site%3Ajobs.lever.co+engineer"


def test_indeed_refuses_a_web_form_query() -> None:
    """NEW SURFACE — Indeed declares no web form, so an engine-bound web
    query is refused loudly rather than silently rerouted.

    Mutation caught: silently substituting the jobs form.
    """
    with pytest.raises(ValueError):
        IndeedSearchStrategy().build_search_url(
            SearchInstruction(title="E", surface_template="web")
        )

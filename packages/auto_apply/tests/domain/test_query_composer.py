"""Pins for the query composer (turn 1 of the query-builder chain).

Label honesty:
  GUARD (new surface) — every pin here covers behaviour that did not exist
  before this change, so none could be run against the old tree. Each pin's
  docstring names the deliberate mutation it catches.
"""
from __future__ import annotations

import pytest

from auto_apply.adapters.secondary.discovery.search_surface_registry import (
    load_surface,
)
from auto_apply.domain.models.search_query import QueryRequest
from auto_apply.domain.models.search_surface import VerificationStatus
from auto_apply.domain.services.query_composer import compose


def _spec(name: str):
    return load_surface(name)


@pytest.mark.parametrize(
    "site,phrase,expected",
    [
        (
            "bamboohr.com/careers",
            "software engineer",
            'site:bamboohr.com/careers ("software engineer")',
        ),
        (
            "jobs.jobvite.com",
            "Software Engineer",
            'site:jobs.jobvite.com ("Software Engineer")',
        ),
        (
            "jobs.gusto.com/boards",
            "Software Engineer",
            'site:jobs.gusto.com/boards ("Software Engineer")',
        ),
    ],
)
def test_the_three_reported_queries_compose_exactly(site, phrase, expected):
    """GUARD: the three queries reported as reliable compose byte-exactly.
    Mutation caught: any change to site/phrase/group formatting."""
    result = compose(
        QueryRequest(surface="google", site=site, phrases=(phrase,)),
        _spec("google"),
    )
    assert result.bar_text == expected


def test_confusables_are_normalised_before_composing():
    """GUARD: a typographic closing quote (U+201D) in pasted text does not
    corrupt the query. Mutation caught: dropping the normalisation pass."""
    phrase = "Software Engineer\u201d"
    result = compose(
        QueryRequest(surface="google", site="jobs.jobvite.com", phrases=(phrase,)),
        _spec("google"),
    )
    assert result.bar_text == 'site:jobs.jobvite.com ("Software Engineer")'


def test_or_is_uppercase_where_the_surface_requires_it():
    """GUARD. Mutation caught: emitting a lower-case 'or' on Google."""
    result = compose(
        QueryRequest(surface="google", any_of=("Alpha", "Beta")),
        _spec("google"),
    )
    assert result.bar_text is not None
    assert " OR " in result.bar_text
    assert " or " not in result.bar_text


def test_no_space_after_an_operator_colon():
    """GUARD. Mutation caught: 'site: example.com' or 'intitle: engineer'."""
    result = compose(
        QueryRequest(surface="google", site="example.com", in_title=("engineer",)),
        _spec("google"),
    )
    assert result.bar_text is not None
    assert "site:example.com" in result.bar_text
    assert "site: " not in result.bar_text
    assert "intitle:engineer" in result.bar_text
    assert "intitle: " not in result.bar_text


def test_a_length_limit_is_never_exceeded():
    """GUARD: over the reported limit, nothing is written — never truncated.
    Mutation caught: removing the max_words check, or trimming instead."""
    words = tuple(f"w{i}" for i in range(40))
    result = compose(QueryRequest(surface="google", required=words), _spec("google"))
    assert result.bar_text is None
    assert result.url is None
    assert any(n.topic == "length" and n.severity == "refused" for n in result.notes)


def test_past_24_hours_lives_in_the_url_not_the_bar():
    """GUARD: Google's date filter is URL-only, and the note says the typed
    nearest (after:) is a different filter. Mutation caught: putting the date
    in the bar text, or dropping the explanation."""
    result = compose(
        QueryRequest(
            surface="google",
            phrases=("Software Engineer",),
            options=(("date", "day"),),
        ),
        _spec("google"),
    )
    assert result.bar_text == '("Software Engineer")'
    assert result.url is not None
    assert "tbs=qdr%3Ad" in result.url
    text = " ".join(n.message for n in result.notes)
    assert "cannot be typed" in text
    assert "after:" in text
    assert "fixed date" in text


def test_an_option_the_surface_lacks_is_refused_with_a_note():
    """GUARD. Mutation caught: silently ignoring an unknown option."""
    result = compose(
        QueryRequest(
            surface="google",
            phrases=("x",),
            options=(("colour", "blue"),),
        ),
        _spec("google"),
    )
    assert result.url is not None
    assert "colour" not in result.url
    assert any(n.severity == "refused" and "colour" in n.message for n in result.notes)


def test_a_site_limit_on_linkedin_is_refused_not_silently_dropped():
    """GUARD. Mutation caught: composing LinkedIn text with site:, dropping
    the note that says the site limit went nowhere, or building a LINK that
    silently drops it (the refusal-both rule: a link without the restriction
    is a different search)."""
    result = compose(
        QueryRequest(surface="linkedin", site="example.com", phrases=("Software Engineer",)),
        _spec("linkedin"),
    )
    assert result.bar_text is None
    assert result.url is None
    text = " ".join(n.message for n in result.notes)
    assert "site" in text.lower()


def test_any_of_on_duckduckgo_is_refused_not_rewritten():
    """GUARD: there is no documented OR on DuckDuckGo, so alternatives are
    never silently ANDed. Mutation caught: plain-joining any_of into the
    link, or answering with a bar."""
    result = compose(
        QueryRequest(
            surface="duckduckgo",
            phrases=("Software Engineer",),
            any_of=("Alpha", "Beta"),
        ),
        _spec("duckduckgo"),
    )
    assert result.bar_text is None
    assert result.url is None
    assert any(n.severity == "refused" and "any of these" in n.message for n in result.notes)


def test_exclusions_compose_single_and_multi_word_forms():
    """GUARD. Mutation caught: quoting a single word or not quoting a phrase."""
    result = compose(
        QueryRequest(
            surface="google",
            phrases=("developer",),
            exclude=("intern", "senior manager"),
        ),
        _spec("google"),
    )
    assert result.bar_text is not None
    assert "-intern" in result.bar_text
    assert '-"senior manager"' in result.bar_text


def test_any_of_composes_as_a_capitalised_or_group():
    """GUARD. Mutation caught: losing the parentheses or the quoted terms."""
    result = compose(
        QueryRequest(surface="google", any_of=("Software Engineer", "Backend Engineer")),
        _spec("google"),
    )
    assert result.bar_text == '("Software Engineer" OR "Backend Engineer")'


def test_intitle_clause_composes():
    """GUARD. Mutation caught: any change to intitle formatting."""
    result = compose(
        QueryRequest(surface="google", in_title=("engineer",)),
        _spec("google"),
    )
    assert result.bar_text == "intitle:engineer"


def test_linkedin_link_uses_plain_keywords_not_quotes():
    """GUARD: LinkedIn's quoting is unverified, so no quotes are emitted.
    Mutation caught: quoting the keywords anyway."""
    result = compose(
        QueryRequest(surface="linkedin", phrases=("Software Engineer",)),
        _spec("linkedin"),
    )
    assert result.bar_text is None
    assert result.url == "https://www.linkedin.com/jobs/search/?keywords=Software+Engineer"


def test_linkedin_date_and_workplace_options_apply():
    """GUARD. Mutation caught: wrong f_TPR/f_WT formats or codes."""
    result = compose(
        QueryRequest(
            surface="linkedin",
            phrases=("Software Engineer",),
            options=(("date", "day"), ("workplace", "remote")),
        ),
        _spec("linkedin"),
    )
    assert result.url is not None
    assert "f_TPR=r86400" in result.url
    assert "f_WT=2" in result.url


def test_indeed_url_carries_location_and_date():
    """GUARD. Mutation caught: dropping l= or mis-formatting fromage."""
    result = compose(
        QueryRequest(
            surface="indeed",
            phrases=("Software Engineer",),
            location="Austin",
            options=(("date", "week"),),
        ),
        _spec("indeed"),
    )
    assert result.url == (
        "https://www.indeed.com/jobs"
        "?q=%28%22Software+Engineer%22%29&l=Austin&fromage=7"
    )


def test_an_empty_request_builds_nothing_with_a_note():
    """GUARD. Mutation caught: producing a '?q=' link for an empty request."""
    result = compose(QueryRequest(surface="google"), _spec("google"))
    assert result.bar_text is None
    assert result.url is None
    assert result.notes


def test_the_url_carries_the_bar_text_url_encoded():
    """GUARD. Mutation caught: quoting rules differing between bar and URL."""
    result = compose(
        QueryRequest(surface="google", phrases=("Software Engineer",)),
        _spec("google"),
    )
    assert result.url == "https://www.google.com/search?q=%28%22Software+Engineer%22%29"


def test_an_unverified_operator_is_never_used():
    """GUARD (verification rule): a site operator marked unverified in a
    mutated spec is refused, never composed. Mutation caught: composing on
    status alone or ignoring status entirely."""
    spec = _spec("google")
    mutated = spec.model_copy(
        update={
            "operators": tuple(
                op.model_copy(update={"status": VerificationStatus.UNVERIFIED})
                if op.name == "site"
                else op
                for op in spec.operators
            )
        }
    )
    result = compose(
        QueryRequest(surface="google", site="example.com", phrases=("x",)),
        mutated,
    )
    assert result.bar_text is None
    assert any(n.severity == "refused" and n.topic == "site" for n in result.notes)


def test_a_surface_without_quoting_gets_unquoted_terms_with_a_note():
    """GUARD: LinkedIn records phrase quoting as unverified, so the link
    carries the terms bare and the notes explain why. Mutation caught:
    quoting without verification, or dropping the explanation."""
    result = compose(
        QueryRequest(surface="linkedin", phrases=("Software Engineer",)),
        _spec("linkedin"),
    )
    assert result.bar_text is None
    assert result.url is not None
    assert "%22" not in result.url
    assert result.notes


def test_date_and_sort_merge_on_one_parameter():
    """GUARD: two options sharing a URL parameter merge with a comma, as
    Google's multivalue tbs requires. Mutation caught: appending a second
    tbs=, or overwriting the first."""
    result = compose(
        QueryRequest(
            surface="google",
            phrases=("x",),
            options=(("date", "day"), ("sort_date", "on")),
        ),
        _spec("google"),
    )
    assert result.url is not None
    assert "tbs=qdr%3Ad%2Csbd%3A1" in result.url

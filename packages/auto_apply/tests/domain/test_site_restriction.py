"""Pins for judging whether an engine kept a query's ``site:`` restriction
(domain/services/site_restriction.py).

Measured 2026-11-08: in AA's browser Google answered six of seven platform
searches with one unrestricted page; Bing answered every ``site:`` value
with the same Greenhouse list. A page with no result on the restricted site
is a different search, not "no jobs"; a page with too few results proves
nothing either way.
"""
from __future__ import annotations

import pytest

from auto_apply.domain.services.site_restriction import (
    MIN_RESULTS_TO_JUDGE,
    check_restriction,
    host_within,
    restriction_of,
)


@pytest.mark.parametrize(
    "query,restriction",
    [
        ('site:jobs.lever.co ("Software Engineer")', "jobs.lever.co"),
        ('("Software Engineer") site:Jobs.Lever.co/', "jobs.lever.co"),
        ('site:jobs.gusto.com/boards ("Backend Engineer")', "jobs.gusto.com/boards"),
        # An excluded site is not the restriction.
        ('"engineer" -site:linkedin.com site:apply.workable.com', "apply.workable.com"),
        ('"engineer" -site:linkedin.com', ""),
        ("Software Engineer in Chicago", ""),
        ("", ""),
    ],
)
def test_the_restriction_is_the_first_included_site_operand(query, restriction):
    assert restriction_of(query) == restriction


@pytest.mark.parametrize(
    "host,restriction,within",
    [
        ("jobs.lever.co", "jobs.lever.co", True),
        ("adobe.wd5.myworkdayjobs.com", "myworkdayjobs.com", True),  # subdomains count
        ("www.jobs.lever.co", "jobs.lever.co", True),
        ("jobs.gusto.com", "jobs.gusto.com/boards", True),  # the host part of a path
        ("boards.greenhouse.io", "job-boards.greenhouse.io", False),
        ("evil-jobs.lever.co.example", "jobs.lever.co", False),
        ("notmyworkdayjobs.com", "myworkdayjobs.com", False),
        ("", "jobs.lever.co", False),
    ],
)
def test_a_result_is_on_the_site_when_its_host_is_the_site_or_a_subdomain(host, restriction, within):
    assert host_within(host, restriction) is within


def test_no_result_on_the_site_out_of_enough_results_is_a_dropped_restriction():
    """Bing, 2026-11-08: ``site:jobs.lever.co`` gave ten Greenhouse results."""
    check = check_restriction("jobs.lever.co", ["boards.greenhouse.io"] * 10)
    assert check.dropped and check.state == "dropped"
    assert check.describe() == "0 of 10 results on jobs.lever.co"


def test_any_result_on_the_site_means_it_was_kept():
    check = check_restriction("jobs.lever.co", ["jobs.lever.co"] + ["ads.example"] * 9)
    assert not check.dropped and check.state == "kept"


def test_too_few_results_prove_nothing():
    """A "no results" page with a stray suggestion is not a dropped
    restriction: below the threshold the verdict is unknown, never dropped."""
    few = ["elsewhere.example"] * (MIN_RESULTS_TO_JUDGE - 1)
    check = check_restriction("jobs.lever.co", few)
    assert not check.dropped and check.state == "unknown"
    assert check_restriction("jobs.lever.co", []).state == "unknown"


def test_no_restriction_is_never_dropped():
    assert not check_restriction("", ["a.example"] * 10).dropped

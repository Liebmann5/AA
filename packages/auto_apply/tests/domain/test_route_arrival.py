"""Teeth pins for the shown destination and the arrival check of an opaque
route (domain/services/route_arrival.py).

Review round on the site-search-shown change (2026-11-08): both reviewers
asked whether the destination a results page shows can differ from where
the link goes, and what confirms it when AA lands. The answer pinned here:
the shown host is read strictly, and the landing is checked against the
platform's posting patterns before anything on the page is used.
"""
from __future__ import annotations

import pytest

from auto_apply.adapters.secondary.discovery.ats_registry import ATSRegistry
from auto_apply.domain.services.route_arrival import arrival_problem, shown_host

_ROUTE = "https://www.google.com/goto?url=CAESaQHEIkXXo_WqMhp-QAnfytxyPIc3nz1rqUjgMcnlZef"


@pytest.mark.parametrize(
    "shown,host",
    [
        ("jobs.jobvite.com", "jobs.jobvite.com"),
        ("jobs.jobvite.com/brahma", "jobs.jobvite.com"),
        ("https://jobs.jobvite.com › brahma › job", "jobs.jobvite.com"),
        ("WWW.Jobs.Jobvite.com:443/acme", "www.jobs.jobvite.com"),
        ("jobs.jobvite.com.", "jobs.jobvite.com"),
        # The holes: a host read by splitting at "/" alone would be fooled.
        ("evil.com/jobs.jobvite.com", "evil.com"),
        ("jobs.jobvite.com@evil.com", "evil.com"),
        ("evil.com/x@jobs.jobvite.com", "evil.com"),
        ("", ""),
        ("jobs.jobvite.com evil.com", ""),
        ("https:", ""),
    ],
)
def test_the_shown_host_is_read_as_a_url_authority(shown, host):
    assert shown_host(shown) == host


def test_the_registry_never_claims_a_string_that_is_not_a_host():
    """TEETH: ``platform_for_host("evil.com/jobs.jobvite.com")`` answered
    "jobvite" (suffix match over the whole string)."""
    registry = ATSRegistry()
    assert registry.platform_for_host("evil.com/jobs.jobvite.com") is None
    assert registry.platform_for_host("evil.com/x@jobs.jobvite.com") is None
    assert registry.platform_for_host("WWW.jobs.jobvite.com:443") == "jobvite"
    assert registry.platform_for_host("user@jobs.jobvite.com") == "jobvite"


def test_a_jobvite_posting_landing_is_confirmed():
    landed = "https://jobs.jobvite.com/brahma/job/oAbCdEfG"
    assert arrival_problem(_ROUTE, landed, "jobvite", ATSRegistry()) == ""


@pytest.mark.parametrize(
    "landed,fragment",
    [
        ("", "unknown"),
        (_ROUTE, "did not resolve"),
        ("https://www.google.com/sorry/index?continue=x", "did not resolve"),
        ("https://job-boards.greenhouse.io/acme/jobs/4012345", "off platform"),
        ("https://www.example.com/careers/backend", "off platform"),
        # The owner's Google search of 2026-11-08 showed four
        # "jobs.jobvite.com > leantechio > search" results: a company's list
        # of openings on the right platform, not a posting.
        ("https://jobs.jobvite.com/leantechio/search?q=backend", "not a posting"),
    ],
)
def test_a_landing_that_is_not_a_posting_of_the_platform_is_rejected(landed, fragment):
    problem = arrival_problem(_ROUTE, landed, "jobvite", ATSRegistry())
    assert problem.startswith("ArrivalCheck:") and fragment in problem


def test_without_a_registry_nothing_is_confirmed():
    problem = arrival_problem(_ROUTE, "https://jobs.jobvite.com/a/job/oAbCdEfG", "jobvite", None)
    assert "no platform registry" in problem


def test_a_registry_fault_is_a_rejection_never_a_pass():
    class _Broken:
        def platform_for_host(self, host):
            raise RuntimeError("broken")

    problem = arrival_problem(_ROUTE, "https://jobs.jobvite.com/a/job/oAbCdEfG", "jobvite", _Broken())
    assert "off platform" in problem

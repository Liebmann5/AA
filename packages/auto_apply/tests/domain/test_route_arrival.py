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
from auto_apply.domain.services.route_arrival import (
    arrival_problem,
    judge_arrival,
    page_resource_urls,
    shown_host,
)

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


# ── A platform's posting embedded on the employer's own site ────────────────
#
# Live run 2026-11-08: five Greenhouse hits "landed off platform"; three
# carried gh_jid=<id> on the employer's careers page (Greenhouse's documented
# embed: employer job links carry gh_jid, the form loads from
# job-boards.greenhouse.io/embed/job_app), one framed the application form,
# and one landed on a company's list of openings. The list stays rejected.


_GH_ROUTE = "https://www.google.com/goto?url=CAESaQHEIkXX"


def test_an_employer_page_carrying_the_greenhouse_job_id_is_confirmed_teeth():
    """TEETH: rejected as "landed off platform (careers.toasttab.com)"."""
    landed = "https://careers.toasttab.com/jobs?gh_jid=8301214"
    verdict = judge_arrival(_GH_ROUTE, landed, "greenhouse", ATSRegistry(), lambda: [])
    assert verdict.confirmed and verdict.embedded == "gh_jid=8301214"


def test_an_employer_page_framing_the_greenhouse_form_is_confirmed_teeth():
    html = ('<html><body><div id="grnhse_app"><iframe id="grnhse_iframe" '
            'src="https://job-boards.greenhouse.io/embed/job_app?for=okta&amp;token=6512345">'
            "</iframe></div></body></html>")
    landed = "https://www.okta.com/company/careers/opportunity/6512345/"
    verdict = judge_arrival(_GH_ROUTE, landed, "greenhouse", ATSRegistry(),
                            lambda: page_resource_urls(html, landed))
    assert verdict.confirmed and verdict.embedded.startswith("frame job-boards.greenhouse.io/embed/job_app")


def test_a_frame_counts_only_when_the_platform_serves_it():
    """The frame patterns are unanchored; another host carrying the path in
    its query is not Greenhouse's form."""
    html = '<iframe src="https://evil.example/frame?u=greenhouse.io/embed/job_app?for=x"></iframe>'
    landed = "https://careers.example.com/jobs/1"
    verdict = judge_arrival(_GH_ROUTE, landed, "greenhouse", ATSRegistry(),
                            lambda: page_resource_urls(html, landed))
    assert not verdict.confirmed


def test_an_employer_list_of_openings_is_still_off_platform():
    """Only the board script: a list of openings, not one posting."""
    html = '<script src="https://boards.greenhouse.io/embed/job_board/js?for=fanduel"></script>'
    landed = "https://www.fanduel.careers/open-positions"
    verdict = judge_arrival(_GH_ROUTE, landed, "greenhouse", ATSRegistry(),
                            lambda: page_resource_urls(html, landed))
    assert not verdict.confirmed and "landed off platform" in verdict.problem


@pytest.mark.parametrize("landed", [
    "https://careers.example.com/jobs?gh_jid=",          # empty id
    "https://careers.example.com/jobs?gh_jidx=8301214",   # another parameter
    "https://careers.example.com/jobs#gh_jid=8301214",    # not a query parameter
])
def test_a_job_id_must_be_a_real_query_parameter(landed):
    assert not judge_arrival(_GH_ROUTE, landed, "greenhouse", ATSRegistry(), lambda: []).confirmed


def test_embedding_evidence_is_per_platform():
    """gh_jid is Greenhouse's: it confirms nothing for another platform."""
    landed = "https://careers.toasttab.com/jobs?gh_jid=8301214"
    assert not judge_arrival(_GH_ROUTE, landed, "lever", ATSRegistry(), lambda: []).confirmed


def test_page_resources_are_read_only_when_the_host_is_not_the_platform():
    calls = []
    judge_arrival(_GH_ROUTE, "https://boards.greenhouse.io/acme/jobs/4012345", "greenhouse",
                  ATSRegistry(), lambda: calls.append(1) or [])
    assert calls == []


def test_page_resource_urls_resolve_and_bound():
    html = '<iframe src="/embed/x"></iframe><script src="https://cdn.example/a.js"></script><img src="i.png">'
    assert page_resource_urls(html, "https://careers.example.com/jobs/1") == [
        "https://careers.example.com/embed/x", "https://cdn.example/a.js",
    ]
    many = "".join(f'<script src="/s{k}.js"></script>' for k in range(700))
    assert len(page_resource_urls(many, "https://e.example/")) == 500
    assert page_resource_urls("", "https://e.example/") == []

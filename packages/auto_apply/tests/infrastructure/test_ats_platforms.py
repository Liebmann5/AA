"""Pins for the platform-identity expansion (query-builder chain, call 2).

Label honesty — each pin's docstring says which it is:

  TEETH  — fails on the pre-change tree (no tenancy fields, no
           is_terminal_page, six descriptors, no checklist doc).
  GUARD  — holds a property already true, so the expansion cannot silently
           break it.

I have not executed these; each names the mutation it catches.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from auto_apply.adapters.secondary.discovery.ats_registry import ATSRegistry
from auto_apply.application.services.page_analysis_router import PageAnalysisTier

_ATS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src" / "auto_apply" / "resources" / "ats"
)
_SURFACES_DIR = (
    Path(__file__).resolve().parents[2]
    / "src" / "auto_apply" / "resources" / "search_surfaces"
)
_CHECKLIST = (
    Path(__file__).resolve().parents[2]
    / "docs" / "developer_guide" / "verifying_platform_search.md"
)

_TENANCIES = {"none", "subdomain", "path", "opaque", "enterprise"}
_STATUSES = {"vendor", "measured", "third_party", "unverified"}


def test_no_platform_host_appears_in_the_search_surface_catalog():
    """GUARD (single source). The catalog holds engines and job boards;
    platform hosts live only in resources/ats/. Mutation caught: a host list
    copied into search_surfaces/."""
    registry = ATSRegistry()
    for surface_path in _SURFACES_DIR.glob("*.yaml"):
        text = surface_path.read_text(encoding="utf-8")
        for descriptor in registry.all_descriptors():
            for host in descriptor.hosts:
                assert host not in text, (
                    f"{host!r} ({descriptor.name}) appears in {surface_path.name} "
                    "— platform hosts belong only in resources/ats/"
                )


def test_no_two_platforms_claim_the_same_host():
    """GUARD (data integrity). Mutation caught: two descriptors declaring
    the same host — platform_for_host would silently pick the first."""
    seen: dict[str, str] = {}
    for descriptor in ATSRegistry().all_descriptors():
        for host in descriptor.hosts:
            assert host not in seen, f"{host!r} claimed by {seen[host]!r} and {descriptor.name!r}"
            seen[host] = descriptor.name


def test_every_descriptor_carries_valid_search_data():
    """TEETH (the new fields did not exist). Mutation caught: an unknown
    tenancy word, an unknown status, a measured status with no date, an
    empty restriction, or a restriction whose host is not a declared host."""
    registry = ATSRegistry()
    descriptors = registry.all_descriptors()
    assert len(descriptors) >= 30, "the platform expansion did not land"
    for d in descriptors:
        assert d.tenancy in _TENANCIES, f"{d.name}: tenancy {d.tenancy!r}"
        assert d.search_restriction_status in _STATUSES, (
            f"{d.name}: status {d.search_restriction_status!r}"
        )
        if d.search_restriction_status == "measured":
            assert d.search_restriction_verified_on, (
                f"{d.name}: measured without verified_on"
            )
            assert d.search_restriction_source
        assert d.search_restriction, f"{d.name}: no search_restriction"
        restriction_host = d.search_restriction.split("/", 1)[0].lower()
        assert any(
            restriction_host == h or restriction_host.endswith("." + h)
            for h in d.hosts
        ), f"{d.name}: restriction {d.search_restriction!r} matches no declared host"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://boards.greenhouse.io/acme/jobs/123", "greenhouse"),
        ("https://jobs.lever.co/acme/apply", "lever"),
        ("https://acme.myworkdayjobs.com/en-US/corp/job/1", "workday"),
        ("https://careers-acme.icims.com/jobs/123/job", "icims"),
        ("https://acme.taleo.net/careersection/1/jobdetail.ftl?job=1", "taleo"),
        ("https://jobs.ashbyhq.com/acme/apply", "ashby"),
    ],
)
def test_the_existing_six_still_match_their_sample_urls(url, expected):
    """GUARD. Mutation caught: a new pattern shadowing an existing platform
    in sorted load order."""
    descriptor = ATSRegistry().match(url)
    assert descriptor is not None and descriptor.name == expected


def test_a_discovery_only_platform_never_gets_the_known_platform_tier():
    """GUARD (tier safety). New descriptors ship with empty selectors, so
    none may route to KNOWN_PLATFORM. Mutation caught: the router keying the
    tier on match alone."""
    from auto_apply.application.services.page_analysis_router import (
        PageAnalysisRouter,
    )

    router = PageAnalysisRouter(ats_registry=ATSRegistry())
    tier = router.determine_tier("https://apply.workable.com/last-call-media/j/FF37BE66C5/apply/")
    assert tier != PageAnalysisTier.KNOWN_PLATFORM


def test_a_platform_with_selectors_still_gets_the_known_platform_tier():
    """GUARD. Mutation caught: the terminal check or new fields breaking the
    existing tier rule for the six."""
    from auto_apply.application.services.page_analysis_router import (
        PageAnalysisRouter,
    )

    router = PageAnalysisRouter(ats_registry=ATSRegistry())
    tier = router.determine_tier("https://boards.greenhouse.io/acme/jobs/123")
    assert tier == PageAnalysisTier.KNOWN_PLATFORM


@pytest.mark.parametrize(
    ("url", "terminal"),
    [
        ("https://cerecore.catsone.com/careers/56866-General/jobs/16364730-System-Analyst/apply/success", True),
        ("https://dealeron.theresumator.com/apply/confirm/G3gue6dy4D", True),
        ("https://cerecore.catsone.com/careers/56866-General/jobs/16364730-System-Analyst", False),
        ("https://boards.greenhouse.io/acme/jobs/123", False),
    ],
)
def test_terminal_pages_are_recognised_and_postings_are_not(url, terminal):
    """TEETH (is_terminal_page did not exist). Mutation caught: a terminal
    pattern swallowing postings, or a success/confirm page reading as a
    destination."""
    assert ATSRegistry().is_terminal_page(url) is terminal


@pytest.mark.parametrize(
    ("url", "platform", "slug"),
    [
        ("https://holisticai.bamboohr.com/careers/59", "bamboohr", "holisticai"),
        ("https://jobs.jobvite.com/ziffdavis/job/orCdqfwq/apply", "jobvite", "ziffdavis"),
        (
            "https://recruiterflow.com/db_cae6aa6c42ee795815955c2dab38824c/jobs/241",
            "recruiterflow",
            "db_cae6aa6c42ee795815955c2dab38824c",
        ),
        (
            "https://jobs.gusto.com/boards/possip-9d7e6ab2-bfc6-4b25-8517-fa812738ec56",
            "gusto",
            "possip-9d7e6ab2-bfc6-4b25-8517-fa812738ec56",
        ),
    ],
)
def test_tenant_slug_extraction(url, platform, slug):
    """TEETH (the method did not exist): one subdomain tenancy, one path
    tenancy, one opaque-ID platform from Nick's table, plus a path tenancy
    with a shared static prefix. Mutation caught: returning the static
    prefix, the host, or None."""
    descriptor = ATSRegistry().match(url)
    assert descriptor is not None and descriptor.name == platform
    assert descriptor.tenant_slug(url) == slug


@pytest.mark.parametrize(
    ("url", "platform", "restriction"),
    [
        ("https://holisticai.bamboohr.com/careers/59", "bamboohr", "holisticai.bamboohr.com/careers"),
        ("https://jobs.jobvite.com/ziffdavis/job/orCdqfwq/apply", "jobvite", "jobs.jobvite.com/ziffdavis"),
        (None, "jobvite", "jobs.jobvite.com"),
    ],
)
def test_search_restriction_for_a_tenant_url(url, platform, restriction):
    """TEETH. Mutation caught: ignoring the tenant, or returning the wrong
    base when no URL is given."""
    descriptor = next(
        d for d in ATSRegistry().all_descriptors() if d.name == platform
    )
    assert descriptor.search_restriction_for(url) == restriction


def test_the_verification_checklist_covers_every_platform():
    """TEETH (the doc did not exist). Mutation caught: a platform added
    without its checklist row."""
    text = _CHECKLIST.read_text(encoding="utf-8")
    for descriptor in ATSRegistry().all_descriptors():
        assert descriptor.name in text, (
            f"{descriptor.name!r} missing from verifying_platform_search.md"
        )

"""Pins for the builder's platform search.

Label honesty per pin: TEETH fail on the pre-change tree (no platform
methods, no registry injection, no site_template, no refusal-both); GUARDs
hold the surface-level behaviour the platform expansion must not break.
I have not executed these; each names the mutation it catches.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from auto_apply.adapters.secondary.discovery.ats_registry import ATSRegistry
from auto_apply.adapters.secondary.discovery.search_surface_registry import (
    list_surface_names,
    load_surface,
)
from auto_apply.application.services.query_builder import (
    QueryBuilderError,
    QueryBuilderService,
)
from auto_apply.domain.models.search_query import QueryRequest


def _service(registry=None) -> QueryBuilderService:
    return QueryBuilderService(
        profile=None,
        load_spec=load_surface,
        list_names=list_surface_names,
        ats_registry=ATSRegistry() if registry is None else registry,
        recent_path=Path("/nonexistent/recent.json"),
    )


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("jobvite", 'site:jobs.jobvite.com ("Software Engineer")'),
        ("bamboohr", 'site:bamboohr.com/careers ("Software Engineer")'),
        ("gusto", 'site:jobs.gusto.com/boards ("Software Engineer")'),
    ],
)
def test_nicks_three_queries_compose_exactly_through_platform_data(platform, expected):
    """TEETH — the platform data did not exist. Mutation caught: a
    restriction differing from Nick's measured/reported strings by one
    character, or the composer reformatting them."""
    result = _service().build_platform_query(
        platform, QueryRequest(surface="google", phrases=("Software Engineer",))
    )
    assert result.bar_text == expected
    assert result.url is not None and "google.com/search" in result.url


def test_a_domain_restricted_bing_search_uses_web_results():
    """TEETH — Bing defaulted to the jobs vertical. Mutation caught: the
    site template selection ignored or removed."""
    result = _service().build_platform_query(
        "workday", QueryRequest(surface="bing", phrases=("Software Engineer",))
    )
    assert result.url is not None
    assert "bing.com/search" in result.url
    assert "bing.com/jobs" not in result.url


def test_a_restriction_a_surface_cannot_express_refuses_the_link_too():
    """TEETH — the link used to survive with the restriction silently
    dropped. Mutation caught: hard_stop ignored for content refusals."""
    result = _service().build_platform_query(
        "workday", QueryRequest(surface="indeed", phrases=("x",))
    )
    assert result.bar_text is None
    assert result.url is None
    assert any(n.severity == "refused" and n.topic == "site" for n in result.notes)


def test_a_platform_search_on_a_surface_without_site_refuses_cleanly():
    """TEETH. Mutation caught: LinkedIn composing anything from a site
    restriction."""
    result = _service().build_platform_query(
        "greenhouse", QueryRequest(surface="linkedin", phrases=("x",))
    )
    assert result.bar_text is None
    assert result.url is None


def test_an_indeed_search_without_a_location_has_no_empty_parameter():
    """TEETH — an empty l= used to be emitted. Mutation caught: the
    empty-parameter filter removed."""
    result = _service().build_query(QueryRequest(surface="indeed", phrases=("x",)))
    assert result.url is not None
    assert "l=" not in result.url


@pytest.mark.parametrize(
    ("url", "expected_bar"),
    [
        (
            "https://holisticai.bamboohr.com/careers/59",
            'site:holisticai.bamboohr.com/careers ("x")',
        ),
        (
            "https://jobs.jobvite.com/ziffdavis/job/orCdqfwq/apply",
            'site:jobs.jobvite.com/ziffdavis ("x")',
        ),
        (
            "https://recruiterflow.com/db_cae6aa6c42ee795815955c2dab38824c/jobs/241",
            'site:recruiterflow.com/db_cae6aa6c42ee795815955c2dab38824c ("x")',
        ),
    ],
)
def test_a_company_url_scopes_the_search_to_the_tenant(url, expected_bar):
    """TEETH — one subdomain, one path, one opaque tenancy. Mutation caught:
    the slug ignored, or the shared path prefix dropped."""
    result = _service().build_company_query(
        url, QueryRequest(surface="google", phrases=("x",))
    )
    assert result.bar_text == expected_bar


def test_a_company_url_on_no_known_platform_refuses_without_a_guess():
    """TEETH. Mutation caught: composing a restriction from the raw host."""
    result = _service().build_company_query(
        "https://example.org/jobs/1", QueryRequest(surface="google", phrases=("x",))
    )
    assert result.bar_text is None
    assert result.url is None
    assert any(n.severity == "refused" for n in result.notes)


def test_the_platform_list_comes_from_the_injected_registry():
    """TEETH (the method did not exist). Mutation caught: a second,
    hardcoded platform list in the service."""
    names = {d.name for d in _service().platforms()}
    assert {"greenhouse", "lever", "workday", "icims", "taleo", "ashby"} <= names
    assert "jobvite" in names and "jazzhr" in names
    assert len(names) >= 30


def test_a_builder_without_a_registry_refuses_platform_searches_loudly():
    """TEETH. Mutation caught: a quiet empty result where the platform list
    should be."""
    service = QueryBuilderService(
        profile=None,
        load_spec=load_surface,
        list_names=list_surface_names,
        recent_path=Path("/nonexistent/recent.json"),
    )
    assert service.platforms() == ()
    with pytest.raises(QueryBuilderError):
        service.build_platform_query("jobvite", QueryRequest(surface="google", phrases=("x",)))


def test_the_builder_modules_do_not_import_the_registry_adapter():
    """GUARD (hexagonal boundary). Mutation caught: query_builder importing
    adapters.secondary.discovery.ats_registry instead of the domain port."""
    root = Path(__file__).resolve().parents[2] / "src" / "auto_apply"
    path = root / "application" / "services" / "query_builder.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert ".adapters." not in alias.name, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert ".adapters." not in node.module, node.module

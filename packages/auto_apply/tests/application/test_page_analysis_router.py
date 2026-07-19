"""Unit tests for PageAnalysisRouter and its integration with ApplicationsWorkflow."""
from unittest.mock import MagicMock

import pytest

from auto_apply.application.services.page_analysis_router import (
    PageAnalysisRouter,
    PageAnalysisTier,
)
from auto_apply.domain.ports.ats_port import ATSDescriptor


@pytest.fixture
def known_descriptor():
    return ATSDescriptor(
        name="greenhouse",
        url_patterns=("*.greenhouse.io/jobs/*",),
        login_wall_signals=(),
        success_signals=(),
        form_root_selector="",
        submit_button_selector="button#submit_app",
        multi_step=False,
    )


@pytest.fixture
def unknown_descriptor():
    return ATSDescriptor(
        name="unknown",
        url_patterns=("*.unknown.io/*",),
        login_wall_signals=(),
        success_signals=(),
        form_root_selector="",
        submit_button_selector="",
        multi_step=False,
    )


@pytest.fixture
def ats_registry(known_descriptor, unknown_descriptor):
    reg = MagicMock()
    reg.match.side_effect = lambda url: {
        "https://boards.greenhouse.io/acme/jobs/123": known_descriptor,
        "https://someting.unknown.io/job/1": unknown_descriptor,
    }.get(url, None)
    return reg


def test_determine_tier_known_platform_with_submit_selector(ats_registry):
    router = PageAnalysisRouter(ats_registry=ats_registry)
    tier = router.determine_tier("https://boards.greenhouse.io/acme/jobs/123")
    assert tier == PageAnalysisTier.KNOWN_PLATFORM


def test_determine_tier_known_platform_without_submit_selector(ats_registry):
    router = PageAnalysisRouter(ats_registry=ats_registry)
    tier = router.determine_tier("https://someting.unknown.io/job/1")
    assert tier == PageAnalysisTier.CSS_EXTRACTION


def test_determine_tier_structured_data():
    router = PageAnalysisRouter()
    html = '<script type="application/ld+json">{"@type":"JobPosting"}</script>'
    tier = router.determine_tier("https://example.com/job/42", page_html=html)
    assert tier == PageAnalysisTier.STRUCTURED_DATA


def test_determine_tier_form_present():
    router = PageAnalysisRouter()
    html = "<form><input type='text'></form>"
    tier = router.determine_tier("https://example.com/page", page_html=html)
    assert tier == PageAnalysisTier.CSS_EXTRACTION


def test_determine_tier_fallback():
    router = PageAnalysisRouter()
    tier = router.determine_tier("https://example.com/plain")
    assert tier == PageAnalysisTier.FULL_MATH_DOM


def test_determine_tier_fallback_with_empty_html():
    router = PageAnalysisRouter()
    tier = router.determine_tier("https://example.com/none", page_html="")
    assert tier == PageAnalysisTier.FULL_MATH_DOM


def test_has_json_ld_helper():
    assert PageAnalysisRouter._has_json_ld('hello application/ld+json world')
    assert not PageAnalysisRouter._has_json_ld('<script type="text/javascript">')


def test_has_form_helper():
    assert PageAnalysisRouter._has_form("<form><input type='text'></form>")
    assert not PageAnalysisRouter._has_form("no form here")
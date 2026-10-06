"""Pins for the ONE page verdict (domain/services/page_assessment.py).

Fixtures reuse the measured page shapes from test_challenge_assessment.py
(Cloudflare interstitials, postings carrying recaptcha tokens in page data,
the jobrapido embedded-widget shape) plus the shapes the retired
PageClassifier answered (JSON-LD postings, fillable forms, thin login
pages). They are synthetic recreations — tests never read dev_data/.

Pin labels, honestly: against the pre-change tree every test here fails on
ImportError, which is weak evidence. The real teeth are (a) the agreement
pin — discovery and application must answer the same on the same snapshot —
and (b) the fixtures' measured shapes, which the retiring code got wrong.
"""
from __future__ import annotations

import pytest

from auto_apply.domain.services.challenge_assessment import (
    assess_challenge,
    assess_login_wall,
)
from auto_apply.domain.services.page_assessment import assess_page
from auto_apply.domain.types import PageType

_INTERSTITIAL_HTML = (
    "<html><head><title>Just a moment...</title>"
    '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js">'
    "</script></head><body>"
    '<input type="hidden" name="cf-turnstile-response" value=""/>'
    "<p>Checking your browser before continuing.</p>"
    "</body></html>"
)

_POSTING_HTML = (
    "<html><head><title>Backend Engineer | Example Board</title>"
    "<script>var cfg = { captcha: 'recaptcha-site-key' };</script>"
    "</head><body>"
    "<form id='search'><input name='q'/></form>"
    "<form id='alert'><input name='email'/></form>"
    f"<p>{'Backend Engineer role details. ' * 60}</p>"
    "<!-- recaptcha -->"
    "</body></html>"
)

_EMBEDDED_HTML = (
    "<html><head><title>Backend Engineer | Job Board</title></head><body>"
    "<form id='a'><input name='q'/></form>"
    "<form id='b'><input name='e'/></form>"
    f"<p>{'Mid Level Backend Engineer role details. ' * 40}</p>"
    '<div class="g-recaptcha" data-sitekey="x"></div>'
    '<iframe src="https://www.google.com/recaptcha/api2/anchor?k=x"></iframe>'
    "</body></html>"
)

_PASSWORD_FORM_HTML = (
    "<html><body>"
    "<form method='post'>"
    "<input name='user'/><input type='password' name='pw'/>"
    "</form>"
    "<p>Sign in to continue.</p>"
    "</body></html>"
)

_FILLABLE_FORM_HTML = (
    "<html><body><form>"
    "<input name='first'/><input name='last'/><input name='email'/>"
    "</form></body></html>"
)

_FILE_FORM_HTML = (
    "<html><body><form>"
    "<input name='a'/><input type='file' name='resume'/>"
    "</form></body></html>"
)

_JSON_LD_HTML = (
    "<html><head>"
    '<script type="application/ld+json">'
    '{"@context":"https://schema.org","@type":"JobPosting",'
    '"title":"Backend Engineer"}'
    "</script>"
    "</head><body>"
    f"<p>{'Great role at a great company. ' * 40}</p>"
    "</body></html>"
)

_FORM_AND_JSON_LD_HTML = (
    "<html><head>"
    '<script type="application/ld+json">{"@type":"JobPosting","title":"X"}</script>'
    "</head><body><form>"
    "<input name='a'/><input name='b'/><input name='c'/>"
    "</form></body></html>"
)

_DATADOME_HTML = (
    "<html><head>"
    '<script src="https://captcha-delivery.com/captcha/check.js"></script>'
    "</head><body>"
    "<form id='a'><input name='q'/></form>"
    "<form id='b'><input name='e'/></form>"
    f"<p>{'Senior role details. ' * 50}</p>"
    "</body></html>"
)

_CF_SPINNER_HTML = (
    "<html><head><title>One moment</title></head><body>"
    '<div class="cf-spinner"></div>'
    "<p>Please wait.</p>"
    "</body></html>"
)

_PLAIN_HTML = (
    "<html><body><p>Hello world, a perfectly ordinary page.</p></body></html>"
)


def test_gated_interstitial_is_captcha_block_with_cloudflare_vendor():
    result = assess_page(
        url="https://www.ziprecruiter.example/jobs/x",
        title="Just a moment...",
        html=_INTERSTITIAL_HTML,
    )
    assert result.kind is PageType.CAPTCHA_BLOCK
    assert result.challenge == "gated"
    assert "cloudflare" in result.vendors
    assert result.confidence >= 0.9


def test_challenge_url_marker_is_captcha_block():
    result = assess_page(
        url="https://www.google.com/sorry/index?q=x", title="", html=_PLAIN_HTML
    )
    assert result.kind is PageType.CAPTCHA_BLOCK
    assert "challenge-url" in result.signals


def test_verify_url_marker_gates_the_page():
    """The /verify/ marker lifted from the retired detection.py."""
    result = assess_page(
        url="https://accounts.example.com/verify/email", title="", html=_PLAIN_HTML
    )
    assert result.kind is PageType.CAPTCHA_BLOCK
    assert "challenge-url" in result.signals


def test_cf_spinner_widget_gates_the_page():
    """The cf-spinner marker lifted from the retired Cloudflare strategy."""
    result = assess_page(
        url="https://www.example.com/jobs/1", title="One moment", html=_CF_SPINNER_HTML
    )
    assert result.kind is PageType.CAPTCHA_BLOCK
    assert "cloudflare" in result.vendors


def test_posting_with_recaptcha_tokens_is_not_blocked():
    result = assess_page(
        url="https://www.linkedin.example/jobs/view/some-job-123",
        title="Backend Engineer",
        html=_POSTING_HTML,
    )
    assert result.kind is not PageType.CAPTCHA_BLOCK
    assert result.challenge == "clear"


def test_widget_inside_content_page_is_embedded_not_blocked():
    result = assess_page(
        url="https://uk.jobrapido.example/job/1", title="Backend Engineer", html=_EMBEDDED_HTML
    )
    assert result.challenge == "embedded"
    assert result.kind is not PageType.CAPTCHA_BLOCK
    assert "challenge-iframe" in result.signals
    assert "recaptcha" in result.vendors


def test_login_url_is_login_required():
    result = assess_page(
        url="https://ats.example.com/users/sign_in", title="", html=""
    )
    assert result.kind is PageType.LOGIN_REQUIRED
    assert "login-wall" in result.signals


def test_password_form_page_is_login_required():
    result = assess_page(
        url="https://ats.example.com/xyz", title="", html=_PASSWORD_FORM_HTML
    )
    assert result.kind is PageType.LOGIN_REQUIRED


def test_registered_nurse_posting_is_neither_wall_nor_challenge():
    """The title says 'register'; the page is a posting."""
    result = assess_page(
        url="https://boards.example.com/jobs/registered-nurse-123",
        title="Registered Nurse",
        html=_POSTING_HTML,
    )
    assert result.kind is not PageType.LOGIN_REQUIRED
    assert result.kind is not PageType.CAPTCHA_BLOCK


def test_title_404_is_error_404_and_labelled_debt():
    result = assess_page(
        url="https://example.com/gone", title="404 Not Found", html=_PLAIN_HTML
    )
    assert result.kind is PageType.ERROR_404
    assert "title-404" in result.signals
    assert result.confidence == 0.60, "the title-only 404 must stay confidence-capped"


def test_fillable_form_page_is_application_form():
    result = assess_page(
        url="https://ats.example.com/apply/1", title="Apply", html=_FILLABLE_FORM_HTML
    )
    assert result.kind is PageType.APPLICATION_FORM
    assert "fillable-form" in result.signals


def test_file_upload_page_is_application_form():
    result = assess_page(
        url="https://ats.example.com/apply/2", title="Apply", html=_FILE_FORM_HTML
    )
    assert result.kind is PageType.APPLICATION_FORM


def test_json_ld_jobposting_is_job_description():
    """The retired PageClassifier called this SERP 'context dependent'; the
    honest kind is JOB_DESCRIPTION. Nothing on the discovery path branches
    on either."""
    result = assess_page(
        url="https://boards.example.com/jobs/9", title="Backend Engineer", html=_JSON_LD_HTML
    )
    assert result.kind is PageType.JOB_DESCRIPTION
    assert "json-ld-jobposting" in result.signals


def test_fillable_form_outranks_json_ld():
    result = assess_page(
        url="https://ats.example.com/apply/3", title="Apply", html=_FORM_AND_JSON_LD_HTML
    )
    assert result.kind is PageType.APPLICATION_FORM


def test_gated_challenge_outranks_login_url():
    """A Cloudflare gate in front of a login page is CAPTCHA_BLOCK: the wall
    is behind the gate."""
    result = assess_page(
        url="https://ats.example.com/login", title="Just a moment...", html=_INTERSTITIAL_HTML
    )
    assert result.kind is PageType.CAPTCHA_BLOCK


def test_datadome_script_on_content_page_is_clear_with_vendor_annotation():
    result = assess_page(
        url="https://boards.example.com/jobs/7", title="", html=_DATADOME_HTML
    )
    assert result.challenge == "clear"
    assert result.kind is not PageType.CAPTCHA_BLOCK
    assert "datadome" in result.vendors


def test_unknown_when_nothing_matches():
    result = assess_page(url="https://example.com/", title="Hi", html=_PLAIN_HTML)
    assert result.kind is PageType.UNKNOWN
    assert result.confidence == 0.0
    assert "no-structural-verdict" in result.signals


_AGREEMENT_FIXTURES = [
    ("https://www.ziprecruiter.example/jobs/x", "Just a moment...", _INTERSTITIAL_HTML),
    ("https://www.linkedin.example/jobs/view/1", "Backend Engineer", _POSTING_HTML),
    ("https://uk.jobrapido.example/job/1", "Backend Engineer", _EMBEDDED_HTML),
    ("https://ats.example.com/xyz", "", _PASSWORD_FORM_HTML),
    ("https://ats.example.com/apply/1", "Apply", _FILLABLE_FORM_HTML),
    ("https://example.com/", "Hi", _PLAIN_HTML),
]


@pytest.mark.parametrize("url,title,html", _AGREEMENT_FIXTURES)
def test_discovery_and_application_agree_on_the_same_snapshot(url, title, html):
    """TEETH: the answer discovery acts on and the answer the application
    path acts on are computed by ONE engine and cannot drift apart."""
    page = assess_page(url=url, title=title, html=html)
    engine = assess_challenge(url=url, title=title, html=html)

    assert page.challenge == engine.verdict
    assert (page.kind is PageType.CAPTCHA_BLOCK) is (engine.verdict == "gated")
    assert (page.kind is PageType.LOGIN_REQUIRED) is assess_login_wall(url=url, html=html)

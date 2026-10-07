"""Teeth pins for the ONE challenge predicate (item 12A + follow-up).

Each fixture is built from a measured page shape (the 2026-09 triage of
dev_data/detector_samples and the probe_item12 run over the same 20 pages),
not from a keyword list. Tests never read dev_data/ — the shapes are
re-created synthetically here.
"""
from auto_apply.domain.services.challenge_assessment import (
    _PageProbe,
    assess_challenge,
    assess_login_wall,
)


def _posting_html() -> str:
    body_text = "Software Engineer role. Join our team. " * 40
    return (
        "<html><head><title>Registered Nurse</title>"
        "<script>var cfg = { captcha: 'recaptcha-site-key' };</script>"
        "</head><body>"
        "<form id='search'><input name='q'/></form>"
        "<form id='alert'><input name='email'/></form>"
        f"<p>{body_text}</p>"
        "<!-- recaptcha -->"
        "</body></html>"
    )


def test_rendered_posting_with_recaptcha_token_is_clear():
    """TEETH: rendered content, 2+ forms, one 'recaptcha' token in an inline
    script and a comment — NOT a challenge."""
    result = assess_challenge(
        url="https://www.linkedin.com/jobs/view/some-job-123",
        title="Registered Nurse",
        html=_posting_html(),
    )
    assert result.verdict == "clear"
    assert "page-content" in result.signals


def test_comment_and_script_tokens_are_never_matched():
    """The token only ever appeared in page data that is not rendered."""
    html = (
        "<html><body>"
        "<!-- <div class='g-recaptcha'></div> -->"
        "<script>var x = 'cf-turnstile';</script>"
        "<form><input name='a'/></form><form><input name='b'/></form>"
        f"<p>{'real posting text. ' * 60}</p>"
        "</body></html>"
    )
    result = assess_challenge(url="https://example.com/job/1", title="", html=html)
    assert result.verdict == "clear"


def test_interstitial_is_gated_whatever_its_title():
    """TEETH: Cloudflare-style interstitial — challenge markup, no form, no
    apply control — is gated in ANY language, including no title at all."""
    for title in (
        "Just a moment...",
        "Einen Moment bitte",
        "Un instant...",
        "",
    ):
        html = (
            f"<html><head><title>{title}</title>"
            '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js">'
            "</script></head><body>"
            '<input type="hidden" name="cf-turnstile-response" value=""/>'
            "<p>Checking your browser before continuing.</p>"
            "</body></html>"
        )
        result = assess_challenge(
            url="https://www.ziprecruiter.com/jobs/x", title=title, html=html
        )
        assert result.verdict == "gated", f"title={title!r} escaped the verdict"
        assert "no-page-content" in result.signals


def test_interstitial_with_boilerplate_text_is_gated():
    """TEETH (follow-up deliverable 1): the Glassdoor shape measured on the
    real pages — 0 forms, a cf-turnstile input, a challenge-platform script,
    a large inline script, and ~5k characters of non-script boilerplate in
    noscript and hidden elements. Text is not content; structure decides.
    Fails against the text-threshold verdict (read as 'embedded')."""
    boilerplate = "enable javascript and cookies to continue. " * 120
    big_script = "var payload = '" + "x" * 20000 + "';"
    html = (
        "<html><head><title>Just a moment...</title>"
        '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js">'
        "</script>"
        f"<script>{big_script}</script>"
        "</head><body>"
        '<input type="hidden" name="cf-turnstile-response" value=""/>'
        f"<noscript>{boilerplate}</noscript>"
        f"<div style='display:none'>{boilerplate}</div>"
        "</body></html>"
    )
    result = assess_challenge(
        url="https://www.glassdoor.example/job/1",
        title="Just a moment...",
        html=html,
    )
    assert result.verdict == "gated"
    assert "no-page-content" in result.signals


def test_script_bodies_never_count_as_visible_text():
    """TEETH (follow-up deliverable 2): the mutation that survived part A —
    counting <script> bodies as visible text — must kill this test."""
    probe = _PageProbe()
    probe.feed(
        "<html><body><script>"
        + "x" * 20000
        + "</script><p>hi</p></body></html>"
    )
    assert probe.visible_text_chars < 50


def test_rendered_recaptcha_widget_page_is_gated():
    """TEETH: a page whose main content IS a rendered reCAPTCHA — anchor
    iframe and widget div present, nothing else to fill."""
    html = (
        "<html><head><title>Verification</title></head><body>"
        '<div class="g-recaptcha" data-sitekey="x"></div>'
        '<iframe src="https://www.google.com/recaptcha/api2/anchor?k=x"></iframe>'
        "<p>Verify you are human.</p>"
        "</body></html>"
    )
    result = assess_challenge(
        url="https://example.com/verify", title="Verification", html=html
    )
    assert result.verdict == "gated"
    assert "challenge-iframe" in result.signals


def test_widget_inside_a_content_page_is_embedded_not_gated():
    """A reCAPTCHA widget inside a usable page (the jobrapido shape: 2
    forms, real text, anchor iframe) is EMBEDDED — proceed."""
    html = (
        "<html><head><title>Backend Engineer | Job Board</title></head><body>"
        "<form id='a'><input name='q'/></form>"
        "<form id='b'><input name='e'/></form>"
        f"<p>{'Mid Level Backend Engineer role details. ' * 40}</p>"
        '<div class="g-recaptcha" data-sitekey="x"></div>'
        '<iframe src="https://www.google.com/recaptcha/api2/anchor?k=x"></iframe>'
        "</body></html>"
    )
    result = assess_challenge(
        url="https://uk.jobrapido.com/job/1", title="Backend Engineer", html=html
    )
    assert result.verdict == "embedded"
    assert "challenge-iframe" in result.signals
    assert "page-content" in result.signals


def test_challenge_url_marker_is_gated_without_parsing():
    result = assess_challenge(
        url="https://www.google.com/sorry/index?q=x",
        title="",
        html="<html><body>whatever</body></html>",
    )
    assert result.verdict == "gated"
    assert result.signals == ("challenge-url",)


def test_merely_loaded_library_on_content_page_is_clear():
    """A recaptcha api.js script tag on a real posting: loaded, not presented."""
    html = (
        "<html><head>"
        '<script src="https://www.google.com/recaptcha/api.js"></script>'
        "</head><body>"
        "<form><input name='a'/></form><form><input name='b'/></form>"
        f"<p>{'real posting text. ' * 60}</p>"
        "</body></html>"
    )
    result = assess_challenge(url="https://example.com/job/2", title="", html=html)
    assert result.verdict == "clear"


def test_password_form_page_is_a_login_wall():
    html = (
        "<html><body>"
        "<form method='post'>"
        "<input name='user'/><input type='password' name='pw'/>"
        "</form>"
        "<p>Sign in to continue.</p>"
        "</body></html>"
    )
    assert assess_login_wall(url="https://ats.example.com/xyz", html=html) is True


def test_login_url_is_a_wall_without_parsing():
    assert (
        assess_login_wall(
            url="https://ats.example.com/account/login?next=/apply",
            html="<html><body></body></html>",
        )
        is True
    )


def test_registered_nurse_posting_is_not_a_login_wall():
    """TEETH: the title says 'register'; the page is a posting."""
    assert (
        assess_login_wall(
            url="https://boards.example.com/jobs/registered-nurse-123",
            html=_posting_html(),
        )
        is False
    )


def test_login_wall_markers_match_whole_path_segments_only():
    """TEETH (follow-up deliverable 5): '/register' inside
    '/registered-nurse-123' and '/auth' inside '/author' are not walls —
    the same substring class part A removed from the title. Real login
    paths still are walls."""
    posting = _posting_html()
    for url in (
        "https://boards.example.com/jobs/registered-nurse-123",
        "https://boards.example.com/author/jane",
    ):
        assert assess_login_wall(url=url, html=posting) is False, url
    for url in (
        "https://ats.example.com/login",
        "https://ats.example.com/users/sign_in",
    ):
        assert assess_login_wall(url=url, html="") is True, url


def test_interstitial_with_its_own_challenge_form_is_gated():
    """TEETH: a Cloudflare-shaped interstitial that carries its own
    <form id="challenge-form"> is still gated. Before this fix the challenge's
    form counted as page content and the verdict was "embedded"."""
    html = (
        "<html><head><title>Un instant...</title>"
        "<script src='/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1'>"
        "</script></head><body>"
        "<form id='challenge-form' action='/x?__cf_chl_f_tk=1' method='POST'>"
        "<input type='hidden' name='md'/></form>"
        "<div class='cf-turnstile'></div>"
        "<noscript>Enable JavaScript and cookies to continue</noscript>"
        "</body></html>"
    )
    result = assess_challenge(url="https://www.example.com/job/1", title="", html=html)
    assert result.verdict == "gated", result

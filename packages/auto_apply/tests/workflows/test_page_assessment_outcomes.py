"""Pins for the verdict's outcome kinds: SUCCESS_PAGE, ALREADY_APPLIED, CLOSED.

Fixtures are synthetic recreations of the measured shapes (a confirmation
page, a closed posting, a LinkedIn "you applied on" page, a posting whose
polite closing text defeated the retired raw-source scan). Tests never
read dev_data/.

Labels, honestly: against the pre-turn-2 tree these fail on ImportError or
on PageType lacking the members — weak evidence. The real teeth are the
misfire-class pins (weak posting language, "your application" on a form
page) and the deciding-signal pin: a confirmation verdict must say WHY.
"""
from __future__ import annotations

from auto_apply.domain.services.page_assessment import assess_page
from auto_apply.domain.types import PageType

_SUCCESS_HTML = (
    "<html><body><h1>Application submitted</h1>"
    "<p>Thank you for applying! Your application has been submitted. "
    "We will review it shortly.</p></body></html>"
)

_CLOSED_HTML = (
    "<html><body><p>This job is no longer accepting applications. "
    "Please browse our other openings.</p></body></html>"
)

_ALREADY_HTML = (
    "<html><body><p>You applied on 3 January 2026.</p></body></html>"
)

_WEAK_POSTING_HTML = (
    "<html><body>"
    "<form id='search'><input name='q'/></form>"
    f"<p>{'Great role at a great company. ' * 40}"
    "Thank you for your interest in this role. We'll be in touch. "
    "We'll review applications on a rolling basis.</p>"
    "</body></html>"
)

_FORM_HTML = (
    "<html><body><form>"
    "<label>Your application</label>"
    "<input name='first'/><input name='last'/><input name='email'/>"
    "</form></body></html>"
)

_JSON_LD = (
    '<script type="application/ld+json">'
    '{"@type":"JobPosting","title":"Backend Engineer"}'
    "</script>"
)


def test_success_page_kind_and_deciding_signal():
    """TEETH: a confirmation verdict must say WHICH signal decided it."""
    result = assess_page(
        url="https://ats.example.com/application/123/done",
        title="Application submitted",
        html=_SUCCESS_HTML,
    )
    assert result.kind is PageType.SUCCESS_PAGE
    assert any(
        signal.startswith("confirmation-phrase:") for signal in result.signals
    ), f"no deciding signal in {result.signals}"
    assert "confirmation-phrase:thank you for applying" in result.signals


def test_confirmation_url_marker_decides():
    result = assess_page(
        url="https://boards.greenhouse.example/acme/jobs/confirmations/123",
        title="",
        html="<html><body><p>Done.</p></body></html>",
    )
    assert result.kind is PageType.SUCCESS_PAGE
    assert "confirmation-url:/confirmations/" in result.signals
    assert result.confidence == 0.90


def test_weak_posting_language_is_not_a_confirmation():
    """TEETH: 'thank you for your interest', 'we'll be in touch' and
    'we'll review' are posting text, not a confirmation."""
    result = assess_page(
        url="https://boards.example.com/jobs/1", title="", html=_WEAK_POSTING_HTML
    )
    assert result.kind is not PageType.SUCCESS_PAGE
    assert not any(s.startswith("confirmation-") for s in result.signals)


def test_your_application_on_a_form_page_is_not_success():
    """TEETH: the retired raw-source scan read this as SUBMITTED (0.85)."""
    result = assess_page(
        url="https://ats.example.com/apply/1", title="Apply", html=_FORM_HTML
    )
    assert result.kind is PageType.APPLICATION_FORM


def test_already_applied_page():
    result = assess_page(
        url="https://www.linkedin.example/jobs/view/1", title="", html=_ALREADY_HTML
    )
    assert result.kind is PageType.ALREADY_APPLIED
    assert any(
        signal.startswith("already-applied-phrase:") for signal in result.signals
    )


def test_closed_posting_page():
    result = assess_page(
        url="https://boards.example.com/jobs/9", title="", html=_CLOSED_HTML
    )
    assert result.kind is PageType.CLOSED
    assert any(signal.startswith("closed-phrase:") for signal in result.signals)


def test_closed_outranks_json_ld():
    """A closed posting still carrying its schema must not read as live."""
    html = _CLOSED_HTML.replace("</body>", _JSON_LD + "</body>")
    result = assess_page(url="https://boards.example.com/jobs/9", title="", html=html)
    assert result.kind is PageType.CLOSED


def test_already_applied_outranks_fillable_form():
    html = _FORM_HTML.replace("<label>", "<p>You applied on 3 January 2026.</p><label>")
    result = assess_page(url="https://ats.example.com/apply/1", title="", html=html)
    assert result.kind is PageType.ALREADY_APPLIED


def test_fillable_form_outranks_confirmation_text():
    html = _FORM_HTML.replace(
        "<label>", "<p>Thank you for applying in advance.</p><label>"
    )
    result = assess_page(url="https://ats.example.com/apply/1", title="", html=html)
    assert result.kind is PageType.APPLICATION_FORM

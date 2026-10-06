"""Agreement pins: dom_observer and MathPerceptionAdapter must answer what
the ONE verdict answers on the same snapshot.

The adapters delegate page identity (success, closed, already-applied,
login wall) to domain/services/page_assessment.assess_page; these pins
exist so the delegation cannot silently regress into a local answer again.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from auto_apply.adapters.secondary.interaction.dom_observer import DOMObserver
from auto_apply.adapters.secondary.perception.math_perception_adapter import (
    MathPerceptionAdapter,
)
from auto_apply.domain.applications.fsm.states import ApplicationState
from auto_apply.domain.services.page_assessment import assess_page
from auto_apply.domain.types import PageType

_SUCCESS_HTML = (
    "<html><body><p>Thank you for applying! "
    "Your application has been submitted.</p></body></html>"
)
_CLOSED_HTML = (
    "<html><body><p>This job is no longer accepting applications.</p></body></html>"
)
_ALREADY_HTML = "<html><body><p>You applied on 3 January 2026.</p></body></html>"
_PLAIN_HTML = (
    "<html><body><p>Hello world, a perfectly ordinary page.</p></body></html>"
)


def _browser(html: str, url: str = "https://ats.example.com/x") -> MagicMock:
    browser = MagicMock()
    browser.current_url = url
    browser.title = ""
    browser.page_source = html
    browser.execute_script.return_value = ""
    browser.find_elements.return_value = []
    return browser


def test_success_agreement():
    browser = _browser(_SUCCESS_HTML)
    assert assess_page(url=browser.current_url, title="", html=_SUCCESS_HTML).kind is PageType.SUCCESS_PAGE
    observer = DOMObserver(browser=browser)
    assert observer._detect_success(browser) is True
    assert MathPerceptionAdapter(browser).get_current_state() is ApplicationState.SUCCESS


def test_closed_agreement():
    browser = _browser(_CLOSED_HTML)
    assert assess_page(url=browser.current_url, title="", html=_CLOSED_HTML).kind is PageType.CLOSED
    observer = DOMObserver(browser=browser)
    assert observer._detect_closed(browser) is True
    assert MathPerceptionAdapter(browser).get_current_state() is ApplicationState.CLOSED


def test_already_applied_agreement():
    browser = _browser(_ALREADY_HTML)
    assert assess_page(url=browser.current_url, title="", html=_ALREADY_HTML).kind is PageType.ALREADY_APPLIED
    observer = DOMObserver(browser=browser)
    assert observer._detect_already_applied() is True
    assert MathPerceptionAdapter(browser).get_current_state() is ApplicationState.ALREADY_APPLIED


def test_plain_page_agreement():
    browser = _browser(_PLAIN_HTML)
    assert assess_page(url=browser.current_url, title="", html=_PLAIN_HTML).kind is PageType.UNKNOWN
    observer = DOMObserver(browser=browser)
    assert observer._detect_success(browser) is False
    assert observer._detect_closed(browser) is False
    assert observer._detect_already_applied() is False
    assert MathPerceptionAdapter(browser).get_current_state() is ApplicationState.UNKNOWN

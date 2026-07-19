"""Unit tests for adapters/secondary/perception/math_perception_adapter.py.

MathDOMAdapter is mocked (via patch) to control the DOMNode trees returned,
so these tests verify the UIModel translation logic in isolation.
"""

from unittest.mock import MagicMock, patch

import pytest

from auto_apply.adapters.secondary.perception.math_perception_adapter import (
    MathPerceptionAdapter,
    _classify_node,
    _is_interactable,
    _is_visible,
)
from auto_apply.domain.applications.fsm.states import ApplicationState
from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.models.ui import UIElementType

_ADAPTER_PATH = "auto_apply.adapters.secondary.perception.math_perception_adapter.MathDOMAdapter"


def _patched_adapter(tree, url="https://example.com", title="Test Page"):
    mock_dom = MagicMock()
    mock_dom.extract_full_dom_tree.return_value = tree
    mock_dom.get_current_url.return_value = url
    mock_dom.get_page_title.return_value = title
    return mock_dom


# ── _is_visible helper ────────────────────────────────────────────────────────

def test_is_visible_with_positive_dimensions():
    node = DOMNode(tag="input", geometry=Geometry(x=0, y=0, width=100, height=50))
    assert _is_visible(node)


def test_is_visible_zero_width():
    node = DOMNode(tag="input", geometry=Geometry(x=0, y=0, width=0, height=50))
    assert not _is_visible(node)


def test_is_visible_zero_height():
    node = DOMNode(tag="input", geometry=Geometry(x=0, y=0, width=100, height=0))
    assert not _is_visible(node)


def test_is_visible_no_geometry():
    node = DOMNode(tag="input")
    assert not _is_visible(node)


# ── _is_interactable helper ───────────────────────────────────────────────────

@pytest.mark.parametrize("tag", ["input", "textarea", "select", "button", "a"])
def test_is_interactable_by_tag(tag):
    node = DOMNode(tag=tag)
    assert _is_interactable(node)


@pytest.mark.parametrize("role", ["button", "checkbox", "radio", "textbox", "combobox", "listbox", "link"])
def test_is_interactable_by_role(role):
    node = DOMNode(tag="div", attributes=(("role", role),))
    assert _is_interactable(node)


def test_non_interactable_div():
    node = DOMNode(tag="div")
    assert not _is_interactable(node)


# ── _classify_node helper ─────────────────────────────────────────────────────

def test_classify_select_tag():
    node = DOMNode(tag="select")
    assert _classify_node(node) == UIElementType.SELECT


def test_classify_checkbox_input():
    node = DOMNode(tag="input", attributes=(("type", "checkbox"),))
    assert _classify_node(node) == UIElementType.CHECKBOX


def test_classify_radio_input():
    node = DOMNode(tag="input", attributes=(("type", "radio"),))
    assert _classify_node(node) == UIElementType.RADIO


def test_classify_file_input():
    node = DOMNode(tag="input", attributes=(("type", "file"),))
    assert _classify_node(node) == UIElementType.FILE_UPLOAD


def test_classify_textarea():
    node = DOMNode(tag="textarea")
    assert _classify_node(node) == UIElementType.TEXT_AREA


def test_classify_button():
    node = DOMNode(tag="button")
    assert _classify_node(node) == UIElementType.BUTTON


def test_classify_link():
    node = DOMNode(tag="a")
    assert _classify_node(node) == UIElementType.LINK


def test_classify_text_input_fallback():
    node = DOMNode(tag="input", attributes=(("type", "text"),))
    assert _classify_node(node) == UIElementType.TEXT_INPUT


# ── scan_page ────────────────────────────────────────────────────────────────

def test_scan_page_empty_dom():
    browser = MagicMock()
    with patch(_ADAPTER_PATH, return_value=_patched_adapter(None)):
        adapter = MathPerceptionAdapter(browser)
        model = adapter.scan_page()
    assert model.elements == []


def test_scan_page_collects_visible_input():
    visible_input = DOMNode(
        tag="input",
        attributes=(("type", "text"), ("name", "email"), ("placeholder", "Email")),
        geometry=Geometry(x=100, y=100, width=200, height=40),
        depth=1,
    )
    root = DOMNode(tag="body", depth=0, children=(visible_input,))

    browser = MagicMock()
    with patch(_ADAPTER_PATH, return_value=_patched_adapter(root)):
        adapter = MathPerceptionAdapter(browser)
        model = adapter.scan_page()

    assert len(model.elements) == 1
    assert model.elements[0].name == "email"
    assert model.elements[0].element_type == UIElementType.TEXT_INPUT


def test_scan_page_skips_hidden_element():
    hidden = DOMNode(
        tag="input",
        attributes=(("type", "text"), ("name", "trap")),
        geometry=Geometry(x=0, y=0, width=0, height=0),
        depth=1,
    )
    root = DOMNode(tag="body", depth=0, children=(hidden,))

    browser = MagicMock()
    with patch(_ADAPTER_PATH, return_value=_patched_adapter(root)):
        adapter = MathPerceptionAdapter(browser)
        model = adapter.scan_page()

    assert model.elements == []


def test_scan_page_collects_multiple_elements():
    nodes = [
        DOMNode(
            tag="input",
            attributes=(("type", "text"), ("name", f"field_{i}"), ("placeholder", f"Field {i}")),
            geometry=Geometry(x=0, y=i * 50, width=200, height=40),
            depth=1,
        )
        for i in range(3)
    ]
    root = DOMNode(tag="body", depth=0, children=tuple(nodes))

    browser = MagicMock()
    with patch(_ADAPTER_PATH, return_value=_patched_adapter(root)):
        adapter = MathPerceptionAdapter(browser)
        model = adapter.scan_page()

    assert len(model.elements) == 3


def test_scan_page_url_and_title_forwarded():
    root = DOMNode(tag="body", depth=0)
    browser = MagicMock()
    with patch(_ADAPTER_PATH, return_value=_patched_adapter(root, url="https://jobs.example.com", title="Apply Here")):
        adapter = MathPerceptionAdapter(browser)
        model = adapter.scan_page()

    assert model.url == "https://jobs.example.com"
    assert model.title == "Apply Here"


def test_scan_page_classifies_button_correctly():
    btn = DOMNode(
        tag="button",
        attributes=(("type", "submit"),),
        text="Submit",
        geometry=Geometry(x=200, y=300, width=100, height=40),
        depth=1,
    )
    root = DOMNode(tag="body", depth=0, children=(btn,))
    browser = MagicMock()
    with patch(_ADAPTER_PATH, return_value=_patched_adapter(root)):
        adapter = MathPerceptionAdapter(browser)
        model = adapter.scan_page()

    assert len(model.elements) == 1
    assert model.elements[0].element_type == UIElementType.BUTTON


# ── get_current_state ─────────────────────────────────────────────────────────

def test_get_current_state_success():
    browser = MagicMock()
    browser.execute_script.return_value = "Thank you for applying! Your application was submitted."
    browser.find_elements.return_value = []
    adapter = MathPerceptionAdapter(browser)
    state = adapter.get_current_state()
    assert state == ApplicationState.SUCCESS


def test_get_current_state_login_wall():
    browser = MagicMock()
    browser.execute_script.return_value = "Please sign in to continue your application."
    browser.find_elements.return_value = []
    adapter = MathPerceptionAdapter(browser)
    state = adapter.get_current_state()
    assert state == ApplicationState.LOGIN_WALL


def test_get_current_state_form_step_fallback():
    browser = MagicMock()
    browser.execute_script.return_value = "Fill out the form below."

    def _find_elements(by, selector):
        if "input" in selector or "textarea" in selector:
            return [MagicMock()]
        return []

    browser.find_elements.side_effect = _find_elements
    adapter = MathPerceptionAdapter(browser)
    state = adapter.get_current_state()
    assert state == ApplicationState.FORM_STEP


def test_get_current_state_unknown_fallback():
    browser = MagicMock()
    browser.execute_script.return_value = "Some generic page text."
    browser.find_elements.return_value = []
    adapter = MathPerceptionAdapter(browser)
    state = adapter.get_current_state()
    assert state == ApplicationState.UNKNOWN


def test_get_current_state_exception_returns_unknown():
    browser = MagicMock()
    browser.execute_script.side_effect = Exception("driver crashed")
    adapter = MathPerceptionAdapter(browser)
    state = adapter.get_current_state()
    assert state == ApplicationState.UNKNOWN


# ── get_page_text ─────────────────────────────────────────────────────────────

def test_get_page_text_returns_inner_text():
    browser = MagicMock()
    browser.execute_script.return_value = "Senior Python Engineer\n5 years experience"
    adapter = MathPerceptionAdapter(browser)
    assert adapter.get_page_text() == "Senior Python Engineer\n5 years experience"


def test_get_page_text_none_returns_empty_string():
    browser = MagicMock()
    browser.execute_script.return_value = None
    adapter = MathPerceptionAdapter(browser)
    assert adapter.get_page_text() == ""


def test_get_page_text_exception_returns_empty_string():
    browser = MagicMock()
    browser.execute_script.side_effect = Exception("no body yet")
    adapter = MathPerceptionAdapter(browser)
    assert adapter.get_page_text() == ""
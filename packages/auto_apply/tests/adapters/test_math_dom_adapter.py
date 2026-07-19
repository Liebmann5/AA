"""Unit tests for adapters/secondary/perception/math_dom_adapter.py.

BrowserInterface is mocked; tests verify the DOMNode tree is built correctly
from the JSON data returned by the browser's execute_script call.
"""

from unittest.mock import MagicMock

import pytest

from auto_apply.adapters.secondary.perception.math_dom_adapter import MathDOMAdapter
from auto_apply.domain.models.math_dom import DOMNode, Geometry


def _make_browser(script_return=None, find_elements_return=None):
    browser = MagicMock()
    browser.execute_script.return_value = script_return
    browser.find_elements.return_value = find_elements_return or []
    browser.current_url = "https://example.com/jobs/apply"
    browser.title = "Apply Now"
    return browser


_SIMPLE_DOM = {
    "tag": "body",
    "attributes": {},
    "text": "",
    "geometry": {"x": 0, "y": 0, "width": 1280, "height": 800},
    "children": [
        {
            "tag": "div",
            "attributes": {"class": "container"},
            "text": "",
            "geometry": {"x": 10, "y": 10, "width": 1000, "height": 500},
            "children": [
                {
                    "tag": "input",
                    "attributes": {"type": "text", "name": "email"},
                    "text": "",
                    "geometry": {"x": 50, "y": 50, "width": 300, "height": 40},
                    "children": [],
                }
            ],
        }
    ],
}


# ── extract_full_dom_tree ─────────────────────────────────────────────────────

def test_extract_returns_root_node():
    browser = _make_browser(script_return=_SIMPLE_DOM)
    adapter = MathDOMAdapter(browser, max_depth=10)
    root = adapter.extract_full_dom_tree()
    assert root is not None
    assert root.tag == "body"


def test_extract_root_depth_is_zero():
    browser = _make_browser(script_return=_SIMPLE_DOM)
    adapter = MathDOMAdapter(browser, max_depth=10)
    root = adapter.extract_full_dom_tree()
    assert root.depth == 0


def test_extract_child_depth_increments():
    browser = _make_browser(script_return=_SIMPLE_DOM)
    adapter = MathDOMAdapter(browser, max_depth=10)
    root = adapter.extract_full_dom_tree()
    container = root.children[0]
    assert container.depth == 1
    input_node = container.children[0]
    assert input_node.depth == 2


def test_extract_preserves_tag_names():
    browser = _make_browser(script_return=_SIMPLE_DOM)
    adapter = MathDOMAdapter(browser, max_depth=10)
    root = adapter.extract_full_dom_tree()
    tags = [n.tag for n in root.iter_nodes()]
    assert "body" in tags
    assert "div" in tags
    assert "input" in tags


def test_extract_preserves_attributes():
    browser = _make_browser(script_return=_SIMPLE_DOM)
    adapter = MathDOMAdapter(browser, max_depth=10)
    root = adapter.extract_full_dom_tree()
    input_node = root.children[0].children[0]
    assert input_node.get_attribute("type") == "text"
    assert input_node.get_attribute("name") == "email"


def test_extract_geometry_set_correctly():
    browser = _make_browser(script_return=_SIMPLE_DOM)
    adapter = MathDOMAdapter(browser, max_depth=10)
    root = adapter.extract_full_dom_tree()
    assert root.geometry is not None
    assert root.geometry.width == pytest.approx(1280.0)
    assert root.geometry.height == pytest.approx(800.0)


def test_extract_no_geometry_when_absent():
    dom = {
        "tag": "body",
        "attributes": {},
        "text": "",
        "geometry": None,
        "children": [],
    }
    browser = _make_browser(script_return=dom)
    adapter = MathDOMAdapter(browser, max_depth=10)
    root = adapter.extract_full_dom_tree()
    assert root is not None
    assert root.geometry is None


def test_extract_returns_none_when_script_returns_none():
    browser = _make_browser(script_return=None)
    adapter = MathDOMAdapter(browser, max_depth=10)
    root = adapter.extract_full_dom_tree()
    assert root is None


def test_extract_returns_none_on_exception():
    browser = MagicMock()
    browser.execute_script.side_effect = Exception("JS execution error")
    browser.find_elements.return_value = []
    adapter = MathDOMAdapter(browser, max_depth=10)
    root = adapter.extract_full_dom_tree()
    assert root is None


def test_extract_calls_execute_script_once():
    browser = _make_browser(script_return=_SIMPLE_DOM)
    adapter = MathDOMAdapter(browser, max_depth=10)
    adapter.extract_full_dom_tree()
    browser.execute_script.assert_called_once()


# ── _stitch_iframes — ordering guard ──────────────────────────────────────────

def test_stitch_iframes_skips_on_count_mismatch():
    browser = _make_browser()
    browser.find_elements.return_value = [MagicMock(), MagicMock()]
    adapter = MathDOMAdapter(browser)

    iframe_node = DOMNode(tag="iframe", geometry=Geometry(0, 0, 300, 200), depth=1)
    root = DOMNode(tag="body", depth=0, children=(iframe_node,))

    result = adapter._stitch_iframes(root)

    assert result is root
    browser.switch_to_iframe.assert_not_called()


def test_extract_nested_tree_structure():
    dom = {
        "tag": "body",
        "attributes": {},
        "text": "",
        "geometry": {"x": 0, "y": 0, "width": 1000, "height": 600},
        "children": [
            {
                "tag": "form",
                "attributes": {},
                "text": "",
                "geometry": {"x": 10, "y": 10, "width": 500, "height": 300},
                "children": [
                    {"tag": "label", "attributes": {}, "text": "Name", "geometry": None, "children": []},
                    {"tag": "input", "attributes": {"name": "name"}, "text": "", "geometry": {"x": 10, "y": 50, "width": 200, "height": 30}, "children": []},
                ],
            }
        ],
    }
    browser = _make_browser(script_return=dom)
    adapter = MathDOMAdapter(browser, max_depth=10)
    root = adapter.extract_full_dom_tree()
    assert root.tag == "body"
    form = root.children[0]
    assert form.tag == "form"
    assert len(form.children) == 2


# ── get_current_url / get_page_title ─────────────────────────────────────────

def test_get_current_url():
    browser = _make_browser(script_return=_SIMPLE_DOM)
    adapter = MathDOMAdapter(browser)
    assert adapter.get_current_url() == "https://example.com/jobs/apply"


def test_get_page_title():
    browser = _make_browser(script_return=_SIMPLE_DOM)
    adapter = MathDOMAdapter(browser)
    assert adapter.get_page_title() == "Apply Now"


def test_get_current_url_exception_returns_empty():
    from unittest.mock import PropertyMock
    browser = MagicMock()
    type(browser).current_url = PropertyMock(side_effect=Exception("driver died"))
    adapter = MathDOMAdapter(browser)
    url = adapter.get_current_url()
    assert url == ""
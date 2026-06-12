"""Unit tests for adapters/secondary/perception/bs4_adapter.py.

The HTTPClientPort is mocked so no real network I/O occurs.
Tests cover navigate, scan_page, get_current_state, and extract_full_dom_tree.
"""

from unittest.mock import MagicMock

import pytest

from auto_apply.adapters.secondary.perception.bs4_adapter import (
    BS4PerceptionAdapter,
    _classify_element,
)
from auto_apply.domain.applications.fsm.states import ApplicationState
from auto_apply.domain.models.ui import UIElementType
from auto_apply.domain.ports.http_client_port import HTTPResponse


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _http_client(html: str = "", url: str = "https://example.com", status: int = 200) -> MagicMock:
    client = MagicMock()
    client.get.return_value = HTTPResponse(status_code=status, text=html, url=url)
    return client


def _adapter(html: str = "", url: str = "https://example.com", title: str = "Test") -> BS4PerceptionAdapter:
    """Returns an adapter whose internal state is pre-set (skips real navigate call)."""
    adapter = BS4PerceptionAdapter(_http_client())
    adapter._current_html = html
    adapter._current_url = url
    adapter._current_title = title
    return adapter


# ─────────────────────────────────────────────────────────────────────────────
# _classify_element
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tag,type_attr,role,expected", [
    ("select", "", "", UIElementType.SELECT),
    ("div", "", "listbox", UIElementType.SELECT),
    ("input", "checkbox", "", UIElementType.CHECKBOX),
    ("input", "radio", "", UIElementType.RADIO),
    ("input", "file", "", UIElementType.FILE_UPLOAD),
    ("textarea", "", "", UIElementType.TEXT_AREA),
    ("div", "", "textbox", UIElementType.TEXT_AREA),
    ("button", "", "", UIElementType.BUTTON),
    ("input", "submit", "", UIElementType.BUTTON),
    ("a", "", "", UIElementType.LINK),
    ("input", "text", "", UIElementType.TEXT_INPUT),
    ("input", "", "", UIElementType.TEXT_INPUT),
])
def test_classify_element(tag, type_attr, role, expected):
    assert _classify_element(tag, type_attr, role) == expected


# ─────────────────────────────────────────────────────────────────────────────
# navigate
# ─────────────────────────────────────────────────────────────────────────────

def test_navigate_stores_html_and_title():
    html = "<html><head><title>Apply Now</title></head><body></body></html>"
    adapter = BS4PerceptionAdapter(_http_client(html=html, url="https://jobs.example.com"))
    adapter.navigate("https://jobs.example.com")
    assert adapter._current_url == "https://jobs.example.com"
    assert adapter._current_title == "Apply Now"
    assert adapter._current_html == html


def test_navigate_http_error_clears_title():
    adapter = BS4PerceptionAdapter(_http_client(html="", status=404, url="https://example.com"))
    adapter.navigate("https://example.com/404")
    assert adapter._current_title == ""


def test_navigate_uses_final_redirect_url():
    client = MagicMock()
    client.get.return_value = HTTPResponse(
        status_code=200, text="<title>Redirected</title>", url="https://final.example.com"
    )
    adapter = BS4PerceptionAdapter(client)
    adapter.navigate("https://original.example.com")
    assert adapter._current_url == "https://final.example.com"


# ─────────────────────────────────────────────────────────────────────────────
# scan_page — element discovery
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_page_empty_html_returns_empty_model():
    model = _adapter("").scan_page()
    assert model.elements == []


def test_scan_page_url_and_title_forwarded():
    model = _adapter("", url="https://jobs.acme.com", title="Apply Here").scan_page()
    assert model.url == "https://jobs.acme.com"
    assert model.title == "Apply Here"


def test_scan_page_discovers_text_input():
    html = '<form><input type="text" name="email" placeholder="Email"/></form>'
    model = _adapter(html).scan_page()
    assert len(model.elements) == 1
    assert model.elements[0].element_type == UIElementType.TEXT_INPUT
    assert model.elements[0].name == "email"


def test_scan_page_discovers_textarea():
    html = '<form><textarea name="cover_letter"></textarea></form>'
    model = _adapter(html).scan_page()
    assert len(model.elements) == 1
    assert model.elements[0].element_type == UIElementType.TEXT_AREA


def test_scan_page_discovers_select():
    html = '<form><select name="country"><option>US</option><option>CA</option></select></form>'
    model = _adapter(html).scan_page()
    assert len(model.elements) == 1
    assert model.elements[0].element_type == UIElementType.SELECT
    assert model.elements[0].options == ["US", "CA"]


def test_scan_page_discovers_checkbox():
    html = '<form><input type="checkbox" name="terms"/></form>'
    model = _adapter(html).scan_page()
    assert len(model.elements) == 1
    assert model.elements[0].element_type == UIElementType.CHECKBOX


def test_scan_page_discovers_radio():
    html = '<form><input type="radio" name="gender" value="M"/></form>'
    model = _adapter(html).scan_page()
    assert len(model.elements) == 1
    assert model.elements[0].element_type == UIElementType.RADIO


def test_scan_page_discovers_file_input():
    html = '<form><input type="file" name="resume"/></form>'
    model = _adapter(html).scan_page()
    assert len(model.elements) == 1
    assert model.elements[0].element_type == UIElementType.FILE_UPLOAD


def test_scan_page_discovers_button():
    html = '<form><button type="submit">Submit Application</button></form>'
    model = _adapter(html).scan_page()
    assert len(model.elements) == 1
    assert model.elements[0].element_type == UIElementType.BUTTON


def test_scan_page_skips_hidden_input():
    html = '<form><input type="hidden" name="csrf_token" value="abc"/></form>'
    model = _adapter(html).scan_page()
    assert model.elements == []


def test_scan_page_skips_submit_input():
    # type="submit" as <input> (not <button>) — should also be skipped.
    html = '<form><input type="submit" value="Apply"/></form>'
    model = _adapter(html).scan_page()
    assert model.elements == []


def test_scan_page_is_required_attribute():
    html = '<form><input type="text" name="first_name" required/></form>'
    model = _adapter(html).scan_page()
    assert model.elements[0].is_required is True


def test_scan_page_not_required_by_default():
    html = '<form><input type="text" name="middle_name"/></form>'
    model = _adapter(html).scan_page()
    assert model.elements[0].is_required is False


def test_scan_page_multiple_elements():
    html = """
    <form>
        <input type="text" name="first"/>
        <input type="text" name="last"/>
        <select name="country"><option>US</option></select>
        <button>Submit</button>
    </form>
    """
    model = _adapter(html).scan_page()
    assert len(model.elements) == 4


# ─────────────────────────────────────────────────────────────────────────────
# scan_page — label resolution
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_page_resolves_aria_label():
    html = '<input type="text" name="q" aria-label="Search jobs"/>'
    model = _adapter(html).scan_page()
    assert model.elements[0].label == "Search jobs"


def test_scan_page_resolves_aria_labelledby():
    html = """
    <span id="lbl">Full Name</span>
    <input type="text" name="fullname" aria-labelledby="lbl"/>
    """
    model = _adapter(html).scan_page()
    assert model.elements[0].label == "Full Name"


def test_scan_page_resolves_label_for():
    html = """
    <label for="email_input">Email Address</label>
    <input type="email" id="email_input" name="email"/>
    """
    model = _adapter(html).scan_page()
    assert model.elements[0].label == "Email Address"


def test_scan_page_resolves_ancestor_label():
    html = """
    <label>Phone Number <input type="tel" name="phone"/></label>
    """
    model = _adapter(html).scan_page()
    assert "Phone Number" in (model.elements[0].label or "")


def test_scan_page_resolves_placeholder_fallback():
    html = '<input type="text" name="city" placeholder="City"/>'
    model = _adapter(html).scan_page()
    assert model.elements[0].label == "City"


def test_scan_page_no_label_returns_none():
    html = '<input type="text" name="mystery"/>'
    model = _adapter(html).scan_page()
    assert model.elements[0].label is None


# ─────────────────────────────────────────────────────────────────────────────
# get_current_state
# ─────────────────────────────────────────────────────────────────────────────

def test_get_current_state_empty_html_returns_unknown():
    assert _adapter("").get_current_state() == ApplicationState.UNKNOWN


@pytest.mark.parametrize("phrase,expected", [
    ("thank you for applying", ApplicationState.SUCCESS),
    ("you already applied", ApplicationState.ALREADY_APPLIED),
    ("no longer accepting", ApplicationState.CLOSED),
    ("sign in to apply", ApplicationState.LOGIN_WALL),
    ("upload resume", ApplicationState.UPLOAD_STEP),
    ("review your application", ApplicationState.REVIEW_STEP),
    ("browse all jobs", ApplicationState.REDIRECT_TO_CAREERS_PAGE),
    ("easy apply", ApplicationState.INITIAL_START),
])
def test_get_current_state_keyword_detection(phrase, expected):
    html = f"<p>{phrase}</p>"
    assert _adapter(html).get_current_state() == expected


def test_get_current_state_redirect_many_job_cards():
    cards = "".join(f'<div data-job-id="{i}">Job {i}</div>' for i in range(5))
    html = f"<body>{cards}</body>"
    assert _adapter(html).get_current_state() == ApplicationState.REDIRECT_TO_LIST


def test_get_current_state_redirect_many_apply_links():
    links = "".join(f'<a href="/jobs/{i}">Apply</a>' for i in range(5))
    html = f"<body>{links}</body>"
    assert _adapter(html).get_current_state() == ApplicationState.REDIRECT_TO_LIST


def test_get_current_state_modal_open():
    # Content must not match any keyword rule (keyword scan runs first).
    html = '<div role="dialog"><p>Please confirm your details.</p></div>'
    assert _adapter(html).get_current_state() == ApplicationState.MODAL_OPEN


def test_get_current_state_form_step_fallback():
    html = "<form><input type='text' name='q'/></form>"
    assert _adapter(html).get_current_state() == ApplicationState.FORM_STEP


def test_get_current_state_unknown_plain_page():
    html = "<html><body><p>Nothing to see here.</p></body></html>"
    assert _adapter(html).get_current_state() == ApplicationState.UNKNOWN


# ─────────────────────────────────────────────────────────────────────────────
# extract_full_dom_tree
# ─────────────────────────────────────────────────────────────────────────────

def test_extract_full_dom_tree_returns_soup_object():
    html = "<html><body><p>Hello</p></body></html>"
    adapter = _adapter(html)
    tree = adapter.extract_full_dom_tree()
    assert tree is not None
    assert tree.find("p") is not None


def test_extract_full_dom_tree_returns_none_when_empty():
    adapter = _adapter("")
    assert adapter.extract_full_dom_tree() is None


# ─────────────────────────────────────────────────────────────────────────────
# get_page_text
# ─────────────────────────────────────────────────────────────────────────────

def test_get_page_text_empty_before_navigate():
    assert _adapter("").get_page_text() == ""


def test_get_page_text_returns_visible_text():
    html = "<html><body><h1>Senior Python Engineer</h1><p>5 years experience</p></body></html>"
    text = _adapter(html).get_page_text()
    assert "Senior Python Engineer" in text
    assert "5 years experience" in text


def test_get_page_text_excludes_script_and_style():
    html = (
        "<html><body><script>track('x')</script>"
        "<style>.a{color:red}</style><p>Real content</p></body></html>"
    )
    text = _adapter(html).get_page_text()
    assert "Real content" in text
    assert "track" not in text
    assert "color:red" not in text


def test_get_page_text_offline_after_navigate():
    html = "<html><body><p>Job description body</p></body></html>"
    adapter = BS4PerceptionAdapter(_http_client(html=html, url="https://jobs.example.com"))
    adapter.navigate("https://jobs.example.com")
    assert "Job description body" in adapter.get_page_text()

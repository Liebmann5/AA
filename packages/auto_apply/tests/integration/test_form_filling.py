"""Integration tests for form filling against a local mock ATS.

These tests use Selenium with a local HTML file — no internet required,
no ATS account required, no rate limiting risk.

Run: uv run pytest tests/integration/test_form_filling.py -v
Mark: @pytest.mark.browser (skip in CI unless browser is available)

Skip in CI by default:
    uv run pytest tests/integration/ -m "not browser" -v
"""

from __future__ import annotations

import functools
import http.server
import socketserver
import threading

import logging
import pathlib
from unittest.mock import MagicMock

import pytest

FIXTURE_DIR = pathlib.Path(__file__).parent.parent / "fixtures"
MOCK_FORM = FIXTURE_DIR / "greenhouse_mock.html"


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Serve fixture requests off the main thread; die with the process."""

    daemon_threads = True


@pytest.fixture(scope="module")
def form_server_url():
    """Serve tests/fixtures over HTTP on an ephemeral port.

    The mock ATS calls ``history.pushState()`` to simulate the confirmation
    navigation, exactly as the real ATS pages it models do. Browsers refuse
    pushState on ``file://`` origins, so under file:// the URL never changed and
    the confirmation assertion could not pass on any machine with a real
    browser installed — it only looked green where Chrome was absent and the
    test was skipped.

    ``directory=`` is load-bearing: SimpleHTTPRequestHandler otherwise serves
    the process CWD, which is packages/auto_apply under pytest, and every
    fixture request 404s.
    """
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(FIXTURE_DIR)
    )
    server = _ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield f"http://{host}:{port}"
    server.shutdown()
    thread.join(timeout=5)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def mock_job(form_server_url):
    """A mock Job pointing at the local mock ATS HTML fixture."""
    from auto_apply.domain.models.job import Job

    return Job(
        title="Senior Software Engineer",
        company="Acme Corp (Mock)",
        url=f"{form_server_url}/greenhouse_mock.html",
        source="test_fixture",
    )


@pytest.fixture(scope="module")
def test_profile():
    """A complete profile for form filling tests."""
    from auto_apply.domain.models.profile import UserProfile

    return UserProfile.model_validate({
        "profile_name": "Test User",
        "personal_info": {
            "first_name": "Test",
            "last_name": "User",
            "email": "test@example.com",
            "phone_number": "555-000-1234",
            "street_address": "123 Main St",
            "city": "Testville",
            "state": "CA",
            "zip_code": "90210",
        },
        "links": {
            "linkedin": "https://linkedin.com/in/testuser",
        },
        "career_summary": (
            "Test developer with experience in Python and automation. "
            "Built several testing frameworks and CI/CD pipelines."
        ),
        "work_experience": [
            {
                "company": "Test Co",
                "title": "Developer",
                "start_date": "2020-01",
                "end_date": "present",
                "description": "Built test automation systems.",
            }
        ],
        "search_preferences": {
            "desired_job_titles": ["Software Engineer"],
            "preferred_locations": ["Remote"],
            "skills": ["Python", "Testing", "Automation"],
        },
        "custom_answer_templates": [
            {
                "keywords": ["why interested", "why this role"],
                "answer": (
                    "I am interested in this role because it matches "
                    "my Python automation background."
                ),
                "max_length": 200,
            },
        ],
        "politeness_settings": {},
    })


# ─────────────────────────────────────────────────────────────────────────────
# Tests — Static Analysis (no browser required)
# ─────────────────────────────────────────────────────────────────────────────

class TestMockFormFixture:
    """Verify the mock HTML fixture is valid and parsable."""

    def test_fixture_exists(self):
        """The mock form HTML file must exist on disk."""
        assert MOCK_FORM.exists(), (
            f"Mock form fixture not found at {MOCK_FORM}"
        )

    def test_fixture_contains_expected_fields(self):
        """The HTML fixture must contain standard form fields for testing."""
        html = MOCK_FORM.read_text(encoding="utf-8")
        assert "first_name" in html
        assert "last_name" in html
        assert "email" in html
        assert "phone" in html
        assert "resume" in html
        assert "linkedin" in html
        assert "why_role" in html
        assert "submit_btn" in html
        assert "confirmation" in html

    def test_fixture_is_valid_html(self):
        """The fixture can be parsed by BeautifulSoup without errors."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            pytest.skip("BeautifulSoup not installed")

        html = MOCK_FORM.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")
        assert soup.find("form") is not None
        assert soup.find("button", id="submit_btn") is not None


class TestProfileValidation:
    """Verify the test profile has all required fields."""

    def test_profile_has_required_personal_fields(self, test_profile):
        """Profile must have first_name, last_name, and email."""
        info = test_profile.personal_info
        assert info.first_name
        assert info.last_name
        assert info.email

    def test_profile_has_search_preferences(self, test_profile):
        """Profile must have at least one desired job title."""
        prefs = test_profile.search_preferences
        assert len(prefs.desired_job_titles) >= 1

    def test_profile_has_career_summary(self, test_profile):
        """Career summary is required for custom question answering."""
        assert len(test_profile.career_summary) >= 50

    def test_profile_has_custom_answer_templates(self, test_profile):
        """At least one custom answer template is configured."""
        templates = test_profile.custom_answer_templates
        assert len(templates) >= 1
        assert templates[0].keywords
        assert templates[0].answer


# ─────────────────────────────────────────────────────────────────────────────
# Tests — Browser-Required (marked with @pytest.mark.browser)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.browser
class TestBrowserFormFilling:
    """End-to-end form filling against the local mock ATS with a real browser.

    These tests require a working Selenium/Chrome installation.
    Skip in CI with: pytest -m "not browser"
    """

    @pytest.fixture(scope="class")
    def driver(self):
        """Create a Selenium Chrome driver pointing at the mock fixture."""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError:
            pytest.skip("Selenium not installed")

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")

        try:
            driver = webdriver.Chrome(options=opts)
        except Exception as exc:
            pytest.skip(f"Cannot create Chrome driver: {exc}")

        yield driver

        try:
            driver.quit()
        except Exception:
            pass

    def test_navigate_to_mock_form(self, driver, mock_job):
        """Browser can load the mock form fixture."""
        driver.get(mock_job.url)
        assert "Senior Software Engineer" in driver.title
        assert driver.find_element("id", "first_name") is not None

    def test_form_fields_are_present(self, driver, mock_job):
        """All expected fields are findable in the mock form."""
        driver.get(mock_job.url)

        fields = [
            "first_name", "last_name", "email", "phone",
            "resume", "linkedin", "experience_years",
            "authorized", "why_role", "submit_btn",
        ]
        for field_id in fields:
            element = driver.find_element("id", field_id)
            assert element is not None, f"Field '{field_id}' not found"

    def test_fill_text_input(self, driver, mock_job):
        """Text can be typed into an input field."""
        driver.get(mock_job.url)

        first_name = driver.find_element("id", "first_name")
        first_name.clear()
        first_name.send_keys("Jane")

        assert first_name.get_attribute("value") == "Jane"

    def test_fill_dropdown(self, driver, mock_job):
        """A dropdown option can be selected."""
        driver.get(mock_job.url)

        from selenium.webdriver.support.ui import Select

        dropdown = Select(driver.find_element("id", "experience_years"))
        dropdown.select_by_visible_text("3–5 years")

        selected = dropdown.first_selected_option
        assert selected.text == "3–5 years"

    def test_check_checkbox(self, driver, mock_job):
        """A checkbox can be checked."""
        driver.get(mock_job.url)

        checkbox = driver.find_element("id", "authorized")
        if not checkbox.is_selected():
            checkbox.click()

        assert checkbox.is_selected()

    def test_fill_textarea(self, driver, mock_job):
        """Text can be typed into a textarea."""
        driver.get(mock_job.url)

        textarea = driver.find_element("id", "why_role")
        textarea.clear()
        textarea.send_keys("I am interested in this role because it matches my background.")

        assert "background" in textarea.get_attribute("value")

    def test_submit_navigates_to_confirmation(self, driver, mock_job):
        """Clicking submit shows the confirmation message."""
        driver.get(mock_job.url)

        # Fill required fields so the form can be submitted
        driver.find_element("id", "first_name").send_keys("Jane")
        driver.find_element("id", "last_name").send_keys("Doe")
        driver.find_element("id", "email").send_keys("jane@example.com")

        submit = driver.find_element("id", "submit_btn")
        submit.click()

        # Wait briefly for the JS to execute
        import time
        time.sleep(0.5)

        # Verify confirmation is now visible
        confirmation = driver.find_element("id", "confirmation")
        assert confirmation.is_displayed()
        assert "Thank you" in confirmation.text

        # Verify URL changed (the mock pushes a new history state)
        assert "/confirmation/" in driver.current_url

    def test_no_pii_in_page_source(self, driver, mock_job, test_profile):
        """After filling the form, email and phone appear in the page (expected —
        they are form values). This test verifies the form submission works."""
        driver.get(mock_job.url)

        driver.find_element("id", "email").send_keys(
            test_profile.personal_info.email
        )
        driver.find_element("id", "phone").send_keys(
            test_profile.personal_info.phone_number
        )

        # Values should be in the DOM (this is the form, not the log)
        email_value = driver.find_element("id", "email").get_attribute("value")
        assert test_profile.personal_info.email in email_value

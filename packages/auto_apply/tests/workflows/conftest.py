"""Shared fixtures for workflow tests.

All fixtures use MagicMock objects to satisfy port contracts without touching
real browsers, databases, or network connections.
"""
import pytest
from unittest.mock import MagicMock

from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import (
    ApplicationPreferences,
    JobSearchPreferences,
    PersonalInfo,
    ProfessionalLinks,
    UserProfile,
)


# ─────────────────────────────────────────────────────────────────────────────
# Core domain fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_profile() -> UserProfile:
    """A minimal but fully valid UserProfile for tests."""
    return UserProfile.model_validate({
        "profile_name": "test-profile",
        "personal_info": {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane.doe@example.com",
            "phone_number": "555-0100",
            "street_address": "123 Main St",
            "city": "Anytown",
            "state": "CA",
            "zip_code": "90210",
        },
        "links": {},
        "career_summary": (
            "Experienced software engineer with 7 years of Python development, "
            "cloud infrastructure, and distributed systems background."
        ),
        "search_preferences": {
            "desired_job_titles": ["Software Engineer", "Backend Engineer"],
            "preferred_locations": ["Remote"],
            "skills": ["Python", "SQL", "Docker"],
        },
        "politeness_settings": {},
    })


@pytest.fixture
def sample_job() -> Job:
    """A minimal valid Job instance for tests."""
    return Job(
        title="Software Engineer",
        company="Acme Corp",
        url="https://acme.example.com/jobs/123",
        source="test",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Infrastructure mock fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_event_bus():
    """A MagicMock event bus with a capturing publish subscriber."""
    bus = MagicMock()
    bus.published_events = []

    def _capture_publish(event, payload=None):
        bus.published_events.append((event, payload))

    bus.publish.side_effect = _capture_publish
    return bus


@pytest.fixture
def mock_job_repo():
    """A MagicMock job repository."""
    repo = MagicMock()
    repo.add_job.return_value = None
    repo.save.return_value = None
    repo.mark_applied.return_value = None
    return repo


@pytest.fixture
def mock_task_queue():
    """A MagicMock work queue."""
    queue = MagicMock()
    queue.queue_task.return_value = None
    return queue


@pytest.fixture
def mock_text_matcher():
    """A MagicMock TextMatcher that returns sensible defaults."""
    matcher = MagicMock()
    matcher.get_similarity.return_value = 0.85
    matcher.find_best_match.return_value = ("Software Engineer", 0.85)
    matcher.extract_entities.return_value = {
        "skills": ["Python", "SQL"],
        "locations": ["Remote"],
        "organizations": [],
        "experience_years": ["3"],
    }
    matcher.split_sentences.return_value = ["Sample sentence."]
    matcher.load_skills_vocabulary.return_value = None
    return matcher


@pytest.fixture
def mock_perception_port():
    """A MagicMock perception port.

    The canonical text path is PerceptionPort.get_page_text(); the workflow
    reads the job description through it (not via scan_page/text_content).
    """
    port = MagicMock()
    port.get_page_text.return_value = (
        "Software Engineer at Acme Corp. Python SQL required. 3 years."
    )
    port.scan_page.return_value = MagicMock()
    port.navigate.return_value = None
    return port


@pytest.fixture
def mock_interaction_port():
    """A MagicMock interaction port."""
    port = MagicMock()
    port.click.return_value = None
    port.fill.return_value = None
    return port


@pytest.fixture
def mock_browser():
    """A MagicMock browser that satisfies BrowserInterface."""
    browser = MagicMock()
    browser.current_url = "https://acme.example.com/jobs/123"
    browser.page_source = "<html><body><form>...</form></body></html>"
    browser.get.return_value = None
    return browser

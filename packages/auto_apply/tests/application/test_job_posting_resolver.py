"""Unit tests for JobPostingResolver.

Verifies that the resolver correctly extracts title/company from a live browser
page, builds a fallback stub from URL analysis, and gracefully handles
navigation failures.
"""

from unittest.mock import MagicMock

import pytest

from auto_apply.application.services.job_posting_resolver import JobPostingResolver


def _make_mock_driver(title: str = "Software Engineer — Acme Corp") -> MagicMock:
    """Return a mocked BrowserInterface with a configurable title."""
    driver = MagicMock()
    driver.title = title
    return driver


class TestResolveWithBrowser:
    """Browser-based extraction tests."""

    def test_resolve_extracts_title_and_company_from_page(self):
        """Title is cleaned (suffix stripped) and company derived from URL."""
        driver = _make_mock_driver(title="Backend Engineer | TechCo")
        resolver = JobPostingResolver()

        job = resolver.resolve(
            url="https://jobs.techco.com/apply/12345",
            driver=driver,
        )

        assert job.title == "Backend Engineer"
        assert job.company == "Techco"          # domain: jobs.techco.com → Techco
        assert job.url == "https://jobs.techco.com/apply/12345"
        assert job.source == "user_direct_input"
        driver.get.assert_called_once_with("https://jobs.techco.com/apply/12345")

    def test_resolve_falls_back_to_stub_on_navigation_failure(self):
        """When driver.get raises, a stub Job is returned."""
        driver = _make_mock_driver()
        driver.get.side_effect = RuntimeError("boom")
        resolver = JobPostingResolver()

        job = resolver.resolve(
            url="https://example.com/jobs/special-role",
            driver=driver,
        )

        # Stub: domain = example, title_hint = "Special Role"
        assert job.company == "Example"
        assert job.title == "Special Role"
        assert job.url == "https://example.com/jobs/special-role"
        assert job.source == "user_direct_input"

    def test_resolve_handles_empty_title_after_navigation(self):
        """If page title is empty, default 'Job Opening' is used."""
        driver = _make_mock_driver(title="")
        resolver = JobPostingResolver()

        job = resolver.resolve(
            url="https://careers.acme.com/j/42",
            driver=driver,
        )
        assert job.title == "Job Opening"
        # "careers" is a generic ATS-subdomain prefix (same rule as
        # "jobs.techco.com" -> "Techco" above) — no employer is literally
        # named "Careers", so the resolver skips it in favor of the next
        # label.
        assert job.company == "Acme"

    def test_resolve_strips_multiple_ats_suffixes(self):
        """Only the text before the first separator is kept."""
        driver = _make_mock_driver(title="Data Engineer · BigCorp – Careers")
        resolver = JobPostingResolver()

        job = resolver.resolve(url="https://bigcorp.com/jobs/1", driver=driver)
        assert job.title == "Data Engineer"


class TestResolveWithoutBrowser:
    """Fallback-stub tests when no driver is available."""

    def test_resolve_stub_from_url_path(self):
        """Path segments become a title hint; company from domain."""
        resolver = JobPostingResolver()

        job = resolver.resolve(url="https://www.awesome-co.com/careers/software-developer")

        assert job.company == "Awesome-Co"
        assert job.title == "Software Developer"
        assert job.url == "https://www.awesome-co.com/careers/software-developer"
        assert job.source == "user_direct_input"

    def test_resolve_stub_drops_numeric_segments(self):
        """Numeric path parts like /123 are ignored for title hint."""
        resolver = JobPostingResolver()

        job = resolver.resolve(url="https://example.com/jobs/456/senior-analyst")

        # path_parts: ["jobs", "456", "senior-analyst"] → "Senior Analyst"
        assert job.title == "Senior Analyst"

    def test_resolve_stub_short_segments_ignored(self):
        """Segments <= 3 chars are dropped."""
        resolver = JobPostingResolver()

        job = resolver.resolve(url="https://example.com/go/ab/xyz/app/careers")

        # path_parts: "careers" (others too short or numeric)
        assert job.title == "Careers"

    def test_resolve_stub_empty_path_produces_job_opening(self):
        """When there is no usable path segment, title defaults."""
        resolver = JobPostingResolver()

        job = resolver.resolve(url="https://career.example.com")
        assert job.title == "Job Opening"
        # "career" is a generic ATS-subdomain prefix — skipped in favor of
        # the next label, same rule as "jobs.techco.com" -> "Techco".
        assert job.company == "Example"

    def test_resolve_stub_company_truncated_to_200_chars(self):
        """Company field is capped at 200 characters (just smoke test)."""
        resolver = JobPostingResolver()
        long_domain = "this-is-a-very-long-company-name.example.com"
        url = f"https://{long_domain}/jobs/analyst"
        job = resolver.resolve(url)
        assert len(job.company) <= 200
        assert job.company == "This-Is-A-Very-Long-Company-Name"  # .title() capitalisation


class TestEdgeCases:
    """Miscellaneous edge cases."""

    def test_resolve_returns_job_even_if_driver_is_none(self):
        """Resolver must never return None — fallback to stub."""
        resolver = JobPostingResolver()
        job = resolver.resolve(url="https://x.com", driver=None)
        assert job.company == "X"
        assert job.title == "Job Opening"  # no path segments

    def test_resolve_handles_url_with_query_string(self):
        resolver = JobPostingResolver()
        job = resolver.resolve(url="https://jobs.example.com/listing?ref=homepage")
        assert job.url == "https://jobs.example.com/listing?ref=homepage"
        # path is /listing, title hint = "Listing"
        assert job.title == "Listing"
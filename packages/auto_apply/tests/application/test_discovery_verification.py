"""The discovery verification harness must catch every class of bad output.

These pins ARE the "know, not hope" guarantee: they feed the verifier known-good
and known-bad job lists and assert it passes the good and flags the bad — missing
fields, malformed URLs, duplicates that slipped dedup, and counts over the cap.
If the verifier ever stops catching one of these, discovery could silently ship
garbage and these tests go red.
"""
from __future__ import annotations

import pytest

from auto_apply.application.services.auditing.discovery_verification import (
    DiscoveryVerificationError,
    DiscoveryVerifier,
)
from auto_apply.domain.models.job import Job


def _job(title="Engineer", company="Acme", url="https://acme.com/jobs/1", source="Google"):
    return Job(title=title, company=company, url=url, source=source)


def _clean(n=5):
    return [_job(url=f"https://acme.com/jobs/{i}") for i in range(n)]


# --- the good case -----------------------------------------------------------

def test_clean_list_passes():
    report = DiscoveryVerifier(max_results=30).verify(_clean())
    assert report.passed
    assert report.total_jobs == 5
    report.assert_valid()  # must not raise


def test_no_cap_skips_cap_check_only():
    # "cap" is the only name that may disappear when max_results is None.
    # The set is the assertion's proxy for that, so it grows when a check is
    # added — "chrome" arrived with the navigation check. The intent, and what
    # this pin still guards, is that no OTHER check is skipped along with cap.
    report = DiscoveryVerifier(max_results=None).verify(_clean())
    names = {c.name for c in report.checks}
    assert names == {"fields", "chrome", "dedup"}
    assert "cap" not in names
    assert report.passed


# --- field validity ----------------------------------------------------------

@pytest.mark.parametrize("bad", [
    _job(title=""),
    _job(title="   "),
    _job(company=""),
    _job(company="   "),
    _job(url=""),
    _job(url="not-a-url"),
    _job(url="ftp://acme.com/x"),
    _job(url="javascript:void(0)"),
])
def test_invalid_fields_are_flagged(bad):
    report = DiscoveryVerifier(max_results=30).verify(_clean() + [bad])
    assert not report.passed
    assert any(c.name == "fields" and not c.passed for c in report.checks)


def test_valid_https_and_http_pass():
    jobs = [_job(url="https://a.com/1"), _job(url="http://b.com/2")]
    assert DiscoveryVerifier().verify(jobs).passed


# --- deduplication -----------------------------------------------------------

def test_duplicate_url_is_flagged():
    report = DiscoveryVerifier().verify(_clean() + [_job(url="https://acme.com/jobs/0")])
    assert any(c.name == "dedup" and not c.passed for c in report.checks)


def test_duplicate_url_is_case_insensitive():
    jobs = [_job(url="https://Acme.com/JOBS/1"), _job(url="https://acme.com/jobs/1")]
    assert not DiscoveryVerifier().verify(jobs).passed


# --- cap ---------------------------------------------------------------------

def test_over_cap_is_flagged():
    report = DiscoveryVerifier(max_results=3).verify(_clean(5))
    assert any(c.name == "cap" and not c.passed for c in report.checks)


def test_exactly_at_cap_passes():
    assert DiscoveryVerifier(max_results=5).verify(_clean(5)).passed


# --- report surface ----------------------------------------------------------

def test_assert_valid_raises_with_details():
    report = DiscoveryVerifier(max_results=30).verify([_job(url="bad")])
    with pytest.raises(DiscoveryVerificationError) as exc:
        report.assert_valid()
    assert "fields" in str(exc.value)


def test_summary_names_verdict_and_count():
    summary = DiscoveryVerifier(max_results=30).verify(_clean(4)).summary()
    assert "PASS" in summary and "4 jobs" in summary


def test_empty_input_passes_trivially():
    report = DiscoveryVerifier(max_results=30).verify([])
    assert report.passed
    assert report.total_jobs == 0

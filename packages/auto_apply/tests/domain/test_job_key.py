"""Pins for the job key (P0-2): one identity per posting, any URL shape.

The host component is the full hostname (leading "www." folded), never the
registrable domain: requisition ids and careers paths are per-employer, and
the tenant lives in the subdomain. These fail without the module; the
tenant-collision pins fail with registrable-domain keying.
"""

from __future__ import annotations

from auto_apply.domain.models.job import Job
from auto_apply.domain.models.job_key import compute_job_key


def _job(url: str, **metadata) -> Job:
    return Job(
        title="Engineer",
        company="Acme",
        url=url,
        source="test",
        metadata=metadata,
    )


def test_identifier_from_structured_posting_wins_over_path():
    job = _job(
        "https://boards.example.io/acme/jobs/999",
        structured_posting={"identifier": "ABC-123", "source": "json-ld"},
    )
    key = compute_job_key(job)
    assert key.posting_id == "ABC-123"
    assert key.host == "boards.example.io"


def test_path_and_query_are_the_fallback_identity():
    key = compute_job_key(_job("https://boards.example.io/acme/jobs/999?x=1"))
    assert key.posting_id == "/acme/jobs/999?x=1"


def test_query_distinguishes_postings_sharing_a_path():
    a = compute_job_key(_job("https://example.com/viewjob?jk=abc"))
    b = compute_job_key(_job("https://example.com/viewjob?jk=def"))
    assert a.as_string != b.as_string


def test_tracking_only_difference_changes_the_key_documented_miss():
    """A tracking-only difference yields a second key — a miss, never a false
    block. The JSON-LD identifier (when the posting was read) is what joins
    the two shapes."""
    a = compute_job_key(_job("https://example.com/job/1?utm_source=a"))
    b = compute_job_key(_job("https://example.com/job/1?utm_source=b"))
    assert a.as_string != b.as_string


def test_wrapped_and_direct_urls_join_on_the_identifier():
    direct = _job(
        "https://boards.example.io/acme/jobs/123",
        structured_posting={"identifier": "J-1"},
    )
    wrapped = _job(
        "https://www.google.com/url?q=https%3A//boards.example.io/acme/jobs/123",
        structured_posting={"identifier": "J-1"},
    )
    assert compute_job_key(direct) == compute_job_key(wrapped)


def test_landed_url_beats_the_card_url():
    job = _job(
        "https://www.google.com/goto?url=opaque",
        landed_url="https://boards.example.io/acme/jobs/5",
    )
    assert compute_job_key(job).host == "boards.example.io"


def test_tenants_of_one_ats_host_never_join_on_a_shared_requisition():
    """Measured: two employers, one platform, one requisition number. Keying
    on the registrable domain joins them; the full hostname keeps them apart."""
    acme = _job(
        "https://acme.wd5.myworkdayjobs.com/en-US/x/job/Engineer_R-1001",
        structured_posting={"identifier": "R-1001"},
    )
    globex = _job(
        "https://globex.wd1.myworkdayjobs.com/en-US/y/job/Analyst_R-1001",
        structured_posting={"identifier": "R-1001"},
    )
    assert compute_job_key(acme) != compute_job_key(globex)


def test_tenants_of_one_ats_host_never_join_on_a_shared_path():
    """Measured: two employers, one careers path, no identifier. The tenant
    is the subdomain, and the subdomain is part of the key."""
    acme = compute_job_key(_job("https://acme.bamboohr.com/careers/12"))
    globex = compute_job_key(_job("https://globex.bamboohr.com/careers/12"))
    assert acme != globex


def test_a_leading_www_folds():
    a = compute_job_key(_job("https://www.example.com/job/1"))
    b = compute_job_key(_job("https://example.com/job/1"))
    assert a == b


def test_empty_url_never_raises():
    key = compute_job_key(_job(""))
    assert key.as_string  # a stable, if weak, identity


def test_malformed_url_never_raises():
    """An unterminated IPv6 literal escapes urlsplit; the key must not."""
    key = compute_job_key(_job("http://[::1/"))
    assert key.host == ""
    assert key.as_string  # stable, weak, and does not crash the dedup check

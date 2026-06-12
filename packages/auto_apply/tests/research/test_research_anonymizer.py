"""Unit tests for application/services/research/anonymizer.py — DataAnonymizer."""

import pytest

from auto_apply.application.services.research.anonymizer import DataAnonymizer


@pytest.fixture
def anon():
    return DataAnonymizer()


# ── _hash_value ───────────────────────────────────────────────────────────────

def test_hash_value_returns_string(anon):
    result = anon._hash_value("test_value")
    assert isinstance(result, str)


def test_hash_value_deterministic(anon):
    assert anon._hash_value("same_input") == anon._hash_value("same_input")


def test_hash_value_different_inputs(anon):
    assert anon._hash_value("alpha") != anon._hash_value("beta")


def test_hash_value_empty_returns_empty(anon):
    assert anon._hash_value("") == ""


def test_hash_value_has_hash_prefix(anon):
    result = anon._hash_value("any value")
    assert result.startswith("hash_")


# ── _mask_value ───────────────────────────────────────────────────────────────

def test_mask_value_without_format(anon):
    result = anon._mask_value("hello", preserve_format=False)
    assert result == "X" * 5


def test_mask_value_preserves_format(anon):
    result = anon._mask_value("555-123-4567", preserve_format=True)
    # Digits replaced with X, hyphens preserved
    assert "-" in result
    assert "5" not in result


def test_mask_value_caps_at_ten(anon):
    long_str = "A" * 50
    result = anon._mask_value(long_str, preserve_format=False)
    assert len(result) == 10


def test_mask_value_empty(anon):
    assert anon._mask_value("", preserve_format=False) == ""


# ── _genericize_value ─────────────────────────────────────────────────────────

def test_genericize_name_field(anon):
    # "company_name" contains "name" which matches before "company" in the if-elif chain
    assert anon._genericize_value("company_name", "Acme Corp") == "[GENERIC_NAME]"


def test_genericize_address_field(anon):
    assert anon._genericize_value("address", "123 Main St") == "[GENERIC_LOCATION]"


def test_genericize_other_field(anon):
    result = anon._genericize_value("some_field", "some value")
    assert result == "[GENERIC_VALUE]"


# ── anonymize_job_data ────────────────────────────────────────────────────────

def test_anonymize_job_data_hashes_url(anon):
    data = {"url": "https://acme.com/jobs/123", "title": "Engineer"}
    result = anon.anonymize_job_data(data)
    # URL should be anonymized
    assert result["url"] != "https://acme.com/jobs/123"
    assert result["url"].startswith("https://")


def test_anonymize_job_data_preserves_non_sensitive(anon):
    data = {"posted_date": "2026-01-01", "job_id": "12345"}
    result = anon.anonymize_job_data(data)
    assert result["posted_date"] == "2026-01-01"
    assert result["job_id"] == "12345"


def test_anonymize_job_data_handles_empty(anon):
    result = anon.anonymize_job_data({})
    assert result == {}


# ── anonymize_application_data ────────────────────────────────────────────────

def test_anonymize_application_data_hashes_job_url(anon):
    app_data = {
        "job_url": "https://acme.com/apply",
        "platform": "linkedin",
        "success": True,
        "completion_time": 120,
    }
    result = anon.anonymize_application_data(app_data)
    assert "job_id" in result
    assert result["job_id"] != "https://acme.com/apply"


def test_anonymize_application_data_preserves_platform(anon):
    app_data = {"platform": "greenhouse", "success": False}
    result = anon.anonymize_application_data(app_data)
    assert result["platform"] == "greenhouse"


def test_anonymize_application_data_preserves_outcome(anon):
    app_data = {"success": True}
    result = anon.anonymize_application_data(app_data)
    assert result["success"] is True


# ── _anonymize_url ─────────────────────────────────────────────────────────────

def test_anonymize_url_preserves_domain(anon):
    result = anon._anonymize_url("https://jobs.lever.co/acme/abc123")
    assert "lever.co" in result


def test_anonymize_url_hashes_path(anon):
    url = "https://acme.com/jobs/senior-engineer-123"
    result = anon._anonymize_url(url)
    assert "senior-engineer-123" not in result
    assert "anonymized_path_" in result


def test_anonymize_url_empty_returns_empty(anon):
    assert anon._anonymize_url("") == ""


def test_anonymize_url_no_path(anon):
    result = anon._anonymize_url("https://acme.com/")
    assert "acme.com" in result


# ── _generalize_salary ────────────────────────────────────────────────────────

@pytest.mark.parametrize("amount,expected", [
    (30000, "<50k"),
    (55000, "50k-75k"),
    (80000, "75k-100k"),
    (120000, "100k-150k"),
    (175000, "150k-200k"),
    (250000, ">200k"),
])
def test_generalize_salary_buckets(anon, amount, expected):
    assert anon._generalize_salary(amount) == expected


def test_generalize_salary_none(anon):
    assert anon._generalize_salary(None) is None


# ── _anonymize_locations ──────────────────────────────────────────────────────

def test_anonymize_locations_empty(anon):
    assert anon._anonymize_locations([]) == []


def test_anonymize_locations_none(anon):
    assert anon._anonymize_locations(None) == []


def test_anonymize_locations_city_state(anon):
    result = anon._anonymize_locations(["New York, NY"])
    assert result == ["[CITY], NY"]


def test_anonymize_locations_preserves_simple_location(anon):
    result = anon._anonymize_locations(["Remote"])
    assert result == ["Remote"]


def test_anonymize_locations_street_address_genericized(anon):
    result = anon._anonymize_locations(["123 Main Street"])
    assert result == ["[GENERIC_LOCATION]"]

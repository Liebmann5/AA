"""Unit tests for application/services/research/pipeline.py.

Tests cover Anonymizer (PII hashing/stripping), ConsentManager, and
ResearchPipeline (recording, export, summary aggregation). All file I/O
uses tmp_path so nothing is written to the user's home directory.
"""

import json
import tempfile
from pathlib import Path

import pytest

from auto_apply.application.services.research.pipeline import (
    ATSType,
    ApplicationOutcome,
    Anonymizer,
    ConsentManager,
    ResearchPipeline,
    VettingOutcome,
)


# ── Anonymizer ────────────────────────────────────────────────────────────────

class TestAnonymizer:
    def test_hash_value_is_deterministic(self):
        anon = Anonymizer(salt="fixed_salt_for_test")
        assert anon.hash_value("acme_corp") == anon.hash_value("acme_corp")

    def test_different_values_different_hashes(self):
        anon = Anonymizer(salt="fixed_salt")
        assert anon.hash_value("company_a") != anon.hash_value("company_b")

    def test_hash_value_empty_string(self):
        anon = Anonymizer(salt="fixed_salt")
        assert anon.hash_value("") == ""

    def test_hash_value_length(self):
        anon = Anonymizer(salt="s")
        h = anon.hash_value("test")
        assert len(h) == 16  # first 16 chars of sha256

    def test_anonymize_url_returns_hash(self):
        anon = Anonymizer(salt="s")
        result = anon.anonymize_url("https://acme.com/jobs/123")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_anonymize_company_returns_hash(self):
        anon = Anonymizer(salt="s")
        result = anon.anonymize_company("Acme Corporation")
        assert isinstance(result, str)

    def test_anonymize_query_returns_placeholder(self):
        anon = Anonymizer(salt="s")
        result = anon.anonymize_query("software engineer New York")
        assert result == "[search_query]"

    def test_strip_pii_removes_email(self):
        anon = Anonymizer(salt="s")
        result = anon.strip_pii("Contact john.doe@example.com for details")
        assert "[EMAIL]" in result
        assert "john.doe" not in result

    def test_strip_pii_removes_phone(self):
        anon = Anonymizer(salt="s")
        result = anon.strip_pii("Call us at 555-123-4567")
        assert "[PHONE]" in result

    def test_strip_pii_removes_zip(self):
        anon = Anonymizer(salt="s")
        result = anon.strip_pii("Located in 10001")
        assert "[ZIP]" in result

    def test_strip_pii_preserves_non_pii(self):
        anon = Anonymizer(salt="s")
        result = anon.strip_pii("Apply now for this great opportunity")
        assert result == "Apply now for this great opportunity"

    def test_strip_pii_empty_string(self):
        anon = Anonymizer(salt="s")
        assert anon.strip_pii("") == ""


# ── ConsentManager ────────────────────────────────────────────────────────────

class TestConsentManager:
    def test_defaults_to_not_granted(self, tmp_path):
        mgr = ConsentManager(data_dir=tmp_path)
        assert not mgr.is_granted()

    def test_grant_sets_consent(self, tmp_path):
        mgr = ConsentManager(data_dir=tmp_path)
        mgr.grant()
        assert mgr.is_granted()

    def test_revoke_clears_consent(self, tmp_path):
        mgr = ConsentManager(data_dir=tmp_path)
        mgr.grant()
        mgr.revoke()
        assert not mgr.is_granted()

    def test_consent_persists_across_instances(self, tmp_path):
        mgr1 = ConsentManager(data_dir=tmp_path)
        mgr1.grant()
        mgr2 = ConsentManager(data_dir=tmp_path)
        assert mgr2.is_granted()

    def test_delete_all_data_removes_files(self, tmp_path):
        research_dir = tmp_path / "research"
        research_dir.mkdir()
        (research_dir / "session_abc.json").write_text("{}")
        (research_dir / "applications_abc.csv").write_text("header\n")
        (research_dir / "other.txt").write_text("keep this")
        mgr = ConsentManager(data_dir=tmp_path)
        count = mgr.delete_all_data(research_dir)
        assert count == 2
        assert (research_dir / "other.txt").exists()


# ── ResearchPipeline ──────────────────────────────────────────────────────────

class TestResearchPipeline:
    def test_inactive_by_default(self):
        pipeline = ResearchPipeline(consent_granted=False)
        assert not pipeline.is_active

    def test_active_with_consent(self, tmp_path):
        pipeline = ResearchPipeline(consent_granted=True, output_dir=tmp_path)
        assert pipeline.is_active

    # -- recording when inactive --

    def test_inactive_pipeline_ignores_discovery(self):
        pipeline = ResearchPipeline(consent_granted=False)
        pipeline.record_discovery("google", "engineer", "NYC", 10, 5)
        assert pipeline.generate_session_summary().jobs_discovered == 0

    def test_inactive_pipeline_ignores_vetting(self):
        pipeline = ResearchPipeline(consent_granted=False)
        pipeline.record_vetting("http://x.com", VettingOutcome.PASSED)
        summary = pipeline.generate_session_summary()
        assert summary.jobs_vetted_pass == 0

    def test_inactive_pipeline_ignores_application(self):
        pipeline = ResearchPipeline(consent_granted=False)
        pipeline.record_application(
            "http://x.com", "Acme", ATSType.UNKNOWN, ApplicationOutcome.SUCCESS
        )
        summary = pipeline.generate_session_summary()
        assert summary.applications_attempted == 0

    # -- recording when active --

    def test_records_discovery_event(self, tmp_path):
        pipeline = ResearchPipeline(consent_granted=True, output_dir=tmp_path)
        pipeline.record_discovery("google", "engineer", "NYC", 10, 5, load_time_ms=200, pages=2)
        summary = pipeline.generate_session_summary()
        assert summary.jobs_discovered == 10

    def test_records_multiple_discoveries(self, tmp_path):
        pipeline = ResearchPipeline(consent_granted=True, output_dir=tmp_path)
        pipeline.record_discovery("google", "eng", "NYC", 5, 3)
        pipeline.record_discovery("indeed", "dev", "Remote", 8, 6)
        assert pipeline.generate_session_summary().jobs_discovered == 13

    def test_records_vetting_pass(self, tmp_path):
        pipeline = ResearchPipeline(consent_granted=True, output_dir=tmp_path)
        pipeline.record_vetting("http://x.com", VettingOutcome.PASSED, fit_score=0.9)
        summary = pipeline.generate_session_summary()
        assert summary.jobs_vetted_pass == 1
        assert summary.jobs_vetted_fail == 0

    def test_records_vetting_fail(self, tmp_path):
        pipeline = ResearchPipeline(consent_granted=True, output_dir=tmp_path)
        pipeline.record_vetting(
            "http://x.com", VettingOutcome.FAILED_TITLE_MISMATCH, rejection_reason="mismatch"
        )
        summary = pipeline.generate_session_summary()
        assert summary.jobs_vetted_pass == 0
        assert summary.jobs_vetted_fail == 1

    def test_records_application_success(self, tmp_path):
        pipeline = ResearchPipeline(consent_granted=True, output_dir=tmp_path)
        pipeline.record_application(
            "http://x.com", "Acme", ATSType.GREENHOUSE, ApplicationOutcome.SUCCESS,
            form_steps=3, form_fields=5, fields_filled=5, time_ms=15000,
        )
        summary = pipeline.generate_session_summary()
        assert summary.applications_attempted == 1
        assert summary.applications_succeeded == 1
        assert summary.applications_failed == 0

    def test_records_application_failure(self, tmp_path):
        pipeline = ResearchPipeline(consent_granted=True, output_dir=tmp_path)
        pipeline.record_application(
            "http://x.com", "Acme", ATSType.LEVER, ApplicationOutcome.FAILED_NAVIGATION,
        )
        summary = pipeline.generate_session_summary()
        assert summary.applications_attempted == 1
        assert summary.applications_succeeded == 0
        assert summary.applications_failed == 1

    def test_unique_companies_counted(self, tmp_path):
        pipeline = ResearchPipeline(consent_granted=True, output_dir=tmp_path)
        pipeline.record_application("http://a.com", "Alpha", ATSType.UNKNOWN, ApplicationOutcome.SUCCESS)
        pipeline.record_application("http://b.com", "Beta", ATSType.UNKNOWN, ApplicationOutcome.SUCCESS)
        pipeline.record_application("http://a2.com", "Alpha", ATSType.UNKNOWN, ApplicationOutcome.SUCCESS)
        summary = pipeline.generate_session_summary()
        # Alpha hashes to one value, Beta to another → 2 unique companies
        assert summary.unique_companies == 2

    # -- export --

    def test_export_returns_none_when_inactive(self):
        pipeline = ResearchPipeline(consent_granted=False)
        assert pipeline.export_session("test") is None

    def test_export_creates_json_file(self, tmp_path):
        pipeline = ResearchPipeline(consent_granted=True, output_dir=tmp_path)
        pipeline.record_discovery("google", "dev", "Remote", 3, 2)
        path = pipeline.export_session("sess_001")
        assert path is not None
        assert path.exists()
        assert path.suffix == ".json"

    def test_export_json_structure(self, tmp_path):
        pipeline = ResearchPipeline(consent_granted=True, output_dir=tmp_path)
        pipeline.record_discovery("indeed", "eng", "NYC", 7, 4)
        path = pipeline.export_session("sess_002")
        data = json.loads(path.read_text())
        assert "meta" in data
        assert "discovery_events" in data
        assert data["meta"]["session_id"] == "sess_002"
        assert data["meta"]["event_counts"]["discovery"] == 1

    def test_export_csv_returns_none_when_no_applications(self, tmp_path):
        pipeline = ResearchPipeline(consent_granted=True, output_dir=tmp_path)
        assert pipeline.export_session_csv("sess") is None

    def test_export_csv_creates_file(self, tmp_path):
        pipeline = ResearchPipeline(consent_granted=True, output_dir=tmp_path)
        pipeline.record_application(
            "http://x.com", "Acme", ATSType.WORKDAY, ApplicationOutcome.SUCCESS,
        )
        path = pipeline.export_session_csv("sess_csv")
        assert path is not None
        assert path.exists()
        assert path.suffix == ".csv"

    def test_export_csv_has_header(self, tmp_path):
        pipeline = ResearchPipeline(consent_granted=True, output_dir=tmp_path)
        pipeline.record_application(
            "http://x.com", "Acme", ATSType.WORKDAY, ApplicationOutcome.SUCCESS,
        )
        path = pipeline.export_session_csv("csv_test")
        lines = path.read_text().splitlines()
        assert len(lines) >= 2  # header + at least one row

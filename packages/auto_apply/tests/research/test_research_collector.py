"""Unit tests for application/services/research/collector.py.

ResearchCollector requires a CapabilitiesRegistry and EventBus. Both are
mocked so no file I/O or threading is needed for the core unit tests.
ResearchSignal.to_csv_row() is tested independently as a pure function.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from auto_apply.application.services.research.collector import (
    ResearchCollector,
    ResearchSignal,
    ResearchSignalType,
    _CSV_HEADERS,
)


# ── ResearchSignal ────────────────────────────────────────────────────────────

class TestResearchSignal:
    def test_to_csv_row_length_matches_headers(self):
        signal = ResearchSignal(
            session_id="test123",
            signal_type=ResearchSignalType.ATS_NO_RESPONSE,
        )
        row = signal.to_csv_row()
        assert len(row) == len(_CSV_HEADERS)

    def test_to_csv_row_contains_session_id(self):
        signal = ResearchSignal(session_id="sess_abc", signal_type=ResearchSignalType.CAPTCHA_EXCESSIVE)
        row = signal.to_csv_row()
        assert "sess_abc" in row

    def test_to_csv_row_contains_signal_type_name(self):
        signal = ResearchSignal(
            session_id="s", signal_type=ResearchSignalType.SALARY_RANGE_DISCLOSED
        )
        row = signal.to_csv_row()
        assert "SALARY_RANGE_DISCLOSED" in row

    def test_to_csv_row_years_required_empty_when_none(self):
        signal = ResearchSignal(
            session_id="s",
            signal_type=ResearchSignalType.ENTRY_LEVEL_EXPERIENCE_REQUIRED,
            years_required=None,
        )
        row = signal.to_csv_row()
        years_idx = _CSV_HEADERS.index("years_required")
        assert row[years_idx] == ""

    def test_to_csv_row_years_required_as_string(self):
        signal = ResearchSignal(
            session_id="s",
            signal_type=ResearchSignalType.ENTRY_LEVEL_EXPERIENCE_REQUIRED,
            years_required=3,
        )
        row = signal.to_csv_row()
        years_idx = _CSV_HEADERS.index("years_required")
        assert row[years_idx] == "3"

    def test_to_csv_row_timestamp_is_iso_format(self):
        ts = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        signal = ResearchSignal(
            session_id="s",
            signal_type=ResearchSignalType.ATS_REJECTION_RAPID,
            timestamp=ts,
        )
        row = signal.to_csv_row()
        assert "2026-05-01" in row[0]

    def test_all_fields_represented_as_strings(self):
        signal = ResearchSignal(
            session_id="s",
            signal_type=ResearchSignalType.FORM_LOGIC_CONFLICT,
            platform_type="greenhouse",
            job_tier_listed="senior",
            detail_code="test_detail",
        )
        row = signal.to_csv_row()
        assert all(isinstance(cell, str) for cell in row)


# ── ResearchSignalType category mapping ──────────────────────────────────────

class TestSignalTypeCategories:
    def test_category_for_seniority_signal(self):
        category = ResearchCollector._category_for(ResearchSignalType.TITLE_DESCRIPTION_MISMATCH)
        assert category == "seniority"

    def test_category_for_ats_signal(self):
        category = ResearchCollector._category_for(ResearchSignalType.ATS_REJECTION_RAPID)
        assert category == "ats_process"

    def test_category_for_friction_signal(self):
        category = ResearchCollector._category_for(ResearchSignalType.CAPTCHA_EXCESSIVE)
        assert category == "friction"

    def test_category_for_positive_signal(self):
        category = ResearchCollector._category_for(ResearchSignalType.SALARY_RANGE_DISCLOSED)
        assert category == "positive"

    def test_category_for_form_design_signal(self):
        category = ResearchCollector._category_for(ResearchSignalType.YIN_YANG_CONFLICT)
        assert category == "form_design"


# ── ResearchCollector._classify_platform ─────────────────────────────────────

class TestClassifyPlatform:
    @pytest.mark.parametrize("url,expected", [
        ("https://linkedin.com/jobs/view/123", "linkedin"),
        ("https://www.indeed.com/viewjob?jk=abc", "indeed"),
        ("https://boards.greenhouse.io/acme/jobs/1", "greenhouse"),
        ("https://jobs.lever.co/acme/abc", "lever"),
        ("https://acme.workday.com/apply", "workday"),
        ("https://unknownjobboard.io/jobs/1", "other"),
        ("", "unknown"),
    ])
    def test_platform_classification(self, url, expected):
        assert ResearchCollector._classify_platform(url) == expected


# ── ResearchCollector._sanitize_detail ───────────────────────────────────────

class TestSanitizeDetail:
    def test_strips_urls(self):
        result = ResearchCollector._sanitize_detail("See https://example.com for details")
        assert "https://" not in result
        assert "[url]" in result

    def test_strips_emails(self):
        result = ResearchCollector._sanitize_detail("Contact admin@example.com")
        assert "admin@" not in result
        assert "[email]" in result

    def test_truncates_at_80_chars(self):
        long_text = "a" * 200
        result = ResearchCollector._sanitize_detail(long_text)
        assert len(result) <= 80

    def test_empty_string(self):
        assert ResearchCollector._sanitize_detail("") == ""


# ── ResearchCollector construction ───────────────────────────────────────────

class TestResearchCollectorConstruction:
    def _make_registry(self, enabled=False):
        registry = MagicMock()
        registry.is_research_enabled.return_value = enabled
        return registry

    def test_disabled_when_research_not_enabled(self, tmp_path):
        registry = self._make_registry(enabled=False)
        collector = ResearchCollector(
            registry=registry,
            event_bus=MagicMock(),
            session_id="test",
            data_dir=tmp_path,
        )
        assert not collector._enabled

    def test_enabled_when_research_enabled(self, tmp_path):
        registry = self._make_registry(enabled=True)
        collector = ResearchCollector(
            registry=registry,
            event_bus=MagicMock(),
            session_id="test",
            data_dir=tmp_path,
        )
        assert collector._enabled

    def test_record_does_nothing_when_disabled(self, tmp_path):
        registry = self._make_registry(enabled=False)
        collector = ResearchCollector(
            registry=registry,
            event_bus=MagicMock(),
            session_id="test",
            data_dir=tmp_path,
        )
        signal = ResearchSignal(
            session_id="test",
            signal_type=ResearchSignalType.ATS_NO_RESPONSE,
        )
        # Should not raise and queue should remain empty
        collector.record(signal)
        assert collector._queue.empty()

    def test_record_enqueues_when_enabled(self, tmp_path):
        registry = self._make_registry(enabled=True)
        collector = ResearchCollector(
            registry=registry,
            event_bus=MagicMock(),
            session_id="test",
            data_dir=tmp_path,
        )
        signal = ResearchSignal(
            session_id="test",
            signal_type=ResearchSignalType.CAPTCHA_EXCESSIVE,
        )
        collector.record(signal)
        assert not collector._queue.empty()

    def test_record_signal_does_nothing_when_disabled(self, tmp_path):
        registry = self._make_registry(enabled=False)
        collector = ResearchCollector(
            registry=registry,
            event_bus=MagicMock(),
            session_id="test",
            data_dir=tmp_path,
        )
        collector.record_signal(ResearchSignalType.ATS_NO_RESPONSE, platform_type="linkedin")
        assert collector._queue.empty()

    def test_record_signal_enqueues_when_enabled(self, tmp_path):
        registry = self._make_registry(enabled=True)
        collector = ResearchCollector(
            registry=registry,
            event_bus=MagicMock(),
            session_id="sess_001",
            data_dir=tmp_path,
        )
        collector.record_signal(
            ResearchSignalType.SALARY_RANGE_DISCLOSED,
            platform_type="linkedin",
            detail_code="salary_disclosed",
        )
        assert not collector._queue.empty()
        signal = collector._queue.get_nowait()
        assert signal.signal_type == ResearchSignalType.SALARY_RANGE_DISCLOSED
        assert signal.session_id == "sess_001"

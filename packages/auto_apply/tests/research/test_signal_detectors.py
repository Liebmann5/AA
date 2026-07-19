"""Pure‑Python unit tests for research signal detectors.

Every test constructs a ``DetectionContext`` with exactly the fields required
to trigger (or not trigger) a signal.  No database, browser, or network I/O
is performed.

Coverage goal:
    - At least two tests per detector category (positive trigger + negative)
    - ``run_all_detectors()`` integration smoke test
    - Edge cases: minimal context must not crash the pipeline
    - All 29 detectors exercised through run_all_detectors
    - Unicode safety: detectors must handle non‑ASCII characters
    - Empty/null field safety: detectors must handle missing optional fields

Intentionally NOT tested here:
    - Integration with ResearchSignalAggregator or SQLite (covered in test_signal_aggregator.py)
    - Full‑corpus macro‑analysis signals (LM-01 etc.) — those require corpus data
"""

import pytest

from auto_apply.domain.services.signal_detectors.base import DetectionContext, ResearchSignal
# Import specific detector classes so we can invoke them directly.
from auto_apply.domain.services.signal_detectors.ghost_job_detectors import (
    PostingAgeAnomalyDetector,
)
from auto_apply.domain.services.signal_detectors.salary_detectors import (
    SalaryTransparencyLegalViolationDetector,
)
from auto_apply.domain.services.signal_detectors.qualification_detectors import (
    ExperienceYearImpossibilityDetector,
)
from auto_apply.domain.services.signal_detectors.discrimination_detectors import (
    GenderedLanguageDetector,
)
from auto_apply.domain.services.signal_detectors.dark_pattern_detectors import (
    ToxicCultureObfuscationDetector,
)
from auto_apply.domain.services.signal_detectors.extended_detectors import (
    TitleDescriptionMismatchDetector,
)

# ─────────────────────────────────────────────────────────────────────────────
# Ghost Job Detectors (GJ‑01)
# ─────────────────────────────────────────────────────────────────────────────

def test_gj01_fires_on_stale_posting():
    """A posting live 120 days triggers a GJ‑01 signal."""
    ctx = DetectionContext(
        job_title="Senior Software Engineer",
        days_live=120,
    )
    signals = PostingAgeAnomalyDetector().detect(ctx)
    assert len(signals) >= 1
    # The primary signal code must be present.
    assert any(s.signal_type.startswith("GJ-") for s in signals)


def test_gj01_does_not_fire_on_fresh_posting():
    """A posting first seen today produces no signals."""
    ctx = DetectionContext(
        job_title="Software Engineer",
        days_live=1,
    )
    signals = PostingAgeAnomalyDetector().detect(ctx)
    assert len(signals) == 0


def test_gj01_does_not_fire_when_days_live_is_none():
    """When days_live is not set, no signal should fire."""
    ctx = DetectionContext(
        job_title="Engineer",
        days_live=None,
    )
    signals = PostingAgeAnomalyDetector().detect(ctx)
    assert len(signals) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Salary Transparency Detectors (ST‑01)
# ─────────────────────────────────────────────────────────────────────────────

def test_st01_fires_when_salary_absent_in_regulated_state():
    """A Colorado job without a disclosed salary must trigger ST‑01."""
    ctx = DetectionContext(
        job_title="Backend Engineer",
        job_description="Competitive salary and great benefits.",
        jurisdiction="CO",
        salary_min=None,
        salary_max=None,
    )
    signals = SalaryTransparencyLegalViolationDetector().detect(ctx)
    assert len(signals) >= 1
    assert any(s.signal_type.startswith("ST-") for s in signals)


def test_st01_does_not_fire_when_salary_present():
    """When a salary range is available, no violation is reported."""
    ctx = DetectionContext(
        job_title="Backend Engineer",
        job_description="Competitive salary.",
        jurisdiction="CO",
        salary_min=90000,
        salary_max=120000,
    )
    signals = SalaryTransparencyLegalViolationDetector().detect(ctx)
    assert len(signals) == 0


def test_st01_does_not_fire_outside_pay_transparency_state():
    """A job in a non‑regulated location with no salary is not flagged."""
    ctx = DetectionContext(
        job_title="Engineer",
        job_description="Competitive salary.",
        jurisdiction="TX",  # no pay‑transparency law here
        salary_min=None,
        salary_max=None,
    )
    signals = SalaryTransparencyLegalViolationDetector().detect(ctx)
    assert len(signals) == 0


def test_st01_does_not_fire_when_jurisdiction_is_none():
    """When jurisdiction is None, ST‑01 should not fire."""
    ctx = DetectionContext(
        job_title="Engineer",
        job_description="Competitive salary.",
        jurisdiction=None,
        salary_min=None,
        salary_max=None,
    )
    signals = SalaryTransparencyLegalViolationDetector().detect(ctx)
    assert len(signals) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Qualification Inflation (QS‑01)
# ─────────────────────────────────────────────────────────────────────────────

def test_qs01_fires_experience_exceeds_technology_age():
    """Requesting 11 years of React (2013) should fire a signal."""
    ctx = DetectionContext(
        job_title="DevOps Engineer",
        job_description="Must have 11 years of experience with React.",
    )
    signals = ExperienceYearImpossibilityDetector().detect(ctx)
    assert len(signals) >= 1
    assert any(s.signal_type.startswith("QS-") for s in signals)


def test_qs01_does_not_fire_reasonable_experience():
    """3 years of Python (1991) is perfectly reasonable — no signal."""
    ctx = DetectionContext(
        job_title="Data Scientist",
        job_description="3 years of Python required.",
    )
    signals = ExperienceYearImpossibilityDetector().detect(ctx)
    assert len(signals) == 0


def test_qs01_does_not_fire_empty_description():
    """Empty description should produce no signals, not raise."""
    ctx = DetectionContext(
        job_title="Engineer",
        job_description="",
    )
    signals = ExperienceYearImpossibilityDetector().detect(ctx)
    assert len(signals) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Discrimination Detectors (DISC‑01)
# ─────────────────────────────────────────────────────────────────────────────

def test_disc_masculine_coded_language():
    """A description with heavy masculine‑coded words triggers DISC‑01."""
    ctx = DetectionContext(
        job_title="Software Developer",
        job_description=(
            "We are looking for a competitive, ambitious ninja who can "
            "dominate our fast‑paced environment. You must be fearless and "
            "assertive. Crush every challenge!"
        ),
    )
    signals = GenderedLanguageDetector().detect(ctx)
    assert len(signals) >= 1
    assert any(s.signal_type.startswith("DISC-") for s in signals)


def test_disc_neutral_language_no_signal():
    """A balanced description should not fire a gendered‑language signal."""
    ctx = DetectionContext(
        job_title="Graphic Designer",
        job_description=(
            "We value teamwork, creativity, and attention to detail. "
            "Collaborate with a supportive team to create great designs."
        ),
    )
    signals = GenderedLanguageDetector().detect(ctx)
    assert len(signals) == 0


def test_disc_empty_description_no_signal():
    """Empty description must not crash gendered language detector."""
    ctx = DetectionContext(
        job_title="Designer",
        job_description="",
    )
    signals = GenderedLanguageDetector().detect(ctx)
    assert len(signals) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Dark Pattern Detectors (DP‑02 — Toxic Culture Obfuscation)
# ─────────────────────────────────────────────────────────────────────────────
# DP‑02 is the most reliable dark‑pattern detector in this version.
def test_dp02_fires_on_obfuscated_exploitation():
    """Patterns like 'work hard and play hard' indicate toxic culture."""
    ctx = DetectionContext(
        job_title="Account Manager",
        job_description=(
            "We are a fast‑paced, work‑hard and play‑hard startup. "
            "You'll wear many hats and be part of our family!"
        ),
    )
    signals = ToxicCultureObfuscationDetector().detect(ctx)
    assert len(signals) >= 1
    assert any(s.signal_type.startswith("DP-") for s in signals)


def test_dp02_clean_posting_no_signal():
    """A standard, non‑obfuscated description passes without signals."""
    ctx = DetectionContext(
        job_title="Product Manager",
        job_description=(
            "Lead product roadmap, collaborate with engineering, and "
            "drive customer outcomes. We offer standard benefits."
        ),
    )
    signals = ToxicCultureObfuscationDetector().detect(ctx)
    assert len(signals) == 0


def test_dp02_empty_description_no_signal():
    """Empty description must not crash toxic culture detector."""
    ctx = DetectionContext(
        job_title="PM",
        job_description="",
    )
    signals = ToxicCultureObfuscationDetector().detect(ctx)
    assert len(signals) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Title‑Description Mismatch (DP‑01)
# ─────────────────────────────────────────────────────────────────────────────

def test_dp01_fires_on_mismatched_title_and_description():
    """A title like 'Software Engineer' with nursing keywords should mismatch."""
    ctx = DetectionContext(
        job_title="Software Engineer",
        job_description=(
            "Provide patient care, administer medications, monitor vital signs, "
            "and coordinate with physicians on treatment plans. "
            "Must have valid RN license and 2 years clinical experience."
        ),
    )
    signals = TitleDescriptionMismatchDetector().detect(ctx)
    assert len(signals) >= 1
    assert any(s.signal_type.startswith("DP-") for s in signals)


def test_dp01_does_not_fire_on_matching_title_and_description():
    """Title and description both about engineering should match."""
    ctx = DetectionContext(
        job_title="Software Engineer",
        job_description=(
            "Design, develop, and maintain software applications. "
            "Work with engineering team on system architecture and code reviews. "
            "Build and deploy scalable solutions using modern frameworks."
        ),
    )
    signals = TitleDescriptionMismatchDetector().detect(ctx)
    assert len(signals) == 0


def test_dp01_short_description_no_signal():
    """Very short descriptions may not have enough keywords to trigger."""
    ctx = DetectionContext(
        job_title="Nurse Practitioner",
        job_description="Competitive salary.",
    )
    signals = TitleDescriptionMismatchDetector().detect(ctx)
    assert len(signals) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Edge Cases — Unicode and null safety
# ─────────────────────────────────────────────────────────────────────────────

def test_detectors_handle_unicode_characters():
    """Detectors must handle non‑ASCII Unicode characters without crashing."""
    ctx = DetectionContext(
        job_title="Développeur Senior — Fran\u00e7ais",
        job_description=(
            "R\u00f4le exigeant n\u00e9cessitant 5 ann\u00e9es d'exp\u00e9rience "
            "avec React et Python. Salaire comp\u00e9titif et avantages sociaux."
        ),
        jurisdiction="CA",
        salary_min=None,
        salary_max=None,
    )
    from auto_apply.domain.services.signal_detectors import run_all_detectors
    signals = run_all_detectors(ctx)
    assert isinstance(signals, list)


def test_detectors_handle_extremely_long_text():
    """Detectors must handle extremely long job descriptions without OOM."""
    long_text = "Experience required. " * 5000  # ~100K chars
    ctx = DetectionContext(
        job_title="Engineer",
        job_description=long_text,
    )
    from auto_apply.domain.services.signal_detectors import run_all_detectors
    signals = run_all_detectors(ctx)
    assert isinstance(signals, list)


def test_detectors_handle_all_none_optional_fields():
    """When all optional fields are None, detectors must not crash."""
    ctx = DetectionContext(
        job_title="",
        job_description="",
        company_name=None,
        location=None,
        jurisdiction=None,
        salary_min=None,
        salary_max=None,
        platform=None,
        first_seen_date=None,
        days_live=None,
        posting_hash=None,
        form_field_count=None,
        form_has_salary_history_field=False,
        form_wcag_violations=[],
        times_seen_cross_platform=1,
        application_url_is_generic=False,
    )
    from auto_apply.domain.services.signal_detectors import run_all_detectors
    signals = run_all_detectors(ctx)
    assert isinstance(signals, list)


def test_detectors_handle_null_characters():
    """Null bytes in text fields must not crash detector regex engines."""
    ctx = DetectionContext(
        job_title="Software Engineer",
        job_description="We need a \x00 developer with 5 years of React.",
    )
    from auto_apply.domain.services.signal_detectors import run_all_detectors
    signals = run_all_detectors(ctx)
    assert isinstance(signals, list)


# ─────────────────────────────────────────────────────────────────────────────
# Integration — run_all_detectors
# ─────────────────────────────────────────────────────────────────────────────

def test_run_all_detectors_returns_list(minimal_context):
    """The top‑level function always returns a list (possibly empty)."""
    from auto_apply.domain.services.signal_detectors import run_all_detectors
    signals = run_all_detectors(minimal_context)
    assert isinstance(signals, list)
    # A completely generic context may produce signals (e.g., salary in a
    # transparent state not set — but our fixture has salary set and no
    # jurisdiction → no salary transparency signal). This test only verifies
    # the return type and that no exception is raised.


def test_run_all_detectors_no_crash_on_bare_context():
    """Passing the absolute minimum context must never raise an exception."""
    from auto_apply.domain.services.signal_detectors import run_all_detectors
    try:
        run_all_detectors(DetectionContext())  # all defaults
    except Exception as exc:
        pytest.fail(f"run_all_detectors raised unexpectedly: {exc}")


def test_run_all_detectors_returns_research_signal_objects():
    """Each item in the returned list must be a ResearchSignal instance."""
    from auto_apply.domain.services.signal_detectors import run_all_detectors

    # Create a context that should trigger multiple detectors
    ctx = DetectionContext(
        job_title="Senior Software Engineer",
        job_description=(
            "We are looking for a competitive, ambitious ninja who can "
            "dominate our fast‑paced environment. Must have 11 years of "
            "React experience. Competitive salary."
        ),
        jurisdiction="CO",
        days_live=150,
    )
    signals = run_all_detectors(ctx)

    for signal in signals:
        assert isinstance(signal, ResearchSignal)
        assert signal.signal_type  # non‑empty
        assert signal.severity in ("flag", "concern", "violation")
        assert 0.0 <= signal.confidence <= 1.0


def test_run_all_detectors_signals_sorted_by_confidence():
    """run_all_detectors returns signals sorted by confidence descending."""
    from auto_apply.domain.services.signal_detectors import run_all_detectors

    # A context likely to trigger multiple signals with varying confidence
    ctx = DetectionContext(
        job_title="Entry Level Software Engineer",
        job_description=(
            "We are looking for a competitive, ambitious ninja who can "
            "dominate our fast‑paced environment. Must have 11 years of "
            "React experience. Work hard and play hard."
        ),
        jurisdiction="CO",
        days_live=150,
        salary_min=None,
        salary_max=None,
    )
    signals = run_all_detectors(ctx)

    if len(signals) >= 2:
        for i in range(len(signals) - 1):
            assert signals[i].confidence >= signals[i + 1].confidence, (
                f"Signal {i} ({signals[i].signal_type}, conf={signals[i].confidence:.2f}) "
                f"should be >= signal {i + 1} ({signals[i + 1].signal_type}, "
                f"conf={signals[i + 1].confidence:.2f})"
            )


def test_run_all_detectors_deduplicates_by_posting_hash():
    """When posting_hash is set, duplicate signals collapse to one per type+date."""
    from auto_apply.domain.services.signal_detectors import run_all_detectors

    ctx = DetectionContext(
        job_title="Entry Level Engineer",
        job_description="Must have 11 years of React. Competitive salary.",
        jurisdiction="CO",
        days_live=150,
        posting_hash="test-hash-123",
    )
    signals1 = run_all_detectors(ctx)
    signals2 = run_all_detectors(ctx)  # same context → same signals

    # With a posting_hash, each signal_type should produce exactly one signal
    # across both runs (INSERT OR IGNORE on deterministic signal_id)
    types1 = {s.signal_type for s in signals1}
    types2 = {s.signal_type for s in signals2}
    assert types1 == types2
    # Each type appears once per run
    for st in types1:
        count1 = sum(1 for s in signals1 if s.signal_type == st)
        count2 = sum(1 for s in signals2 if s.signal_type == st)
        assert count1 == 1, f"{st} appears {count1} times in run 1"
        assert count2 == 1, f"{st} appears {count2} times in run 2"

"""
Extended Signal Detectors — Research Module v2.1

Implements the remaining detectors from the Research Module Specification
that were not in the initial v2.0 implementation:

  GJ-04   Apply-with-no-ATS                  (Ghost Job)
  DISC-05 Geographic Pay Discrimination       (Discrimination)
  DP-01   Title-Description Mismatch          (Dark Pattern)
  DP-05   Phantom Company Detection           (Dark Pattern)
  AH-01   ATS Knockout Question Pattern       (AI Hiring Bias)
  AH-02   Readability/Complexity Asymmetry    (AI Hiring Bias)

All detectors are pure — zero I/O, fully unit-testable. Where corpus data or
external enrichment is required (DISC-05's COL index, AH-01's market norms),
the data is loaded from YAML resources at module import time (lazy, cached)
following the exact pattern established in qualification_detectors.py and
salary_detectors.py.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from auto_apply.domain.constants import (
    SEVERITY_CONCERN,
    SEVERITY_FLAG,
    SEVERITY_VIOLATION,
    SIG_AH_01,
    SIG_AH_02,
    SIG_DISC_05,
    SIG_DP_01,
    SIG_DP_05,
    SIG_GJ_04,
)
from auto_apply.domain.services.research_statistics import (
    flesch_kincaid_grade,
    gunning_fog_index,
    overlap_coefficient,
    role_keywords,
)
from auto_apply.domain.services.signal_detectors.base import (
    DetectionContext,
    ResearchSignal,
    SignalDetector,
)

_RESOURCES_DIR = Path(__file__).parent.parent.parent.parent / "resources" / "research"


# ── GJ-04: Apply-with-no-ATS ──────────────────────────────────────────────────

class ApplyWithNoATSDetector:
    """GJ-04: Detects 'Apply' buttons that don't lead to a real application form.

    AA's navigation to the application endpoint is the evidence. When the
    'Apply' link resolves to a generic company homepage, a mailto: link, or
    a 404, and the resulting page has zero detected form fields, this is
    either a ghost job or a structurally broken (and therefore non-functional)
    posting. Either way, a candidate cannot actually apply.
    """
    signal_type = SIG_GJ_04

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        if not ctx.application_url_is_generic:
            return []
        if ctx.application_form_field_count is None:
            return []
        if ctx.application_form_field_count > 0:
            return []  # A real form was found despite a generic-looking URL — fine

        evidence = (
            f"'Apply' for '{ctx.job_title[:50]}' resolves to a non-form page "
            f"(generic URL, 0 form fields detected). No functional application "
            f"path exists for candidates."
        )
        return [ResearchSignal.create(
            signal_type=self.signal_type, severity=SEVERITY_CONCERN,
            confidence=0.80, evidence_text=evidence,
            platform=ctx.platform, jurisdiction=ctx.jurisdiction,
            company_name=ctx.company_name,
        )]


# ── DISC-05: Geographic Pay Discrimination ────────────────────────────────────

_COL_INDEX: dict[str, float] | None = None


def _load_col_index() -> dict[str, float]:
    """Load metro-area cost-of-living index (national average = 1.0).

    Source intended: BLS Regional CPI / MIT Living Wage Calculator.
    The bundled YAML provides illustrative values; operators should replace
    with current BLS data for production research use.
    """
    global _COL_INDEX
    if _COL_INDEX is None:
        try:
            with open(_RESOURCES_DIR / "col_index.yaml") as f:
                _COL_INDEX = yaml.safe_load(f) or {}
        except Exception:
            _COL_INDEX = {}
    return _COL_INDEX


class GeographicPayDiscriminationDetector:
    """DISC-05: Flags salary that is anomalously low after cost-of-living normalization.

    This detector does NOT claim discrimination on its own — it flags a
    candidate data point. Discrimination is established at the AGGREGATE level
    (regression of normalized salary residuals against MSA demographics, per
    Section 8 LM-03 of the spec). This detector's job is to compute and attach
    the COL-normalized salary so the aggregation pipeline can use it.

    Severity is intentionally capped at FLAG — individual postings are evidence
    points, not conclusions.
    """
    signal_type = SIG_DISC_05
    _LOW_NORMALIZED_THRESHOLD: float = 0.65  # normalized salary < 65% of nat'l median

    # National median salary baseline (USD/year) for normalization.
    # In production this should come from the salary corpus (BLS OEWS data);
    # this constant is the worst-case fallback when corpus is empty.
    _NATIONAL_MEDIAN_SALARY: float = 68_000.0

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        if ctx.salary_min is None and ctx.salary_max is None:
            return []
        if ctx.metro_area is None:
            return []

        col_index = ctx.cost_of_living_index
        if col_index is None:
            col_index = _load_col_index().get(ctx.metro_area)
        if col_index is None or col_index <= 0:
            return []  # No COL data for this metro — cannot normalize

        salary = ctx.salary_max or ctx.salary_min
        if not salary:
            # Falsy salary (None via the `or` chain, or a literal $0) carries
            # no pay-compression signal. A max of 0 with min=None previously
            # produced `None / col_index` — a TypeError on a common posting
            # shape. Guarded exactly like col_index above.
            return []
        normalized_salary = salary / col_index
        ratio_to_national = normalized_salary / self._NATIONAL_MEDIAN_SALARY

        if ratio_to_national >= self._LOW_NORMALIZED_THRESHOLD:
            return []

        confidence = min(0.70, 0.35 + (self._LOW_NORMALIZED_THRESHOLD - ratio_to_national))
        evidence = (
            f"Salary ${salary:,.0f} in {ctx.metro_area} (COL index {col_index:.2f}) "
            f"normalizes to ${normalized_salary:,.0f}, "
            f"{ratio_to_national:.0%} of national median (${self._NATIONAL_MEDIAN_SALARY:,.0f}). "
            f"Individual data point for aggregate MSA-demographic regression (LM-03)."
        )
        return [ResearchSignal.create(
            signal_type=self.signal_type, severity=SEVERITY_FLAG,
            confidence=confidence, evidence_text=evidence,
            platform=ctx.platform, jurisdiction=ctx.jurisdiction,
            company_name=ctx.company_name,
        )]


# ── DP-01: Title-Description Mismatch (Bait and Switch) ──────────────────────

class TitleDescriptionMismatchDetector:
    """DP-01: Detects when the job title doesn't match the described role.

    Tier 0 implementation: overlap-coefficient similarity over role-defining
    keyword sets extracted from title vs. description (zero dependency,
    works on worst-case hardware). Overlap coefficient — |A∩B| / min(|A|,|B|)
    — is used rather than plain Jaccard similarity because titles are
    inherently short (2-4 words) while descriptions are much longer; Jaccard's
    union-based denominator would structurally suppress the score for any
    long, detailed (i.e. good) description regardless of how well it actually
    matches the title. If a TextSimilarityPort (SpaCy/sentence-transformers)
    is available, inject a richer similarity_fn for Tier 1/2 accuracy — the
    detection logic and threshold are identical either way.

    Args:
        similarity_fn: Optional callable(set[str], set[str]) -> float in [0,1].
            Defaults to the overlap coefficient (Tier 0, zero dependency).
    """
    signal_type = SIG_DP_01
    _SIMILARITY_THRESHOLD: float = 0.15  # Below this = likely bait-and-switch
    _MIN_TITLE_KEYWORDS: int = 2  # Titles are inherently short (2-4 words).
    _MIN_DESC_KEYWORDS: int = 5  # A description with only a couple of
    # keywords (e.g. "Competitive salary.") is too sparse to make a
    # reliable title/description comparison at all — it isn't really
    # describing a role, so treating its near-zero overlap with the title
    # as a "mismatch" would be a false positive, not a real signal. Titles
    # don't get held to this same floor since they're expected to be short.

    def __init__(self, similarity_fn=None) -> None:
        self._similarity_fn = similarity_fn or overlap_coefficient

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        title_kw = role_keywords(ctx.job_title)
        # Use only the first ~150 words of the description — the role summary,
        # not the full requirements/benefits boilerplate which dilutes signal.
        first_chunk = " ".join(ctx.job_description.split()[:150])
        desc_kw = role_keywords(first_chunk)

        if (
            len(title_kw) < self._MIN_TITLE_KEYWORDS
            or len(desc_kw) < self._MIN_DESC_KEYWORDS
        ):
            return []

        similarity = self._similarity_fn(title_kw, desc_kw)
        if similarity >= self._SIMILARITY_THRESHOLD:
            return []

        confidence = min(0.85, 0.55 + (self._SIMILARITY_THRESHOLD - similarity) * 2.0)
        evidence = (
            f"Title '{ctx.job_title[:50]}' shares {similarity:.0%} keyword overlap "
            f"with description opening (threshold: {self._SIMILARITY_THRESHOLD:.0%}). "
            f"Title keywords: {sorted(title_kw)[:6]} | "
            f"Description keywords: {sorted(desc_kw)[:6]}"
        )
        return [ResearchSignal.create(
            signal_type=self.signal_type, severity=SEVERITY_CONCERN,
            confidence=confidence, evidence_text=evidence,
            platform=ctx.platform, jurisdiction=ctx.jurisdiction,
            company_name=ctx.company_name,
        )]


# ── DP-05: Phantom Company Detection ──────────────────────────────────────────

class PhantomCompanyDetector:
    """DP-05: Detects postings from companies with no verifiable existence.

    Distinguishes fraud from incompetence: small legitimate startups have thin
    web presence too, so this detector requires MULTIPLE absence signals before
    flagging, and caps severity at CONCERN (never VIOLATION) since false
    positives on legitimate small companies are likely.

    Requires enrichment: company_linkedin_age_days, company_domain_age_days,
    company_has_web_presence. These come from an external lookup pipeline
    (Crunchbase, WHOIS, LinkedIn API) — if not populated (None), this detector
    silently returns no signals (graceful degradation).
    """
    signal_type = SIG_DP_05
    _NEW_THRESHOLD_DAYS: int = 90

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        absence_signals: list[str] = []

        if ctx.company_linkedin_age_days is not None and ctx.company_linkedin_age_days < 30:
            absence_signals.append(
                f"LinkedIn page created {ctx.company_linkedin_age_days}d ago"
            )
        if ctx.company_domain_age_days is not None and ctx.company_domain_age_days < self._NEW_THRESHOLD_DAYS:
            absence_signals.append(
                f"company domain registered {ctx.company_domain_age_days}d ago"
            )
        if ctx.company_has_web_presence is False:
            absence_signals.append("no news/social media presence found")

        if len(absence_signals) < 2:
            return []  # Require corroboration — single-signal is too noisy

        confidence = min(0.75, 0.45 + len(absence_signals) * 0.12)
        evidence = (
            f"Company '{ctx.company_name or 'unknown'}' has {len(absence_signals)} "
            f"absence signals: {'; '.join(absence_signals)}. "
            f"May indicate fraudulent posting or newly-formed legitimate entity."
        )
        return [ResearchSignal.create(
            signal_type=self.signal_type, severity=SEVERITY_CONCERN,
            confidence=confidence, evidence_text=evidence,
            platform=ctx.platform, jurisdiction=ctx.jurisdiction,
            company_name=ctx.company_name,
        )]


# ── AH-01: ATS Knockout Question Pattern Analysis ─────────────────────────────

_KNOCKOUT_NORMS: dict[str, dict] | None = None


def _load_knockout_norms() -> dict[str, dict]:
    """Load market-norm thresholds for common knockout question types."""
    global _KNOCKOUT_NORMS
    if _KNOCKOUT_NORMS is None:
        try:
            with open(_RESOURCES_DIR / "knockout_norms.yaml") as f:
                _KNOCKOUT_NORMS = yaml.safe_load(f) or {}
        except Exception:
            _KNOCKOUT_NORMS = {
                "min_years_experience": {"p90": 8, "direction": "higher_is_stricter"},
                "min_salary_expectation_ceiling": {"p90": 200000, "direction": "lower_is_stricter"},
                "min_degree_level": {"p90": 2, "direction": "higher_is_stricter"},  # 0=none,1=BA,2=MA,3=PhD
            }
    return _KNOCKOUT_NORMS


class KnockoutQuestionPatternDetector:
    """AH-01: Flags ATS knockout-question thresholds set above market norms.

    AA's unique capability: it fills out the form and records the EXACT
    threshold the ATS enforces for binary knockout questions — data no
    academic study has access to, since they only observe outcomes, not
    the screening logic itself.

    For each threshold present in ctx.knockout_thresholds, compares against
    the 90th-percentile market norm loaded from knockout_norms.yaml. A
    threshold above the 90th percentile is unusually strict.
    """
    signal_type = SIG_AH_01

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        if not ctx.knockout_thresholds:
            return []

        norms = _load_knockout_norms()
        results: list[ResearchSignal] = []

        for question_type, observed_value in ctx.knockout_thresholds.items():
            norm = norms.get(question_type)
            if norm is None:
                continue
            p90 = norm.get("p90")
            direction = norm.get("direction", "higher_is_stricter")
            if p90 is None:
                continue

            is_outlier = (
                observed_value > p90 if direction == "higher_is_stricter"
                else observed_value < p90
            )
            if not is_outlier:
                continue

            deviation = abs(observed_value - p90) / max(abs(p90), 1.0)
            confidence = min(0.85, 0.55 + deviation * 0.5)

            evidence = (
                f"Knockout question '{question_type}' threshold = {observed_value} "
                f"(market 90th-percentile: {p90}, direction: {direction}). "
                f"Job: '{ctx.job_title[:40]}'"
            )
            results.append(ResearchSignal.create(
                signal_type=self.signal_type, severity=SEVERITY_CONCERN,
                confidence=confidence, evidence_text=evidence,
                platform=ctx.platform, jurisdiction=ctx.jurisdiction,
                company_name=ctx.company_name,
            ))
        return results


# ── AH-02: Readability and Complexity Asymmetry ───────────────────────────────

class ReadabilityAsymmetryDetector:
    """AH-02: Flags job descriptions with unusually high reading-level requirements.

    Uses zero-dependency Flesch-Kincaid Grade Level and Gunning Fog Index
    (implemented in research_statistics.py, matching the existing
    statistics/core.py zero-dependency philosophy).

    Hypothesis: deliberately complex descriptions selectively deter
    less-credentialed candidates regardless of actual job complexity.
    Flags descriptions requiring postgraduate-level reading (grade 16+)
    for roles that don't inherently require that (entry/mid level).
    """
    signal_type = SIG_AH_02
    _HIGH_GRADE_THRESHOLD: float = 16.0  # College graduate + reading level
    _MIN_WORD_COUNT: int = 50  # Too short for readability formulas to be meaningful

    _ENTRY_MID_KEYWORDS: frozenset[str] = frozenset({
        "entry", "junior", "associate", "coordinator", "assistant", "specialist",
    })

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        word_count = len(ctx.job_description.split())
        if word_count < self._MIN_WORD_COUNT:
            return []

        is_entry_mid = any(kw in ctx.title_lower for kw in self._ENTRY_MID_KEYWORDS)
        if not is_entry_mid:
            return []  # Complexity asymmetry is most meaningful for entry/mid roles

        fk_grade = flesch_kincaid_grade(ctx.job_description)
        fog_index = gunning_fog_index(ctx.job_description)

        if fk_grade < self._HIGH_GRADE_THRESHOLD:
            return []

        confidence = min(0.78, 0.45 + (fk_grade - self._HIGH_GRADE_THRESHOLD) * 0.05)
        evidence = (
            f"Entry/mid-level role '{ctx.job_title[:40]}' has Flesch-Kincaid grade "
            f"{fk_grade:.1f} (threshold: {self._HIGH_GRADE_THRESHOLD}), "
            f"Gunning Fog {fog_index:.1f}. Description complexity may selectively "
            f"deter qualified candidates with less formal education."
        )
        return [ResearchSignal.create(
            signal_type=self.signal_type, severity=SEVERITY_FLAG,
            confidence=confidence, evidence_text=evidence,
            platform=ctx.platform, jurisdiction=ctx.jurisdiction,
            company_name=ctx.company_name,
        )]


EXTENDED_DETECTORS: list[SignalDetector] = [
    ApplyWithNoATSDetector(),
    GeographicPayDiscriminationDetector(),
    TitleDescriptionMismatchDetector(),
    PhantomCompanyDetector(),
    KnockoutQuestionPatternDetector(),
    ReadabilityAsymmetryDetector(),
]

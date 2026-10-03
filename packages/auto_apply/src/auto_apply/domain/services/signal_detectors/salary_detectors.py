"""
Salary Transparency Signal Detectors (ST-01 through ST-04).

Academic grounding:
- DLA Piper (2026): 15+ US states/cities with mandatory salary disclosure.
- Beqom (2025): Low-wage workers remain exploited as smaller employers flout compliance.
- Colorado Equal Pay for Equal Work Act (2021), NYC Pay Transparency Law (2022),
  WA, CA, IL, MN, NJ, MA, HI, DC, MD and growing list of jurisdictions.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import yaml
from auto_apply.domain.constants import (
    SEVERITY_CONCERN, SEVERITY_FLAG, SEVERITY_VIOLATION,
    SIG_ST_01, SIG_ST_02, SIG_ST_03, SIG_ST_04,
)
from auto_apply.domain.services.signal_detectors.base import (
    DetectionContext, ResearchSignal, SignalDetector,
)


@dataclass(frozen=True)
class PayTransparencyLaw:
    """A single pay transparency jurisdiction's legal requirements."""
    jurisdiction_code: str
    jurisdiction_name: str
    effective_date: str
    threshold_employees: int
    requires_range: bool
    penalty_max_usd: int | None = None
    notes: str = ""


_PAY_TRANSPARENCY_LAWS: dict[str, PayTransparencyLaw] | None = None


def _load_transparency_laws() -> dict[str, PayTransparencyLaw]:
    global _PAY_TRANSPARENCY_LAWS
    if _PAY_TRANSPARENCY_LAWS is None:
        try:
            path = Path(__file__).parent.parent.parent.parent / "resources" / "research" / "pay_transparency_laws.yaml"
            with open(path) as f:
                raw = yaml.safe_load(f) or {}
            _PAY_TRANSPARENCY_LAWS = {
                code: PayTransparencyLaw(**data)
                for code, data in raw.items()
            }
        except Exception:
            # Fallback: core laws hardcoded for worst-case no-file scenario
            _PAY_TRANSPARENCY_LAWS = {
                "CO":  PayTransparencyLaw("CO",  "Colorado",      "2021-01-01", 1,  True, 500),
                "NYC": PayTransparencyLaw("NYC", "New York City",  "2022-11-01", 4,  True, 250000),
                "WA":  PayTransparencyLaw("WA",  "Washington",     "2023-01-01", 15, True, 1000),
                "CA":  PayTransparencyLaw("CA",  "California",     "2023-01-01", 15, True, None),
                "IL":  PayTransparencyLaw("IL",  "Illinois",       "2025-01-01", 15, True, None),
                "MN":  PayTransparencyLaw("MN",  "Minnesota",      "2025-01-01", 30, True, None),
                "NJ":  PayTransparencyLaw("NJ",  "New Jersey",     "2025-06-01", 10, True, None),
                "MA":  PayTransparencyLaw("MA",  "Massachusetts",  "2025-10-29", 25, True, None),
                "HI":  PayTransparencyLaw("HI",  "Hawaii",         "2024-01-01", 50, True, None),
                "DC":  PayTransparencyLaw("DC",  "Washington DC",  "2024-06-30", 1,  True, None),
                "MD":  PayTransparencyLaw("MD",  "Maryland",       "2024-10-01", 15, True, None),
            }
    return _PAY_TRANSPARENCY_LAWS


# Patterns that indicate salary is NOT disclosed
_NO_SALARY_INDICATORS: list[re.Pattern] = [
    re.compile(r"\bcompetitive\s+(?:salary|compensation|pay)\b", re.I),
    re.compile(r"\bmarket\s+(?:rate|salary|compensation)\b", re.I),
    re.compile(r"\bcommensurate\s+with\s+experience\b", re.I),
    re.compile(r"\btbd\b|\btba\b", re.I),
]


def _has_disclosed_salary(ctx: DetectionContext) -> bool:
    """True if any US-dollar pay figure was found on the posting."""
    return ctx.salary_min is not None or ctx.salary_max is not None


def _law_in_effect(law: PayTransparencyLaw, on: date) -> bool:
    """Whether the law was in effect on the posting's own date.

    ``on`` is DetectionContext.current_date — the capture date in a replay,
    the run date live — never the wall clock. Law data that cannot be
    parsed suppresses the finding: bad data must not fabricate a violation.
    """
    try:
        return on >= date.fromisoformat(law.effective_date)
    except ValueError:
        return False


def _is_single_figure(ctx: DetectionContext) -> bool:
    """Exactly one pay figure was disclosed (one-sided, or min == max)."""
    if ctx.salary_min is None and ctx.salary_max is None:
        return False
    if ctx.salary_min is None or ctx.salary_max is None:
        return True
    return ctx.salary_min == ctx.salary_max


class SalaryTransparencyLegalViolationDetector:
    """ST-01: records pay non-disclosure where a transparency law may require it.

    What AA can know about a posting: whether a US-dollar pay figure
    appeared in its text, which jurisdiction it names, and whether that
    jurisdiction's law was in effect on the capture date. What AA cannot
    know: the employer's size (most laws exempt small employers), and pay
    shown only in an image or a non-USD currency.

    So severity is "violation" only where the law covers every employer
    (threshold_employees <= 1 — employer size is not in question there);
    otherwise "concern", and the evidence text says plainly what was seen
    and what could not be known. A posting captured before its law took
    effect produces nothing. A jurisdiction whose law requires disclosure
    only on request (requires_range is false, e.g. RI) produces nothing:
    non-disclosure is not a finding there. A single pay figure where the
    law requires a range is a separate, weaker finding at severity "flag" —
    whether one figure complies is a legal question AA does not decide.
    """
    signal_type = SIG_ST_01

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        if ctx.jurisdiction is None:
            return []

        laws = _load_transparency_laws()
        law = laws.get(ctx.jurisdiction)
        if law is None or not law.requires_range:
            return []
        if not _law_in_effect(law, ctx.current_date):
            return []

        code = ctx.jurisdiction
        if _has_disclosed_salary(ctx):
            if _is_single_figure(ctx):
                figure = ctx.salary_max if ctx.salary_min is None else ctx.salary_min
                evidence = (
                    f"One pay figure shown (${figure:,}); {code}'s pay-transparency "
                    f"law requires covered employers to disclose a RANGE. Whether one "
                    f"figure complies is a legal question AA does not decide."
                )
                return [ResearchSignal.create(
                    signal_type=self.signal_type, severity=SEVERITY_FLAG,
                    confidence=0.6, evidence_text=evidence,
                    platform=ctx.platform, jurisdiction=code,
                    company_name=ctx.company_name,
                )]
            return []

        # Check if at least one "no salary" indicator is present (confirms omission)
        has_deflection = any(p.search(ctx.job_description) for p in _NO_SALARY_INDICATORS)
        confidence = 0.92 if has_deflection else 0.78

        if law.threshold_employees <= 1:
            evidence = (
                f"Observation: no US-dollar pay figure found in {code}. {code}'s "
                f"pay-transparency law (since {law.effective_date}) covers every "
                f"employer; AA reads text only, so image-only or non-USD pay would "
                f"not be seen."
            )
            severity = SEVERITY_VIOLATION
        else:
            evidence = (
                f"Observation, not a legal finding: no US-dollar pay figure found "
                f"in {code}. {code}'s law (since {law.effective_date}) covers "
                f"employers with {law.threshold_employees}+ employees; AA cannot "
                f"know employer size"
            ) + (
                ". Vague pay wording used instead." if has_deflection
                else " or image-only pay."
            )
            severity = SEVERITY_CONCERN

        return [ResearchSignal.create(
            signal_type=self.signal_type, severity=severity,
            confidence=confidence, evidence_text=evidence,
            platform=ctx.platform, jurisdiction=code,
            company_name=ctx.company_name,
        )]


class SalaryRangeWashingDetector:
    """ST-02: Detects salary ranges so wide they convey no real information.

    Colorado and other states require 'good faith' salary ranges. A range where
    max > 2x min is not a good faith range. Max > 3x min is egregious.
    """
    signal_type = SIG_ST_02
    _CONCERN_RATIO: float = 2.0
    _VIOLATION_RATIO: float = 3.0

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        if ctx.salary_min is None or ctx.salary_max is None:
            return []
        if ctx.salary_min <= 0:
            return []

        ratio = ctx.salary_max / ctx.salary_min
        if ratio < self._CONCERN_RATIO:
            return []

        severity = SEVERITY_VIOLATION if ratio >= self._VIOLATION_RATIO else SEVERITY_CONCERN
        confidence = min(0.95, 0.70 + (ratio - self._CONCERN_RATIO) * 0.08)

        evidence = (
            f"Salary range ${ctx.salary_min:,}–${ctx.salary_max:,} "
            f"(spread ratio: {ratio:.1f}x — "
            f"{'egregious range washing' if ratio >= self._VIOLATION_RATIO else 'range washing'}). "
            f"Good-faith pay-range laws (e.g. Colorado's) require meaningful ranges."
        )
        return [ResearchSignal.create(
            signal_type=self.signal_type, severity=severity,
            confidence=confidence, evidence_text=evidence,
            platform=ctx.platform, jurisdiction=ctx.jurisdiction,
            company_name=ctx.company_name,
        )]


# Prior salary history patterns — these fields on ATS forms are illegal in many jurisdictions
_SALARY_HISTORY_FIELD_PATTERNS: list[re.Pattern] = [
    re.compile(r"current\s+(?:salary|compensation|base|pay)", re.I),
    re.compile(r"previous\s+(?:salary|compensation|base|pay)", re.I),
    re.compile(r"most\s+recent\s+(?:salary|compensation)", re.I),
    re.compile(r"salary\s+history", re.I),
    re.compile(r"expected\s+(?:salary|compensation)", re.I),
    re.compile(r"desired\s+(?:salary|compensation)", re.I),
]

# Jurisdictions prohibiting salary history inquiries
_SALARY_HISTORY_BANNED_JURISDICTIONS: frozenset[str] = frozenset({
    "CA", "CO", "CT", "DC", "HI", "IL", "ME", "MD", "MA", "MI",
    "NV", "NJ", "NY", "NYC", "OR", "RI", "VT", "WA",
    # Cities (subset):
    "Chicago", "Cincinnati", "Louisville", "Montgomery_County_MD",
    "Philadelphia", "Pittsburgh", "Toledo",
})


class SalaryHistoryInquiryDetector:
    """ST-04: Detects ATS forms requesting prior salary in banned jurisdictions.

    Unlike other detectors, this one fires on FORM data (form_has_salary_history_field),
    not job description text. AA's form observation during application is the
    primary data source — no other tool collects this.

    This is direct, irrefutable evidence: the form field IS the violation.
    """
    signal_type = SIG_ST_04

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        if not ctx.form_has_salary_history_field:
            return []
        if ctx.jurisdiction is None:
            return []
        if ctx.jurisdiction not in _SALARY_HISTORY_BANNED_JURISDICTIONS:
            return []

        evidence = (
            f"ATS form in {ctx.jurisdiction} requests prior salary history. "
            f"This is prohibited under {ctx.jurisdiction} salary history ban law. "
            f"Platform: {ctx.platform or 'unknown'}"
        )
        return [ResearchSignal.create(
            signal_type=self.signal_type, severity=SEVERITY_VIOLATION,
            confidence=0.97,  # Form field IS the evidence — very high confidence
            evidence_text=evidence,
            platform=ctx.platform, jurisdiction=ctx.jurisdiction,
            company_name=ctx.company_name,
        )]


class BelowMarketSalaryDetector:
    """ST-03: Detects salary below the 25th percentile for equivalent requirements.

    Provides the first continuous, real-time measure of below-market salary
    prevalence — better than periodic surveys because it's computed from
    AA's accumulated corpus in real time.

    Requires `salary_corpus_p25_for_role` to be populated by the
    ResearchSignalAggregator from the salary_observations table (see
    SignalAggregator.compute_role_percentile()). If the corpus doesn't yet
    have enough samples for this role (sample_size < _MIN_CORPUS_SAMPLE),
    this detector returns no signal — it does not guess.
    """
    signal_type = SIG_ST_03
    _MIN_CORPUS_SAMPLE: int = 20  # Statistical minimum before trusting percentile

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        if ctx.salary_corpus_p25_for_role is None:
            return []
        if ctx.salary_corpus_sample_size < self._MIN_CORPUS_SAMPLE:
            return []

        salary = ctx.salary_max or ctx.salary_min
        if salary is None:
            return []

        if salary >= ctx.salary_corpus_p25_for_role:
            return []

        shortfall_pct = (ctx.salary_corpus_p25_for_role - salary) / ctx.salary_corpus_p25_for_role
        confidence = min(0.85, 0.55 + shortfall_pct * 0.6)
        severity = SEVERITY_VIOLATION if shortfall_pct > 0.30 else SEVERITY_CONCERN

        evidence = (
            f"Offered salary ${salary:,} is {shortfall_pct:.0%} below the corpus "
            f"25th percentile (${ctx.salary_corpus_p25_for_role:,.0f}, "
            f"n={ctx.salary_corpus_sample_size}) for equivalent role/skill requirements."
        )
        return [ResearchSignal.create(
            signal_type=self.signal_type, severity=severity,
            confidence=confidence, evidence_text=evidence,
            platform=ctx.platform, jurisdiction=ctx.jurisdiction,
            company_name=ctx.company_name,
        )]


SALARY_DETECTORS: list[SignalDetector] = [
    SalaryTransparencyLegalViolationDetector(),
    SalaryRangeWashingDetector(),
    SalaryHistoryInquiryDetector(),
    BelowMarketSalaryDetector(),
]

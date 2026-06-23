"""
Macro Analysis — Labor Market Macro-Signals (LM-01, LM-02, LM-03)

These signals are fundamentally different from the per-posting detectors in
signal_detectors/: they operate on AGGREGATED corpus data, not a single
DetectionContext. They run periodically (e.g. weekly) over accumulated
research_signals, salary_observations, and job_lifecycles tables.

ARCHITECTURE: This module is pure domain logic — it accepts plain Python
data structures (lists of dicts / dataclasses) and returns analysis results.
The adapter layer (signal_aggregator.py) is responsible for querying SQLite
and passing data in. This keeps macro analysis fully unit-testable with
synthetic data, with zero database dependency in the domain layer.

Academic grounding: BLS JOLTS shows job openings exceed hires by 2M+/month
since 2024 (LM-01). Ontario's 2026 mandatory-acknowledgment law is the first
of its kind, motivating LM-02. California AB 218 (2024) intersectionality
recognition motivates the demographic regression in LM-03.
"""
from __future__ import annotations

from dataclasses import dataclass

from auto_apply.domain.constants import (
    SEVERITY_FLAG,
    SIG_LM_01,
    SIG_LM_02,
    SIG_LM_03,
)
from auto_apply.domain.services.research_statistics import kendall_tau, percentile
from auto_apply.domain.services.signal_detectors.base import ResearchSignal


# ── LM-01: Sector Opening-to-Application Ratio ───────────────────────────────

@dataclass(frozen=True)
class SectorPostingCount:
    """Aggregate posting count for one sector (BLS SIC code) over a period.

    Attributes:
        sic_code: Standard Industrial Classification code.
        sector_name: Human-readable sector name.
        total_postings: Total unique postings observed by AA in this period.
        bls_jolts_openings: BLS JOLTS reported openings for this sector
            (external data, fetched separately — None if unavailable).
    """
    sic_code: str
    sector_name: str
    total_postings: int
    bls_jolts_openings: int | None = None


def compute_sector_opening_ratios(
    sector_counts: list[SectorPostingCount],
) -> list[ResearchSignal]:
    """LM-01: Compare AA's observed posting volume to BLS JOLTS data per sector.

    A sector where AA observes dramatically more unique postings than BLS
    JOLTS reports "openings" suggests either (a) AA is seeing duplicate/ghost
    postings BLS doesn't count, or (b) BLS undercounts that sector. Either
    finding is publishable — this is a validation/challenge of official
    labor statistics at the sector level.

    Args:
        sector_counts: Per-sector posting counts with optional BLS comparison data.

    Returns:
        Signals for sectors where the AA/BLS ratio is a statistical outlier
        (>2x or <0.5x the cross-sector median ratio).
    """
    ratios: list[tuple[SectorPostingCount, float]] = []
    for sc in sector_counts:
        if sc.bls_jolts_openings and sc.bls_jolts_openings > 0:
            ratios.append((sc, sc.total_postings / sc.bls_jolts_openings))

    if len(ratios) < 3:
        return []  # Need at least 3 sectors for a median comparison

    median_ratio = percentile([r for _, r in ratios], 50)
    results: list[ResearchSignal] = []

    for sc, ratio in ratios:
        if median_ratio == 0:
            continue
        deviation = ratio / median_ratio
        if 0.5 <= deviation <= 2.0:
            continue  # Within normal range

        evidence = (
            f"Sector '{sc.sector_name}' (SIC {sc.sic_code}): AA observed "
            f"{sc.total_postings} postings vs BLS JOLTS {sc.bls_jolts_openings} "
            f"openings (ratio {ratio:.2f}, cross-sector median {median_ratio:.2f}, "
            f"deviation {deviation:.1f}x)."
        )
        results.append(ResearchSignal.create(
            signal_type=SIG_LM_01, severity=SEVERITY_FLAG,
            confidence=0.60, evidence_text=evidence,
            job_category=sc.sic_code,
        ))
    return results


# ── LM-02: Application Black Hole Mapping ────────────────────────────────────

@dataclass(frozen=True)
class ResponseRateRecord:
    """Per-platform or per-company response rate observation.

    Attributes:
        entity_id: Anonymized company_id, or platform name (e.g. "greenhouse").
        entity_type: "company" or "platform".
        applications_sent: Total applications AA submitted to this entity.
        responses_received: Count that received ANY acknowledgment within 30 days
            (auto-reply, rejection, or interview request — any signal of receipt).
    """
    entity_id: str
    entity_type: str
    applications_sent: int
    responses_received: int

    @property
    def response_rate(self) -> float:
        """Fraction of applications that received any response."""
        if self.applications_sent == 0:
            return 0.0
        return self.responses_received / self.applications_sent


def compute_black_hole_index(
    records: list[ResponseRateRecord],
    min_applications: int = 10,
) -> list[ResearchSignal]:
    """LM-02: Identify platforms/companies with near-zero response rates.

    The "Application Black Hole" effect — candidates' applications vanish
    without any acknowledgment. This data directly supports legislative
    pushes for mandatory acknowledgment requirements (Ontario 2026 is first).

    Args:
        records: Per-entity response rate observations.
        min_applications: Minimum sample size before computing a rate
            (avoids flagging a single non-response as a 0% rate).

    Returns:
        Signals for entities with response_rate < 0.05 (5%) and
        sufficient sample size.
    """
    _BLACK_HOLE_THRESHOLD = 0.05
    results: list[ResearchSignal] = []

    for rec in records:
        if rec.applications_sent < min_applications:
            continue
        if rec.response_rate >= _BLACK_HOLE_THRESHOLD:
            continue

        confidence = min(0.85, 0.50 + (rec.applications_sent / 200.0))
        evidence = (
            f"{rec.entity_type.capitalize()} '{rec.entity_id}': "
            f"{rec.responses_received}/{rec.applications_sent} applications "
            f"received any acknowledgment ({rec.response_rate:.1%}, "
            f"threshold: {_BLACK_HOLE_THRESHOLD:.0%})."
        )
        results.append(ResearchSignal.create(
            signal_type=SIG_LM_02, severity=SEVERITY_FLAG,
            confidence=confidence, evidence_text=evidence,
            platform=rec.entity_id if rec.entity_type == "platform" else None,
            company_name=None,  # entity_id is already anonymized if a company
        ))
    return results


# ── LM-03: Geographic Pay Compression by Demographics ────────────────────────

@dataclass(frozen=True)
class MetroSalaryDemographic:
    """Per-metro salary observation paired with demographic data.

    Attributes:
        metro_area: MSA name.
        col_normalized_salary_median: Median COL-normalized salary observed in this metro.
        demographic_index: A single summary statistic representing the metro's
            demographic composition relevant to the hypothesis being tested
            (e.g., percent non-white population from Census ACS data).
            This is intentionally abstract — the caller supplies whatever
            demographic variable is being studied, with appropriate caveats.
    """
    metro_area: str
    col_normalized_salary_median: float
    demographic_index: float


def compute_geographic_pay_compression(
    records: list[MetroSalaryDemographic],
) -> list[ResearchSignal]:
    """LM-03: Correlate COL-normalized salary with metro demographic composition.

    Uses Kendall's Tau (monotone, non-parametric) rather than Pearson — salary
    compression need not be linear with demographic composition.

    IMPORTANT CAVEAT (must be included in any publication using this signal):
    This is an ECOLOGICAL correlation across metro areas. It identifies
    geographic patterns, NOT individual-level discrimination. Ecological
    correlations can suffer from the ecological fallacy — do not interpret
    results as claims about individual hiring decisions.

    Args:
        records: Per-metro salary and demographic observations.

    Returns:
        A single FLAG signal if |tau| > 0.3 and p < 0.05, with the ecological
        caveat embedded in the evidence text. Empty list otherwise.
    """
    if len(records) < 10:
        return []  # Kendall's tau needs reasonable n for the normal approximation

    salaries = [r.col_normalized_salary_median for r in records]
    demographics = [r.demographic_index for r in records]

    tau, p_value = kendall_tau(salaries, demographics)

    if abs(tau) <= 0.3 or p_value >= 0.05:
        return []

    direction = "negative" if tau < 0 else "positive"
    evidence = (
        f"Kendall's tau = {tau:.3f} (p={p_value:.4f}, n={len(records)}) between "
        f"COL-normalized salary and metro demographic index — {direction} "
        f"correlation. ECOLOGICAL CORRELATION ONLY: identifies geographic "
        f"patterns across {len(records)} metros, NOT individual-level "
        f"discrimination. Subject to ecological fallacy — do not generalize "
        f"to individual hiring decisions without individual-level data."
    )
    return [ResearchSignal.create(
        signal_type=SIG_LM_03, severity=SEVERITY_FLAG,
        confidence=min(0.65, abs(tau)), evidence_text=evidence,
    )]

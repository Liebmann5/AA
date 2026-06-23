"""
Ghost Job Signal Detectors (GJ-01 through GJ-05).

Academic grounding: Clarify Capital (Jan 2025) — 1 in 3 employers admit posting
with no intention to hire. Greenhouse (2024) — 18-22% of online listings are fake.
SHRM average time-to-fill: 41 days across all roles.

All detectors are pure functions — no I/O, no state, fully testable.
"""
from __future__ import annotations

from auto_apply.domain.constants import (
    SEVERITY_CONCERN,
    SEVERITY_FLAG,
    SEVERITY_VIOLATION,
    SIG_GJ_01, SIG_GJ_02, SIG_GJ_03, SIG_GJ_04, SIG_GJ_05,
)
from auto_apply.domain.services.signal_detectors.base import (
    DetectionContext,
    ResearchSignal,
    SignalDetector,
)

# SHRM average time-to-fill by role category (days).
# Source: SHRM Talent Acquisition Benchmarking Report 2024.
_FILL_TIME_THRESHOLDS: dict[str, int] = {
    "default": 41,
    "engineering": 52,
    "executive": 68,
    "healthcare": 49,
    "retail": 24,
    "warehouse": 18,
    "seasonal": 14,
}

# Evergreen roles that legitimately stay open indefinitely.
_EVERGREEN_ROLE_KEYWORDS: frozenset[str] = frozenset({
    "retail", "warehouse", "cashier", "seasonal", "part-time", "part time",
    "delivery", "driver", "food service", "housekeeping",
})


class PostingAgeAnomalyDetector:
    """GJ-01: Detects postings that have been live longer than typical fill times."""

    signal_type = SIG_GJ_01

    # Days thresholds: (threshold_days, severity, confidence)
    _THRESHOLDS: list[tuple[int, str, float]] = [
        (120, SEVERITY_VIOLATION, 0.88),
        (90,  SEVERITY_CONCERN,   0.72),
        (41,  SEVERITY_FLAG,      0.55),
    ]

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        if ctx.days_live is None:
            return []

        # Exempt evergreen roles
        title_lower = ctx.title_lower
        if any(kw in title_lower for kw in _EVERGREEN_ROLE_KEYWORDS):
            return []

        # Determine appropriate threshold for this role category
        threshold = _FILL_TIME_THRESHOLDS["default"]
        for kw, days in _FILL_TIME_THRESHOLDS.items():
            if kw in title_lower:
                threshold = days
                break

        if ctx.days_live <= threshold:
            return []

        # Find the highest applicable severity
        severity, confidence = SEVERITY_FLAG, 0.55
        for min_days, sev, conf in self._THRESHOLDS:
            if ctx.days_live >= min_days:
                severity, confidence = sev, conf
                break

        evidence = (
            f"Posting live {ctx.days_live} days "
            f"(SHRM fill threshold for this role: {threshold} days)"
        )
        return [
            ResearchSignal.create(
                signal_type=self.signal_type,
                severity=severity,
                confidence=confidence,
                evidence_text=evidence,
                platform=ctx.platform,
                jurisdiction=ctx.jurisdiction,
                company_name=ctx.company_name,
            )
        ]


class FreshnessLaunderingDetector:
    """GJ-02: Detects the same job appearing across platforms with different posting dates.

    This is 'freshness laundering' — reposting old jobs to appear newly listed,
    gaming job board 'new this week' algorithms. When the same structural hash
    appears on Platform A as '3 days old' and Platform B as '6 weeks old',
    one of those timestamps is manufactured.
    """

    signal_type = SIG_GJ_02

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        if ctx.times_seen_cross_platform < 2:
            return []
        if not ctx.previous_posting_dates:
            return []

        # The most recent and least recent dates we've seen this hash
        dates_sorted = sorted(ctx.previous_posting_dates)
        date_spread_days = (dates_sorted[-1] - dates_sorted[0]).days

        if date_spread_days < 14:
            return []  # Less than 2 weeks difference — might just be propagation delay

        confidence = min(0.95, 0.60 + (date_spread_days / 180.0) * 0.35)
        severity = SEVERITY_VIOLATION if date_spread_days > 60 else SEVERITY_CONCERN

        evidence = (
            f"Identical job hash seen across {ctx.times_seen_cross_platform} platforms "
            f"with posting date spread of {date_spread_days} days "
            f"(earliest: {dates_sorted[0]}, latest: {dates_sorted[-1]})"
        )
        return [
            ResearchSignal.create(
                signal_type=self.signal_type,
                severity=severity,
                confidence=confidence,
                evidence_text=evidence,
                platform=ctx.platform,
                jurisdiction=ctx.jurisdiction,
                company_name=ctx.company_name,
            )
        ]


class RefillWithoutHireDetector:
    """GJ-03: Detects roles that cycle through open/closed/open repeatedly.

    A role that appears, disappears (presumably filled), then reappears with
    the same description 3+ times in 6 months suggests either impossibly high
    turnover or permanent ghost posting for pipeline building.
    """

    signal_type = SIG_GJ_03
    _CYCLE_THRESHOLD: int = 3

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        cycle_count = len(ctx.previous_posting_dates)
        if cycle_count < self._CYCLE_THRESHOLD:
            return []

        confidence = min(0.92, 0.65 + (cycle_count - self._CYCLE_THRESHOLD) * 0.05)
        evidence = (
            f"Role '{ctx.job_title[:60]}' has cycled open/closed "
            f"{cycle_count} times (threshold: {self._CYCLE_THRESHOLD})"
        )
        return [
            ResearchSignal.create(
                signal_type=self.signal_type,
                severity=SEVERITY_CONCERN,
                confidence=confidence,
                evidence_text=evidence,
                platform=ctx.platform,
                jurisdiction=ctx.jurisdiction,
                company_name=ctx.company_name,
            )
        ]


class EarningsSeasonClusteringDetector:
    """GJ-05: Correlates posting spikes with earnings season for public companies.

    Hypothesis: Companies post jobs during earnings windows to signal growth to
    investors, with no genuine hiring intent. This is a novel finding not yet
    published at scale. Requires cross-referencing with SEC filing dates.

    Note: This detector emits FLAG (not VIOLATION) — correlation, not causation.
    Requires enrichment data (is_earnings_window) from an external data source.
    """

    signal_type = SIG_GJ_05

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        # This detector requires context enrichment from SEC EDGAR data.
        # It fires only when the orchestration layer has flagged this company
        # as being in an earnings window. The flag is set via DetectionContext
        # enrichment, represented here by a convention: if company_has_warn_filing
        # is True and days_live < 30 and posting appeared within 2 weeks of earnings.
        # Full implementation requires SEC EDGAR integration (see P3 roadmap).
        # For now, this detector is structurally present but emits no signals
        # until the enrichment pipeline is wired.
        return []


# ── Registry ──────────────────────────────────────────────────────────────────

GHOST_JOB_DETECTORS: list[SignalDetector] = [
    PostingAgeAnomalyDetector(),
    FreshnessLaunderingDetector(),
    RefillWithoutHireDetector(),
    EarningsSeasonClusteringDetector(),
]

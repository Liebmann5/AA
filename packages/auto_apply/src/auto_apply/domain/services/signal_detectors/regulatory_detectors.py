"""
Regulatory Non-Compliance Detectors (RC-01 through RC-03).
"""
from __future__ import annotations
import re
from auto_apply.domain.constants import (
    SEVERITY_CONCERN, SEVERITY_VIOLATION,
    SIG_RC_01, SIG_RC_02, SIG_RC_03,
)
from auto_apply.domain.services.signal_detectors.base import (
    DetectionContext, ResearchSignal, SignalDetector,
)

# ── Jurisdictions where non-competes are void ─────────────────────────────────
_NON_COMPETE_VOID_JURISDICTIONS: frozenset[str] = frozenset({
    "CA",  # Cal. Bus. & Prof. Code § 16600
    "MN",  # Void since 2023
    "ND",  # North Dakota — void
    "OK",  # Oklahoma — void
    "DC",  # DC non-compete ban 2021
})
_NON_COMPETE_RESTRICTED_JURISDICTIONS: frozenset[str] = frozenset({
    "IL", "MA", "NH", "OR", "WA", "CO", "MD", "VA",
})

_NON_COMPETE_PATTERN = re.compile(
    r"\bnon.?compete\b|\bnon.?solicitation\b|\brestrict(?:ions?)?\s+on\s+future\s+employment\b",
    re.I,
)

_UNPAID_INTERNSHIP_PATTERN = re.compile(r"\bunpaid\s+intern(?:ship)?\b", re.I)

# FLSA primary beneficiary test indicators (presence = likely employee, not intern)
_PRODUCTION_WORK_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bwill\s+(?:build|develop|create|manage|lead|own)\b", re.I),
    re.compile(r"\bresponsible\s+for\s+(?:production|live|customer-facing)\b", re.I),
    re.compile(r"\bno\s+academic\s+credit\s+required\b", re.I),
    re.compile(r"\byear.?round\b|\bongoing\b", re.I),
]


class WarnActPostingDetector:
    """RC-01: Detects companies posting jobs while having active WARN Act filings.

    WARN Act filings are public (DOL database). Cross-referencing with job postings
    proves that 'openings' exist simultaneously with mass layoffs — direct evidence
    of ghost job mechanisms or deceptive hiring practices.
    """
    signal_type = SIG_RC_01

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        # Fires only when enrichment pipeline has set company_has_warn_filing.
        if not ctx.company_has_warn_filing:
            return []
        evidence = (
            f"Company '{ctx.company_name or 'unknown'}' has an active WARN Act filing "
            f"while posting for '{ctx.job_title[:60]}'. "
            f"Simultaneous layoff + hiring activity suggests ghost posting or department-level contradiction."
        )
        return [ResearchSignal.create(
            signal_type=self.signal_type, severity=SEVERITY_VIOLATION,
            confidence=0.88, evidence_text=evidence,
            platform=ctx.platform, jurisdiction=ctx.jurisdiction,
            company_name=ctx.company_name,
        )]


class NonCompeteIllegalityDetector:
    """RC-02: Detects non-compete clauses in jurisdictions where they are void."""
    signal_type = SIG_RC_02

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        if ctx.jurisdiction is None:
            return []
        match = _NON_COMPETE_PATTERN.search(ctx.job_description)
        if not match:
            return []

        if ctx.jurisdiction in _NON_COMPETE_VOID_JURISDICTIONS:
            evidence = (
                f"Non-compete/non-solicitation clause in {ctx.jurisdiction} "
                f"where non-competes are VOID by statute. "
                f"Text: '{match.group(0)[:80]}'"
            )
            return [ResearchSignal.create(
                signal_type=self.signal_type, severity=SEVERITY_VIOLATION,
                confidence=0.90, evidence_text=evidence,
                platform=ctx.platform, jurisdiction=ctx.jurisdiction,
                company_name=ctx.company_name,
            )]
        elif ctx.jurisdiction in _NON_COMPETE_RESTRICTED_JURISDICTIONS:
            evidence = (
                f"Non-compete clause in {ctx.jurisdiction} (restricted jurisdiction). "
                f"Requires review for enforceability."
            )
            return [ResearchSignal.create(
                signal_type=self.signal_type, severity=SEVERITY_CONCERN,
                confidence=0.75, evidence_text=evidence,
                platform=ctx.platform, jurisdiction=ctx.jurisdiction,
                company_name=ctx.company_name,
            )]
        return []


class UnpaidInternshipFLSADetector:
    """RC-03: Detects unpaid internships that fail the FLSA primary beneficiary test.

    The FLSA requires interns to be the 'primary beneficiary' of the experience.
    If the work primarily benefits the employer (production code, live systems,
    displacing regular employees), the intern is legally an employee and must be paid.
    """
    signal_type = SIG_RC_03

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        if not _UNPAID_INTERNSHIP_PATTERN.search(ctx.job_description):
            return []

        # Count how many FLSA test factors suggest employer-beneficiary (failed test)
        failed_factors = sum(
            1 for p in _PRODUCTION_WORK_PATTERNS if p.search(ctx.job_description)
        )

        if failed_factors < 2:
            return []

        confidence = min(0.90, 0.60 + failed_factors * 0.08)
        evidence = (
            f"Unpaid internship with {failed_factors}/4 FLSA test factors "
            f"indicating employer-primary-beneficiary (potential wage theft). "
            f"Role: '{ctx.job_title[:50]}'"
        )
        return [ResearchSignal.create(
            signal_type=self.signal_type, severity=SEVERITY_VIOLATION,
            confidence=confidence, evidence_text=evidence,
            platform=ctx.platform, jurisdiction=ctx.jurisdiction,
            company_name=ctx.company_name,
        )]


REGULATORY_DETECTORS: list[SignalDetector] = [
    WarnActPostingDetector(),
    NonCompeteIllegalityDetector(),
    UnpaidInternshipFLSADetector(),
]

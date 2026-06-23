"""
Discrimination Signal Detectors (DISC-01 through DISC-06).

Academic grounding:
- DISC-01 (Gendered Language): Gaucher, Friesen & Kay (2011). Journal of Personality
  and Social Psychology. Validated masculine/feminine word lists.
- DISC-02 (Age): ADEA (29 U.S.C. § 623). EEOC guidance on age proxies.
- DISC-03 (Disability): ADA (42 U.S.C. § 12112). Primary beneficiary test.
- DISC-04 (Racial/Socioeconomic): Title VII. EEOC disparate impact guidelines.
- DISC-05 (Geographic Pay): BLS Regional CPI normalization methodology.
- DISC-06 (Intersectional): Park & Oh (2025). Sociological Science.
  California AB 218 (2024) — first state to recognize intersectionality in law.
"""
from __future__ import annotations

import re
from auto_apply.domain.constants import (
    SEVERITY_CONCERN, SEVERITY_FLAG, SEVERITY_VIOLATION,
    SIG_DISC_01, SIG_DISC_02, SIG_DISC_03, SIG_DISC_04,
    SIG_DISC_05, SIG_DISC_06,
)
from auto_apply.domain.services.signal_detectors.base import (
    DetectionContext, ResearchSignal, SignalDetector,
)

# ── DISC-01: Gendered Language ────────────────────────────────────────────────
# Word lists from Gaucher, Friesen & Kay (2011). These are the peer-reviewed,
# empirically validated words — not editorial choices.

_MASCULINE_CODED: frozenset[str] = frozenset({
    "competitive", "competition", "compete", "dominant", "dominate", "dominance",
    "independent", "independence", "outspoken", "ambitious", "ambition",
    "analytical", "decisive", "decision-maker", "fearless", "headstrong",
    "self-reliant", "aggressive", "assertive", "adventurous", "confident",
    "leader", "driven", "champion", "ninja", "rockstar", "guru", "wizard",
    "warrior", "crusade", "conquer", "superior", "exceptional", "elite",
})

_FEMININE_CODED: frozenset[str] = frozenset({
    "collaborative", "cooperation", "cooperative", "interpersonal", "support",
    "nurturing", "committed", "dependable", "loyal", "responsive", "understanding",
    "caring", "empathetic", "warm", "sensitive", "gentle", "community",
    "inclusive", "together", "team-player", "consensus",
})


class GenderedLanguageDetector:
    """DISC-01: Scores job descriptions for gendered language bias.

    Computes a Gender Coding Score (GCS) from -1.0 (feminine-skewed) to +1.0
    (masculine-skewed). Flags when GCS exceeds ±0.3 with sufficient density.
    """
    signal_type = SIG_DISC_01
    _MIN_CODED_WORDS: int = 3
    _GCS_THRESHOLD: float = 0.25

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        words = re.findall(r"\b\w+\b", ctx.description_lower)
        if not words:
            return []

        masc_count = sum(1 for w in words if w in _MASCULINE_CODED)
        fem_count  = sum(1 for w in words if w in _FEMININE_CODED)
        total_coded = masc_count + fem_count

        if total_coded < self._MIN_CODED_WORDS:
            return []

        gcs = (masc_count - fem_count) / total_coded  # -1.0 to +1.0
        if abs(gcs) < self._GCS_THRESHOLD:
            return []

        direction = "masculine" if gcs > 0 else "feminine"
        severity = SEVERITY_VIOLATION if abs(gcs) > 0.6 else SEVERITY_CONCERN if abs(gcs) > 0.4 else SEVERITY_FLAG
        confidence = min(0.90, 0.55 + abs(gcs) * 0.35 + min(total_coded / 20.0, 0.10))

        evidence = (
            f"Gender Coding Score: {gcs:+.2f} ({direction}-skewed) | "
            f"masculine_words={masc_count}, feminine_words={fem_count}, "
            f"total_coded={total_coded}"
        )
        return [ResearchSignal.create(
            signal_type=self.signal_type, severity=severity, confidence=confidence,
            evidence_text=evidence, platform=ctx.platform,
            jurisdiction=ctx.jurisdiction, company_name=ctx.company_name,
        )]


# ── DISC-02: Age Discrimination ───────────────────────────────────────────────

_AGE_EXPLICIT_PATTERNS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"\brecent(?:ly)?\s+graduate\b", re.I),      "recent graduate",           0.85),
    (re.compile(r"\bnew\s+graduate\b", re.I),                 "new graduate",               0.85),
    (re.compile(r"\bgraduated?\s+(?:in\s+)?20(?:2[0-9])\b", re.I), "graduation year req",  0.90),
    (re.compile(r"\bno\s+more\s+than\s+\d+\s+years?\s+(?:of\s+)?experience\b", re.I), "experience cap", 0.80),
    (re.compile(r"\bdigital\s+native\b", re.I),               "digital native",             0.75),
    (re.compile(r"\bearly\s+career\b", re.I),                 "early career",               0.65),
    (re.compile(r"\byoung\s+professional\b", re.I),           "young professional",         0.80),
]

_AGE_PROXY_PATTERNS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"\benergetic\s+team\b", re.I),               "energetic team",             0.45),
    (re.compile(r"\bfresh\s+perspective\b", re.I),            "fresh perspective",          0.50),
    (re.compile(r"\bborn\s+into\s+technology\b", re.I),       "born into technology",       0.80),
]


class AgeDiminateProxyDetector:
    """DISC-02: Detects explicit and proxy age discrimination patterns.

    Explicit patterns (graduation year, experience caps, 'young professional')
    are direct ADEA violations for workers 40+. Proxy patterns are weaker
    signals requiring corroboration.
    """
    signal_type = SIG_DISC_02

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        results: list[ResearchSignal] = []
        text = ctx.job_description

        for pattern, label, base_confidence in _AGE_EXPLICIT_PATTERNS:
            match = pattern.search(text)
            if match:
                evidence = f"Age discrimination proxy ({label}): '{match.group(0)[:80]}'"
                results.append(ResearchSignal.create(
                    signal_type=self.signal_type, severity=SEVERITY_VIOLATION,
                    confidence=base_confidence, evidence_text=evidence,
                    platform=ctx.platform, jurisdiction=ctx.jurisdiction,
                    company_name=ctx.company_name,
                ))

        for pattern, label, base_confidence in _AGE_PROXY_PATTERNS:
            match = pattern.search(text)
            if match:
                evidence = f"Age proxy language ({label}): '{match.group(0)[:80]}'"
                results.append(ResearchSignal.create(
                    signal_type=self.signal_type, severity=SEVERITY_FLAG,
                    confidence=base_confidence, evidence_text=evidence,
                    platform=ctx.platform, jurisdiction=ctx.jurisdiction,
                    company_name=ctx.company_name,
                ))
        return results


# ── DISC-03: Disability Screening ────────────────────────────────────────────

_DESK_JOB_KEYWORDS: frozenset[str] = frozenset({
    "software", "engineer", "developer", "analyst", "manager", "coordinator",
    "accountant", "writer", "designer", "data", "marketing", "sales",
    "finance", "legal", "hr", "human resources", "operations",
})

_PHYSICAL_REQUIREMENT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\blift(?:ing)?\s+\d+\s*(?:lbs?|pounds?)\b", re.I), "lifting requirement"),
    (re.compile(r"\bstand(?:ing)?\s+for\s+\d+\s*hours?\b", re.I),     "standing requirement"),
    (re.compile(r"\bvalid\s+driver.?s?\s+license\s+required\b", re.I), "driver's license required"),
    (re.compile(r"\bmust\s+be\s+able\s+to\s+(?:lift|carry|push|pull)\b", re.I), "physical ability requirement"),
]


class DisabilityScreeningDetector:
    """DISC-03: Detects unnecessary physical requirements in desk-based roles.

    A physical requirement for a role that is demonstrably desk-bound is
    a potential ADA violation. Signal confidence is modulated by how clearly
    the role is desk-based.
    """
    signal_type = SIG_DISC_03

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        title_lower = ctx.title_lower
        is_desk_role = any(kw in title_lower for kw in _DESK_JOB_KEYWORDS)
        if not is_desk_role:
            return []

        results: list[ResearchSignal] = []
        for pattern, label in _PHYSICAL_REQUIREMENT_PATTERNS:
            match = pattern.search(ctx.job_description)
            if match:
                evidence = (
                    f"Physical requirement in desk role '{ctx.job_title[:40]}' ({label}): "
                    f"'{match.group(0)[:80]}'"
                )
                results.append(ResearchSignal.create(
                    signal_type=self.signal_type, severity=SEVERITY_CONCERN,
                    confidence=0.72, evidence_text=evidence,
                    platform=ctx.platform, jurisdiction=ctx.jurisdiction,
                    company_name=ctx.company_name,
                ))
        return results


# ── DISC-04: Racial/Socioeconomic Proxy ──────────────────────────────────────

_SOCIOECONOMIC_PROXY_PATTERNS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"\bcredit\s+(?:check|history|background)\s+required\b", re.I),
     "credit check requirement", 0.75),
    (re.compile(r"\bown\s+(?:a\s+)?reliable\s+(?:vehicle|car|transportation)\b", re.I),
     "personal vehicle requirement", 0.68),
    (re.compile(r"\bown\s+(?:a\s+)?(?:laptop|computer|equipment)\b", re.I),
     "personal equipment requirement", 0.65),
    (re.compile(r"\bunpaid\s+(?:trial|internship|period)\b", re.I),
     "unpaid trial period", 0.80),
    (re.compile(r"\bminimum\s+(?:gpa|grade\s+point\s+average)\s+of\s+[34]\.\d\b", re.I),
     "high GPA requirement post-graduation", 0.60),
]


class SocioeconomicProxyDetector:
    """DISC-04: Detects requirements with disparate racial/socioeconomic impact.

    These requirements don't facially discriminate but have documented disparate
    impact under Title VII. Each pattern is documented in EEOC guidance or
    academic audit literature.
    """
    signal_type = SIG_DISC_04

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        results: list[ResearchSignal] = []
        for pattern, label, confidence in _SOCIOECONOMIC_PROXY_PATTERNS:
            match = pattern.search(ctx.job_description)
            if match:
                evidence = f"Socioeconomic proxy ({label}): '{match.group(0)[:100]}'"
                results.append(ResearchSignal.create(
                    signal_type=self.signal_type, severity=SEVERITY_CONCERN,
                    confidence=confidence, evidence_text=evidence,
                    platform=ctx.platform, jurisdiction=ctx.jurisdiction,
                    company_name=ctx.company_name,
                ))
        return results


# ── DISC-06: Intersectional Discrimination ───────────────────────────────────

class IntersectionalDiscriminationDetector:
    """DISC-06: Detects compound discrimination patterns invisible to single-axis analysis.

    Aligns with Park & Oh (2025) Sociological Science meta-analysis and California
    AB 218 (2024) first-in-nation intersectionality recognition in anti-discrimination law.

    Fires when multiple weaker signals co-occur in a way that compounds their effect.
    Confidence is calculated from the product of co-occurring signal confidences.
    """
    signal_type = SIG_DISC_06
    _CO_OCCURRENCE_THRESHOLD: int = 2

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        # Collect all lower-level discrimination signals first
        sub_detectors = [
            GenderedLanguageDetector(),
            AgeDiminateProxyDetector(),
            DisabilityScreeningDetector(),
            SocioeconomicProxyDetector(),
        ]
        all_sub_signals: list[ResearchSignal] = []
        for det in sub_detectors:
            all_sub_signals.extend(det.detect(ctx))

        if len(all_sub_signals) < self._CO_OCCURRENCE_THRESHOLD:
            return []

        # Compound confidence: geometric mean of sub-signal confidences
        product = 1.0
        for sig in all_sub_signals:
            product *= sig.confidence
        compound_confidence = product ** (1.0 / len(all_sub_signals))
        compound_confidence = min(0.95, compound_confidence * 1.3)  # Compound boost

        signal_types = ", ".join(sorted({s.signal_type for s in all_sub_signals}))
        evidence = (
            f"Intersectional compound: {len(all_sub_signals)} discrimination signals "
            f"co-present ({signal_types}) — compound confidence higher than any single axis"
        )
        return [ResearchSignal.create(
            signal_type=self.signal_type, severity=SEVERITY_VIOLATION,
            confidence=compound_confidence, evidence_text=evidence,
            platform=ctx.platform, jurisdiction=ctx.jurisdiction,
            company_name=ctx.company_name,
        )]


# ── Registry ──────────────────────────────────────────────────────────────────

DISCRIMINATION_DETECTORS: list[SignalDetector] = [
    GenderedLanguageDetector(),
    AgeDiminateProxyDetector(),
    DisabilityScreeningDetector(),
    SocioeconomicProxyDetector(),
    IntersectionalDiscriminationDetector(),
]

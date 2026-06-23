"""
Dark Pattern Detectors (DP-01 through DP-05).
"""
from __future__ import annotations
import re
from pathlib import Path
import yaml
from auto_apply.domain.constants import (
    SEVERITY_CONCERN, SEVERITY_FLAG, SEVERITY_VIOLATION,
    SIG_DP_01, SIG_DP_02, SIG_DP_03, SIG_DP_04, SIG_DP_05,
)
from auto_apply.domain.services.signal_detectors.base import (
    DetectionContext, ResearchSignal, SignalDetector,
)

# ── Obfuscation lexicon (loaded lazily from YAML) ─────────────────────────────
_OBFUSCATION_LEXICON: list[dict] | None = None

def _load_obfuscation_lexicon() -> list[dict]:
    global _OBFUSCATION_LEXICON
    if _OBFUSCATION_LEXICON is None:
        try:
            path = Path(__file__).parent.parent.parent.parent / "resources" / "research" / "obfuscation_lexicon.yaml"
            with open(path) as f:
                _OBFUSCATION_LEXICON = yaml.safe_load(f) or []
        except Exception:
            _OBFUSCATION_LEXICON = [
                {"pattern": "work hard and play hard", "meaning": "unpaid overtime culture", "weight": 0.75},
                {"pattern": "wear many hats", "meaning": "understaffed, multiple jobs one salary", "weight": 0.80},
                {"pattern": "unlimited pto", "meaning": "no accrued PTO, peer pressure prevents use", "weight": 0.70},
                {"pattern": "fast-paced environment", "meaning": "understaffed unsustainable pace", "weight": 0.65},
                {"pattern": "like a family", "meaning": "interpersonal boundary violations common", "weight": 0.72},
                {"pattern": "self-starter", "meaning": "no support or training provided", "weight": 0.60},
                {"pattern": "competitive salary", "meaning": "below-market, transparency avoidance", "weight": 0.65},
                {"pattern": "equity opportunity", "meaning": "likely worthless options at private co", "weight": 0.68},
                {"pattern": "passionate about our mission", "meaning": "mission used to justify low pay", "weight": 0.72},
                {"pattern": "startup culture", "meaning": "long hours, low stability, no processes", "weight": 0.65},
                {"pattern": "results-only work environment", "meaning": "no labor protections applied", "weight": 0.70},
                {"pattern": "high-energy environment", "meaning": "understaffed, unsustainable pace", "weight": 0.68},
            ]
    return _OBFUSCATION_LEXICON


class ToxicCultureObfuscationDetector:
    """DP-02: Scores job descriptions for obfuscated exploitative conditions.

    Each matched pattern adds to a composite Toxicity Score. Posts above
    threshold are flagged with the accumulated evidence.
    """
    signal_type = SIG_DP_02
    _FLAG_THRESHOLD: float = 0.65
    _CONCERN_THRESHOLD: float = 1.20
    _VIOLATION_THRESHOLD: float = 2.00

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        lexicon = _load_obfuscation_lexicon()
        matched: list[dict] = []
        desc_lower = ctx.description_lower

        for entry in lexicon:
            if entry["pattern"].lower() in desc_lower:
                matched.append(entry)

        if not matched:
            return []

        toxicity_score = sum(e["weight"] for e in matched)

        if toxicity_score < self._FLAG_THRESHOLD:
            return []

        if toxicity_score >= self._VIOLATION_THRESHOLD:
            severity = SEVERITY_VIOLATION
        elif toxicity_score >= self._CONCERN_THRESHOLD:
            severity = SEVERITY_CONCERN
        else:
            severity = SEVERITY_FLAG

        confidence = min(0.90, 0.55 + toxicity_score * 0.12)
        patterns_found = "; ".join(f"'{m['pattern']}' ({m['meaning']})" for m in matched[:3])
        evidence = f"Toxicity Score {toxicity_score:.2f} | Patterns: {patterns_found}"

        return [ResearchSignal.create(
            signal_type=self.signal_type, severity=severity,
            confidence=confidence, evidence_text=evidence,
            platform=ctx.platform, jurisdiction=ctx.jurisdiction,
            company_name=ctx.company_name,
        )]


class UnpaidLaborExtractionDetector:
    """DP-03: Detects application processes that extract unpaid labor.

    FTC guidance: take-home tests >2 hours for hourly-equivalent work
    is in wage-theft territory. Portfolio requirements for entry-level
    roles exploit candidates who cannot afford to build spec work.
    """
    signal_type = SIG_DP_03
    _EXCESSIVE_HOURS_THRESHOLD: int = 4  # Hours

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        results: list[ResearchSignal] = []

        if (ctx.estimated_completion_minutes is not None and
                ctx.estimated_completion_minutes > self._EXCESSIVE_HOURS_THRESHOLD * 60):
            hours = ctx.estimated_completion_minutes / 60
            evidence = (
                f"Application estimated completion: {hours:.1f} hours "
                f"(FTC guidance threshold: {self._EXCESSIVE_HOURS_THRESHOLD} hours)"
            )
            results.append(ResearchSignal.create(
                signal_type=self.signal_type, severity=SEVERITY_CONCERN,
                confidence=0.80, evidence_text=evidence,
                platform=ctx.platform, jurisdiction=ctx.jurisdiction,
                company_name=ctx.company_name,
            ))

        # Detect take-home test language
        takehome_pattern = re.compile(
            r"\btake.?home\s+(?:test|project|assignment|challenge|exercise)\b", re.I
        )
        match = takehome_pattern.search(ctx.job_description)
        if match:
            evidence = f"Take-home assessment required: '{match.group(0)[:80]}'"
            results.append(ResearchSignal.create(
                signal_type=self.signal_type, severity=SEVERITY_FLAG,
                confidence=0.65, evidence_text=evidence,
                platform=ctx.platform, jurisdiction=ctx.jurisdiction,
                company_name=ctx.company_name,
            ))
        return results


class ApplicationBloatDetector:
    """DP-04: Detects excessive application complexity relative to role seniority.

    Correlates with candidate attrition by socioeconomic status — candidates who
    cannot take time off work are systematically filtered out by bloated processes.
    """
    signal_type = SIG_DP_04

    # (max_fields_for_severity, severity) for entry-level roles
    _ENTRY_THRESHOLDS: list[tuple[int, str]] = [
        (50, SEVERITY_VIOLATION),
        (35, SEVERITY_CONCERN),
        (25, SEVERITY_FLAG),
    ]
    _SENIOR_THRESHOLDS: list[tuple[int, str]] = [
        (70, SEVERITY_VIOLATION),
        (55, SEVERITY_CONCERN),
        (40, SEVERITY_FLAG),
    ]

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        if ctx.form_field_count is None:
            return []

        is_entry = any(kw in ctx.title_lower for kw in ("junior", "entry", "associate", "intern"))
        thresholds = self._ENTRY_THRESHOLDS if is_entry else self._SENIOR_THRESHOLDS

        severity = None
        for max_fields, sev in thresholds:
            if ctx.form_field_count >= max_fields:
                severity = sev
                break

        if severity is None:
            return []

        evidence = (
            f"Application form has {ctx.form_field_count} fields "
            f"({ctx.form_required_fields or '?'} required) for "
            f"{'entry-level' if is_entry else 'senior-level'} role '{ctx.job_title[:40]}'"
        )
        confidence = min(0.88, 0.60 + ctx.form_field_count / 100.0)
        return [ResearchSignal.create(
            signal_type=self.signal_type, severity=severity,
            confidence=confidence, evidence_text=evidence,
            platform=ctx.platform, jurisdiction=ctx.jurisdiction,
            company_name=ctx.company_name,
        )]


DARK_PATTERN_DETECTORS: list[SignalDetector] = [
    ToxicCultureObfuscationDetector(),
    UnpaidLaborExtractionDetector(),
    ApplicationBloatDetector(),
]

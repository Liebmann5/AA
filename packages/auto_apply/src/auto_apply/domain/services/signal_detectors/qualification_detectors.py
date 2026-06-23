"""
Qualification Stacking Detectors (QS-01 through QS-05).

Academic grounding: Harvard Business School / Burning Glass (2024) — 85% of
companies claim skills-based hiring; only 0.14% of hires are affected.
Hershbein & Kahn (2018): credential inflation intensifies during high unemployment.
"""
from __future__ import annotations
import re
from pathlib import Path
import yaml
from auto_apply.domain.constants import (
    SEVERITY_CONCERN, SEVERITY_FLAG, SEVERITY_VIOLATION,
    SIG_QS_01, SIG_QS_02, SIG_QS_03, SIG_QS_04, SIG_QS_05,
)
from auto_apply.domain.services.signal_detectors.base import (
    DetectionContext, ResearchSignal, SignalDetector,
)

# ── Tech release dates (loaded lazily) ───────────────────────────────────────
_TECH_RELEASE_DATES: dict[str, int] | None = None

def _load_tech_dates() -> dict[str, int]:
    global _TECH_RELEASE_DATES
    if _TECH_RELEASE_DATES is None:
        try:
            path = Path(__file__).parent.parent.parent.parent / "resources" / "research" / "tech_release_dates.yaml"
            with open(path) as f:
                _TECH_RELEASE_DATES = yaml.safe_load(f) or {}
        except Exception:
            _TECH_RELEASE_DATES = {}
    return _TECH_RELEASE_DATES


_EXPERIENCE_PATTERN = re.compile(
    r"(\d+)[\+\-]?\s*(?:to\s*\d+\s*)?(?:\+)?\s*years?\s+(?:of\s+)?(?:experience|exp)",
    re.I,
)
_TECH_EXPERIENCE_PATTERN = re.compile(
    r"(\d+)[\+\-]?\s*(?:years?\s+)(?:of\s+)?(?:experience\s+(?:with|in|using)\s+)([\w\s\+\#\.]+?)(?=\s*[\.,;]|$)",
    re.I,
)


class ExperienceYearImpossibilityDetector:
    """QS-01: Detects requirements for more experience than a technology has existed."""
    signal_type = SIG_QS_01
    _CURRENT_YEAR: int = 2026

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        tech_dates = _load_tech_dates()
        if not tech_dates:
            return []

        results: list[ResearchSignal] = []
        for match in _TECH_EXPERIENCE_PATTERN.finditer(ctx.job_description):
            years_required = int(match.group(1))
            tech_name_raw = match.group(2).strip().lower()

            for tech_name, release_year in tech_dates.items():
                if tech_name.lower() in tech_name_raw or tech_name_raw in tech_name.lower():
                    tech_age = self._CURRENT_YEAR - release_year
                    # Flag if required years > 80% of the technology's age
                    if years_required > tech_age * 0.8:
                        impossible = years_required > tech_age
                        evidence = (
                            f"'{tech_name}' requires {years_required} years experience, "
                            f"but was released in {release_year} ({tech_age} years old). "
                            f"{'IMPOSSIBLE' if impossible else 'Highly improbable'}."
                        )
                        results.append(ResearchSignal.create(
                            signal_type=self.signal_type,
                            severity=SEVERITY_VIOLATION if impossible else SEVERITY_CONCERN,
                            confidence=0.92 if impossible else 0.75,
                            evidence_text=evidence,
                            platform=ctx.platform, jurisdiction=ctx.jurisdiction,
                            company_name=ctx.company_name,
                        ))
        return results


# ── Entry-level contradiction keywords ────────────────────────────────────────
_ENTRY_LEVEL_TITLES: frozenset[str] = frozenset({
    "entry level", "entry-level", "junior", "associate", "jr.", "jr ",
    "early career", "new grad", "recent graduate", "trainee", "apprentice",
})
_SENIOR_EXPERIENCE_THRESHOLD: int = 4  # Years that categorize a role as mid/senior


class EntryLevelContradictionDetector:
    """QS-02: Detects jobs labeled entry-level but requiring senior-level experience."""
    signal_type = SIG_QS_02

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        title_lower = ctx.title_lower
        is_entry_level = any(kw in title_lower for kw in _ENTRY_LEVEL_TITLES)
        if not is_entry_level:
            return []

        match = _EXPERIENCE_PATTERN.search(ctx.job_description)
        if not match:
            return []

        years_required = int(match.group(1))
        if years_required < _SENIOR_EXPERIENCE_THRESHOLD:
            return []

        confidence = min(0.95, 0.70 + (years_required - _SENIOR_EXPERIENCE_THRESHOLD) * 0.05)
        evidence = (
            f"Role titled '{ctx.job_title[:50]}' (entry-level) requires "
            f"{years_required}+ years experience (entry-level threshold: "
            f"<{_SENIOR_EXPERIENCE_THRESHOLD} years)"
        )
        return [ResearchSignal.create(
            signal_type=self.signal_type,
            severity=SEVERITY_VIOLATION if years_required >= 5 else SEVERITY_CONCERN,
            confidence=confidence,
            evidence_text=evidence,
            platform=ctx.platform, jurisdiction=ctx.jurisdiction,
            company_name=ctx.company_name,
        )]


class SalarySkillsMismatchDetector:
    """QS-04: Detects when required skills bundle commands higher market salary than offered."""
    signal_type = SIG_QS_04

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        # Requires salary corpus data — populated by signal_aggregator.
        # This detector is structurally present; full implementation fires
        # once the salary corpus has >100 observations for the role category.
        # Placeholder confidence model based on hard-coded market data:
        if ctx.salary_max is None:
            return []

        # Example heuristic: if salary < $65k and description contains 5+ senior tech keywords
        senior_tech_keywords = frozenset({
            "kubernetes", "terraform", "distributed systems", "machine learning",
            "principal engineer", "staff engineer", "system design", "aws architect",
        })
        tech_count = sum(1 for kw in senior_tech_keywords if kw in ctx.description_lower)

        if tech_count >= 4 and ctx.salary_max < 65_000:
            evidence = (
                f"Salary max ${ctx.salary_max:,}/yr with {tech_count} senior-tech keywords "
                f"(market expectation for this skill set: $120k–$180k)"
            )
            return [ResearchSignal.create(
                signal_type=self.signal_type, severity=SEVERITY_CONCERN,
                confidence=0.68, evidence_text=evidence,
                platform=ctx.platform, jurisdiction=ctx.jurisdiction,
                company_name=ctx.company_name,
            )]
        return []


class ImpossibleSkillsCombinationDetector:
    """QS-05: Detects mutually exclusive or professionally unrealistic skills combinations."""
    signal_type = SIG_QS_05

    # Each tuple: (set of skills where requiring all together is unusual, explanation)
    _CONFLICTS: list[tuple[frozenset[str], str]] = [
        (frozenset({"react", "angular", "vue"}),
         "React + Angular + Vue (competing front-end frameworks, no team uses all three)"),
        (frozenset({"aws", "azure", "gcp"}),
         "AWS + Azure + GCP expert-level (companies use one primary cloud)"),
        (frozenset({"postgresql", "oracle", "mongodb", "mysql", "cassandra"}),
         "4+ competing database systems at expert level"),
    ]

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        results: list[ResearchSignal] = []
        desc_lower = ctx.description_lower

        for skill_set, explanation in self._CONFLICTS:
            matched = {skill for skill in skill_set if skill in desc_lower}
            if len(matched) >= 3:
                evidence = f"Impossible skills combination: {explanation}"
                results.append(ResearchSignal.create(
                    signal_type=self.signal_type, severity=SEVERITY_FLAG,
                    confidence=0.65, evidence_text=evidence,
                    platform=ctx.platform, jurisdiction=ctx.jurisdiction,
                    company_name=ctx.company_name,
                ))
        return results


QUALIFICATION_DETECTORS: list[SignalDetector] = [
    ExperienceYearImpossibilityDetector(),
    EntryLevelContradictionDetector(),
    SalarySkillsMismatchDetector(),
    ImpossibleSkillsCombinationDetector(),
]

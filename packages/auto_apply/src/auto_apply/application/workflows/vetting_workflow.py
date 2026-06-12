"""Vetting Workflow — judges each discovered job against the user's profile.

What this engine does:
    For each job that Discovery enqueues, fetch its description, parse it with
    SpaCy, run the ordered filter chain, compute a weighted fit score, optionally
    invoke GPT4All for borderline jobs, persist the outcome, and enqueue approved
    jobs as APPLY WorkUnits.

8-step sequence:
    1. _fetch_job_description           — navigate to job URL via perception port
    2. _parse_with_spacy                — extract skills, experience, metadata via TextMatcher
    3. _run_filter_chain                — short-circuit on first filter failure (cheapest first)
    4. _compute_fit_score               — weighted sum over partial filter scores
    5. _invoke_gpt4all_borderline_reasoning — YES/NO LLM nudge for borderline scores
    6. _record_vetting_outcome          — persist status, fit_score, rejection_reason
    7. _enqueue_apply_task              — push APPLY WorkUnit (priority ∝ fit score)
    8. _emit_vetting_telemetry          — anonymized signal to research_collector

Inputs:
    profile      — UserProfile (desired titles, skills, experience level)
    filters      — ordered list[BaseVettingFilter] (cheapest first; ThrottlingFilter goes first)
    job_repo     — JobRepositoryPort (persistence)
    task_queue   — WorkQueuePort (receives APPLY WorkUnits)
    event_bus    — EventBus
    text_matcher — TextMatcher (NLP entity extraction)

Outputs:
    Returns bool — True iff job passed all filters and APPLY task enqueued.
    Publishes: JOB_VETTED_PASS, JOB_VETTED_FAIL.

Filter pipeline order (cheapest → most expensive):
    ThrottlingFilter      (0.10) — DB lookup; blocks known-bad companies early
    SpatialLocationFilter (0.15) — coordinate math; blocks commute violations
    LogicFilters          (0.15) — string logic; blocks title/blacklist mismatches
    ExperienceFilter      (0.15) — metadata lookup; blocks seniority mismatch
    HardSkillsFilter      (0.20) — set intersection; blocks skill gap
    RoleAlignmentFilter   (0.25) — SpaCy similarity; most expensive, highest weight

How to extend:
    To add a new filter: subclass BaseVettingFilter (domain/vetting/base_filter.py)
    and add it to the ordered filter list in infrastructure/composition_root.py.
    Add its weight to VettingWorkflow.DEFAULT_WEIGHTS (values must sum to ~1.0).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from auto_apply.domain.events import Event
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.parsed_job_description import ParsedJobDescription
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.work_unit import TaskType, WorkUnit
from auto_apply.domain.types import JobStatus

logger = logging.getLogger(__name__)

_SENIORITY_KEYWORDS = [
    "junior", "entry", "associate", "mid", "senior", "lead", "staff",
    "principal", "director",
]
_EMPLOYMENT_PATTERNS = [
    "full-time", "full time", "part-time", "part time",
    "contract", "freelance", "internship",
]
_REMOTE_POSITIVE = ["remote", "work from home", "wfh", "fully remote"]
_REMOTE_NEGATIVE = ["on-site only", "in-office required", "no remote", "onsite only"]


class VettingWorkflow:
    """Orchestrates the full Vetting pipeline for a single job."""

    DEFAULT_WEIGHTS: dict[str, float] = {
        "ThrottlingFilter":      0.10,
        "SpatialLocationFilter": 0.15,
        "LogicFilters":          0.15,
        "ExperienceFilter":      0.15,
        "HardSkillsFilter":      0.20,
        "RoleAlignmentFilter":   0.25,
    }

    def __init__(
        self,
        profile: UserProfile,
        filters: list,
        job_repo,
        task_queue,
        event_bus,
        text_matcher,
        text_generation_port=None,
        perception_port=None,
        research_collector=None,
        config: dict | None = None,
        borderline_band: tuple[float, float] = (0.45, 0.65),
        weights: dict[str, float] | None = None,
    ) -> None:
        """Initialize with all dependencies injected.

        Args:
            profile: The active user profile.
            filters: Ordered list of vetting filters (cheapest first).
            job_repo: JobRepositoryPort — persistence for vetting outcomes.
            task_queue: WorkQueuePort — receives APPLY WorkUnits.
            event_bus: EventBus — receives vetting events.
            text_matcher: TextMatcher — NLP entity extraction and similarity.
            text_generation_port: TextGenerationPort | None — GPT4All or None.
            perception_port: PerceptionPort | None — for fetching job descriptions.
            research_collector: ResearchCollector | None — anonymized telemetry.
            config: Effective config dict from registry.
            borderline_band: Fit scores in this range trigger GPT4All reasoning.
            weights: Per-filter weight overrides. Defaults to DEFAULT_WEIGHTS.
        """
        self._profile = profile
        self._filters = filters
        self._job_repo = job_repo
        self._task_queue = task_queue
        self._event_bus = event_bus
        self._text_matcher = text_matcher
        self._text_generation_port = text_generation_port
        self._perception_port = perception_port
        self._research_collector = research_collector
        self._config = config or {}
        self._borderline_band = borderline_band
        self._weights = weights or self.DEFAULT_WEIGHTS

    def _cfg(self, key: str, default: Any) -> Any:
        """Read a dot-path config key from self._config with a default fallback."""
        parts = key.split(".")
        node = self._config
        for part in parts:
            if not isinstance(node, dict):
                return default
            node = node.get(part, default)
            if node is default:
                return default
        return node

    def _fetch_job_description(self, job: Job) -> str:
        """Navigate to the job URL and extract page text.

        Args:
            job: The Job to fetch.

        Returns:
            Page text content, or job title on any failure.
        """
        if self._perception_port is None:
            return job.title or ""

        try:
            self._perception_port.navigate(job.url)
            # Canonical text path (PerceptionPort.get_page_text): works for both
            # the live-browser and BS4 zero-browser adapters. Falls back to the
            # job title if the page yields no extractable text.
            text = self._perception_port.get_page_text() or ""
            return text or (job.title or "")
        except Exception as exc:
            logger.warning(
                "VettingWorkflow: failed to fetch description | job=%s error=%s",
                job.url, exc,
            )
            return job.title or ""

    def _parse_with_spacy(self, job: Job, description: str) -> ParsedJobDescription:
        """Run NLP extraction on the job description and store results in metadata.

        Args:
            job: The Job being vetted (metadata mutated in place).
            description: Full job description text.

        Returns:
            ParsedJobDescription with all extracted fields.
        """
        entities: dict = {}
        try:
            entities = self._text_matcher.extract_entities(description)
        except Exception as exc:
            logger.warning("VettingWorkflow._parse_with_spacy extract failed: %s", exc)

        year_strings: list[str] = entities.get("experience_years", [])
        years_ints: list[int] = []
        for ys in year_strings:
            cleaned = re.sub(r"\D", "", str(ys))
            if cleaned.isdigit():
                years_ints.append(int(cleaned))

        experience_years_min: int | None = years_ints[0] if years_ints else None
        experience_years_max: int | None = years_ints[1] if len(years_ints) > 1 else None

        title_lower = (job.title or "").lower()
        desc_lower = description.lower()
        seniority_signal: str | None = None
        for kw in _SENIORITY_KEYWORDS:
            if kw in title_lower or kw in desc_lower:
                seniority_signal = kw
                break

        employment_type: str | None = None
        for et in _EMPLOYMENT_PATTERNS:
            if et in desc_lower:
                employment_type = et.replace(" ", "-")
                break

        is_remote: bool | None = None
        if any(p in desc_lower for p in _REMOTE_POSITIVE):
            is_remote = True
        elif any(p in desc_lower for p in _REMOTE_NEGATIVE):
            is_remote = False

        parsed = ParsedJobDescription(
            required_skills=entities.get("skills", []),
            experience_years_min=experience_years_min,
            experience_years_max=experience_years_max,
            locations=entities.get("locations", []),
            organizations=entities.get("organizations", []),
            employment_type=employment_type,
            seniority_signal=seniority_signal,
            is_remote=is_remote,
        )

        if hasattr(job, "metadata"):
            job.metadata["parsed"] = parsed.model_dump()

        return parsed

    def _run_filter_chain(
        self, job: Job
    ) -> tuple[bool, str, dict[str, float]]:
        """Run filters in order, short-circuiting on first failure.

        Args:
            job: The Job being evaluated.

        Returns:
            (passed, reason, partial_scores) where partial_scores maps
            filter class name → 1.0 (pass) or 0.0 (fail).
        """
        partial_scores: dict[str, float] = {}

        for filt in self._filters:
            filter_name = type(filt).__name__
            try:
                passed, reason = filt.check(job)
            except Exception as exc:
                logger.warning(
                    "VettingWorkflow: filter %s raised unexpectedly: %s",
                    filter_name, exc,
                )
                passed, reason = False, f"filter_exception:{exc}"

            if passed:
                partial_scores[filter_name] = 1.0
            else:
                partial_scores[filter_name] = 0.0
                logger.info(
                    "Vetting FAIL | job=%s company=%s filter=%s reason=%s",
                    job.title, job.company, filter_name, reason,
                )
                return False, f"{filter_name}: {reason}", partial_scores

        return True, "all_filters_passed", partial_scores

    def _compute_fit_score(self, partial_scores: dict[str, float]) -> float:
        """Compute weighted fit score from filter pass/fail scores.

        Args:
            partial_scores: Dict mapping filter name → 0.0 or 1.0.

        Returns:
            Float in [0.0, 1.0].
        """
        if not partial_scores:
            return 0.0

        total = sum(
            self._weights.get(name, 0.0) * score
            for name, score in partial_scores.items()
        )
        return max(0.0, min(1.0, total))

    def _invoke_gpt4all_borderline_reasoning(
        self, job: Job, fit_score: float
    ) -> tuple[float, str]:
        """Invoke GPT4All for a YES/NO judgment on borderline-score jobs.

        Args:
            job: The Job being evaluated.
            fit_score: Current fit score.

        Returns:
            (adjusted_score, note) where note explains what happened.
        """
        if self._text_generation_port is None:
            return fit_score, "gpt4all_unavailable"

        low, high = self._borderline_band
        if not (low <= fit_score <= high):
            return fit_score, "not_in_borderline_band"

        parsed: dict = job.metadata.get("parsed", {}) if hasattr(job, "metadata") else {}
        parsed_skills = parsed.get("required_skills", [])
        prefs = getattr(self._profile, "search_preferences", None)
        career_summary = getattr(self._profile, "career_summary", "not provided") or "not provided"

        prompt = (
            f"Job title: {job.title}\n"
            f"Company: {job.company}\n"
            f"Required skills: {', '.join(parsed_skills) if parsed_skills else 'not listed'}\n"
            f"User background: {career_summary}\n\n"
            "Based only on the above, is this job a good mutual fit for this candidate?\n"
            "Answer with exactly one word: YES or NO."
        )

        try:
            response = self._text_generation_port.generate(prompt, max_tokens=10)
        except Exception as exc:
            logger.warning("VettingWorkflow: GPT4All call failed: %s", exc)
            return fit_score, "gpt4all_exception"

        if response is None:
            return fit_score, "gpt4all_returned_none"

        response_upper = response.upper()
        if "YES" in response_upper:
            adjusted = min(1.0, high + 0.01)
            return adjusted, "gpt4all:YES"
        if "NO" in response_upper:
            adjusted = max(0.0, low - 0.01)
            return adjusted, "gpt4all:NO"

        return fit_score, f"gpt4all_unparseable:{response[:20]!r}"

    def _record_vetting_outcome(
        self, job: Job, passed: bool, reason: str, fit_score: float
    ) -> None:
        """Persist the vetting decision and publish the appropriate event.

        Args:
            job: The vetted Job (mutated in place).
            passed: Whether the job passed all filters.
            reason: Human-readable reason string.
            fit_score: Computed fit score.
        """
        if hasattr(job, "fit_score"):
            job.fit_score = fit_score
        if hasattr(job, "rejection_reason"):
            job.rejection_reason = reason if not passed else None
        if hasattr(job, "status"):
            job.status = JobStatus.VETTED if passed else JobStatus.REJECTED
        if hasattr(job, "is_vetted"):
            job.is_vetted = True

        try:
            if hasattr(self._job_repo, "add_job"):
                self._job_repo.add_job(job)
            elif hasattr(self._job_repo, "save"):
                self._job_repo.save(job)
        except Exception as exc:
            logger.warning("VettingWorkflow: job_repo persistence failed: %s", exc)

        event = Event.JOB_VETTED_PASS if passed else Event.JOB_VETTED_FAIL
        payload = {
            "job_title": job.title,
            "company": job.company,
            "fit_score": fit_score,
            "reason": reason,
        }
        try:
            self._event_bus.publish(event, payload)
        except Exception as exc:
            logger.warning("VettingWorkflow: event publish failed: %s", exc)

    def _enqueue_apply_task(self, job: Job) -> None:
        """Enqueue an APPLY WorkUnit, prioritized by fit score.

        Higher fit score → lower priority value → processed first.

        Args:
            job: The approved Job to enqueue.
        """
        fit = getattr(job, "fit_score", 0.0) or 0.0
        priority = max(1, int((1.0 - fit) * 10) + 1)
        try:
            self._task_queue.queue_task(
                WorkUnit(
                    priority=priority,
                    task_type=TaskType.APPLY,
                    payload=job,
                    source=getattr(job, "source", "vetting") or "vetting",
                    context_data={},
                )
            )
        except Exception as exc:
            logger.warning("VettingWorkflow: failed to enqueue APPLY task: %s", exc)

    def _emit_vetting_telemetry(
        self, job: Job, partial_scores: dict[str, float], reason: str
    ) -> None:
        """Emit anonymized vetting telemetry to the research collector.

        No job URLs, no company names, no user data — only aggregate counts.

        Args:
            job: The vetted job (used only for fit_score).
            partial_scores: Per-filter scores.
            reason: Rejection/pass reason.
        """
        if self._research_collector is None:
            return

        try:
            self._research_collector.record_signal(
                Event.JOB_VETTED_FAIL if reason != "all_filters_passed" else Event.JOB_VETTED_PASS,
                {
                    "partial_scores": partial_scores,
                    "fit_score": getattr(job, "fit_score", 0.0),
                    "rejection_filter": reason.split(":")[0] if ":" in reason else reason,
                    "gpt4all_invoked": self._text_generation_port is not None,
                },
            )
        except Exception as exc:
            logger.debug("VettingWorkflow: telemetry signal failed: %s", exc)

    def run(self, job: Job) -> bool:
        """Vet a single job against the user's profile.

        Executes the 8-step vetting pipeline in order, short-circuiting on first
        filter failure. Enqueues an APPLY WorkUnit for approved jobs.

        Args:
            job: The Job to evaluate. Must have job.url set.

        Returns:
            True if the job passed all filters and an APPLY WorkUnit was enqueued.
            False if the job was rejected at any filter.
        """
        logger.debug(
            "VettingWorkflow.run() | job=%s company=%s", job.title, job.company
        )

        description = self._fetch_job_description(job)
        self._parse_with_spacy(job, description)

        passed, reason, partial_scores = self._run_filter_chain(job)
        fit_score = self._compute_fit_score(partial_scores)
        fit_score, gpt4all_note = self._invoke_gpt4all_borderline_reasoning(job, fit_score)

        self._record_vetting_outcome(job, passed, reason, fit_score)
        self._emit_vetting_telemetry(job, partial_scores, reason)

        if passed:
            self._enqueue_apply_task(job)
            logger.info(
                "VettingWorkflow: PASS | job=%s fit_score=%.2f gpt4all=%s",
                job.title, fit_score, gpt4all_note,
            )

        return passed

"""
Immutable, serializable session configuration. The single authoritative
source for how this particular session should run. Serializing this to
disk gives you complete experiment parameters for research reproducibility.
"""
from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from auto_apply.domain.models.effective_config import EffectiveConfig
from auto_apply.domain.models.timing import BehaviorParameters


class SessionExecutionMode(str, Enum):
    """First‑class execution modes for the AA pipeline.

    Each mode determines which stages (discovery, vetting, application)
    are executed and what tasks are enqueued.  The default is FULL_PIPELINE
    for backward compatibility.
    """

    FULL_PIPELINE = "full_pipeline"
    DISCOVER_ONLY = "discover_only"
    DISCOVER_AND_VET = "discover_and_vet"
    VET_ONLY = "vet_only"
    VET_AND_APPLY = "vet_and_apply"
    APPLY_ONLY = "apply_only"
    HUMAN_ASSIST = "human_assist"
    RESEARCH_AUDIT = "research_audit"

    @property
    def includes_discovery(self) -> bool:
        return self in (
            SessionExecutionMode.FULL_PIPELINE,
            SessionExecutionMode.DISCOVER_ONLY,
            SessionExecutionMode.DISCOVER_AND_VET,
        )

    @property
    def includes_vetting(self) -> bool:
        return self in (
            SessionExecutionMode.FULL_PIPELINE,
            SessionExecutionMode.DISCOVER_AND_VET,
            SessionExecutionMode.VET_ONLY,
            SessionExecutionMode.VET_AND_APPLY,
        )

    @property
    def includes_application(self) -> bool:
        return self in (
            SessionExecutionMode.FULL_PIPELINE,
            SessionExecutionMode.VET_AND_APPLY,
            SessionExecutionMode.APPLY_ONLY,
        )


class SearchPair(BaseModel):
    """A single (title, location, workplace_type) search tuple.

    Used as the canonical representation of discovery queries so that every
    provider receives exactly the same instructions.
    """
    model_config = ConfigDict(frozen=True)

    title: str = Field(..., description="Job title or keyword phrase.")
    location: str = Field(..., description="Location string (city, state, 'Remote').")
    workplace_type: str = Field("remote", description="On‑site, hybrid, or remote.")


class SessionPlan(BaseModel):
    """Immutable session config assembled at startup, never changes during a run.

    Attributes:
        session_id: Unique identifier for this run (UUID).
        created_at: When this session started.
        max_concurrency: Max concurrent browser-using operations (enforced by BrowserLeaseManager).
        max_results_per_query: Cap on results per provider per query.
        max_applications_per_session: Hard session-level application cap.
        max_applications_per_company: Per-company application limit.
        max_queries_per_session: Maximum title × location cross-product queries.
        enable_company_page_mining: Whether to follow company careers URLs.
        use_ats_site_search: Whether to build site: operator queries.
        date_range: How old results to accept ('day'/'week'/'month'/None).
        active_providers: Which discovery providers to use.
        linear_mode_platforms: Platforms forcing one-at-a-time processing.
        research_enabled: Whether research data collection is active.
        consent_version: Version of research consent user agreed to (if any).
        behavior: All timing and behavioral parameters for this session.
        nlp_tier: Which NLP tier is available (basic/spacy/transformer).
        browser_framework: Which browser framework is in use.
        list_only_mode: If True, discover+vet but never apply.
        cover_letter_enabled: Whether LLM cover letters are generated.
        has_live_browser: Whether a live browser session is available for discovery.
        execution_mode: Which pipeline stages to run (default FULL_PIPELINE).
        search_pairs: Pre‑computed search queries for discovery; empty = derive from profile.
    """
    model_config = ConfigDict(frozen=True)

    session_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Concurrency
    max_concurrency: int = Field(default=1, ge=1, le=8)

    # Discovery limits
    max_results_per_query: int = Field(default=30, ge=1, le=500)
    max_applications_per_session: int = Field(default=50, ge=0, le=1000)
    max_applications_per_company: int = Field(default=3, ge=1, le=20)

    # Feature flags
    enable_company_page_mining: bool = Field(default=False)
    use_ats_site_search: bool = Field(default=False)
    date_range: Literal["day", "week", "month"] | None = Field(default=None)
    list_only_mode: bool = Field(default=False)
    cover_letter_enabled: bool = Field(default=False)

    # Provider configuration
    active_providers: tuple[str, ...] = Field(default=("google", "bing", "indeed"))
    linear_mode_platforms: frozenset[str] = Field(default_factory=lambda: frozenset({"linkedin", "indeed"}))
    max_queries_per_session: int = Field(default=20, ge=1)

    # Research
    research_enabled: bool = Field(default=False)
    consent_version: str | None = Field(default=None)

    # Behavioral parameters (includes random_seed for determinism)
    behavior: BehaviorParameters = Field(default_factory=BehaviorParameters)

    # Runtime capabilities
    nlp_tier: Literal["basic", "spacy", "transformer"] = Field(default="basic")
    browser_framework: Literal["selenium", "playwright", "static"] = Field(default="selenium")
    has_live_browser: bool = Field(default=True, description="Whether a live browser session is available for discovery.")

    # Execution mode (new)
    execution_mode: SessionExecutionMode = Field(
        default=SessionExecutionMode.FULL_PIPELINE,
        description="Which pipeline stages to run during this session.",
    )

    # Pre‑computed search pairs (empty = derive from profile)
    search_pairs: tuple[SearchPair, ...] = Field(default=(), description="Explicit search tuples; overrides profile-derived queries.")

    @property
    def is_deterministic(self) -> bool:
        """True when this session will produce reproducible outputs."""
        return self.behavior.random_seed is not None

    @classmethod
    def from_config(
        cls,
        session_id: str,
        config: dict,
        behavior: BehaviorParameters,
        nlp_tier: Literal["basic", "spacy", "transformer"] = "basic",
        browser_framework: Literal["selenium", "playwright", "static"] = "selenium",
    ) -> "SessionPlan":
        """Build from merged effective_config. Called only by composition_root.py.

        Config-derived values come from a typed EffectiveConfig: a renamed or
        missing key raises at construction instead of silently returning a
        hardcoded default. Fields with no config source keep their model default
        rather than pretending to read one. ``execution_mode`` is an admin/session
        grant (policy injects a ``session`` section), not a YAML knob, so it is
        read from the raw merged config where policy places it.
        """
        settings = EffectiveConfig.from_mapping(config)
        execution_mode = SessionExecutionMode(
            config.get("session", {}).get("execution_mode", "full_pipeline")
        )

        return cls(
            session_id=session_id,
            max_concurrency=settings.discovery.max_concurrent_sources,
            max_results_per_query=settings.max_discovery_results_per_query,
            max_applications_per_session=settings.max_applications_per_session,
            max_applications_per_company=settings.max_applications_per_company,
            research_enabled=settings.enable_research_collection,
            # Preserved from prior behaviour: no config source exists, so this
            # stayed empty. The field default diverges ({'indeed','linkedin'});
            # whether linear mode should default on is a separate decision.
            linear_mode_platforms=frozenset(),
            behavior=behavior,
            nlp_tier=nlp_tier,
            browser_framework=browser_framework,
            has_live_browser=settings.discovery_strategy != "static_fetch",
            execution_mode=execution_mode,
        )
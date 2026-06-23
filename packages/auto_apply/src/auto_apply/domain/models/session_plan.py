"""
Immutable, serializable session configuration. The single authoritative
source for how this particular session should run. Serializing this to
disk gives you complete experiment parameters for research reproducibility.
"""
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from auto_apply.domain.models.timing import BehaviorParameters


class SessionPlan(BaseModel):
    """Immutable session config assembled at startup, never changes during a run.

    Attributes:
        session_id: Unique identifier for this run (UUID).
        created_at: When this session started.
        max_concurrency: Max concurrent browser-using operations (enforced by BrowserLeaseManager).
        max_results_per_query: Cap on results per provider per query.
        max_applications_per_session: Hard session-level application cap.
        max_applications_per_company: Per-company application limit.
        enable_company_page_mining: Whether to follow company careers URLs.
        use_ats_site_search: Whether to build site: operator queries.
        date_range: How old results to accept ('day'/'week'/'month'/None).
        active_providers: Which discovery providers to use.
        linear_mode_platforms: Platforms forcing one-at-a-time processing.
        research_enabled: Whether research data collection is active.
        behavior: All timing and behavioral parameters for this session.
        nlp_tier: Which NLP tier is available (basic/spacy/transformer).
        browser_framework: Which browser framework is in use.
        headless: Whether browser runs headless.
        stealth_mode: Whether anti-detection patches are active.
        list_only_mode: If True, discover+vet but never apply.
        cover_letter_enabled: Whether LLM cover letters are generated.
        consent_version: Version of research consent user agreed to (if any).
    """
    model_config = ConfigDict(frozen=True)

    session_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

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

    # Research
    research_enabled: bool = Field(default=False)
    consent_version: str | None = Field(default=None)

    # Behavioral parameters (includes random_seed for determinism)
    behavior: BehaviorParameters = Field(default_factory=BehaviorParameters)

    # Runtime capabilities
    nlp_tier: Literal["basic", "spacy", "transformer"] = Field(default="basic")
    browser_framework: Literal["selenium", "playwright", "static"] = Field(default="selenium")
    headless: bool = Field(default=True)
    stealth_mode: bool = Field(default=True)

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
        """Build from merged effective_config. Called only by composition_root.py."""
        disc = config.get("discovery", {})
        apps = config.get("applications", {})
        browser = config.get("browser", {})
        research = config.get("research", {})

        return cls(
            session_id=session_id,
            max_concurrency=disc.get("max_concurrent_sources", 1),
            max_results_per_query=disc.get("max_results_per_query", 30),
            max_applications_per_session=apps.get("max_applications_per_session", 50),
            max_applications_per_company=apps.get("max_applications_per_company", 3),
            enable_company_page_mining=disc.get("enable_company_page_mining", False),
            use_ats_site_search=disc.get("use_ats_site_search", False),
            date_range=disc.get("date_range"),
            list_only_mode=apps.get("list_only_mode", False),
            cover_letter_enabled=apps.get("enable_cover_letter_generation", False),
            active_providers=tuple(disc.get("providers", ["google", "bing", "indeed"])),
            research_enabled=research.get("enabled", False),
            consent_version=research.get("consent_version"),
            behavior=behavior,
            nlp_tier=nlp_tier,
            browser_framework=browser_framework,
            headless=browser.get("headless", True),
            stealth_mode=browser.get("stealth_mode", True),
        )

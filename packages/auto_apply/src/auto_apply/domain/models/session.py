"""Immutable session plan — the complete configuration blueprint for a single session.

Built once at session start from the effective configuration, this plan is
the single source of truth for every runtime parameter. It never changes
during a session.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionPlan(BaseModel):
    """Frozen, serializable configuration for a single AA session.

    After construction, the plan is immutable and can be safely shared
    across components. All fields have sensible defaults that match
    ``runtime_defaults.yaml``.
    """
    model_config = ConfigDict(frozen=True)

    # ── Identity ────────────────────────────────────────────────────────
    session_id: str = Field(default="unset", description="Unique identifier for this session.")

    # ── Resource limits ────────────────────────────────────────────────
    max_concurrency: int = Field(default=1, ge=1, description="Maximum concurrent browser leases (enforced by BrowserLeaseManager).")
    max_results_per_query: int = Field(default=30, ge=1, description="Cap on discovery results per provider per query.")
    max_applications_per_session: int = Field(default=50, ge=0, description="Hard cap on applications per session; 0 = list mode.")
    max_applications_per_company: int = Field(default=3, ge=1, description="Prevent re-applying to the same company too often.")

    # ── Discovery strategy ─────────────────────────────────────────────
    max_queries_per_session: int = Field(default=20, ge=1, description="Maximum title × location cross-product queries per session.")
    enable_company_page_mining: bool = Field(default=False, description="Follow company career pages during discovery.")
    use_ats_site_search: bool = Field(default=False, description="Build site: operator queries for ATS platforms.")
    date_range: str | None = Field(default=None, description="Restrict to recently posted: 'day', 'week', 'month', or None.")
    providers: list[str] = Field(default_factory=lambda: ["google", "bing", "indeed"], description="Active discovery provider names.")

    # ── Platform-specific linear mode ─────────────────────────────────
    linear_mode_platforms: set[str] = Field(default_factory=set, description="Platforms where company batching is disabled (e.g. LinkedIn).")

    # ── Research & reproducibility ────────────────────────────────────
    research_enabled: bool = Field(default=False, description="Whether research data collection is active.")
    random_seed: int | None = Field(default=None, description="Fixed seed for deterministic mode; None → production non-deterministic.")

    # ── NLP and intelligence tier ──────────────────────────────────────
    nlp_tier: Literal["basic", "spacy", "transformer"] = Field(default="basic", description="NLP engine tier active this session.")

    # ── Browser choice ─────────────────────────────────────────────────
    browser_framework: Literal["selenium", "playwright", "static"] = Field(default="selenium", description="Browser automation framework.")
    headless: bool = Field(default=True, description="Run browser without visible window.")
    stealth_mode: bool = Field(default=True, description="Apply anti-detection evasion patches.")

    # ── Runtime capability flags ───────────────────────────────────────
    has_live_browser: bool = Field(default=True, description="Whether a live browser session is available for discovery.")
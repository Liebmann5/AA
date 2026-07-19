"""Frozen, typed instruction for a single discovery search.

This value object is the **only** data a DiscoveryProviderPort implementation
ever needs to execute one search.  It replaces the old ``override_criteria:
dict | None`` parameter with a contract that is structurally enforceable —
a provider cannot ignore the user's intent because it has no access to the
user profile and receives exactly one instruction per ``run()`` call.

-----------------------------------------------------------------------------

Architecture note (per AA Architecture Bible §23):
    This model crosses the boundary between the application layer
    (DiscoveryWorkflow) and the adapter layer (providers).  It must be a
    Pydantic v2 model so that serialisation (checkpointing, research logs)
    is validated and type‑safe.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SearchInstruction(BaseModel):
    """A single, unambiguous search that a provider must execute.

    Attributes:
        title: Job title or keyword phrase to search for.  Required even
            when ``raw_query_string`` is set — serves as a human‑readable
            label for logs and observability.
        location: Location string — city, state, or ``"Remote"``.
        workplace_type: On‑site, hybrid, or remote preference.
        raw_query_string: Advanced boolean query string.  When set, the
            provider MUST use this verbatim instead of composing a query
            from ``title`` and ``location``.
        date_range: Time‑window filter.  Providers map this to their
            URL‑specific parameters.  ``None`` = no date filter.

    Example:
        >>> # Simple search
        >>> SearchInstruction(title="Python Engineer", location="Remote")
        >>>
        >>> # Advanced boolean search
        >>> SearchInstruction(
        ...     title="ATS Site Search",
        ...     location="Remote",
        ...     raw_query_string="site:jobs.ashbyhq.com | site:jobs.lever.co engineer -senior",
        ... )
        >>>
        >>> # Time‑windowed search
        >>> SearchInstruction(
        ...     title="React Developer",
        ...     location="Austin, TX",
        ...     date_range="week",
        ... )
    """

    model_config = ConfigDict(frozen=True)

    # ── Required core fields ────────────────────────────────────────────
    title: str = Field(
        ...,
        min_length=1,
        description=(
            "Job title or keyword phrase to search for.  Required even when "
            "``raw_query_string`` is set — serves as a human‑readable label "
            "for logs and observability."
        ),
    )
    location: str = Field(
        default="Remote",
        description="Location string (city, state, or 'Remote').",
    )
    workplace_type: str = Field(
        default="remote",
        description="On‑site, hybrid, or remote.",
    )

    # ── Power‑user fields ───────────────────────────────────────────────
    raw_query_string: str | None = Field(
        default=None,
        description=(
            "Advanced boolean query string.  When set, the provider MUST "
            "use this verbatim instead of composing a query from title and "
            "location.  Example: "
            "'site:jobs.ashbyhq.com (engineer OR developer) -Senior'"
        ),
    )
    date_range: Literal["hour", "day", "week", "month", "year"] | None = Field(
        default=None,
        description=(
            "Time‑window filter for job postings.  Providers map this to "
            "their URL‑specific parameters (Google tbs=qdr:, Indeed fromage=, "
            "etc.).  None = no date filter (all results)."
        ),
    )
    max_results: int = Field(
        default=30,
        ge=1,
        le=500,
        description=(
            "Per-query result cap. Resolved by the workflow from the session "
            "plan's max_results_per_query (itself the low-resource-clamped "
            "max_discovery_results_per_query), so a 2GB machine's clamp of 15 "
            "actually reaches the scraper instead of being computed and discarded."
        ),
    )

    # ── Derived properties ──────────────────────────────────────────────

    @property
    def effective_query(self) -> str:
        """Returns the query string the provider should use.

        When ``raw_query_string`` is set, returns it directly.  Otherwise,
        composes a query from ``title`` and ``location``.

        This is the single method providers should call to get the query
        text they will type into a search bar or encode into a URL.
        """
        if self.raw_query_string:
            return self.raw_query_string
        return self.raw_query

    @property
    def raw_query(self) -> str:
        """Returns a pre‑composed query string for simple searches.

        Example:
            ``"Software Engineer jobs in Remote"``
        """
        return f"{self.title} jobs in {self.location}"

    def __repr__(self) -> str:
        extras = []
        if self.raw_query_string:
            extras.append(f"raw_query={self.raw_query_string[:50]!r}")
        if self.date_range:
            extras.append(f"date_range={self.date_range}")
        tail = f" ({', '.join(extras)})" if extras else ""
        return (
            f"SearchInstruction(title={self.title!r}, "
            f"location={self.location!r}, "
            f"workplace_type={self.workplace_type!r}){tail}"
        )
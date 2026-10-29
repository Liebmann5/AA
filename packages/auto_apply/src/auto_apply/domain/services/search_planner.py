"""Automated site-restricted search planning.

When a session enables ATS-targeted search (``discovery.use_ats_site_search``),
this planner turns the session's titles, locations, enabled engines and
enabled platforms into an ordered set of engine-bound, site-restricted
queries.

The rules this module exists to keep:

* **Composition is single-sourced.** Every query string is built by
  :func:`auto_apply.domain.services.query_composer.compose` from the
  bundled search-surface catalog. Nothing here formats a ``site:`` clause
  by hand, and nothing hard-codes an engine or a host.
* **Refusal-both, carried into automation.** An engine that cannot carry a
  site restriction gets no query at all — never a degraded one — with a
  note saying why. A platform below the automation evidence level is not
  planned. A restriction shaped like a terminal page is never planned.
* **Deterministic.** Planning involves no chance: engines rotate innermost
  and platforms outermost in caller order, so no engine host receives
  consecutive queries while another enabled target is available, and the
  same inputs always produce the same plan. That is also why there is no
  seeded-RNG namespace for this module — there is nothing to seed.
* **Budgets are hard.** The planner never emits more queries than the
  session budget, and reports exactly which targets were dropped.
* **No reallocation.** The plan is a pure function of its inputs. It reads
  no yield, no history and no clock, so by construction it cannot shift
  budget mid-session — which is what keeps a seeded run and a replay
  comparable.

Pure domain code: no I/O, no clock, no randomness. Engine and platform data
arrive as plain values from the caller, so the planner never imports an
adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Protocol, Sequence

from auto_apply.domain.models.search_query import QueryRequest
from auto_apply.domain.models.search_surface import (
    SearchSurfaceSpec,
    VerificationStatus,
)
from auto_apply.domain.services.query_composer import compose

#: Platform restriction statuses admitted into automated plans.
#:
#: Stricter than the interactive builder's floor by design: a person building
#: a search by hand is shown the evidence label and decides; automation acts
#: with no one reading a label, and every host it queries becomes part of
#: the research record's sampling frame. Platforms measured by hand or
#: documented by the platform itself qualify; third-party reports and
#: sample-derived guesses stay out until someone measures them
#: (docs/developer_guide/verifying_platform_search.md).
AUTOMATION_STATUSES: frozenset[VerificationStatus] = frozenset(
    {VerificationStatus.MEASURED, VerificationStatus.VENDOR}
)


@dataclass(frozen=True)
class PlatformTarget:
    """One ATS platform as a planning target.

    Plain data built from an ATS descriptor by the caller, so the planner
    never imports the registry adapter.

    Attributes:
        name: The descriptor name (e.g. ``"greenhouse"``).
        restriction: The ``site:`` restriction (e.g.
            ``"boards.greenhouse.io"``).
        status: The descriptor's restriction status (a
            :class:`VerificationStatus` value).
    """

    name: str
    restriction: str
    status: str


@dataclass(frozen=True)
class PlannedQuery:
    """One composed, engine-bound query, ready to become a SearchInstruction."""

    engine: str
    platform: str
    title: str
    location: str
    workplace_type: str
    raw_query_string: str
    surface_template: str
    date_range: str | None
    max_results: int


@dataclass(frozen=True)
class PlannerNote:
    """A human-readable note about what was not planned, and why."""

    severity: str  # "info" | "warning"
    message: str


@dataclass(frozen=True)
class PlannedSearch:
    """The planner's output: the ordered queries and the notes behind them."""

    queries: tuple[PlannedQuery, ...] = ()
    notes: tuple[PlannerNote, ...] = ()
    dropped_targets: tuple[str, ...] = ()


class SiteSearchStrategy(Protocol):
    """How platform targets are grouped and ordered for planning.

    Selected by configuration. A strategy decides grouping and order, never
    query text — the composition of every query still goes through the
    catalog's composer.

    Grouped composition (several restrictions in one query) needs composer
    support that does not exist yet, so a strategy returning a group of more
    than one platform is refused loudly and planning falls back to one query
    per platform.
    """

    @property
    def name(self) -> str:
        """The strategy's registry name."""
        ...

    def group(
        self, platforms: list[PlatformTarget]
    ) -> list[tuple[PlatformTarget, ...]]:
        """The platforms to plan, as ordered groups."""
        ...


class PerPlatformStrategy:
    """One query per platform per engine — the default strategy."""

    name = "per_platform"

    def group(
        self, platforms: list[PlatformTarget]
    ) -> list[tuple[PlatformTarget, ...]]:
        return [(platform,) for platform in platforms]


class SearchPlanner:
    """Plans site-restricted searches across engines and platforms.

    Constructed once per session with catalog and platform data as plain
    values; :meth:`plan` is then called for each search base set.

    Args:
        engine_specs: Catalog specs for automatable engines, by engine name.
        platform_targets: Planning data for known platforms, by name.
        is_terminal: Optional predicate — true when a URL is a terminal
            (success/confirm/closed) page. Restrictions shaped like one are
            never planned.
        strategy_name: The configured composition strategy. Unknown names
            fall back to ``per_platform`` with a warning note.
        strategies: Extra strategies to register beyond the default.
    """

    def __init__(
        self,
        *,
        engine_specs: Mapping[str, SearchSurfaceSpec],
        platform_targets: Mapping[str, PlatformTarget],
        is_terminal: Callable[[str], bool] | None = None,
        strategy_name: str = "per_platform",
        strategies: Iterable[SiteSearchStrategy] = (),
    ) -> None:
        self._engine_specs = dict(engine_specs)
        self._platform_targets = dict(platform_targets)
        self._is_terminal = is_terminal or (lambda _url: False)
        self._strategies: dict[str, SiteSearchStrategy] = {
            PerPlatformStrategy.name: PerPlatformStrategy(),
        }
        for strategy in strategies:
            self._strategies[strategy.name] = strategy
        self._strategy_name = strategy_name

    def plan(
        self,
        *,
        bases: Sequence[tuple[str, str, str]],
        engines: Sequence[str],
        platforms: Sequence[str],
        date_range: str | None,
        max_results: int,
        budget: int,
    ) -> PlannedSearch:
        """Plan the searches for the given bases.

        Args:
            bases: ``(title, location, workplace_type)`` triples.
            engines: The session's enabled engines, in the caller's order.
            platforms: The session's enabled platform names, in caller order.
            date_range: Carried onto every query; applied at run time only
                where the engine's form supports it.
            max_results: Per-query result cap (already resource-clamped).
            budget: Hard cap on queries produced. Truncation is reported,
                never silent.

        Returns:
            The ordered queries plus notes naming every exclusion. An empty
            query list with notes is a valid, honest answer.
        """
        notes: list[PlannerNote] = []
        queries: list[PlannedQuery] = []
        dropped: list[str] = []

        usable_engines = self._usable_engines(engines, notes)
        usable_platforms = self._usable_platforms(platforms, notes)
        clean_bases = [b for b in bases if b[0].strip()]
        if len(clean_bases) != len(bases):
            notes.append(
                PlannerNote("info", "Bases with an empty title were skipped.")
            )
        if not usable_engines or not usable_platforms or not clean_bases:
            return PlannedSearch((), tuple(notes), ())

        strategy = self._strategies.get(self._strategy_name)
        if strategy is None:
            notes.append(
                PlannerNote(
                    "warning",
                    f"Unknown site-search strategy {self._strategy_name!r}; "
                    "using 'per_platform'.",
                )
            )
            strategy = self._strategies[PerPlatformStrategy.name]

        for title, location, workplace_type in clean_bases:
            groups = strategy.group(list(usable_platforms))
            if any(len(group) != 1 for group in groups):
                notes.append(
                    PlannerNote(
                        "warning",
                        f"Strategy {strategy.name!r} produced a multi-platform "
                        "group, which the composer cannot combine into one "
                        "query yet; planning one query per platform instead.",
                    )
                )
                groups = [(platform,) for platform in usable_platforms]
            for group in groups:
                target = group[0]
                for engine in usable_engines:
                    label = f"{target.name} on {engine} ({title})"
                    if len(queries) >= budget:
                        dropped.append(label)
                        continue
                    planned = self._compose_query(
                        engine=engine,
                        target=target,
                        title=title,
                        location=location,
                        workplace_type=workplace_type,
                        date_range=date_range,
                        max_results=max_results,
                        notes=notes,
                    )
                    if planned is not None:
                        queries.append(planned)

        if dropped:
            shown = "; ".join(dropped[:5]) + (" ..." if len(dropped) > 5 else "")
            notes.append(
                PlannerNote(
                    "warning",
                    f"The query budget ({budget}) was reached; "
                    f"{len(dropped)} planned search(es) were not scheduled: "
                    f"{shown}",
                )
            )
        return PlannedSearch(tuple(queries), tuple(notes), tuple(dropped))

    # ------------------------------------------------------------------
    # Admission
    # ------------------------------------------------------------------

    def _usable_engines(
        self, engines: Sequence[str], notes: list[PlannerNote]
    ) -> list[str]:
        usable: list[str] = []
        for name in engines:
            spec = self._engine_specs.get(name)
            if spec is None:
                notes.append(
                    PlannerNote(
                        "warning",
                        f"Engine {name!r} is not in the search-surface "
                        "catalog; skipped.",
                    )
                )
                continue
            if spec.automation_url is None:
                notes.append(
                    PlannerNote(
                        "info",
                        f"Engine {name!r} has no automated form in the "
                        "catalog; skipped.",
                    )
                )
                continue
            usable.append(name)
        return usable

    def _usable_platforms(
        self, platforms: Sequence[str], notes: list[PlannerNote]
    ) -> list[PlatformTarget]:
        usable: list[PlatformTarget] = []
        for name in platforms:
            target = self._platform_targets.get(name)
            if target is None:
                notes.append(
                    PlannerNote(
                        "warning",
                        f"Platform {name!r} has no ATS descriptor; skipped.",
                    )
                )
                continue
            if not target.restriction:
                notes.append(
                    PlannerNote(
                        "info",
                        f"Platform {name!r} declares no search restriction; "
                        "skipped.",
                    )
                )
                continue
            try:
                status = VerificationStatus(target.status)
            except ValueError:
                notes.append(
                    PlannerNote(
                        "warning",
                        f"Platform {name!r} has an unknown restriction "
                        f"status {target.status!r}; skipped.",
                    )
                )
                continue
            if status not in AUTOMATION_STATUSES:
                notes.append(
                    PlannerNote(
                        "info",
                        f"Platform {name!r} is {status.value}-verified, below "
                        "the level automation requires (measured or "
                        "vendor-documented). It is not planned until "
                        "verified.",
                    )
                )
                continue
            if self._is_terminal(f"https://{target.restriction}"):
                notes.append(
                    PlannerNote(
                        "warning",
                        f"Platform {name!r}'s restriction looks like a "
                        "terminal page (success/confirm); never planned.",
                    )
                )
                continue
            usable.append(target)
        return usable

    # ------------------------------------------------------------------
    # Composition (single-sourced through the catalog's composer)
    # ------------------------------------------------------------------

    def _compose_query(
        self,
        *,
        engine: str,
        target: PlatformTarget,
        title: str,
        location: str,
        workplace_type: str,
        date_range: str | None,
        max_results: int,
        notes: list[PlannerNote],
    ) -> PlannedQuery | None:
        spec = self._engine_specs[engine]
        template = spec.site_template
        if template is None:
            notes.append(
                PlannerNote(
                    "warning",
                    f"Engine {engine!r} declares no form for site-restricted "
                    f"searches; {target.name} is not planned on it.",
                )
            )
            return None
        result = compose(
            QueryRequest(
                surface=engine,
                site=target.restriction,
                phrases=(title,),
            ),
            spec,
        )
        if result.bar_text is None:
            refusal = next(
                (n.message for n in result.notes if n.severity == "refused"),
                "the engine cannot carry a site restriction",
            )
            notes.append(
                PlannerNote(
                    "info",
                    f"{target.name} on {engine}: not planned — {refusal}",
                )
            )
            return None
        bar_text = result.bar_text
        # Location is user intent. Engines whose form has a location field
        # get it through the URL at run time; engines without one get the
        # place as bare words, the way a person would type it.
        url_template = spec.urls[template]
        has_location_field = any(
            parameter.source == "location"
            for parameter in url_template.parameters
        )
        if location.strip() and not has_location_field:
            bar_text = f"{bar_text} {location.strip()}"
        return PlannedQuery(
            engine=engine,
            platform=target.name,
            title=title,
            location=location,
            workplace_type=workplace_type,
            raw_query_string=bar_text,
            surface_template=template,
            date_range=date_range,
            max_results=max_results,
        )

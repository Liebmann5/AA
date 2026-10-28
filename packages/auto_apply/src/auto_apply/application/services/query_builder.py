"""The query builder service — the application seam the surfaces call.

What this service owns:

  * the offered surfaces, with the verification rule applied (an unverified
    or not-yet-composable capability is never offered);
  * defaults read from the user's profile (saved job titles, locations,
    workplace types) — strictly read-only; building a query never writes to
    the profile;
  * the last few queries the user built (default 5), stored at
    <data home>/query_builder_recent.json — deduplicated, capped, clearable,
    and known to the uninstaller.

What it deliberately does not do:

  * write anything on build. ``build()`` composes and returns; it never
    touches the disk. A surface may rebuild the preview on every keystroke,
    so recording there would store half-typed queries and write to the device
    without a deliberate user action. Recording is explicit: surfaces call
    ``remember()`` only when the user copies or opens a result.
  * open or drive a browser, or touch the network — nothing this module or
    the composer imports can do either;
  * write anywhere else. In particular nothing here ever reaches the research
    store, and the recent-queries file is removed by --uninstall (it is in
    the uninstaller's known data-home entries);
  * decide anything about research. If a future, separately-consented
    research feature ever studies how people build searches, it will need its
    own versioned consent through the existing research-consent mechanism —
    this file contains no hook, port or placeholder for it.

On the recent-queries file's protection level, said plainly: it is plaintext,
the same protection class as the logs, checkpoints and session reports that
already live in the data home. It is not vault-encrypted, because the vault
is opt-in and per-profile — conditional encryption would protect some users
and silently not others.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path

from auto_apply.application.services.i18n import get_text
from auto_apply.domain.config import USER_DATA_DIR
from auto_apply.domain.exceptions import QueryBuilderError
from auto_apply.domain.models.search_query import (
    BuilderDefaults,
    OfferedCapability,
    OfferedChoice,
    PlatformOffer,
    QueryNote,
    QueryRequest,
    QueryResult,
    SurfaceOffer,
)
from auto_apply.domain.ports.ats_port import ATSDescriptor, ATSRegistryPort
from auto_apply.domain.models.search_surface import (
    OFFERED_STATUSES,
    SearchSurfaceSpec,
)
from auto_apply.domain.services.query_composer import compose

logger = logging.getLogger(__name__)

DEFAULT_RECENT_PATH = USER_DATA_DIR / "query_builder_recent.json"
DEFAULT_MAX_RECENT = 5


# QueryBuilderError lives in domain.exceptions (imported above); existing
# imports from this module keep working through that re-export.


class QueryBuilderService:
    """Profile defaults, offered surfaces, and remembered queries."""

    def __init__(
        self,
        *,
        profile=None,
        load_spec: Callable[[str], SearchSurfaceSpec] | None = None,
        list_names: Callable[[], list[str]] | None = None,
        ats_registry: ATSRegistryPort | None = None,
        recent_path: Path = DEFAULT_RECENT_PATH,
        max_recent: int = DEFAULT_MAX_RECENT,
    ) -> None:
        self._profile = profile
        self._load_spec = load_spec
        self._list_names = list_names
        self._ats_registry = ats_registry
        self._recent_path = recent_path
        self._max_recent = max(1, int(max_recent))

    # ------------------------------------------------------------------
    # Offered surfaces — the verification rule applied
    # ------------------------------------------------------------------

    def surfaces(self) -> tuple[SurfaceOffer, ...]:
        """Every catalogued surface, with unverified capabilities removed.

        A catalog defect propagates (SearchSurfaceError) — a wrong offer is
        worse than a loud failure.
        """
        if self._list_names is None or self._load_spec is None:
            return ()
        return tuple(self._offer(self._load_spec(name)) for name in self._list_names())

    @staticmethod
    def _offer(spec: SearchSurfaceSpec) -> SurfaceOffer:
        operators = tuple(
            OfferedCapability(
                key=op.name,
                label=op.label,
                explanation=op.explanation,
                channel=op.channel,
                status=op.status.value,
            )
            for op in spec.operators
            if op.composable and op.status in OFFERED_STATUSES
        )
        options = tuple(
            OfferedCapability(
                key=opt.option,
                label=opt.label,
                explanation=opt.explanation,
                channel=opt.channel,
                status=opt.status.value,
                choices=tuple(
                    OfferedChoice(key=k, label=v)
                    for k, v in (opt.option_labels or {k: k for k in opt.codes}).items()
                ),
            )
            for opt in spec.url_options
            if opt.composable and opt.status in OFFERED_STATUSES
        )
        return SurfaceOffer(
            name=spec.name,
            display_name=spec.display_name,
            kind=spec.kind,
            summary=spec.summary,
            usage_note=spec.usage_note,
            operators=operators,
            options=options,
            templates=tuple(spec.urls),
        )

    # ------------------------------------------------------------------
    # Profile defaults — strictly read-only
    # ------------------------------------------------------------------

    def defaults(self) -> BuilderDefaults:
        """The profile's saved search values, offered as one-click choices."""
        prefs = getattr(self._profile, "search_preferences", None)
        return BuilderDefaults(
            titles=tuple(getattr(prefs, "desired_job_titles", ()) or ()),
            locations=tuple(getattr(prefs, "preferred_locations", ()) or ()),
            workplace_types=tuple(getattr(prefs, "workplace_types", ()) or ()),
        )

    # ------------------------------------------------------------------
    # Build (writes nothing) and remember (explicit)
    # ------------------------------------------------------------------

    def build(self, request: QueryRequest) -> QueryResult:
        """Compose the bar text and URL. Writes NOTHING.

        The surfaces may rebuild the preview as the user types, so building
        must not touch the disk. Recording is the surfaces' explicit choice
        via remember(), called only when the user copies or opens a result.
        """
        if self._load_spec is None:
            raise QueryBuilderError(
                "no search-surface catalog is wired into the query builder"
            )
        spec = self._load_spec(request.surface)
        return compose(request, spec)

    # ------------------------------------------------------------------
    # Platform searches — platform identity comes from the injected ATS
    # registry; the engine's site: syntax comes from the catalog. Nothing
    # here imports the registry adapter.
    # ------------------------------------------------------------------

    def platforms(self) -> tuple[ATSDescriptor, ...]:
        """The hiring platforms the builder can target: every descriptor
        with at least one host. Search reliability is descriptor data
        (search_restriction_status), shown by the surfaces — not an offer
        gate: the capability being offered is the engine's vendor-documented
        site: operator applied to a host that demonstrably exists."""
        if self._ats_registry is None:
            return ()
        return tuple(d for d in self._ats_registry.all_descriptors() if d.hosts)

    def platform_offers(self) -> tuple[PlatformOffer, ...]:
        """Every targetable platform with its verification label.

        The label is computed here — once, from the shared locale strings —
        so every surface renders the same words and carries no status
        vocabulary of its own. Measured and vendor-verified platforms carry
        no badge.
        """
        offers: list[PlatformOffer] = []
        for descriptor in self.platforms():
            status = descriptor.search_restriction_status
            if status == "unverified":
                label = get_text("builder.platform.unverified")
            elif status == "third_party":
                label = get_text("builder.platform.third_party")
            else:
                label = ""
            offers.append(
                PlatformOffer(name=descriptor.name, status=status, label=label)
            )
        return tuple(offers)

    def platform_restriction_for(
        self, platform: str | None = None, url: str | None = None
    ) -> str:
        """The resolved site: restriction — for a platform name, optionally
        narrowed to a tenant URL, or for a tenant URL alone (the platform is
        matched from the URL).

        This is the one definition of what a platform or company query
        resolves to, so a remembered query replays identically.
        """
        if url is not None:
            if self._ats_registry is None:
                raise QueryBuilderError(
                    "no ATS registry is wired into the query builder"
                )
            descriptor = self._ats_registry.match(url)
            if descriptor is None:
                raise QueryBuilderError(
                    f"no hiring platform is known for {url!r}"
                )
            if platform is not None and descriptor.name != platform:
                raise QueryBuilderError(
                    f"{url!r} is on {descriptor.name!r}, not {platform!r}"
                )
            return descriptor.search_restriction_for(url)
        if platform is None:
            raise QueryBuilderError(
                "platform_restriction_for needs a platform or a URL"
            )
        return self._descriptor_for(platform).search_restriction_for()

    def build_platform_search(
        self, platform: str, request: QueryRequest
    ) -> QueryResult:
        """A domain-restricted engine search for one platform.

        The restriction is composed through the normal composer, so the
        same refusals, notes and length limits apply. Writes nothing.
        """
        if request.site:
            raise QueryBuilderError(
                "the request already carries a site restriction"
            )
        restricted = request.model_copy(
            update={"site": self.platform_restriction_for(platform)}
        )
        return self.build(restricted)

    def build_company_search(self, url: str, request: QueryRequest) -> QueryResult:
        """A company-scoped engine search from a pasted tenant URL.

        The URL's platform is matched and its tenant slug narrows the
        restriction (holisticai.bamboohr.com, jobs.lever.co/acme,
        recruiterflow.com/db_<id>). A URL on no known platform gets a refusal
        note, never a guess. Writes nothing.
        """
        if self._ats_registry is None:
            raise QueryBuilderError(
                "no ATS registry is wired into the query builder"
            )
        descriptor = self._ats_registry.match(url)
        if descriptor is None:
            return QueryResult(
                surface=request.surface,
                display_name=request.surface,
                bar_text=None,
                url=None,
                notes=(
                    QueryNote(
                        severity="refused",
                        topic="platform",
                        message=(
                            "that address is not on a hiring platform AA "
                            "knows, so no search was built."
                        ),
                    ),
                ),
            )
        if request.site:
            raise QueryBuilderError(
                "the request already carries a site restriction"
            )
        restricted = request.model_copy(
            update={"site": self.platform_restriction_for(url=url)}
        )
        return self.build(restricted)

    def _descriptor_for(self, platform: str) -> ATSDescriptor:
        """One descriptor by name, or a loud error — a quiet empty result
        for an unknown platform would be a different-search lie."""
        if self._ats_registry is None:
            raise QueryBuilderError(
                "no ATS registry is wired into the query builder"
            )
        for descriptor in self._ats_registry.all_descriptors():
            if descriptor.name == platform:
                return descriptor
        raise QueryBuilderError(f"unknown platform {platform!r}")

    def remember(self, request: QueryRequest) -> None:
        """Record a query as one of the recent few.

        Called by the surfaces only when the user copies or opens a result —
        never on preview builds.
        """
        self._record_recent(request)

    # ------------------------------------------------------------------
    # Recent queries
    # ------------------------------------------------------------------

    def recent(self) -> tuple[QueryRequest, ...]:
        """The remembered queries, newest first."""
        out: list[QueryRequest] = []
        for item in self._read_recent():
            try:
                out.append(QueryRequest.model_validate(item))
            except Exception:  # noqa: BLE001 — a stale or partial entry is skipped
                continue
        return tuple(out)

    def clear_recent(self) -> None:
        """Forget every remembered query. The file is removed, not emptied."""
        try:
            self._recent_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("could not clear recent queries: %s", exc)

    def _record_recent(self, request: QueryRequest) -> None:
        entry = json.loads(request.model_dump_json())
        entries = [entry]
        for item in self._read_recent():
            if item != entry:
                entries.append(item)
        entries = entries[: self._max_recent]
        payload = (
            json.dumps(entries, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8")
        try:
            self._recent_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._recent_path.with_suffix(".tmp")
            tmp.write_bytes(payload)
            os.replace(tmp, self._recent_path)
        except OSError as exc:
            logger.warning("could not record a recent query: %s", exc)

    def _read_recent(self) -> list[dict]:
        try:
            data = json.loads(self._recent_path.read_bytes().decode("utf-8"))
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else []

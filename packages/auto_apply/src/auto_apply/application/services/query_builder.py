"""The query builder service — the application seam the surfaces call (turn 3).

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

from auto_apply.domain.config import USER_DATA_DIR
from auto_apply.domain.models.search_query import (
    BuilderDefaults,
    OfferedCapability,
    OfferedChoice,
    QueryRequest,
    QueryResult,
    SurfaceOffer,
)
from auto_apply.domain.models.search_surface import (
    OFFERED_STATUSES,
    SearchSurfaceSpec,
)
from auto_apply.domain.services.query_composer import compose

logger = logging.getLogger(__name__)

DEFAULT_RECENT_PATH = USER_DATA_DIR / "query_builder_recent.json"
DEFAULT_MAX_RECENT = 5


class QueryBuilderError(RuntimeError):
    """The builder could not complete the request."""


class QueryBuilderService:
    """Profile defaults, offered surfaces, and remembered queries."""

    def __init__(
        self,
        *,
        profile=None,
        load_spec: Callable[[str], SearchSurfaceSpec] | None = None,
        list_names: Callable[[], list[str]] | None = None,
        recent_path: Path = DEFAULT_RECENT_PATH,
        max_recent: int = DEFAULT_MAX_RECENT,
    ) -> None:
        self._profile = profile
        self._load_spec = load_spec
        self._list_names = list_names
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

        Turn 3's surfaces may rebuild the preview as the user types, so
        building must not touch the disk. Recording is the surfaces' explicit
        choice via remember(), called only when the user copies or opens a
        result.
        """
        if self._load_spec is None:
            raise QueryBuilderError(
                "no search-surface catalog is wired into the query builder"
            )
        spec = self._load_spec(request.surface)
        return compose(request, spec)

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

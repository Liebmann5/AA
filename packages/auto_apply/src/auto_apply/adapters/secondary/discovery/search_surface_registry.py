"""Loading and validation for the search-surface catalog.

The catalog (resources/search_surfaces/*.surface.yaml) is the single source
of truth for what every search surface accepts — typed operators, address-bar
parameters, URL construction — shared by the automated engine strategies and
the user-facing query builder.

File reading and user-override merging are REUSED from SelectorLoader (the
engines' loader), including its prepend semantics for user lists. The failure
rules are deliberately unlike the pay-transparency loader's silent hidden
fallback (a known defect): a missing, unreadable or invalid BUNDLED
definition raises SearchSurfaceError; a malformed or invalid USER override
logs a warning and falls back to the bundled definition.

Two read paths, on purpose:

  * ``load_surface`` (merged) — the builder's user-facing path; user
    overrides apply, so a user can extend the surfaces they search by hand.
  * ``load_surface_bundled`` (bundled only) — the automation path. AA's
    automated discovery must send the same URL bytes no matter what a user
    has overridden for their own manual searches, so engine_strategies reads
    only the bundled catalog until job provenance records a catalog digest
    on every job (planned; not yet built).
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import ValidationError

from auto_apply.adapters.secondary.discovery.strategies.selector_loader import (
    SelectorLoader,
)
from auto_apply.domain.config import USER_DATA_DIR
from auto_apply.domain.models.search_surface import SearchSurfaceSpec

logger = logging.getLogger(__name__)

SURFACE_SUFFIX = ".surface.yaml"

_BUNDLED_DIR: Path = (
    Path(__file__).resolve().parent  # discovery/
    .parent                          # secondary/
    .parent                          # adapters/
    .parent                          # auto_apply/
    / "resources"
    / "search_surfaces"
)

_USER_OVERRIDE_DIR: Path = USER_DATA_DIR / "search_surfaces"


class SearchSurfaceError(RuntimeError):
    """The search-surface catalog could not be loaded or validated."""


_default_loader: SelectorLoader | None = None
_spec_cache: dict[str, SearchSurfaceSpec] = {}
_bundled_cache: dict[str, SearchSurfaceSpec] = {}


def _loader() -> SelectorLoader:
    global _default_loader
    if _default_loader is None:
        _default_loader = SelectorLoader(
            bundled_dir=_BUNDLED_DIR,
            user_override_dir=_USER_OVERRIDE_DIR,
        )
    return _default_loader


def _bundled_spec(name: str, loader: SelectorLoader) -> SearchSurfaceSpec:
    bundled = loader.load_bundled(name, suffix=SURFACE_SUFFIX)
    if not bundled:
        raise SearchSurfaceError(
            f"no bundled search-surface definition for {name!r} "
            f"(expected {_BUNDLED_DIR / (name + SURFACE_SUFFIX)})"
        )
    try:
        return SearchSurfaceSpec.model_validate(bundled)
    except ValidationError as exc:
        raise SearchSurfaceError(
            f"the bundled search-surface definition for {name!r} is invalid: "
            f"{exc}"
        ) from exc


def load_surface(
    name: str, *, loader: SelectorLoader | None = None
) -> SearchSurfaceSpec:
    """Load and validate one surface's catalog entry (user overrides applied).

    This is the builder's user-facing path. For AA's automated discovery use
    load_surface_bundled() — automation bytes must never depend on a user
    override.

    Raises:
        SearchSurfaceError: no bundled definition exists, or the bundled
            definition is unreadable or invalid. User overrides never raise;
            a bad override is ignored with a warning.
    """
    loader = loader or _loader()
    cached = loader is _default_loader and name in _spec_cache
    if cached:
        return _spec_cache[name]

    bundled_spec = _bundled_spec(name, loader)

    merged = loader.load(name, suffix=SURFACE_SUFFIX)
    if merged == bundled_spec.model_dump():
        spec = bundled_spec
    else:
        try:
            spec = SearchSurfaceSpec.model_validate(merged)
        except ValidationError as exc:
            logger.warning(
                "Search-surface override for %r is invalid and was ignored: %s",
                name,
                exc,
            )
            spec = bundled_spec

    if loader is _default_loader:
        _spec_cache[name] = spec
    return spec


def load_surface_bundled(
    name: str, *, loader: SelectorLoader | None = None
) -> SearchSurfaceSpec:
    """Load ONLY the bundled catalog entry — the automation path.

    AA's automated discovery must send the same URL bytes regardless of any
    user override in <data>/search_surfaces, so this path never reads the
    user override directory. The byte-identity pin
    (tests/adapters/test_engine_url_byte_identity.py) covers what automation
    sends; tests/infrastructure/test_search_surface_registry.py pins that
    overrides cannot reach it.

    Raises:
        SearchSurfaceError: no bundled definition exists, or it is invalid.
    """
    loader = loader or _loader()
    cached = loader is _default_loader and name in _bundled_cache
    if cached:
        return _bundled_cache[name]

    spec = _bundled_spec(name, loader)

    if loader is _default_loader:
        _bundled_cache[name] = spec
    return spec


def list_surface_names(loader: SelectorLoader | None = None) -> list[str]:
    """Every surface name with a definition, bundled first, then user-only."""
    loader = loader or _loader()
    names: list[str] = []
    seen: set[str] = set()
    for directory in (loader.bundled_dir, loader.user_override_dir):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob(f"*{SURFACE_SUFFIX}")):
            name = path.name[: -len(SURFACE_SUFFIX)]
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names

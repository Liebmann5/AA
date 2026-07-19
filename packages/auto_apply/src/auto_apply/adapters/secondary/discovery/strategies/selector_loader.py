"""YAML‑driven selector configuration loader with user‑override support.

Loads bundled selector definitions from ``resources/engines/<name>.yaml`` and
merges optional user overrides from ``<USER_DATA_DIR>/engines/<name>.yaml``.

Merge semantics:
    - Scalars (strings, booleans, numbers): user value wins.
    - Lists: user entries are PREPENDED (tried first), bundled entries follow.
    - Nested dicts: recursively merged with the same rules.
    - selectors within a step: user selectors are prepended so they are tried
      before the bundled defaults, giving users the ability to fix broken
      selectors without waiting for an AA release.

Graceful degradation:
    - If the bundled YAML is missing, an empty config is returned (caller handles it).
    - If the user YAML is malformed, a warning is logged and the bundled config
      is used unchanged.
    - If pyyaml is not installed, bundled configs cannot be loaded — an empty
      config is returned.

Examples:
    >>> loader = SelectorLoader()
    >>> config = loader.load("google")
    >>> config["engine"]
    'google'
    >>> config["search_bar_selectors"][0]
    "input[name='q']"
"""

from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from auto_apply.domain.config import USER_DATA_DIR

logger = logging.getLogger(__name__)

# Path to the bundled YAML descriptor directory.
_BUNDLED_DIR: Path = (
    Path(__file__).resolve().parent  # strategies/
    .parent                          # discovery/
    .parent                          # secondary/
    .parent                          # adapters/
    .parent                          # auto_apply/
    / "resources"
    / "engines"
)

# Path where users may place overriding YAML files.
_USER_OVERRIDE_DIR: Path = USER_DATA_DIR / "engines"

try:
    import yaml as _yaml

    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    _yaml = None  # type: ignore[assignment]
    _YAML_AVAILABLE = False


class SelectorLoader:
    """Loads and caches selector configurations from YAML files.

    Each engine (google, bing, indeed) has a bundled YAML file in
    ``resources/engines/``.  Users may optionally place an override file at
    ``<USER_DATA_DIR>/engines/<name>.yaml`` which is merged on top of the
    bundled version.

    Configs are cached in memory after first load — subsequent calls for the
    same engine are O(1) dict lookups.

    Args:
        bundled_dir: Override path to the bundled YAML directory.
            Defaults to ``resources/engines/`` inside the package.
        user_override_dir: Override path for user YAML files.
            Defaults to ``<USER_DATA_DIR>/engines/``.
    """

    def __init__(
        self,
        bundled_dir: Path | None = None,
        user_override_dir: Path | None = None,
    ) -> None:
        self._bundled_dir = bundled_dir or _BUNDLED_DIR
        self._user_override_dir = user_override_dir or _USER_OVERRIDE_DIR
        self._cache: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, engine_name: str) -> dict[str, Any]:
        """Return the merged selector configuration for *engine_name*.

        On first call the YAML files are read, merged, and cached.  Subsequent
        calls return the cached config immediately.

        Args:
            engine_name: Lowercase engine identifier (e.g. ``"google"``).

        Returns:
            A dict with the merged configuration.  Returns an empty dict
            when the bundled YAML is missing or unparseable.
        """
        if engine_name in self._cache:
            return self._cache[engine_name]

        config = self._load_and_merge(engine_name)
        self._cache[engine_name] = config
        return config

    def reload(self, engine_name: str) -> dict[str, Any]:
        """Force a re‑read of both YAML files, bypassing the cache.

        Useful after a user edits their override file mid‑session (during
        development or debugging — not a normal production path).

        Args:
            engine_name: Lowercase engine identifier.

        Returns:
            Freshly merged configuration dict.
        """
        self._cache.pop(engine_name, None)
        return self.load(engine_name)

    def clear_cache(self) -> None:
        """Drop all cached configurations."""
        self._cache.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_and_merge(self, engine_name: str) -> dict[str, Any]:
        """Load bundled and user YAML, then merge."""
        bundled = self._read_yaml(self._bundled_dir / f"{engine_name}.yaml")
        if bundled is None:
            logger.warning(
                "SelectorLoader: bundled config for %r not found — "
                "toolbar selectors will be unavailable",
                engine_name,
            )
            return {}

        user = self._read_yaml(self._user_override_dir / f"{engine_name}.yaml")
        if user is not None:
            logger.info(
                "SelectorLoader: merging user overrides for engine %r",
                engine_name,
            )
            return _deep_merge(bundled, user)

        return bundled

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any] | None:
        """Read a single YAML file and return its contents as a dict.

        Returns None when the file does not exist, is unparseable, or pyyaml
        is not installed.  All errors are logged — the caller receives None
        and can degrade gracefully.
        """
        if not _YAML_AVAILABLE:
            logger.debug(
                "SelectorLoader: pyyaml not installed — cannot read %s", path
            )
            return None

        if not path.is_file():
            logger.debug("SelectorLoader: config file not found | path=%s", path)
            return None

        try:
            with path.open(encoding="utf-8") as fh:
                data = _yaml.safe_load(fh)
            if not isinstance(data, dict):
                logger.warning(
                    "SelectorLoader: %s is not a YAML mapping — ignoring", path.name
                )
                return None
            return data
        except Exception as exc:
            logger.warning(
                "SelectorLoader: failed to read %s | error=%s", path.name, exc
            )
            return None


# --------------------------------------------------------------------------
# Module‑level merge helper
# --------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*.

    Rules:
        - Scalars: override wins.
        - Lists: override entries are PREPENDED to base entries (user's
          selectors are tried first).
        - Nested dicts: recursively merged.

    The original *base* dict is NOT mutated — a new dict is returned.
    """
    result = deepcopy(base)

    for key, val in override.items():
        if key not in result:
            # New key — add it directly.
            result[key] = deepcopy(val)
        elif isinstance(val, dict) and isinstance(result[key], dict):
            # Both are dicts → recurse.
            result[key] = _deep_merge(result[key], val)
        elif isinstance(val, list) and isinstance(result[key], list):
            # Lists → prepend user entries.
            result[key] = list(val) + list(result[key])
        else:
            # Scalar or type mismatch → override wins.
            result[key] = deepcopy(val)

    return result
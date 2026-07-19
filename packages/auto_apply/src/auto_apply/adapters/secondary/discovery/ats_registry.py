"""ATS platform registry — loads YAML descriptors and matches URLs.

At startup, :class:`ATSRegistry` reads every ``*.yaml`` file in
``resources/ats/`` and compiles the URL patterns into regex objects.
``match(url)`` then returns the first matching :class:`ATSDescriptor` in
O(n·p) time, where n is the number of platforms and p is the number of
patterns per platform (both small constants).

Graceful degradation:
    - ``pyyaml`` not installed → warning logged, registry returns no matches.
    - A malformed YAML file → that file is skipped, rest load normally.
    - ``resources/ats/`` directory missing → warning logged, empty registry.

Example:
    >>> registry = ATSRegistry()
    >>> d = registry.match("https://boards.greenhouse.io/acme/jobs/12345")
    >>> d.name
    'greenhouse'
    >>> d.multi_step
    False
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from auto_apply.domain.ports.ats_port import ATSDescriptor

logger = logging.getLogger(__name__)

# Path to the YAML descriptor directory, relative to this file.
# Resolves to: src/auto_apply/resources/ats/
_ATS_DIR: Path = (
    Path(__file__).resolve().parent  # discovery/
    .parent                          # secondary/
    .parent                          # adapters/
    .parent                          # auto_apply/
    / "resources"
    / "ats"
)

try:
    import yaml as _yaml

    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    _yaml = None  # type: ignore[assignment]
    _YAML_AVAILABLE = False


@dataclass
class _CompiledEntry:
    """Internal: an ATSDescriptor paired with its compiled URL pattern regexes."""

    descriptor: ATSDescriptor
    patterns: list[re.Pattern[str]]


class ATSRegistry:
    """Loads ATS descriptors from YAML and resolves URLs to platform names.

    Constructed once at startup (typically inside ``build_orchestrator``).
    Thread-safe after construction — all state is immutable.

    Args:
        ats_dir: Override path to the YAML directory. Defaults to
            ``resources/ats/`` inside the package. Useful for testing.
    """

    def __init__(self, ats_dir: Path | None = None) -> None:
        self._entries: list[_CompiledEntry] = []
        self._load(ats_dir or _ATS_DIR)

    # ─────────────────────────────────────────────────────────────────────────
    # Public interface
    # ─────────────────────────────────────────────────────────────────────────

    def match(self, url: str) -> ATSDescriptor | None:
        """Returns the first ATSDescriptor whose URL patterns match *url*.

        Matching is case-insensitive; the URL scheme (``https://``) is
        stripped before comparison.

        Args:
            url: Fully-qualified job application URL.

        Returns:
            :class:`ATSDescriptor` for the matched platform, or ``None`` if
            no descriptor covers the URL.
        """
        normalised = _strip_scheme(url)
        for entry in self._entries:
            for pat in entry.patterns:
                if pat.search(normalised):
                    logger.debug(
                        "ATSRegistry.match | ats=%s url=%s",
                        entry.descriptor.name,
                        url,
                    )
                    return entry.descriptor
        return None

    def all_descriptors(self) -> list[ATSDescriptor]:
        """Returns every loaded ATSDescriptor, in load order."""
        return [e.descriptor for e in self._entries]

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        names = [e.descriptor.name for e in self._entries]
        return f"ATSRegistry(platforms={names})"

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _load(self, directory: Path) -> None:
        """Loads all ``*.yaml`` files from *directory*."""
        if not _YAML_AVAILABLE:
            logger.warning(
                "pyyaml is not installed — ATSRegistry will return no matches. "
                "Run: pip install pyyaml"
            )
            return

        if not directory.is_dir():
            logger.warning(
                "ATSRegistry: descriptor directory not found | path=%s", directory
            )
            return

        yaml_files = sorted(directory.glob("*.yaml"))
        if not yaml_files:
            logger.warning("ATSRegistry: no *.yaml files found in %s", directory)
            return

        for path in yaml_files:
            entry = self._load_file(path)
            if entry is not None:
                self._entries.append(entry)

        logger.info(
            "ATSRegistry loaded | platforms=%d dir=%s",
            len(self._entries),
            directory,
        )

    def _load_file(self, path: Path) -> _CompiledEntry | None:
        """Loads a single YAML descriptor file.

        Returns None and logs a warning if the file is malformed or missing
        required fields.
        """
        try:
            with path.open(encoding="utf-8") as fh:
                data = _yaml.safe_load(fh)
        except Exception as exc:
            logger.warning("ATSRegistry: failed to read %s | error=%s", path.name, exc)
            return None

        if not isinstance(data, dict):
            logger.warning("ATSRegistry: %s is not a YAML mapping — skipping", path.name)
            return None

        try:
            descriptor = _build_descriptor(data, path.name)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "ATSRegistry: malformed descriptor in %s | error=%s", path.name, exc
            )
            return None

        patterns = _compile_patterns(descriptor.url_patterns)
        if not patterns:
            logger.warning(
                "ATSRegistry: %s has no valid URL patterns — skipping", path.name
            )
            return None

        logger.debug(
            "ATSRegistry: loaded ats=%s patterns=%d",
            descriptor.name,
            len(patterns),
        )
        return _CompiledEntry(descriptor=descriptor, patterns=patterns)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_descriptor(data: dict, filename: str) -> ATSDescriptor:
    """Constructs an ATSDescriptor from a raw YAML dict.

    Raises ``KeyError`` if required fields are missing.
    """
    name = str(data.get("name") or Path(filename).stem)

    raw_patterns = data.get("url_patterns") or []
    raw_login = data.get("login_wall_signals") or []
    raw_success = data.get("success_signals") or []

    # Normalise multi-line YAML scalars (folded/literal block) that pyyaml
    # keeps as single strings — split on newlines and commas, strip whitespace.
    submit_selector = _normalise_selector(data.get("submit_button_selector", ""))
    form_selector = _normalise_selector(data.get("form_root_selector", ""))

    return ATSDescriptor(
        name=name,
        url_patterns=tuple(str(p).strip() for p in raw_patterns if p),
        login_wall_signals=tuple(str(s).lower().strip() for s in raw_login if s),
        success_signals=tuple(str(s).lower().strip() for s in raw_success if s),
        form_root_selector=form_selector,
        submit_button_selector=submit_selector,
        multi_step=bool(data.get("multi_step", False)),
    )


def _normalise_selector(raw: str) -> str:
    """Collapses a possibly multi-line, whitespace-heavy CSS selector to one line."""
    return " ".join(raw.split())


def _compile_patterns(patterns: tuple[str, ...]) -> list[re.Pattern[str]]:
    """Compiles glob-style URL patterns to case-insensitive regex objects.

    ``*`` is converted to ``.*`` (matches any run of characters, including
    path separators and dots) so that ``*.greenhouse.io/jobs/*`` correctly
    matches ``company.greenhouse.io/jobs/12345``.
    """
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            # Escape regex meta-characters, then restore our wildcard.
            regex_src = re.escape(pattern).replace(r"\*", ".*")
            compiled.append(re.compile(regex_src, re.IGNORECASE))
        except re.error as exc:
            logger.warning(
                "ATSRegistry: could not compile pattern %r | error=%s", pattern, exc
            )
    return compiled


def _strip_scheme(url: str) -> str:
    """Removes the URL scheme (``http://`` / ``https://``) for pattern matching."""
    for prefix in ("https://", "http://"):
        if url.lower().startswith(prefix):
            return url[len(prefix):]
    return url
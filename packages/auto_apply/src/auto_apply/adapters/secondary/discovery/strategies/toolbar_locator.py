"""Toolbar element locator — CSS/XPath selectors with Math‑DOM fallback.

This module provides :class:`ToolbarElementLocator`, which is the decoupled
selector system injected into :class:`SearchEngineStrategy` subclasses.  It
replaces the hardcoded CSS/XPath selectors previously embedded in each
strategy's ``apply_toolbar_filters()`` method.

Architecture:
    SearchEngineStrategy
        └── ToolbarElementLocator  (injected via constructor)
              ├── SelectorLoader   (YAML → selector definitions)
              ├── SelectorConfidenceTracker (per‑selector success/failure stats)
              └── MathDOMAdapter   (optional — geometry‑aware fallback)

Locator flow for a single element lookup:
    1. Get ordered selectors from the YAML config (sorted by confidence).
    2. Try each CSS/XPath selector against the live browser.
    3. If all selectors fail AND a MathDOMAdapter is available:
       a. Extract the full DOM tree.
       b. Search for elements matching the fallback descriptor (tag, role,
          aria‑label, visible text).
       c. Return the first matching element.
    4. Record success/failure for each selector in the confidence tracker.
    5. Return None if no element could be found (caller skips the filter).

Graceful degradation:
    - No MathDOMAdapter → Math fallback is skipped.
    - No YAML config → empty selector list → always falls back to Math or None.
    - All selectors fail + no Math → returns None (caller skips the toolbar step).

Example:
    >>> from auto_apply.adapters.secondary.discovery.strategies.selector_loader import SelectorLoader
    >>> from auto_apply.adapters.secondary.discovery.strategies.toolbar_locator import ToolbarElementLocator
    >>>
    >>> loader = SelectorLoader()
    >>> locator = ToolbarElementLocator(browser=driver, engine_name="google", loader=loader)
    >>>
    >>> el = locator.find_element("toolbar.date_filter.open_button")
    >>> if el is not None:
    ...     el.click()
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from auto_apply.domain.config import USER_DATA_DIR
from auto_apply.domain.models.math_dom import DOMNode
from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)

# How many successes before a selector is considered "proven" and given top
# priority regardless of its original YAML ordering.
_PROVEN_THRESHOLD: int = 3

# File where confidence data is persisted across sessions.
_CONFIDENCE_FILE: Path = USER_DATA_DIR / "selector_confidence.json"


class _UseDefaultFileType:
    """Sentinel type distinguishing 'no file_path argument given' (use the
    real default persistent file) from an explicit ``file_path=None``
    (ephemeral, in-memory only). Using ``None`` itself as the "use default"
    sentinel was the original bug: it made every test that (reasonably)
    passed ``file_path=None`` to mean "don't persist" instead read from and
    write to the same real production file as every other test.
    """

    def __repr__(self) -> str:
        return "<USE_DEFAULT_FILE>"


_USE_DEFAULT_FILE = _UseDefaultFileType()


# ═════════════════════════════════════════════════════════════════════════════
# Selector confidence tracker
# ═════════════════════════════════════════════════════════════════════════════

class SelectorConfidenceTracker:
    """Tracks per‑selector success/failure rates across sessions.

    Selectors that succeed repeatedly are prioritised; selectors that fail
    repeatedly are deprecated to the bottom of the trial order.

    Data is persisted to ``<USER_DATA_DIR>/selector_confidence.json`` by
    default so confidence survives restarts (this is what you get by
    constructing with no arguments: ``SelectorConfidenceTracker()``). The
    in‑memory state is the authoritative source during a session; the file
    is written on each update.

    Pass an explicit ``file_path=<some path>`` to persist somewhere else
    (e.g. a ``tmp_path`` in tests that specifically exercise the save/load
    cycle — see test_persistence_round_trip).

    Pass ``file_path=None`` explicitly for a purely in-memory tracker that
    never touches disk at all — this is what every other unit test should
    use, so tests don't silently share and mutate the real production
    confidence file on disk (which is exactly what was happening before
    this fix: file_path=None was being treated as "use the default file",
    so every test constructed with file_path=None was actually reading and
    writing the same real <USER_DATA_DIR>/selector_confidence.json file as
    every other test and as a live production run, corrupting all of their
    results with cross-test and cross-run pollution).
    """

    def __init__(
        self, file_path: "Path | _UseDefaultFileType | None" = _USE_DEFAULT_FILE
    ) -> None:
        if file_path is _USE_DEFAULT_FILE:
            self._file_path: Path | None = _CONFIDENCE_FILE
        else:
            # None means "ephemeral, in-memory only" — anything else is an
            # explicit path to persist to.
            self._file_path = file_path
        # _data[engine_name][selector_key][selector_value] = {success, fail}
        self._data: dict[str, dict[str, dict[str, dict[str, int]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(lambda: {"success": 0, "fail": 0}))
        )
        self._load()

    # ── Public API ────────────────────────────────────────────────────────

    def record_success(self, engine: str, key: str, selector: str) -> None:
        """Record that a selector successfully located its target element."""
        entry = self._data[engine][key][selector]
        entry["success"] += 1
        self._save()

    def record_failure(self, engine: str, key: str, selector: str) -> None:
        """Record that a selector did NOT locate its target element."""
        entry = self._data[engine][key][selector]
        entry["fail"] += 1
        self._save()

    def get_confidence(self, engine: str, key: str, selector: str) -> float:
        """Return a confidence score in [0.0, 1.0] for a selector.

        Uses Laplace smoothing: (success + 1) / (success + fail + 2).
        An unseen selector starts at 0.5 (neutral).
        """
        entry = self._data[engine][key].get(selector)
        if entry is None:
            return 0.5
        total = entry["success"] + entry["fail"]
        if total == 0:
            return 0.5
        return (entry["success"] + 1.0) / (total + 2.0)

    def order_selectors(
        self,
        engine: str,
        key: str,
        selectors: list[str],
    ) -> list[str]:
        """Return *selectors* sorted by descending confidence.

        Selectors with ≥ ``_PROVEN_THRESHOLD`` successes are placed at the
        front regardless of their raw confidence, so proven selectors are
        tried before unproven ones.
        """
        scored = []
        for sel in selectors:
            conf = self.get_confidence(engine, key, sel)
            entry = self._data[engine][key].get(sel, {})
            successes = entry.get("success", 0)
            proven_bonus = 1.0 if successes >= _PROVEN_THRESHOLD else 0.0
            scored.append((conf + proven_bonus, conf, sel))

        scored.sort(reverse=True)
        return [sel for _, _, sel in scored]

    def get_stats(self, engine: str, key: str) -> dict[str, dict[str, int]]:
        """Return raw stats for all selectors under a given engine + key."""
        return dict(self._data[engine].get(key, {}))

    def reset(self, engine: str | None = None, key: str | None = None) -> None:
        """Clear confidence data, optionally scoped to engine/key."""
        if engine is None:
            self._data.clear()
        elif key is None:
            self._data.pop(engine, None)
        else:
            self._data.get(engine, {}).pop(key, None)
        self._save()

    # ── Persistence ───────────────────────────────────────────────────────

    def _save(self) -> None:
        """Write current confidence data to disk as JSON.

        No-op for ephemeral (in-memory only) trackers, i.e. when this
        instance was constructed with file_path=None.
        """
        if self._file_path is None:
            return
        try:
            # Convert defaultdicts to plain dicts for JSON serialisation.
            serialisable: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
            for eng, keys in self._data.items():
                serialisable[eng] = {}
                for key, sels in keys.items():
                    serialisable[eng][key] = dict(sels)

            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_path.write_text(
                json.dumps(serialisable, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug(
                "SelectorConfidenceTracker: could not persist confidence data: %s",
                exc,
            )

    def _load(self) -> None:
        """Load confidence data from disk, if available.

        No-op for ephemeral (in-memory only) trackers, i.e. when this
        instance was constructed with file_path=None.
        """
        if self._file_path is None:
            return
        if not self._file_path.is_file():
            return
        try:
            raw = json.loads(self._file_path.read_text(encoding="utf-8"))
            for eng, keys in raw.items():
                for key, sels in keys.items():
                    for sel, counts in sels.items():
                        self._data[eng][key][sel] = {
                            "success": counts.get("success", 0),
                            "fail": counts.get("fail", 0),
                        }
            logger.debug(
                "SelectorConfidenceTracker: loaded confidence data from %s",
                self._file_path,
            )
        except Exception as exc:
            logger.warning(
                "SelectorConfidenceTracker: failed to load confidence data: %s",
                exc,
            )


# ═════════════════════════════════════════════════════════════════════════════
# Toolbar element locator
# ═════════════════════════════════════════════════════════════════════════════

class ToolbarElementLocator:
    """Find toolbar elements using YAML selectors with Math‑DOM fallback.

    This class is injected into :class:`SearchEngineStrategy` subclasses
    so that toolbar interactions are decoupled from hardcoded selectors.

    Args:
        browser: The active browser interface.
        engine_name: Lowercase engine identifier (``"google"``, ``"bing"``,
            ``"indeed"``).
        loader: A :class:`~selector_loader.SelectorLoader` that provides the
            YAML‑derived selector configuration for *engine_name*.
        math_dom_adapter: Optional :class:`~MathDOMAdapter` used when all
            CSS/XPath selectors fail.  When ``None``, the Math fallback is
            skipped entirely.
        confidence_tracker: Optional :class:`SelectorConfidenceTracker`.  A
            default instance is created if one is not provided.

    Example:
        >>> locator = ToolbarElementLocator(browser, "google", loader)
        >>> el = locator.find_element("toolbar.date_filter.open_button")
        >>> if el:
        ...     el.click()
    """

    def __init__(
        self,
        browser: BrowserInterface,
        engine_name: str,
        loader: Any,  # SelectorLoader (avoids circular import)
        math_dom_adapter: Any | None = None,
        confidence_tracker: SelectorConfidenceTracker | None = None,
    ) -> None:
        self._browser = browser
        self._engine_name = engine_name
        self._loader = loader
        self._math_dom = math_dom_adapter
        self._confidence = confidence_tracker or SelectorConfidenceTracker()
        self._config: dict[str, Any] = loader.load(engine_name)

    # ── Public API ────────────────────────────────────────────────────────

    def find_element(self, section_path: str) -> ElementInterface | None:
        """Locate a toolbar element described by *section_path*.

        *section_path* is a dot‑separated path into the YAML config, e.g.
        ``"toolbar.date_filter.open_button"`` or
        ``"toolbar.date_filter.date_options.past_week"``.

        The lookup order is:
            1. CSS/XPath selectors from the config (ordered by confidence).
            2. Math‑DOM fallback (if a MathDOMAdapter is available).

        Returns:
            The first matching :class:`ElementInterface`, or ``None`` if no
            element could be found.

        Example:
            >>> el = locator.find_element("toolbar.date_filter.open_button")
        """
        section = self._resolve_path(section_path)
        if section is None:
            logger.debug(
                "ToolbarElementLocator: no config at path %r for engine %r",
                section_path,
                self._engine_name,
            )
            return None

        # ── 1. Try CSS/XPath selectors ──────────────────────────────────
        raw_selectors: list[dict[str, str]] = section.get("selectors", [])
        if raw_selectors:
            selector_strings = [
                f"{s['type']}:{s['value']}" for s in raw_selectors
            ]
            ordered = self._confidence.order_selectors(
                self._engine_name, section_path, selector_strings
            )
            for sel_str in ordered:
                sel_type, sel_value = sel_str.split(":", 1)
                locator_type = (
                    Locator.XPATH if sel_type == "xpath" else Locator.CSS_SELECTOR
                )
                element = self._try_find(locator_type, sel_value)
                if element is not None:
                    self._confidence.record_success(
                        self._engine_name, section_path, sel_str
                    )
                    logger.debug(
                        "ToolbarElementLocator: found via selector | path=%s "
                        "selector=%s",
                        section_path,
                        sel_value[:60],
                    )
                    return element
                self._confidence.record_failure(
                    self._engine_name, section_path, sel_str
                )

        # ── 2. Math‑DOM fallback ────────────────────────────────────────
        fallback = section.get("fallback")
        if fallback and self._math_dom is not None:
            element = self._find_via_math_dom(fallback)
            if element is not None:
                logger.info(
                    "ToolbarElementLocator: found via Math‑DOM fallback | path=%s",
                    section_path,
                )
                return element

        logger.debug(
            "ToolbarElementLocator: could not locate element | engine=%s path=%s",
            self._engine_name,
            section_path,
        )
        return None

    def click_element(self, section_path: str) -> bool:
        """Find a toolbar element and click it using human‑like behaviour.

        Convenience wrapper around :meth:`find_element` + click.

        Args:
            section_path: Dot‑separated path into the YAML config.

        Returns:
            ``True`` if the element was found AND clicked, ``False`` otherwise.

        Example:
            >>> locator.click_element("toolbar.date_filter.open_button")
        """
        element = self.find_element(section_path)
        if element is None:
            return False

        try:
            from auto_apply.adapters.secondary.evasion.components import behavior  # noqa: PLC0415

            behavior.human_like_click(self._browser, element)
            return True
        except Exception as exc:
            logger.warning(
                "ToolbarElementLocator: click failed | path=%s error=%s",
                section_path,
                exc,
            )
            return False

    @property
    def search_bar_selectors(self) -> list[str]:
        """Return the search‑bar CSS selectors from the YAML config.

        Used by :class:`HumanSearchNavigation` to locate the search input
        on the engine's homepage.
        """
        return self._config.get("search_bar_selectors", [])

    @property
    def homepage_url(self) -> str:
        """Return the homepage URL from the YAML config."""
        return self._config.get("homepage_url", "")

    # ── Internal helpers ──────────────────────────────────────────────────

    def _resolve_path(self, dot_path: str) -> dict[str, Any] | None:
        """Walk *dot_path* into ``self._config``, returning the leaf dict."""
        node = self._config
        for part in dot_path.split("."):
            if not isinstance(node, dict):
                return None
            node = node.get(part)
            if node is None:
                return None
        return node if isinstance(node, dict) else None

    def _try_find(
        self, locator_type: str, selector: str
    ) -> ElementInterface | None:
        """Attempt a single ``find_element`` call; return None on any error."""
        try:
            return self._browser.find_element(locator_type, selector)
        except Exception:
            return None

    # ── Math‑DOM fallback ─────────────────────────────────────────────────

    def _find_via_math_dom(self, fallback: dict) -> ElementInterface | None:
        """Use the MathDOMAdapter to locate an element by semantic properties.

        Args:
            fallback: A dict with keys:
                - ``tag`` (str): HTML tag name to filter by (optional).
                - ``role`` (str): ARIA role to filter by (optional).
                - ``aria_label_contains`` (list[str]): Substrings the
                  element's ``aria-label`` must contain (optional).
                - ``text_contains`` (list[str]): Substrings the element's
                  visible text must contain (optional).

        Returns:
            An :class:`ElementInterface` if a matching element is found,
            otherwise ``None``.
        """
        if self._math_dom is None:
            return None

        try:
            root = self._math_dom.extract_full_dom_tree()
        except Exception as exc:
            logger.debug(
                "ToolbarElementLocator: Math‑DOM extraction failed: %s", exc
            )
            return None

        if root is None:
            return None

        tag_filter = (fallback.get("tag") or "").lower()
        role_filter = (fallback.get("role") or "").lower()
        aria_substrings: list[str] = [
            s.lower() for s in fallback.get("aria_label_contains", [])
        ]
        text_substrings: list[str] = [
            s.lower() for s in fallback.get("text_contains", [])
        ]

        candidates: list[DOMNode] = []

        for node in root.iter_nodes():
            # Tag filter
            if tag_filter and node.tag != tag_filter:
                continue

            # Role filter
            node_role = node.get_attribute("role", "").lower()
            if role_filter and node_role != role_filter:
                continue

            # ARIA label filter
            node_aria = node.get_attribute("aria-label", "").lower()
            if aria_substrings and not any(
                sub in node_aria for sub in aria_substrings
            ):
                continue

            # Visible text filter
            node_text = (node.text or "").lower()
            if text_substrings and not any(
                sub in node_text for sub in text_substrings
            ):
                continue

            # Must have geometry to be clickable.
            if not node.has_geometry:
                continue

            candidates.append(node)

        if not candidates:
            return None

        # Prefer the largest candidate (most likely the intended button/menu).
        candidates.sort(
            key=lambda n: n.geometry.area if n.geometry else 0.0,
            reverse=True,
        )

        best = candidates[0]

        # Convert the DOMNode back to a live ElementInterface by using a
        # CSS selector built from its attributes.
        el_id = best.get_attribute("id", "")
        if el_id:
            element = self._try_find(Locator.CSS_SELECTOR, f"#{el_id}")
            if element is not None:
                return element

        # If the node has no id, try to locate it by tag + aria-label.
        aria = best.get_attribute("aria-label", "")
        if aria:
            escaped = aria.replace('"', '\\"')
            element = self._try_find(
                Locator.CSS_SELECTOR,
                f'{best.tag}[aria-label="{escaped}"]',
            )
            if element is not None:
                return element

        # As a last resort, return the first live element matching the tag.
        try:
            elements = self._browser.find_elements(Locator.TAG_NAME, best.tag)
            for el in elements:
                if el.get_attribute("aria-label") == aria:
                    return el
        except Exception:
            pass

        return None
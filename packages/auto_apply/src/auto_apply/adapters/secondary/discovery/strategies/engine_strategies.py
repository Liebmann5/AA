"""Search-engine-specific strategies for URL construction and toolbar interactions.

This module provides the ``SearchEngineStrategy`` ABC and concrete implementations
for Google, Bing, and Indeed.  Each strategy encapsulates ALL engine‑specific
knowledge so that providers are pure executors that only handle scraping.

Architecture:
    Provider  →  holds a SearchEngineStrategy
    Navigator →  receives strategy + instruction (no URL, no context_data dict)
    Strategy  →  knows homepage, URL params, toolbar selectors, date‑filter UI

Selector injection (ADR‑011):
    Toolbar selectors are NO LONGER hardcoded inside each strategy.  Instead,
    each strategy receives an optional :class:`ToolbarElementLocator` via its
    constructor.  The locator reads selectors from YAML files in
    ``resources/engines/`` and provides a Math‑DOM fallback when CSS/XPath
    selectors fail.  When no locator is injected, the strategy falls back to
    the legacy hardcoded selectors (backward compatibility).

Design rationale (see ENGINEERING_PHILOSOPHY.md):
    - "General strategies over one-off patches": one class per engine, not
      scattered URL‑building logic inside each provider.
    - "Graceful degradation": toolbar clicks are best‑effort; falling back to
      URL parameters or skipping the filter is acceptable.
    - "Agnostic implementations": selectors are loaded from configuration,
      not hardcoded in source.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from urllib.parse import urlencode

from auto_apply.adapters.secondary.evasion.components import behavior
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# Abstract base
# ═════════════════════════════════════════════════════════════════════════════

class SearchEngineStrategy(ABC):
    """Encapsulates all engine‑specific knowledge for a search provider.

    Each concrete subclass knows:
        - The homepage URL (for human‑typing fallback).
        - How to build a search URL from a ``SearchInstruction``.
        - Which CSS selectors locate the search bar on the homepage.
        - How to interact with post‑search toolbar widgets (date filter, etc.).

    Toolbar interactions are OPTIONAL — the default implementations are no‑ops.
    If a toolbar element cannot be found, the filter is skipped gracefully.

    Selector resolution order:
        1. ``ToolbarElementLocator`` (YAML‑driven + Math fallback) — when injected.
        2. Legacy hardcoded selectors (``_legacy_*`` methods) — fallback.
    """

    # ── Subclass contract ────────────────────────────────────────────────

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Canonical lowercase engine name (e.g. ``"google"``, ``"bing"``)."""
        ...

    @property
    def homepage_url(self) -> str:
        """The homepage URL used by ``HumanSearchNavigation``.

        When a ``ToolbarElementLocator`` is injected, this value is read from
        the YAML config.  Subclasses may still override it for backward
        compatibility.
        """
        return self._homepage_url

    @abstractmethod
    def build_search_url(self, instruction: SearchInstruction) -> str:
        """Build the fully‑qualified search URL for *instruction*.

        Args:
            instruction: The typed search instruction.

        Returns:
            A complete URL that can be passed to ``browser.get()``.
        """
        ...

    # ── Optional overrides ───────────────────────────────────────────────

    @property
    def search_bar_selectors(self) -> list[str]:
        """CSS selectors for finding the search input on the homepage.

        When a ``ToolbarElementLocator`` is injected, this value is read from
        the YAML config.  Subclasses may still override it for backward
        compatibility.
        """
        return self._search_bar_selectors

    def apply_toolbar_filters(
        self,
        browser: BrowserInterface,
        instruction: SearchInstruction,
    ) -> None:
        """Apply post‑search filters by interacting with the toolbar UI.

        The default implementation attempts to use the injected locator
        (YAML‑driven), then falls back to legacy hardcoded selectors.
        Subclasses that need different behaviour should override this method.

        Every interaction is wrapped in try/except so a missing element never
        crashes the provider.

        Args:
            browser: The active browser session (results page already loaded).
            instruction: The search instruction whose filters should be applied.
        """
        if instruction.date_range is None:
            return

        # ── 1. Try the injected locator (YAML‑driven) ──────────────────
        if self._locator is not None:
            if self._apply_via_locator(browser, instruction):
                return
            logger.debug(
                "%s: injected locator failed for date_filter — "
                "falling back to legacy selectors",
                self.engine_name,
            )

        # ── 2. Fall back to legacy hardcoded selectors ──────────────────
        self._apply_toolbar_filters_legacy(browser, instruction)

    # ── Locator injection ───────────────────────────────────────────────

    def set_locator(self, locator) -> None:
        """Inject a :class:`ToolbarElementLocator` for YAML‑driven selectors.

        Called by the composition root after construction.  When set, toolbar
        interactions use the locator's selector chain + Math fallback instead
        of hardcoded selectors.

        Args:
            locator: A :class:`~toolbar_locator.ToolbarElementLocator` instance.
        """
        self._locator = locator
        # If the locator provides selectors, prefer them over hardcoded ones.
        if hasattr(locator, "search_bar_selectors") and locator.search_bar_selectors:
            self._search_bar_selectors = list(locator.search_bar_selectors)
        if hasattr(locator, "homepage_url") and locator.homepage_url:
            self._homepage_url = locator.homepage_url

    # ── Constructor (shared by subclasses) ──────────────────────────────

    def __init__(self, locator=None) -> None:
        """Initialise the strategy.

        Args:
            locator: Optional :class:`ToolbarElementLocator`.  When provided,
                toolbar interactions use YAML‑driven selectors with Math‑DOM
                fallback.  When ``None``, legacy hardcoded selectors are used.
        """
        self._locator = locator
        # Defaults — subclasses override in their own __init__.
        self._homepage_url: str = ""
        self._search_bar_selectors: list[str] = []

    # ── Locator‑based toolbar interaction ───────────────────────────────

    def _apply_via_locator(
        self,
        browser: BrowserInterface,
        instruction: SearchInstruction,
    ) -> bool:
        """Attempt to apply the date filter using the injected locator.

        Returns:
            ``True`` if all toolbar steps succeeded, ``False`` otherwise.
        """
        locator = self._locator
        if locator is None:
            return False

        logger.debug(
            "%s: attempting toolbar date filter via locator | range=%s",
            self.engine_name,
            instruction.date_range,
        )

        # Step 1: open the filter button/menu
        if not locator.click_element("toolbar.date_filter.open_button"):
            logger.debug(
                "%s: locator could not click open_button — skipping date filter",
                self.engine_name,
            )
            return False
        time.sleep(0.5)

        # Step 2: some engines have a separate time menu to open
        _ = locator.click_element("toolbar.date_filter.time_menu")
        time.sleep(0.4)

        # Step 3: click the specific date option
        range_key = _DATE_RANGE_TO_OPTION_KEY.get(instruction.date_range)
        if range_key is None:
            return False

        option_path = f"toolbar.date_filter.date_options.{range_key}"
        if locator.click_element(option_path):
            logger.info(
                "%s: toolbar date filter applied via locator | range=%s",
                self.engine_name,
                instruction.date_range,
            )
            return True

        logger.debug(
            "%s: locator could not click date option %r",
            self.engine_name,
            range_key,
        )
        return False

    # ── Legacy hardcoded fallback ───────────────────────────────────────

    def _apply_toolbar_filters_legacy(
        self,
        browser: BrowserInterface,
        instruction: SearchInstruction,
    ) -> None:
        """Fallback toolbar filter using legacy hardcoded selectors.

        Subclasses MUST override this if they support toolbar interactions.
        The base implementation is a no‑op.
        """
        pass


# ═════════════════════════════════════════════════════════════════════════════
# Date‑range → YAML option key mapping
# ═════════════════════════════════════════════════════════════════════════════

_DATE_RANGE_TO_OPTION_KEY: dict[str, str] = {
    "hour":  "past_hour",
    "day":   "past_day",
    "week":  "past_week",
    "month": "past_month",
    "year":  "past_year",
}


# ═════════════════════════════════════════════════════════════════════════════
# Google
# ═════════════════════════════════════════════════════════════════════════════

# Google's ``tbs=qdr:`` parameter mapping for time‑windowed searches.
_GOOGLE_DATE_RANGE_MAP: dict[str, str] = {
    "hour":  "h",
    "day":   "d",
    "week":  "w",
    "month": "m",
    "year":  "y",
}


class GoogleSearchStrategy(SearchEngineStrategy):
    """Google‑specific search URL construction and toolbar interactions."""

    def __init__(self, locator=None) -> None:
        super().__init__(locator)
        self._homepage_url = "https://www.google.com"
        self._search_bar_selectors = [
            "input[name='q']",
            "textarea[name='q']",
            "input[type='search']",
            "input[id*='search' i]",
            "[aria-label*='search' i]",
        ]

    @property
    def engine_name(self) -> str:
        return "google"

    def build_search_url(self, instruction: SearchInstruction) -> str:
        query = instruction.effective_query
        params: dict[str, str | int] = {
            "q": query,
            "ibp": "htl;jobs",
            "hl": "en",
            "gl": "us",
            "start": 0,
        }
        if instruction.date_range is not None:
            qdr_code = _GOOGLE_DATE_RANGE_MAP.get(instruction.date_range)
            if qdr_code is not None:
                params["tbs"] = f"qdr:{qdr_code}"
        return f"https://www.google.com/search?{urlencode(params)}"

    # ── Legacy hardcoded selectors (used when no locator is injected) ────

    def _apply_toolbar_filters_legacy(
        self,
        browser: BrowserInterface,
        instruction: SearchInstruction,
    ) -> None:
        if instruction.date_range is None:
            return

        logger.debug(
            "GoogleSearchStrategy: attempting legacy toolbar date filter | range=%s",
            instruction.date_range,
        )
        try:
            # 1. Click the "Tools" button to reveal filter bar
            tools_btn = browser.find_element(
                Locator.CSS_SELECTOR,
                "div#hdtb-tls, div[aria-label='Search tools'], "
                "a[aria-label='Tools'], div.hdtb-tl-sel",
            )
            if tools_btn is not None:
                behavior.human_like_click(browser, tools_btn)
                time.sleep(0.5)

            # 2. Click "Any time" dropdown
            time_menu = browser.find_element(
                Locator.CSS_SELECTOR,
                "div[aria-label='Any time'], div.hdtb-mn-hd, "
                "div[aria-label*='time' i], g-menu[role='menu']",
            )
            if time_menu is not None:
                behavior.human_like_click(browser, time_menu)
                time.sleep(0.4)

            # 3. Click the specific date option
            label_map: dict[str, str] = {
                "hour":  "Past hour",
                "day":   "Past 24 hours",
                "week":  "Past week",
                "month": "Past month",
                "year":  "Past year",
            }
            target_label = label_map.get(instruction.date_range)
            if target_label is None:
                return

            option = browser.find_element(
                Locator.XPATH,
                f"//a[contains(normalize-space(), '{target_label}')] | "
                f"//g-menu-item[contains(., '{target_label}')]",
            )
            if option is not None:
                behavior.human_like_click(browser, option)
                logger.info(
                    "GoogleSearchStrategy: legacy toolbar date filter applied | %s",
                    target_label,
                )
            else:
                logger.debug(
                    "GoogleSearchStrategy: date option not found in legacy toolbar | %s",
                    target_label,
                )
        except Exception as exc:
            logger.debug(
                "GoogleSearchStrategy: legacy toolbar filter skipped | error=%s", exc
            )


# ═════════════════════════════════════════════════════════════════════════════
# Bing
# ═════════════════════════════════════════════════════════════════════════════

_BING_DATE_RANGE_MAP: dict[str, str] = {
    "hour":  "h",
    "day":   "d",
    "week":  "w",
    "month": "m",
    "year":  "y",
}


class BingSearchStrategy(SearchEngineStrategy):
    """Bing‑specific search URL construction and toolbar interactions."""

    def __init__(self, locator=None) -> None:
        super().__init__(locator)
        self._homepage_url = "https://www.bing.com"
        self._search_bar_selectors = [
            "input[name='q']",
            "textarea[name='q']",
            "input[id*='sb_form_q']",
            "input[type='search']",
            "[aria-label*='search' i]",
        ]

    @property
    def engine_name(self) -> str:
        return "bing"

    def build_search_url(self, instruction: SearchInstruction) -> str:
        query = instruction.effective_query
        params = {"q": query}
        url = f"https://www.bing.com/jobs?{urlencode(params)}"
        if instruction.date_range is not None:
            interval_code = _BING_DATE_RANGE_MAP.get(instruction.date_range)
            if interval_code is not None:
                url += f"&filters=ex1%3A%22{interval_code}%22"
        return url

    # ── Legacy hardcoded selectors ──────────────────────────────────────

    def _apply_toolbar_filters_legacy(
        self,
        browser: BrowserInterface,
        instruction: SearchInstruction,
    ) -> None:
        if instruction.date_range is None:
            return

        logger.debug(
            "BingSearchStrategy: attempting legacy toolbar date filter | range=%s",
            instruction.date_range,
        )
        try:
            # Bing's date filter is a dropdown on the jobs results page
            date_btn = browser.find_element(
                Locator.CSS_SELECTOR,
                "div[aria-label*='Date posted'], "
                "span[aria-label*='date' i], "
                "div.ftrB > div, a[title*='date' i]",
            )
            if date_btn is not None:
                behavior.human_like_click(browser, date_btn)
                time.sleep(0.3)

            label_map: dict[str, str] = {
                "hour":  "Past 24 hours",
                "day":   "Past 24 hours",
                "week":  "Past week",
                "month": "Past month",
                "year":  "Past year",
            }
            target_label = label_map.get(instruction.date_range)
            if target_label is None:
                return

            option = browser.find_element(
                Locator.XPATH,
                f"//span[contains(normalize-space(), '{target_label}')] | "
                f"//a[contains(normalize-space(), '{target_label}')]",
            )
            if option is not None:
                behavior.human_like_click(browser, option)
                logger.info(
                    "BingSearchStrategy: legacy toolbar date filter applied | %s",
                    target_label,
                )
        except Exception as exc:
            logger.debug(
                "BingSearchStrategy: legacy toolbar filter skipped | error=%s", exc
            )


# ═════════════════════════════════════════════════════════════════════════════
# Indeed
# ═════════════════════════════════════════════════════════════════════════════

_INDEED_DATE_RANGE_DAYS: dict[str, int] = {
    "hour":  1,
    "day":   1,
    "week":  7,
    "month": 30,
    "year":  365,
}


class IndeedSearchStrategy(SearchEngineStrategy):
    """Indeed‑specific search URL construction and toolbar interactions."""

    def __init__(self, locator=None) -> None:
        super().__init__(locator)
        self._homepage_url = "https://www.indeed.com"
        self._search_bar_selectors = [
            "input[name='q']",
            "input[id*='text-input']",
            "input[aria-label*='what' i]",
            "input[aria-label*='job' i]",
            "input[type='search']",
        ]

    @property
    def engine_name(self) -> str:
        return "indeed"

    def build_search_url(self, instruction: SearchInstruction) -> str:
        params: dict[str, str] = {
            "q": instruction.effective_query,
            "l": instruction.location,
        }
        if instruction.date_range is not None:
            days = _INDEED_DATE_RANGE_DAYS.get(instruction.date_range)
            if days is not None:
                params["fromage"] = str(days)
                logger.debug(
                    "IndeedSearchStrategy: date_range=%s → fromage=%d",
                    instruction.date_range,
                    days,
                )
        return f"https://www.indeed.com/jobs?{urlencode(params)}"

    # ── Legacy hardcoded selectors ──────────────────────────────────────

    def _apply_toolbar_filters_legacy(
        self,
        browser: BrowserInterface,
        instruction: SearchInstruction,
    ) -> None:
        if instruction.date_range is None:
            return

        logger.debug(
            "IndeedSearchStrategy: attempting legacy toolbar date filter | range=%s",
            instruction.date_range,
        )
        try:
            # Indeed date filter is a dropdown button in the filter bar
            date_filter = browser.find_element(
                Locator.CSS_SELECTOR,
                "button[data-testid='date-filter'], "
                "button[aria-label*='date' i], "
                "div[class*='date'] button, "
                "button#filter-date-button",
            )
            if date_filter is not None:
                behavior.human_like_click(browser, date_filter)
                time.sleep(0.3)

            label_map: dict[str, str] = {
                "hour":  "Last 24 hours",
                "day":   "Last 24 hours",
                "week":  "Last 7 days",
                "month": "Last 30 days",
                "year":  "Last year",
            }
            target_label = label_map.get(instruction.date_range)
            if target_label is None:
                return

            option = browser.find_element(
                Locator.XPATH,
                f"//a[contains(normalize-space(), '{target_label}')] | "
                f"//li[contains(normalize-space(), '{target_label}')] | "
                f"//button[contains(normalize-space(), '{target_label}')]",
            )
            if option is not None:
                behavior.human_like_click(browser, option)
                logger.info(
                    "IndeedSearchStrategy: legacy toolbar date filter applied | %s",
                    target_label,
                )
        except Exception as exc:
            logger.debug(
                "IndeedSearchStrategy: legacy toolbar filter skipped | error=%s", exc
            )
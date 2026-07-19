"""Finds company careers pages by scanning site navigation menus.

When AA is given a company homepage (e.g. ``https://acme.com``) rather than
a direct job URL, this component walks the page's ``<nav>`` elements and
header areas to locate a "Careers", "Jobs", or "Work with us" link that leads
to the careers listing page.

This is the entry point for the company-page discovery path:

    CompanyHomepage → ToolbarNavigator → CareersPage → GenericSERPStrategy

The navigator is intentionally stateless beyond holding a browser reference —
call ``find_careers_links()`` on any page already loaded in the browser.
"""

from __future__ import annotations

import logging

from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)

# CSS selectors for navigation container elements, tried in priority order.
# Narrower, more specific selectors are tried first to avoid false positives
# from deep page content that happens to contain the word "careers".
_NAV_SELECTORS: tuple[str, ...] = (
    "nav",
    "[role='navigation']",
    "header",
    ".navbar",
    ".nav",
    "#nav",
    ".site-header",
    ".page-header",
    ".top-nav",
    ".main-nav",
    ".primary-nav",
    ".global-nav",
    ".menu",
    "#menu",
    ".header",
    "#header",
)

# Link-text substrings that strongly suggest a careers/jobs destination.
# All matched case-insensitively against the visible link text.
_CAREERS_KEYWORDS: frozenset[str] = frozenset({
    "career",
    "careers",
    "jobs",
    "work with us",
    "work here",
    "join us",
    "join our team",
    "we're hiring",
    "we are hiring",
    "open roles",
    "open positions",
    "opportunities",
    "employment",
    "vacancies",
    "job openings",
})


class ToolbarNavigator:
    """Scans a site's navigation menus for careers/jobs destination links.

    Does NOT navigate away from the current page — call ``navigate_to_careers``
    when you want to follow the first link found.

    Args:
        browser: An active :class:`BrowserInterface` pointing at the page to scan.
    """

    def __init__(self, browser: BrowserInterface) -> None:
        self._browser = browser

    def find_careers_links(self) -> list[str]:
        """Returns all careers-related link URLs found in navigation elements.

        Scans each navigation container selector in priority order.  Within each
        container, collects ``<a href>`` elements whose visible text matches any
        careers keyword.  Deduplicates and filters out empty/javascript URLs.

        Returns:
            Ordered list of unique absolute URL strings. Empty list if nothing
            matches or if the browser raises an exception.
        """
        seen: set[str] = set()
        found: list[str] = []

        for nav_selector in _NAV_SELECTORS:
            try:
                containers = self._browser.find_elements(
                    Locator.CSS_SELECTOR, nav_selector
                )
            except Exception:
                continue

            for container in containers:
                try:
                    links = container.find_elements(
                        Locator.CSS_SELECTOR, "a[href]"
                    )
                except Exception:
                    continue

                for link in links:
                    try:
                        href = link.get_attribute("href") or ""
                        text = (link.text or "").strip().lower()
                    except Exception:
                        continue

                    if not href or not _is_valid_href(href):
                        continue
                    if not _matches_careers_keyword(text):
                        continue
                    if href not in seen:
                        seen.add(href)
                        found.append(href)
                        logger.debug(
                            "ToolbarNavigator: found careers link | text=%r href=%s",
                            text,
                            href,
                        )

        logger.debug(
            "ToolbarNavigator.find_careers_links | url=%s found=%d",
            _safe_current_url(self._browser),
            len(found),
        )
        return found

    def navigate_to_careers(self) -> bool:
        """Navigates the browser to the first careers link found in the nav.

        Returns:
            ``True`` if a careers link was found and navigation succeeded,
            ``False`` otherwise.
        """
        links = self.find_careers_links()
        if not links:
            logger.debug(
                "ToolbarNavigator: no careers links on %s",
                _safe_current_url(self._browser),
            )
            return False

        target = links[0]
        try:
            self._browser.get(target)
            logger.info(
                "ToolbarNavigator: navigated to careers page | url=%s", target
            )
            return True
        except Exception as exc:
            logger.warning(
                "ToolbarNavigator: navigation failed | url=%s error=%s",
                target,
                exc,
            )
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _matches_careers_keyword(text: str) -> bool:
    """Returns True if *text* contains any careers-related keyword."""
    return any(kw in text for kw in _CAREERS_KEYWORDS)


def _is_valid_href(href: str) -> bool:
    """Returns True if *href* is a navigable URL (not javascript: or mailto:)."""
    lowered = href.lower().strip()
    if not lowered or lowered.startswith(("javascript:", "mailto:", "tel:", "#")):
        return False
    return len(lowered) > 5


def _safe_current_url(browser: BrowserInterface) -> str:
    """Returns the current URL without raising."""
    try:
        return browser.current_url
    except Exception:
        return "<unknown>"
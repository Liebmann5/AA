"""Manages browser context switching (frames, windows, shadow DOM).

Navigates the complex hierarchy of modern web pages for secondary adapters
that need to scan across iframes and tabs. Only depends on domain ports.
"""

import logging
from collections.abc import Callable

from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)


class ContextManager:
    """Manages the active context (Frame/Window/ShadowRoot) of the browser."""

    def __init__(self, browser: BrowserInterface) -> None:
        self.browser = browser
        self.main_window = self._get_current_window_handle()
        self.known_windows: set[str] = {self.main_window} if self.main_window else set()

    # --- IFRAME MANAGEMENT ---

    def find_context_with_content(self, predicate: Callable[[BrowserInterface], bool]) -> bool:
        """Deep scans the page (iframes + shadow DOM) to find content matching a predicate.

        If found, the browser REMAINS in that context so you can interact/extract.
        Call reset() when done.
        """
        self.reset()
        if predicate(self.browser):
            return True

        if self._search_frames(predicate):
            return True

        return False

    def _search_frames(self, predicate: Callable) -> bool:
        """Iterates through all iframes in the current context."""
        iframes = self.browser.find_elements(Locator.TAG_NAME, "iframe")

        for i, frame in enumerate(iframes):
            try:
                self.browser.switch_to_iframe(frame)
                if predicate(self.browser):
                    logger.info("ContextManager: Target found in Iframe #%d", i)
                    return True

                nested_frames = self.browser.find_elements(Locator.TAG_NAME, "iframe")
                if nested_frames:
                    for j, nested in enumerate(nested_frames):
                        self.browser.switch_to_iframe(nested)
                        if predicate(self.browser):
                            logger.info("ContextManager: Target found in Nested Iframe #%d->%d", i, j)
                            return True
                        self.browser.switch_to_iframe(frame)

                self.browser.switch_to_default_content()

            except Exception:
                self.browser.switch_to_default_content()
                continue

        return False

    def reset(self) -> None:
        """Resets the browser to the main document."""
        self.browser.switch_to_default_content()

    # --- WINDOW / TAB MANAGEMENT ---

    def switch_to_new_tab(self) -> bool:
        """Identifies and switches to a newly opened tab/window."""
        try:
            current_handles = set(self._get_window_handles())
            new_handles = current_handles - self.known_windows

            if new_handles:
                target = list(new_handles)[0]
                logger.info("ContextManager: Switching to new tab %s", target)
                self.browser.get_raw_driver().switch_to.window(target)
                self.known_windows.add(target)
                return True
        except Exception as e:
            logger.error("Tab switch failed: %s", e)

        return False

    def close_current_tab_and_return(self) -> None:
        """Closes the active tab and returns to the main window."""
        try:
            current = self._get_current_window_handle()
            if current != self.main_window:
                self.browser.close()
                self.browser.get_raw_driver().switch_to.window(self.main_window)
                if current in self.known_windows:
                    self.known_windows.remove(current)
                logger.info("ContextManager: Closed tab and returned to main.")
        except Exception as e:
            logger.error("Failed to close tab: %s", e)

    # --- HELPERS ---

    def _get_current_window_handle(self) -> str:
        try:
            return self.browser.get_raw_driver().current_window_handle
        except Exception:
            return ""

    def _get_window_handles(self) -> list[str]:
        try:
            return self.browser.get_raw_driver().window_handles
        except Exception:
            return []

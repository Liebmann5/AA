"""
Manages the persistent state of a browser "persona" in a framework-agnostic way.
"""
import json
import logging
import random
import time
from pathlib import Path
from typing import Any

from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface
from auto_apply.domain.config import AppSettings

logger = logging.getLogger(__name__)

class SessionState:
    """A data class to hold all browser state for a persona."""

    def __init__(self, cookies=None, local_storage=None, session_storage=None):
        self.cookies = cookies or []
        self.local_storage = local_storage or {}
        self.session_storage = session_storage or {}

class SessionManager:
    """Manages the lifecycle of a browser "persona" state.

    This class is designed to be used as a context manager. Upon entering the
    `with` block, it loads the persona's state from a file into the browser.
    Upon exiting, it automatically saves the browser's final state back to the
    file, ensuring that cookies and storage from the session are preserved for
    the next run.

    Args:
        browser: The framework-agnostic browser adapter instance.
        persona_id: A unique identifier for this persona (e.g., "default_profile").
            This is used to create a unique state file.
        state_directory: The path to the directory where session files will be stored.
        app_settings: Optional injection of the application's global settings.
            Used for configuration like warmup delay ranges. If None,
            warmup logic may fall back to internal defaults.
    """  # noqa: E501

    def __init__(
        self,
        browser: BrowserInterface,
        persona_id: str,
        state_directory: Path,
        app_settings: AppSettings | None = None,
    ) -> None:
        self.browser = browser
        self.persona_id = persona_id
        self.state_file = state_directory / f"{persona_id}_session.json"
        self.state = SessionState()
        self._app_settings = app_settings

    def __enter__(self):
        """Loads the persona's state into the browser upon entering a `with` block."""
        self.load_state()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Saves the persona's state upon exiting a `with` block, guaranteeing persistence."""  # noqa: E501
        self.save_state()

    def load_state(self) -> None:
        """Loads all state (cookies, storage) from the persona's file into the browser.

        The process involves navigating to a benign, high-traffic domain (like google.com)
        to establish a valid context where cookies and storage can be set via
        JavaScript execution.
        """  # noqa: E501
        if not self.state_file.exists():
            logger.info(f"No previous session state found for persona '{self.persona_id}'. Starting fresh.")  # noqa: E501
            return

        logger.info(f"Loading session state for persona '{self.persona_id}'...")
        try:
            with open(self.state_file) as f:
                data = json.load(f)
            self.state = SessionState(**data)

            self.browser.get("https://www.google.com")

            for cookie in self.state.cookies:
                try:
                    self.browser.add_cookie(cookie)
                except Exception:
                    pass

            self.browser.execute_script(
                "Object.entries(arguments[0]).forEach(([key, value]) => window.localStorage.setItem(key, value));",  # noqa: E501
                self.state.local_storage
            )
            self.browser.execute_script(
                "Object.entries(arguments[0]).forEach(([key, value]) => window.sessionStorage.setItem(key, value));",  # noqa: E501
                self.state.session_storage
            )
            logger.info("Successfully loaded and injected previous session state.")
        except Exception as e:
            logger.error(f"Failed to load session state for '{self.persona_id}': {e}", exc_info=True)  # noqa: E501

    def save_state(self) -> None:
        """Extracts all state from the browser and saves it to the persona's file."""
        logger.info(f"Saving session state for persona '{self.persona_id}'...")
        try:
            # If the browser is already dead, these will fail, but the program won't crash.  # noqa: E501
            try:
                self.state.cookies = self.browser.get_cookies()
            except Exception:
                logger.warning("Could not retrieve cookies. The browser may have already closed.")  # noqa: E501

            try:
                self.state.local_storage = self.browser.execute_script("return window.localStorage;")  # noqa: E501
            except Exception:
                 logger.warning("Could not retrieve local storage.")

            try:
                self.state.session_storage = self.browser.execute_script("return window.sessionStorage;")  # noqa: E501
            except Exception:
                logger.warning("Could not retrieve session storage.")

            with open(self.state_file, 'w') as f:
                json.dump(self.state.__dict__, f, indent=2)
            logger.info("Session state save file update successfully.")
        except Exception as e:
            logger.error(f"Failed to save session state for '{self.persona_id}': {e}", exc_info=True)  # noqa: E501

    def intelligent_warmup(self, config: Any) -> None:
        """Executes a dynamic, human-like warmup routine to build a plausible history.

        This method simulates a user browsing a news website. It performs a
        search, clicks on a random number of articles, scrolls to simulate
        reading, and navigates back. This activity builds a more realistic
        browsing history and cookie profile than simply visiting static URLs.

        Args:
            config: The evasion settings object, used to determine navigation delays.
        """
        logger.info("--- Starting Intelligent Session Warming Protocol ---")

        seed_url = "https://news.google.com/search?q=technology"
        logger.info(f"Warming up from seed URL: {seed_url}")
        self.browser.get(seed_url)
        time.sleep(random.uniform(2, 4))

        try:
            headlines: list[ElementInterface] = self.browser.find_elements("css selector", "a[href*='./articles/']")  # noqa: E501
            if not headlines:
                logger.warning("Could not find headlines for warmup. Aborting warmup.")
                return

            for _ in range(random.randint(2, 3)):
                article = random.choice(headlines)
                logger.info(f"Warmup click: Navigating to article '{article.text[:70]}...'")  # noqa: E501
                article.click()
                time.sleep(random.uniform(config.min_navigation_delay_seconds, config.max_navigation_delay_seconds))  # noqa: E501

                self.browser.execute_script(f"window.scrollTo(0, document.body.scrollHeight * {random.uniform(0.4, 0.8)});")  # noqa: E501
                time.sleep(random.uniform(1, 3))

                self.browser.back()
                time.sleep(random.uniform(1, 2))
        except Exception as e:
            logger.error(f"Error during intelligent warmup: {e}", exc_info=True)

        logger.info("--- Intelligent Session Warming Protocol Complete ---")
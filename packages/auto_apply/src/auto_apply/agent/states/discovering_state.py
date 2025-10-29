import logging
from pathlib import Path

from .base_state import BaseState
from ...core.settings_manager import SettingsManager
from ...core.browser_factory import get_driver_adapter
from ...core.browser import BrowserManager
from ...core.proxy_manager import ProxyManager
from ...core.browser_interface import BrowserInterface
from ...user_data.user_profile import UserProfile
from ...scraping import AdaptiveSearchManager
from ...scraping.search import GoogleDirectURLSearch, GoogleHumanTypingSearch, BingGUISearch
from ...config import settings
from ...evasion import get_evasion_manager
from ...evasion.session import SessionManager

logger = logging.getLogger(__name__)

class DiscoveringState(BaseState):
    """The state responsible for finding job opportunities."""

    def execute(self) -> str | None:
        logger.info("Starting job discovery phase...")

        # --- Setup and Configuration ---
        settings_manager = SettingsManager()
        user_profile = settings_manager.profile
        persona_id = settings_manager.profile_name

        data_dir = Path.home() / ".auto_apply"
        proxy_manager = ProxyManager(data_dir / "proxies.txt")
        session_dir = data_dir / "session_state"
        session_dir.mkdir(exist_ok=True)
        screenshots_dir = data_dir / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)

        browser_choice = user_profile.search_preferences.preferred_browser
        framework = "playwright" if browser_choice == "playwright" else "selenium"

        # --- Job Discovery (Search Phase) ---
        raw_results = []
        try:
            browser_adapter = get_driver_adapter(framework, proxy_manager, browser_choice)
            with BrowserManager(browser_adapter) as browser:
                with SessionManager(browser, persona_id, session_dir) as sm:
                    evasion_manager = get_evasion_manager(browser, settings.evasion, sm)
                    evasion_manager.apply_static_evasion()
                    evasion_manager.manage_session_startup()

                    search_manager = self._create_search_manager(browser, user_profile, screenshots_dir)
                    raw_results = search_manager.execute(browser)
        except Exception:
            logger.critical("A catastrophic error occurred during the browser search phase. Aborting run.", exc_info=True)
            # A failure in discovery is critical; we cannot proceed.
            return None

        self.context["discovered_jobs"] = raw_results
        logger.info("Discovered %d potential jobs.", len(raw_results))

        return "VETTING"

    def _create_search_manager(self, browser: BrowserInterface, user_profile: UserProfile, screenshots_dir: Path) -> AdaptiveSearchManager:
        """Constructs and configures the AdaptiveSearchManager."""
        search_manager = AdaptiveSearchManager(screenshots_dir=screenshots_dir)
        all_results, seen_urls = [], set()
        cache_dir = Path.home() / ".auto_apply" / "cache"
        cache_dir.mkdir(exist_ok=True, parents=True)

        search_manager.register_strategy(
            GoogleDirectURLSearch(browser, user_profile.search_preferences, settings.scraping.max_search_results, cache_dir, all_results, seen_urls)
        )
        search_manager.register_strategy(
            GoogleHumanTypingSearch(browser, user_profile.search_preferences, settings.scraping.max_search_results, cache_dir, all_results, seen_urls)
        )
        search_manager.register_strategy(
            BingGUISearch(browser, user_profile.search_preferences, settings.scraping.max_search_results, cache_dir, all_results, seen_urls)
        )
        return search_manager
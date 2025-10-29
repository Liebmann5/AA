import logging
import time
from pathlib import Path

from .base_state import BaseState
from ...core.settings_manager import SettingsManager
from ...core.browser_factory import get_driver_adapter
from ...core.browser import BrowserManager
from ...core.proxy_manager import ProxyManager
from ...core.browser_interface import BrowserInterface
from ...user_data import JobStateManager, JobStatus, AppliedJobsManager
from ...scraping import get_application_strategy
from ...config import settings
from ...evasion import get_evasion_manager
from ...evasion.session import SessionManager

logger = logging.getLogger(__name__)

class ApplyingState(BaseState):
    """The state responsible for applying to vetted jobs."""

    def execute(self) -> str | None:
        logger.info("Starting application phase...")

        jobs_to_apply = self.context.get("jobs_to_apply", [])
        if not jobs_to_apply:
            logger.warning("ApplyingState was entered, but there are no jobs to apply for.")
            return None

        # --- Setup and Configuration ---
        settings_manager = SettingsManager()
        user_profile = settings_manager.profile
        persona_id = settings_manager.profile_name

        data_dir = Path.home() / ".auto_apply"
        proxy_manager = ProxyManager(data_dir / "proxies.txt")
        session_dir = data_dir / "session_state"
        screenshots_dir = data_dir / "screenshots"

        browser_choice = user_profile.search_preferences.preferred_browser
        framework = "playwright" if browser_choice == "playwright" else "selenium"

        applications_completed = 0
        applications_failed = 0

        with JobStateManager(data_dir / "job_states.json") as state_manager, \
             AppliedJobsManager(data_dir / "applied_jobs.json") as applied_manager:

            for job in jobs_to_apply:
                state_manager.update_job_status(job.url, JobStatus.APPLICATION_IN_PROGRESS)

                try:
                    # A fresh browser is created for each application for maximum isolation and resilience.
                    app_browser_adapter = get_driver_adapter(framework, proxy_manager, browser_choice)
                    with BrowserManager(app_browser_adapter) as app_browser:
                        with SessionManager(app_browser, persona_id, session_dir) as app_sm:
                            app_evasion_manager = get_evasion_manager(app_browser, settings.evasion, app_sm)
                            app_evasion_manager.apply_static_evasion()

                            strategy = get_application_strategy(app_browser, user_profile, job)
                            if strategy and strategy.apply():
                                state_manager.update_job_status(job.url, JobStatus.APPLICATION_COMPLETED)
                                applied_manager.add(job.url)
                                applications_completed += 1
                            else:
                                self._handle_application_failure(app_browser, job, state_manager, screenshots_dir)
                                applications_failed += 1
                except Exception as e:
                    logger.error(f"The application process for {job.url} failed catastrophically: {e}", exc_info=True)
                    self._handle_application_failure(None, job, state_manager, screenshots_dir)
                    applications_failed += 1

        self.context["applications_completed"] = applications_completed
        self.context["applications_failed"] = applications_failed

        logger.info("Application phase complete.")
        # This is the final state in the lifecycle.
        return None

    def _handle_application_failure(self, browser: BrowserInterface | None, job, state_manager, screenshots_dir):
        """Centralizes the logic for handling a failed job application."""
        state_manager.update_job_status(job.url, JobStatus.APPLICATION_FAILED)
        if browser:
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            safe_company = "".join(c for c in job.company if c.isalnum() or c in (' ', '_')).rstrip()
            filename = f"failure_application_{safe_company}_{timestamp}.png"
            filepath = screenshots_dir / filename
            try:
                browser.save_screenshot(str(filepath))
                logger.info(f"Saved failure screenshot to: {filepath}")
            except Exception as e:
                logger.error(f"Could not save screenshot: {e}")
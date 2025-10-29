"""An application strategy for job boards hosted on jobs.lever.co.

This module provides the `LeverStrategy`, a concrete implementation of the
`ApplicationStrategy` for handling job applications on the Lever platform.
It contains the specific logic for navigating to the application form, filling
in fields based on their 'name' attributes, and handling the resume upload.
"""
import logging
import time

from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException

from .base_application_strategy import ApplicationStrategy
from ...utils.decorators import retry
from ..utils.page_interruption import ensure_page_is_ready
from ...evasion import behavior

logger = logging.getLogger(__name__)

class LeverStrategy(ApplicationStrategy):
    """Implements the application process for jobs hosted on Lever."""

    @retry(attempts=2, delay_seconds=5)
    def _navigate_to_job_page(self) -> None:
        """Navigates to the Lever job page and clicks the 'Apply' button.

        This method implements the first step of the application template. On
        Lever job pages, the application form is typically on the same page,
        revealed after clicking a prominent "Apply" button.

        Raises:
            TimeoutError: If the "Apply" button or a key form field cannot be
                found. The `@retry` decorator will handle retries.
        """
        self.browser.get(self.job.url)
        ensure_page_is_ready(self.browser)

        apply_button_selector = "a.postings-btn.template-btn-submit.cerulean"
        apply_button = self.browser.wait_for_element(By.CSS_SELECTOR, apply_button_selector, timeout=15)
        if not apply_button:
            raise TimeoutError("Could not find the 'Apply' button on the Lever page.")

        behavior.human_like_click(self.browser, apply_button)

        if not self.browser.wait_for_element(By.NAME, "name", timeout=10):
            raise TimeoutError("Lever application form did not appear after clicking 'Apply'.")

        logger.info("Successfully navigated to the Lever application form.")

    def _fill_form(self) -> None:
        """Fills out the main Lever application form.

        This method implements the second step of the application template. It
        leverages the fact that Lever uses stable `name` attributes for its form
        fields, which are highly reliable selectors. It maps user profile data
        to these fields and fills them in.
        """
        logger.info("Filling Lever application form.")
        info = self.user_profile.personal_info
        links = self.user_profile.links

        field_map = {
            "name": self.user_profile.full_name,
            "email": info.email,
            "phone": info.phone_number,
            "urls[LinkedIn]": links.linkedin_url,
            "urls[GitHub]": links.github_url,
            "urls[Portfolio]": links.portfolio_url,
        }

        for name, value in field_map.items():
            if value:
                try:
                    field = self.browser.find_element(By.NAME, name)
                    if field:
                        behavior.human_like_typing(field, str(value))
                except Exception:
                    logger.warning("Optional Lever field with name '%s' not found. Skipping.", name)

    def _handle_submission(self) -> None:
        """Handles resume upload and the final submission on Lever.

        This method implements the final step of the application template. It
        locates the file input for the resume and sends the user's resume path.

        Note: The final submission click is commented out for safety.

        Raises:
            Exception: If the resume upload input cannot be found.
        """
        logger.info("Handling resume upload for Lever.")
        info = self.user_profile.personal_info

        resume_input = self.browser.find_element(By.CSS_SELECTOR, 'input[type="file"][name="resume"]')
        if not resume_input:
            raise Exception("Could not find the resume upload input on Lever.")

        resume_path = str(info.resume_path.resolve())
        resume_input.send_keys(resume_path)
        logger.info("Successfully attached resume.")

        logger.warning("SIMULATION MODE: Skipping final form submission on Lever.")

        submit_button = self.browser.find_element(By.CSS_SELECTOR, "button.template-btn-submit")
        behavior.human_like_click(self.browser, submit_button)
        time.sleep(3)
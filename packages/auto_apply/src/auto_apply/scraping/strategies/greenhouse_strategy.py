"""An application strategy for job boards hosted on Greenhouse.io.

This module provides the `GreenhouseStrategy`, a concrete implementation of the
`ApplicationStrategy` for handling job applications on the Greenhouse platform.
It contains the specific logic for navigating to the form, identifying fields
by their labels, filling them with user data, and handling the resume upload.
"""
import logging
import time
import random
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from .base_application_strategy import ApplicationStrategy
from ...user_data.user_profile import UserProfile
from ...scraping.search.search_result import SearchResult

from ...utils.decorators import retry
from ...evasion import behavior
from ..utils.page_interruption import ensure_page_is_ready

logger = logging.getLogger(__name__)

class GreenhouseStrategy(ApplicationStrategy):
    """Implements the application process for jobs hosted on Greenhouse."""

    def __init__(self, driver: WebDriver, user_profile: UserProfile, job: SearchResult):
        """Initializes the Greenhouse strategy.

        Args:
            driver: The Selenium WebDriver instance.
            user_profile: The user's complete profile data.
            job: The specific `SearchResult` for the job to apply for.
        """
        super().__init__(driver, user_profile, job)

    def _find_field_by_label(self, label_text: str):
        """Finds a form input element by its corresponding <label> text.

        This is a robust method for finding form fields, as labels are less
        likely to change than IDs or class names. It works by finding the
        label element that starts with the given text and then finding the
        input element associated with that label via its 'for' attribute.

        Args:
            label_text: The visible text of the label to search for (e.g., "First Name").

        Returns:
            The `ElementInterface` for the input field if found, otherwise None.
        """
        try:
            label_xpath = f"//label[starts-with(normalize-space(), '{label_text}')]"
            label_element = self.driver.find_element(By.XPATH, label_xpath)

            target_id = label_element.get_attribute("for")
            if target_id:
                return self.driver.find_element(By.ID, target_id)
        except NoSuchElementException:
            logger.debug("Could not find form field for label: '%s'", label_text)
            return None
        return None

    @retry(attempts=3, delay_seconds=10)
    def _navigate_to_job_page(self) -> None:
        """Navigates to the Greenhouse job page and clicks the 'Apply' button.

        This method implements the first step of the application template. It
        navigates to the job URL, waits for the page to be ready, and then
        locates and clicks the main "Apply" button to reveal the application form.

        Raises:
            Exception: If the "Apply" button or the application form cannot be
                found after the click, the `@retry` decorator will handle retries.
        """
        self.browser.get(self.job.url)

        ensure_page_is_ready(self.browser)

        apply_button = self.browser.wait_for_element(By.ID, "apply_button", timeout=15)
        if not apply_button:
            raise TimeoutError("Could not find the 'Apply' button on the Greenhouse page.")

        behavior.human_like_click(self.driver, apply_button)

        if not self.browser.wait_for_element(By.ID, "application_form", timeout=10):
            raise TimeoutError("Application form did not appear after clicking 'Apply'.")

        logger.info("Navigated to Greenhouse form and it is now visible.")

    def _fill_form(self) -> None:
        """Fills out the main Greenhouse application form.

        This method implements the second step of the application template. It
        iterates through a mapping of required and optional fields, finds each
        form element using the robust `_find_field_by_label` method, and types
        the corresponding user data with human-like behavior.
        """
        logger.info("Starting to fill the main Greenhouse form.")
        info = self.user_profile.personal_info
        links = self.user_profile.links

        required_fields = {
            "First Name": info.first_name,
            "Last Name": info.last_name,
            "Email": info.email,
        }
        for label, value in required_fields.items():
            field = self._find_field_by_label(label)
            if not field or not value:
                raise Exception(f"Required Greenhouse field '{label}' not found or has no value.")
            behavior.human_like_scroll(self.browser, field)
            behavior.human_like_typing(field, value)
            behavior.simulate_idle_time(self.browser, 0.5, 1.5)

        optional_fields = {
            "Phone": info.phone_number,
            "LinkedIn Profile": links.linkedin_url,
        }
        for label, value in optional_fields.items():
            field = self._find_field_by_label(label)
            if field and value:
                behavior.human_like_scroll(self.browser, field)
                behavior.human_like_typing(field, str(value))
                behavior.simulate_idle_time(self.browser, 0.5, 1.5)
            else:
                logger.info("Optional Greenhouse field '%s' not found or no value provided. Skipping.", label)

    def _handle_submission(self) -> None:
        """Handles resume upload and the final submission click.

        This method implements the final step of the application template. It
        locates the file input element for the resume and sends the absolute
        path of the user's resume file to it.

        Note: The final submission click is commented out for safety during
        development and testing.
        """
        logger.info("Handling resume upload and final submission.")
        resume_input = self.driver.find_element(By.CSS_SELECTOR, 'input[type="file"]')
        resume_path = str(self.user_profile.personal_info.resume_path.resolve())
        resume_input.send_keys(resume_path)
        logger.info("Successfully attached resume from: %s", resume_path)

        logger.warning("SIMULATION MODE: Skipping final form submission.")
        submit_button = self.driver.find_element(By.ID, "submit_button")
        behavior.human_like_click(self.driver, submit_button)
        if not self.browser.wait_for_element(By.ID, "application_form", timeout=10):
            raise TimeoutError("Application form did not appear after clicking 'Apply'.")
        time.sleep(3)

    def apply(self) -> bool:
        """Executes the Greenhouse application process."""
        try:
            logger.info("Navigating to Greenhouse job page: %s", self.job.url)
            self.driver.get(self.job.url)

            wait = WebDriverWait(self.driver, 15)
            apply_button = wait.until(
                EC.element_to_be_clickable((By.ID, "apply_button"))
            )
            behavior.human_like_click(self.driver, apply_button)

            wait.until(EC.presence_of_element_located((By.ID, "application_form")))
            logger.info("Application form loaded.")

            field_map = {
                "First Name": self.user_profile.personal_info.first_name,
                "Last Name": self.user_profile.personal_info.last_name,
                "Email": self.user_profile.personal_info.email,
                "Phone": self.user_profile.personal_info.phone_number,
            }

            for label, value in field_map.items():
                field = self._find_field_by_label(label)
                if field and value:
                    behavior.human_like_scroll(self.driver, field)
                    behavior.human_like_typing(field, value)
                    behavior.simulate_idle_time(self.driver, 0.5, 1.5)
                    logger.info("Filled in '%s' field.", label)

            try:
                resume_input = self.driver.find_element(By.CSS_SELECTOR, 'input[type="file"][data-qa="input-resume"]')
                logger.warning("Resume upload is a placeholder. A 'resume_path' is needed in the user profile.")

            except NoSuchElementException:
                logger.error("Could not find the resume upload input field.")
                return False

            submit_button = self.driver.find_element(By.ID, "submit_button")
            behavior.human_like_click(self.driver, submit_button)

            time.sleep(5)
            return True

        except (TimeoutException, NoSuchElementException) as e:
            logger.error("An error occurred during the Greenhouse application process for %s. Error: %s", self.job.url, e)
            return False
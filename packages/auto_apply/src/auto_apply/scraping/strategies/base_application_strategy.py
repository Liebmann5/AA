"""Defines the abstract contract for all job application strategies.

This module contains the `ApplicationStrategy` abstract base class (ABC),
which is the foundational blueprint for all platform-specific application logic.
It uses the "Template Method" design pattern, where the main `apply` method
defines a fixed, high-level algorithm, and the individual steps of that
algorithm are delegated to abstract helper methods that must be implemented
by concrete subclasses.
"""
import logging
from abc import ABC, abstractmethod

from ...core.browser_interface import BrowserInterface
from ...user_data.user_profile import UserProfile
from ...scraping.search.search_result import SearchResult

logger = logging.getLogger(__name__)

class ApplicationStrategy(ABC):
    """The abstract base class for all platform-specific application strategies.

    This class defines the common interface and shared logic for applying to a
    job. It ensures that the main workflow can treat all application strategies
    interchangeably, regardless of whether they target Greenhouse, Lever, or
    any other platform.
    """

    def __init__(self, browser: BrowserInterface, user_profile: UserProfile, job: SearchResult):
        """Initializes the strategy with the necessary context.

        Args:
            browser: A browser adapter that conforms to the BrowserInterface.
            user_profile: The user's complete profile data.
            job: The specific `SearchResult` object for the job to apply for.
        """
        self.browser = browser
        self.user_profile = user_profile
        self.job = job

    def apply(self) -> bool:
        """Executes the complete application process for the given job.

        This is the "Template Method". It defines the skeleton of the
        application algorithm: navigate, fill the form, and submit. It calls
        the abstract helper methods to perform the actual work, ensuring a
        consistent process while allowing for platform-specific implementations.

        Returns:
            True if the application was successfully submitted, False otherwise.
            It provides robust error logging in case of failure.
        """
        try:
            logger.info("Executing application strategy '%s' for '%s'", self.__class__.__name__, self.job.title)
            self._navigate_to_job_page()
            self._fill_form()
            self._handle_submission()
            logger.info("Successfully completed application strategy for '%s'", self.job.title)
            return True
        except Exception as e:
            logger.error(
                "Application strategy failed for job '%s' at URL %s. Reason: %s",
                self.job.title, self.job.url, e, exc_info=True
            )
            return False

    @abstractmethod
    def _navigate_to_job_page(self) -> None:
        """Navigates to the job page and handles any initial steps.

        This abstract method must be implemented by concrete subclasses. Its
        responsibility is to get the browser from the initial job URL to the
        point where the main application form is visible and ready to be
        filled. This may involve clicking an "Apply Now" button, handling
        pop-ups, etc.
        """
        pass

    @abstractmethod
    def _fill_form(self) -> None:
        """Fills out the main application form fields.

        This abstract method must be implemented by concrete subclasses. It is
        responsible for mapping the data from the `user_profile` to the
        specific input fields, text areas, and select boxes of the target
        platform's application form.
        """
        pass

    @abstractmethod
    def _handle_submission(self) -> None:
        """Handles the final steps of the application process.

        This abstract method must be implemented by concrete subclasses. Its
        responsibilities include handling the resume upload, answering any
        custom final-step questions, and clicking the final "Submit" button.
        """
        pass
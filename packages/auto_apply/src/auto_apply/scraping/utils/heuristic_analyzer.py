"""Provides a heuristic-based engine for dynamically finding element selectors.

This module contains the `HeuristicSelectorFinder`, a class designed to make
the scraping process resilient to website layout changes. Instead of relying on
brittle, hardcoded selectors, this engine analyzes a page against a given set
of rules to programmatically identify the most likely container element for a
list of items, such as job postings.
"""
import logging
from ...core.browser_interface import BrowserInterface, ElementInterface # <-- FRAMEWORK AGNOSTIC
from selenium.webdriver.common.by import By
from .heuristic_rules import HeuristicRuleSet

logger = logging.getLogger(__name__)

class HeuristicSelectorFinder:
    """Analyzes a page to find the most likely container for a list of items.

    This class scans a webpage for all potential container elements (`div` or `ul`),
    evaluates the children of each container against a pluggable `HeuristicRuleSet`,
    and identifies the container that has the highest "score" (i.e., the most
    children that match the rules for a valid item).
    """

    def __init__(self, browser: BrowserInterface, rule_set: HeuristicRuleSet):
        """Initializes the HeuristicSelectorFinder.

        Args:
            browser: The framework-agnostic browser adapter instance.
            rule_set: An instantiated object that inherits from `HeuristicRuleSet`.
                This object provides the specific `is_match` logic for the
                target website (e.g., `GoogleJobRuleSet`, `BingJobRuleSet`).
        """
        self.browser = browser
        self.rules = rule_set

    def find_best_selector(self) -> (str, str):
        """Scans the page and returns the selector of the highest-scoring container.

        This is the main public method of the analyzer. It performs the following steps:
        1.  Finds all potential container elements (`div`, `ul`) on the page.
        2.  For each container, it counts how many of its direct children are
            considered a valid "job-like" element according to the provided `rule_set`.
        3.  It identifies the container with the highest count of valid children.
        4.  Finally, it generates a resilient CSS selector for this "best" container
            and returns it.

        Returns:
            A tuple containing the `By` strategy and the selector string
            (e.g., (By.CSS_SELECTOR, "div.job-container-class")) for the best
            container found. Returns (None, None) if no suitable container
            can be identified.
        """
        logger.info("Starting heuristic analysis to find job container...")
        best_container = None
        max_job_count = 0

        potential_containers = self.browser.find_elements(By.CSS_SELECTOR, 'div, ul')

        for container in potential_containers:
            try:
                children = container.find_elements(By.XPATH, './*')
                if not children:
                    continue

                job_count = sum(1 for child in children if self.rules.is_match(child))

                if job_count > max_job_count and job_count > 3:
                    max_job_count = job_count
                    best_container = container
            except Exception as e:
                logger.debug(f"Heuristic analysis encountered a minor error in a container: {e}")
                continue

        if not best_container:
            logger.error("Heuristic analysis failed. Could not find a likely job container.")
            return None, None

        container_class = best_container.get_attribute('class').split(' ')[0]
        selector = f"{best_container.tag_name}.{container_class}"

        logger.info(f"Heuristic analysis complete. Best selector found: '{selector}' with {max_job_count} jobs.")
        return By.CSS_SELECTOR, selector
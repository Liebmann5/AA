"""Defines website-specific rule sets for the heuristic analysis engine.

This module provides the `HeuristicRuleSet` abstract base class and concrete
implementations for different job search websites (e.g., Google, Bing). Each
rule set encapsulates the specific logic required to identify a "job-like"
element on a given platform.

This design allows the generic `HeuristicSelectorFinder` to be configured with a
pluggable, website-specific set of rules at runtime.
"""
import json
from abc import ABC, abstractmethod
from importlib import resources
from selenium.webdriver.common.by import By
from ...core.browser_interface import ElementInterface

class HeuristicRuleSet(ABC):
    """
    An abstract base class (contract) for defining website-specific rules.
    It now loads its configuration from a central file.
    """

    def __init__(self, site_key: str):
        """Initializes the rule set by loading its configuration.

        Args:
            site_key: The key corresponding to the site's configuration in the
                `detection_config.json` file (e.g., "google", "bing").

        Raises:
            ValueError: If the configuration for the given `site_key` cannot be found.
        """
        self.rules = self._load_rules(site_key)

    def _load_rules(self, site_key: str) -> dict:
        """Loads the specific rule configuration for a given site key.

        Args:
            site_key: The key to look up in the "heuristic_rules" section of the config.

        Returns:
            A dictionary containing the rules (e.g., required keywords).
        """
        try:
            with resources.open_text('auto_apply.evasion', 'detection_config.json') as f:
                config = json.load(f)
                return config["heuristic_rules"][site_key]
        except (IOError, KeyError, json.JSONDecodeError) as e:
            raise ValueError(f"Could not load heuristic rules for '{site_key}'. Check detection_config.json. Error: {e}")

    @abstractmethod
    def is_match(self, element: ElementInterface) -> bool:
        """Determines if a given element is a valid item (e.g., a job posting).

        This is the core method of the rule set. It must be implemented by all
        concrete subclasses.

        Args:
            element: The framework-agnostic `ElementInterface` to be evaluated.

        Returns:
            True if the element matches the criteria for a valid item, False otherwise.
        """
        pass

class GoogleJobRuleSet(HeuristicRuleSet):
    """The specific, fortified rules for identifying a job posting on Google's UI."""

    def __init__(self):
        """Initializes the rule set for the 'google' site key."""
        super().__init__("google")

    def is_match(self, element: ElementInterface) -> bool:
        """Applies a multi-layered set of rules for a high-confidence match on Google.

        This implementation checks for three conditions in order:
        1.  The element must contain a link (`<a>` tag).
        2.  The link's URL must contain substrings defined in the config.
        3.  The element's visible text must contain time-based keywords
            (e.g., "days ago"), also from the config.

        An element must pass all three checks to be considered a match.

        Args:
            element: The `ElementInterface` to evaluate.

        Returns:
            True if the element is a high-confidence match, False otherwise.
        """
        try:
            link_element = element.find_element(By.TAG_NAME, 'a')
            if not link_element:
                return False

            href = link_element.get_attribute('href')
            if not href or not any(sub in href for sub in self.rules['required_link_substrings']):
                return False

            text = element.text.lower()
            if not any(keyword in text for keyword in self.rules['required_text_keywords']):
                return False

            return True

        except Exception:
            return False

class BingJobRuleSet(HeuristicRuleSet):
    """
    The specific, fortress-level rules for identifying a job posting on Bing's UI.
    """

    def __init__(self):
        """Initializes the rule set for the 'bing' site key."""
        super().__init__("bing")

    def is_match(self, element: ElementInterface) -> bool:
        """Applies a highly robust, two-stage heuristic for Bing.

        This implementation prioritizes a "golden attribute" for its primary check:
        1.  It first checks if the element has a `data-jid` attribute, which is
            a stable, unique job identifier used by Bing's own scripts.
        2.  As a secondary confirmation, it ensures the element also contains a
            link with a valid URL structure.

        This two-factor approach is extremely reliable.

        Args:
            element: The `ElementInterface` to evaluate.

        Returns:
            True if the element is a high-confidence match, False otherwise.
        """
        try:
            job_id = element.get_attribute('data-jid')
            if not job_id:
                return False

            link_element = element.find_element(By.TAG_NAME, 'a')
            href = link_element.get_attribute('href')
            if not href or not any(sub in href for sub in self.rules['required_link_substrings']):
                return False
            return True
        except Exception:
            return False
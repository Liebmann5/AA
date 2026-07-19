"""Provides components for finding container elements using Semantic Analysis.

This module uses enterprise-grade heuristics based on WAI-ARIA accessibility
standards. Instead of guessing tag names, it looks for semantic roles (list,
feed, tree) which are required for accessibility compliance and are far more
stable than CSS classes or HTML structure.
"""

import logging
import time

from auto_apply.adapters.secondary.evasion.components import behavior
from auto_apply.adapters.secondary.browser.context_manager import ContextManager
from auto_apply.domain.config import settings
from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)


class HeuristicFinder:
    """Analyzes a page to dynamically find the container of a list of items."""

    def __init__(self, browser: BrowserInterface):
        self.browser = browser
        self.ctx_mgr = ContextManager(browser)

    def find_best_container(self, validation_rules: dict[str, list[str]]) -> ElementInterface | None:  # noqa: E501
        """Scans the page (and iframes) to find the element containing the most valid job cards.

        Args:
            validation_rules (Dict[str, List[str]]): Rules to validate children.

        Return:
            Optional[ElementInterface]: The winning container element.
        """  # noqa: E501
        best_container = None

        # We define a "predicate" function that returns True if a good container is found.  # noqa: E501
        # This allows the ContextManager to run this logic inside every iframe.
        def _scan_context(browser) -> bool:
            nonlocal best_container

            # Trigger the appropriate scroll strategy based on config
            self._trigger_lazy_load()

            # --- STRATEGY: SEMANTIC ARIA ROLES + TAGS ---
            # We look for containers that explicitly declare themselves as lists
            semantic_selectors = [
                "ul[role='tree']",  # Google Jobs Widget often uses this
                "div[role='tree']",
                "div[role='feed']",
                "div[role='list']",
                "ul[role='list']",
                "div[id='search']", # Google Organic Results container
                "ul",
                "ol"
            ]

            combined_selector = ", ".join(semantic_selectors)
            candidates = self.browser.find_elements(Locator.CSS_SELECTOR, combined_selector)  # noqa: E501

            # Fallback: If strict semantics fail, check generic structural divs
            if not candidates:
                logger.debug("No semantic roles found. Falling back to generic tag analysis.")  # noqa: E501
                candidates = self.browser.find_elements(Locator.CSS_SELECTOR, "div, ul, ol, section, main")  # noqa: E501

            logger.debug(f"HeuristicFinder: Analyzing {len(candidates)} candidate containers.")  # noqa: E501

            local_best = None
            max_valid_children = 0

            for container in candidates:
                try:
                    # Get direct children (the potential items)
                    children = container.find_elements(Locator.XPATH, "./*")

                    # Heuristic: A list of jobs usually has at least 3 items
                    if len(children) < 3:
                        continue

                    # Count how many children look like valid jobs
                    valid_count = sum(1 for c in children if self._is_child_valid(c, validation_rules))  # noqa: E501

                    if valid_count > max_valid_children:
                        max_valid_children = valid_count
                        local_best = container
                except Exception:
                    continue

            if local_best and max_valid_children > 0:
                best_container = local_best
                logger.info(f"HeuristicFinder found container with {max_valid_children} items.")  # noqa: E501
                return True # This stays True to tell ContextManager we succeeded.
            return False

        found = self.ctx_mgr.find_context_with_content(_scan_context)

        if found:
            logger.info("HeuristicFinder located container (possibly inside iframe).")
            return best_container

        return None

    def _trigger_lazy_load(self) -> None:
        """Scrolls the page based on evasion settings."""
        try:
            if settings.evasion.enable_behavior_humanization:
                logger.debug("Lazy Load: Executing human-like page scan.")
                behavior.human_like_page_scan(self.browser, max_scrolls=5)
            else:
                logger.debug("Lazy Load: Executing fast JS scroll.")
                self.browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")  # noqa: E501
                time.sleep(1.5)

            self.browser.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)
        except Exception:
            pass

    def _is_child_valid(self, element: ElementInterface, rules: dict[str, list[str]]) -> bool:  # noqa: E501
        """Validates a single child element against job card rules."""

        # 1. Size Check (Optimization)
        # Job cards are usually visible blocks. Tiny elements (separators) are ignored.
        try:
            size = element.get_size()
            if size[0] < 50 or size[1] < 20:
                return False
        except Exception:
            # If we can't measure it, it might be hidden or stale
            return False

        # 2. Content Check
        # We need the text to perform keyword matching
        text_content = element.text.lower()
        if not text_content:
            return False

        # 3. Rule Matching
        # Does the card contain specific keywords (e.g. "Apply", "Posted")?
        required_text = rules.get('required_text', [])
        if required_text:
            if not any(keyword in text_content for keyword in required_text):
                return False

        # 4. Link Matching (Optional but strong signal)
        # Does the card contain a link?
        required_link_signals = rules.get('required_link_substrings', [])
        if required_link_signals:
            try:
                # Look for ANY anchor tag inside this element
                links = element.find_elements(Locator.TAG_NAME, "a")
                has_valid_link = False
                for link in links:
                    href = link.get_attribute("href")
                    if href and any(sig in href for sig in required_link_signals):
                        has_valid_link = True
                        break

                if not has_valid_link:
                    return False
            except Exception:
                return False

        return True
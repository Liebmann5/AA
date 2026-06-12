"""Provides advanced handling for Select dropdowns and Comboboxes.

This module implements logic to handle both standard HTML <select> tags and
modern JavaScript-based Comboboxes (React-Select, Select2, etc.). It uses
semantic text matching to robustly select options even when the user's
profile data (e.g., "Applied Math") doesn't exactly match the dropdown
option (e.g., "Mathematics").
"""

import logging
import time

from auto_apply.adapters.secondary.evasion.components import behavior
from auto_apply.adapters.secondary.interaction.handlers.base import BaseInputHandler
from auto_apply.application.services.text_matching import TextMatcher
from auto_apply.domain.ports.browser_port import ElementInterface
from auto_apply.domain.types import Keys, Locator

logger = logging.getLogger(__name__)

class SelectInputHandler(BaseInputHandler):
    """Handles interaction with dropdown selection widgets."""

    def __init__(self, browser, text_matcher=None):
        super().__init__(browser)
        self.matcher = text_matcher if text_matcher is not None else TextMatcher()

    def handle(self, element: ElementInterface, value: str) -> None:
        """Dispatches to standard or custom logic based on element structure."""
        tag = element.get_attribute("tagName").lower()

        if tag == "select":
            self._handle_standard_select(element, value)
        elif self._is_custom_combobox(element):
            self._handle_custom_combobox(element, value)
        else:
            # Fallback for weirdly tagged elements that might just be click-to-open
            self._handle_custom_combobox(element, value)

    def _handle_standard_select(self, element: ElementInterface, user_value: str) -> None:  # noqa: E501
        """Handles standard HTML <select> tags robustly.

        Instead of typing blindly, we:
        1. Get all <option> text values.
        2. Find the semantically closest match to the user's profile value.
        3. Click that specific option.
        """
        logger.info(f"Handling Standard Select for value: '{user_value}'")

        try:
            # 1. Retrieve all options
            options = element.find_elements(Locator.TAG_NAME, "option")
            #option_map = {opt.text.strip(): opt for opt in options if opt.text.strip()}
            if not options:
                logger.warning("Select element has no options.")
                return

            # Extract text from options for matching
            # We filter out empty or placeholder options like "Select..."
            option_map = {}
            for opt in options:
                text = opt.text.strip()
                if text and len(text) > 1:
                    option_map[text] = opt

            if not option_map:
                logger.warning("No valid text options found in select.")
                return

            # 2. Find Best Match (AI/Fuzzy Logic)
            candidates = list(option_map.keys())
            best_match_text, score = self.matcher.find_best_match(user_value, candidates)  # noqa: E501

            logger.info(f"Semantic Match: User='{user_value}' -> Option='{best_match_text}' (Score: {score:.2f})")  # noqa: E501

            # 3. Select logic
            if score > 0.6:
                target_option = option_map[best_match_text]
                target_option.click()
            else:
                # Fallback: If no good match, try typing explicitly (browser native behavior)  # noqa: E501
                logger.warning("Low match score ({score:.2f}). Attempting native typing fallback.")  # noqa: E501
                element.click()
                element.send_keys(user_value)
                element.send_keys(Keys.ENTER)

        except Exception as e:
            logger.error(f"Failed to handle standard select: {e}")

    def _handle_custom_combobox(self, element: ElementInterface, user_value: str) -> None:  # noqa: E501
        """Handles React-Select, Select2, and ARIA comboboxes.

        These are complex because they are often <div>s or <inputs> that spawn
        a separate list container in the DOM when clicked.

        Strategy:
        1. Click trigger to expand.
        2. Type partial keyword to filter results (simulating human search).
        3. Identify the 'listbox' container that appears in the DOM.
        4. Match and click the best result.
        """
        logger.info(f"Handling Custom Combobox for value: '{user_value}'")

        try:
            # 1. Open the dropdown
            behavior.human_like_click(self.browser, element)
            time.sleep(0.5)   # Wait for animation/DOM injection

            # 2. Type to filter (simulating user narrowing down options)
            # We don't type the whole sentence ("Applied Mathematics..."),
            # we try to type the most significant keyword first.
            search_term = self._extract_keyword(user_value)
            behavior.human_like_typing(element, search_term)
            time.sleep(1.0)   # Wait for filter results

            # 3. Identify the results container (Heuristic)
            # Common roles for dropdown results: listbox, menu, grid
            # Or classes like: .select2-results, .react-select__menu
            results_container = self._find_dropdown_results()

            if results_container:
                # Find selectable items (ARIA options, LIs, or divs with classes)
                items = results_container.find_elements(Locator.CSS_SELECTOR, "[role='option'], li, div[class*='option'], div[class*='item']")  # noqa: E501

                # Filter visible items with text
                item_map = {item.text.strip(): item for item in items if item.text.strip()}  # noqa: E501

                if item_map:
                    candidates = list(item_map.keys())
                    best_match_text, score = self.matcher.find_best_match(user_value, candidates)  # noqa: E501

                    if score > 0.7:
                        logger.info(f"Combobox Match: '{best_match_text}'")
                        behavior.human_like_click(self.browser, item_map[best_match_text])  # noqa: E501
                        return

            # Fallback: If we can't find the list or match, hit Enter and hope
            logger.warning("Could not intelligently select from combobox. Sending Enter.")  # noqa: E501
            element.send_keys(Keys.ENTER)

        except Exception as e:
            logger.error(f"Failed to handle custom combobox: {e}")

    def _extract_keyword(self, full_text: str) -> str:
        """Extracts the most distinct keyword from a long string.

        Example: "Applied Mathematics, Concentration in..." -> "Mathematics"
        """
        # Simple heuristic: Take the longest word, or the first noun-like word.
        # Ideally, SpaCy could extract the ROOT noun here.
        # For now, we split and take the first significant word > 3 chars
        words = [w for w in full_text.split() if len(w) > 3]
        #return words[0] if words else full_text
        if not words:
            return full_text

        # Return the longest word (likely the most descriptive noun)
        return max(words, key=len)

    def _is_custom_combobox(self, element: ElementInterface) -> bool:
        """Detects if an element is a modern JS dropdown."""
        role = element.get_attribute("role")
        aria_haspopup = element.get_attribute("aria-haspopup")
        autocomplete = element.get_attribute("autocomplete")
        cls = element.get_attribute("class") or ""

        if role == "combobox":
            return True
        if aria_haspopup in ["listbox", "true", "menu", "grid"]:
            return True
        if autocomplete and autocomplete != "off":
            return True
        if "select" in cls.lower() or "dropdown" in cls.lower():
            return True
        return False

    def _find_dropdown_results(self) -> ElementInterface | None:
        """Scans the DOM for the currently open dropdown list container."""
        # Dropdowns usually get appended to the <body> or adjacent to the input
        # We look for elements with role='listbox' that are visible
        try:
            candidates = self.browser.find_elements(Locator.CSS_SELECTOR, "[role='listbox'], [class*='menu'], [class*='results'], [class*='dropdown-content']")  # noqa: E501
            # We need to filter for the one that is actually visible/active
            # Since ElementInterface doesn't strictly expose 'is_displayed' everywhere yet,  # noqa: E501
            # we assume the last one added to DOM is the active one.
            if candidates:
                # Assume the last one added to DOM is the active/visible one
                return candidates[-1]
        except Exception:
            pass
        return None

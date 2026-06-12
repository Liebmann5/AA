"""Provides DOM scanning capabilities to generate abstract UIModels.

This is responsible for traversing the browser's Accessibility Object
Model (AOM) and DOM to create a platform-agnostic snapshot of the
page's interactable elements.

This module contains 'Smart Parsers' that can extract structured data (Text,
URLs, JSON-LD) from any `ElementInterface`. These parsers use a 'Chain of
Responsibility' pattern to try multiple strategies (tags, classes, attributes)
until valid data is found.
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

# Services
from auto_apply.adapters.secondary.browser.context_manager import ContextManager

# Models
from auto_apply.domain.models.ui import UIElement, UIElementType, UIModel

# Core Interfaces
from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)


class DOMScanner:
    """Scans the active browser page to produce a semantic UIModel.

    This class handles the complexity of:
    1.  Recursive iframe traversal (via ContextManager).
    2.  Semantic role detection (ARIA roles vs HTML tags).
    3.  Label association (linking text labels to input fields).
    """

    def __init__(self, browser: BrowserInterface):
        """Initializes the scanner.

        Args:
            browser (BrowserInterface): The active browser adapter.
        """
        self.browser = browser
        self.context_manager = ContextManager(browser)

    def navigate(self, url: str) -> None:
        """Navigates the browser to the given URL.

        Args:
            url: The fully qualified URL to navigate to.
        """
        self.browser.get(url)

    def scan_page(self) -> UIModel:
        """Performs a comprehensive scan of the current page state.

        Returns:
            UIModel: A snapshot containing all interactable elements found.
        """
        all_elements: list[UIElement] = []

        # --- IDEA #1 ---
        # We use a recursive function that ContextManager can execute inside frames.
        #! (# Predicate function for the ContextManager to execute in each frame)
        def _scan_context(browser: BrowserInterface) -> bool:
            # 1. Identify Interactables in current frame
            # We look for inputs, buttons, and ARIA roles
            raw_elements = self._find_interactables(browser)

            for raw_el in raw_elements:
                ui_element = self._process_element(raw_el)
                if ui_element:
                    all_elements.append(ui_element)

            # Return False to force ContextManager to keep searching ALL other frames
            # (We want to map the *entire* page, not just find one thing)
            return False
        #------------------
        # --- IDEA #2 ---
        # Scan for different types of elements
        # all_elements.extend(self._scan_form_elements())
        # all_elements.extend(self._scan_buttons())
        # all_elements.extend(self._scan_links())
        #------------------

        # Execute the scan across all frames
        self.context_manager.find_context_with_content(_scan_context)

        # Reset to default content after scanning is done
        self.context_manager.reset()

        return UIModel(
            url=self.browser.current_url,
            title=self.browser.title,
            elements=all_elements,
        )

    def _find_interactables(self, browser: BrowserInterface) -> list[ElementInterface]:
        """Locates raw DOM elements that represent user interactions.

        Args:
            browser (BrowserInterface): The browser context to search.

        Returns:
            List[ElementInterface]: A list of raw element wrappers.
        """
        # A robust CSS selector targeting all relevant form/interaction nodes
        selector = (
            "input:not([type='hidden']), "
            "textarea, "
            "select, "
            "button, "
            "[role='button'], "
            "[role='checkbox'], "
            "[role='radio'], "
            "[role='textbox'], "
            "[role='combobox'], "
            "[role='listbox'], "
            "a[href]"
        )
        try:
            return browser.find_elements(Locator.CSS_SELECTOR, selector)
        except Exception as e:
            logger.warning(f"Error finding interactables in frame: {e}")
            return []

    def _process_element(self, raw_el: ElementInterface) -> UIElement | None:
        """Converts a raw DOM element into a semantic UIElement.

        Args:
            raw_el (ElementInterface): The raw browser element.

        Returns:
            Optional[UIElement]: The enriched model, or None if invalid/invisible.
        """
        try:
            # 1. Visibility Check (Optimization: Don't map hidden fields)
            # Note: We might want to keep hidden fields if strict parsing,
            # but for a user-agent, we usually only care about visible ones.
            size = raw_el.get_size()
            if size[0] <= 0 or size[1] <= 0:
                return None

            # 2. Classification (Type Detection)
            # Use the FieldClassifier service logic here
            el_type = self._determine_type(raw_el)

            # 3. Constraint Extraction
            is_required = raw_el.get_attribute("required") is not None
            # Extract regex pattern if available
            pattern = raw_el.get_attribute("pattern")

            # 4. Label Resolution (The hard part)
            label = self._resolve_label(raw_el)
            placeholder = raw_el.get_attribute("placeholder")
            name = raw_el.get_attribute("name") or raw_el.get_attribute("id") or "unknown"  # noqa: E501

            # 5. Build Model
            # Generate a stable ID hash based on attributes to help tracking
            internal_id = f"{name}-{label}-{el_type.value}"

            ui_el = UIElement(
                id=internal_id,
                element_type=el_type,
                name=name,
                label=label,
                placeholder=placeholder,
                is_required=is_required,
                validation_pattern=pattern
            )

            # Attach technical reference (Private, not serialized)
            ui_el.set_reference(raw_el)

            return ui_el

        except Exception as e:
            logger.debug(f"Failed to process element: {e}")
            return None

    #! refactor this logic => belongs inside FieldClassifier
    def _determine_type(self, element: ElementInterface) -> UIElementType:
        """Determines the semantic type of the element."""
        tag = element.get_attribute("tagName").lower()
        role = element.get_attribute("role")
        inputType = element.get_attribute("type")

        if tag == "select" or role == "listbox":
            return UIElementType.SELECT
        if inputType == "checkbox" or role == "checkbox":
            return UIElementType.CHECKBOX
        if inputType == "radio" or role == "radio":
            return UIElementType.RADIO
        if inputType == "file":
            return UIElementType.FILE_UPLOAD
        if tag == "textarea" or role == "textbox":
            return UIElementType.TEXT_AREA
        if tag == "button" or role == "button" or inputType == "submit":
            return UIElementType.BUTTON
        if tag == "a":
            return UIElementType.LINK

        return UIElementType.TEXT_INPUT

    def _resolve_label(self, element: ElementInterface) -> str | None:
        """Attempts to find the human-readable label for an input.

        Strategies:
        1. 'aria-label' attribute.
        2. 'aria-labelledby' (requires lookup).
        3. Associated <label for="id"> tag.
        4. Parent text content (if wrapped in a label).
        """
        # Strategy 1: Direct ARIA
        aria_label = element.get_attribute("aria-label")
        if aria_label:
            return aria_label

        # Strategy 2: Label tag association (Simplified)
        el_id = element.get_attribute("id")
        if el_id:
            try:
                # We try to find a label with 'for' attribute matching this ID
                label_el = self.browser.find_element(Locator.CSS_SELECTOR, f"label[for='{el_id}']")  # noqa: E501
                if label_el:
                    return label_el.text.strip()
            except Exception:
                pass

        # Strategy 3: Parent text (Common in modern frameworks)
        # Often <label>Input</label>
        try:
            parent_text = element.find_element(Locator.XPATH, "./..").text
            # Simple heuristic: remove the input's own value from parent text
            return parent_text.strip()
        except Exception:
            pass

        return None

class BaseExtractor(ABC):
    """The abstract contract for all extraction components."""

    @abstractmethod
    def extract(self, context: ElementInterface) -> str | None:
        """Extracts data from the provided element context.

        Args:
            context (ElementInterface): The web element to search within.

        Returns:
            Optional[str]: The extracted text or value, or None if extraction failed.
        """
        ...


class SmartTextExtractor(BaseExtractor):
    """A resilient extractor that hunts for text using multiple DOM strategies.

    It is designed to handle modern, obfuscated DOMs where titles might be
    h3, h2, div[role='heading'], or simple spans with specific classes.
    """

    def __init__(self, strategies: list[str] = None):
        """Initializes the extractor.

        Args:
            strategies (List[str]): A prioritized list of CSS selectors to check.
        """
        self.strategies = strategies or [
            "h3", "h2", "h4", "a",
            "div[role='heading']",
            "a[role='heading']",
            "div[class*='title']",
            "span[class*='title']",
            "div[class*='header']",
            ".job-title", ".title",
            ".g h3", "a h3", ".g"
        ]

    def extract(self, context: ElementInterface) -> str | None:
        """Iterates through selectors to find non-empty text."""
        # Strategy 1: Look for children matching specific selectors
        for selector in self.strategies:
            try:
                # We search within the context (the job card)
                element = context.find_element(Locator.CSS_SELECTOR, selector)
                if element:
                    text = element.text.strip()
                    if text:
                        return text
            except Exception:
                continue

        # DEBUG LOG: Help us see why it failed
        logger.debug(f"SmartTextExtractor: Failed to find text using strategies: {self.strategies}")  # noqa: E501

        # Strategy 2: Fallback to the text of the container itself
        # (Useful if the container IS the title, e.g., an <a> tag)
        try:
            #return context.text.strip() if context.text else None
            return context.text.strip() or None
        except Exception:
            return None


class SmartURLExtractor(BaseExtractor):
    """A resilient extractor that finds the primary navigational link."""

    def extract(self, context: ElementInterface) -> str | None:
        """Finds the most likely job URL."""
        # Strategy 1: Is the element itself a link?
        try:
            if context.get_attribute("href"):
                return context.get_attribute("href")
        except Exception:
            pass

        # Strategy 2: Look for child anchor tags
        # We prioritize specific classes, then generic links
        candidates = [
            "a[data-job-id]",
            "a[class*='job']",
            "a[class*='title']",
            "a", "a:has(h3)",
            "a.job-link", "a.title",
        ]

        for selector in candidates:
            try:
                link = context.find_element(Locator.CSS_SELECTOR, selector)
                if link:
                    href = link.get_attribute("href")
                    # Basic validation: ignore javascript actions or empty links
                    if href and len(href) > 5 and "javascript" not in href:
                        return href
            except Exception:
                continue

        return None


class JSONLDParser:
    """A specialized parser that extracts job data(structured metadata) from JSON-LD script tags.

    This parser does not follow the BaseParser single-element contract because
    it operates on the entire page context to find structured metadata. This operates
    on the Browser level, not the Element level.
    """  # noqa: E501

    def __init__(self, browser: BrowserInterface):
        """Initializes the parser with the browser instance.

        Args:
            browser (BrowserInterface): The active browser to execute scripts.
        """
        self.browser = browser

    def parse_page(self) -> list[dict[str, Any]]:
        """Scans the entire page for 'JobPosting' schemas in JSON-LD blocks.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries representing the raw
                                  JobPosting data found in the HTML source.
        """
        job_postings = []
        try:
            # We use XPath to find all script tags with the json-ld type
            scripts = self.browser.find_elements(Locator.XPATH, '//script[@type="application/ld+json"]')  # noqa: E501

            for script in scripts:
                # We must use execute_script to get the innerHTML of the script tag reliably,  # noqa: E501
                # as .text can sometimes be hidden by browser optimizations.
                content = self.browser.execute_script("return arguments[0].innerHTML;", script)  # noqa: E501

                if not content:
                    continue

                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    continue

                # JSON-LD can be a single object or a graph (list) of objects
                graph = data.get('@graph', [data])

                if not isinstance(graph, list):
                    graph = [graph]

                for item in graph:
                    if isinstance(item, dict) and item.get('@type') == 'JobPosting':
                        job_postings.append(item)

            if job_postings:
                logger.info(f"JSON-LD Parser extracted {len(job_postings)} items.")

            return job_postings

        except Exception as e:
            logger.warning(f"JSON-LD extraction encountered a non-critical error: {e}")
            return []

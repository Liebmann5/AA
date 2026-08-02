"""Provides advanced handling for file upload interactions.

This module encapsulates the logic for uploading files to web forms. It handles
standard `<input type='file'>` elements as well as modern, stylized upload
buttons where the actual input field is hidden or obscured by CSS. It ensures
the file exists locally before attempting interaction to prevent browser hangs.
"""

import logging
import os
from pathlib import Path
from typing import Any

from auto_apply.adapters.secondary.interaction.handlers.base import BaseInputHandler
from auto_apply.domain.exceptions import InfrastructureError
from auto_apply.domain.ports.browser_port import ElementInterface
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)


class FileInputHandler(BaseInputHandler):
    """Handles file uploads, including detection and manipulation of hidden inputs."""

    def handle(self, element: ElementInterface, value: Any) -> None:
        """Uploads a file to the specified element.

        Strategy:
        1. Validate the local file path exists.
        2. Check if the target element is a valid `<input type='file'>`.
        3. If the target is a styled wrapper (div/span), locate the associated hidden input.
        4. If hidden, force visibility via JavaScript to allow interaction.
        5. Send the file path via `send_keys`.
        6. Wait briefly for the upload to begin processing.

        Args:
            element (ElementInterface): The target element (input or wrapper).
            value (Any): The absolute string path to the file to upload.

        Raises:
            InfrastructureError: If the local file does not exist.
        """  # noqa: E501
        file_path = str(value)
        if not os.path.exists(file_path):
            raise InfrastructureError(f"Cannot upload file. Path does not exist: {file_path}")  # noqa: E501

        # Normalize path for the OS (handles Windows vs Unix slashes)
        abs_path = str(Path(file_path).resolve())

        target_input = element
        tag_name = element.get_attribute("tagName").lower()
        input_type = element.get_attribute("type")

        # Case 1: Element is NOT the input (it's a "Upload Resume" div/button)
        if tag_name != "input" or input_type != "file":
            logger.debug("Target is not a file input. Searching for associated hidden input.")  # noqa: E501
            target_input = self._find_associated_file_input(element)

        if not target_input:
            logger.warning("Could not locate a valid file input for upload.")
            return

        try:
            # Case 2: Input might be hidden (display:none or opacity:0)
            # Standard Selenium/WebDriver cannot interact with hidden elements.
            # We must 'unhide' it temporarily.
            self._force_visibility(target_input)

            logger.info("Uploading file: %s", abs_path)
            target_input.send_keys(abs_path)

            # Wait for the upload to begin processing (file validation,
            # preview, etc.). Readiness, not pacing: poll until the DOM
            # stops changing rather than guessing at a fixed second.
            if not self._await_dom_ready():
                logger.debug(
                    "FileInputHandler: DOM did not settle after upload; "
                    "continuing"
                )

        except Exception as e:
            logger.error("File upload interaction failed: %s", e)

    def _find_associated_file_input(self, wrapper: ElementInterface) -> Any:
        """Heuristics to find the actual input when clicked on a wrapper."""
        # Strategy A: Check immediate children
        try:
            child_inputs = wrapper.find_elements(Locator.XPATH, ".//input[@type='file']")  # noqa: E501
            if child_inputs:
                return child_inputs[0]
        except Exception:
            pass

        # Strategy B: Check immediate siblings
        try:
            sibling_inputs = wrapper.find_elements(Locator.XPATH, "./following-sibling::input[@type='file'] | ./preceding-sibling::input[@type='file']")  # noqa: E501
            if sibling_inputs:
                return sibling_inputs[0]
        except Exception:
            pass

        # Strategy C: Global fallback (Risky, but often necessary for overlay masks)
        # We look for the first file input on the page that is likely related.
        try:
            all_inputs = self.browser.find_elements(Locator.CSS_SELECTOR, "input[type='file']")  # noqa: E501
            if len(all_inputs) == 1:
                return all_inputs[0]
        except Exception:
            pass

        return None

    def _force_visibility(self, element: ElementInterface) -> None:
        """Injects CSS to make a hidden file input interactive."""
        script = """
        arguments[0].style.display = 'block';
        arguments[0].style.visibility = 'visible';
        arguments[0].style.opacity = '1';
        arguments[0].style.width = '1px';
        arguments[0].style.height = '1px';
        arguments[0].removeAttribute('hidden');
        """
        try:
            self.browser.execute_script(script, element)
        except Exception as e:
            logger.debug("Failed to force visibility on file input: %s", e)
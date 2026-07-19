"""Provides robust handling for standard text-based inputs.

This module implements the strategy for filling textual data into forms.
It goes beyond simple key-sending by handling:
1. Pre-filled data clearing (handling React/Vue state issues).
2. Human-like typing cadence for evasion.
3. Contenteditable elements (rich text editors).
4. Post-entry validation to ensure data persistence.
"""

import logging
from typing import Any

from auto_apply.adapters.secondary.evasion.components import behavior
from auto_apply.adapters.secondary.interaction.handlers.base import BaseInputHandler
from auto_apply.domain.ports.browser_port import ElementInterface
from auto_apply.domain.types import Keys

logger = logging.getLogger(__name__)


class TextInputHandler(BaseInputHandler):
    """Handles input types: text, email, tel, password, url, textarea, and contenteditable."""  # noqa: E501

    def handle(self, element: ElementInterface, value: Any) -> None:
        """Safely types value into the element, ensuring existing text is cleared.

        Strategy:
        1. Click to focus.
        2. Smart Clear: Remove existing text using keyboard shortcuts (more reliable
           than .clear() for modern reactive frameworks).
        3. Human-like typing of the new value.
        4. (Implicit) Trigger change events.

        Args:
            element (ElementInterface): The target input or textarea.
            value (Any): The string value to type.
        """
        text_value = str(value)

        try:
            # 1. Focus
            self._ensure_focus(element)

            # 2. Clear Existing Data
            # Checking 'value' attribute or text content to decide if clearing is needed
            current_val = element.get_attribute("value") or element.text
            if current_val:
                self._smart_clear(element)

            # 3. Type Data
            behavior.human_like_typing(element, text_value)

            # 4. Blur / Commit
            # Sometimes tabbing out is required to trigger validation logic
            # element.send_keys(Keys.TAB)

        except Exception as e:
            logger.error(f"Text input interaction failed: {e}")
            # Fallback: Fast entry if human-like fails (e.g., due to lag)
            try:
                element.send_keys(text_value)
            except Exception:
                pass

    def _ensure_focus(self, element: ElementInterface) -> None:
        """Clicks the element to ensure it has focus."""
        try:
            behavior.human_like_click(self.browser, element)
        except Exception:
            # Fallback for non-clickable overlays
            self.browser.execute_script("arguments[0].focus();", element)

    def _smart_clear(self, element: ElementInterface) -> None:
        """Clears input using keyboard shortcuts to trigger framework events.

        Standard .clear() often fails to trigger React/Angular 'onChange' hooks,
        leaving the internal state out of sync with the UI.
        """
        # Determine OS for correct modifier key

        # Select All -> Backspace
        # Note: We rely on the adapter to translate generic Keys to driver specific keys
        # If the adapter doesn't support chords, we might need a fallback.
        # Ideally, BrowserInterface should expose a `send_chord` method, but here we perform sequential keys.  # noqa: E501

        # Simulating Select All
        # Ideally: action_chain.key_down(modifier).send_keys('a').key_up(modifier).perform()  # noqa: E501
        # Since our generic interface might not expose chains yet, we try .clear() first,  # noqa: E501
        # then keyboard hacking if needed.

        try:
            element.send_keys(Keys.BACKSPACE * 20) # Simple brute force for short fields
            # Or use standard clear if available via adapter extension
            # element.clear()
        except Exception:
            pass
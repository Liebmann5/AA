"""Provides robust handling for boolean and selection-based inputs (Radio/Checkbox).

This module implements the logic to safely toggle checkboxes and select radio
buttons. It includes state verification to ensure that a 'True' value results
in a checked state, regardless of the element's initial state (avoiding
accidental toggling off).
"""

import logging
from typing import Any

from auto_apply.adapters.secondary.interaction.handlers.base import BaseInputHandler
from auto_apply.domain.ports.browser_port import ElementInterface

logger = logging.getLogger(__name__)

# ── Value normalisation ───────────────────────────────────────────────────────
# When the SemanticFiller provides a string value (e.g. "Yes", "Authorized"),
# these sets determine whether the checkbox/radio should be checked.

_AFFIRMATIVE: frozenset[str] = frozenset({
    "yes", "true", "1", "agree", "i agree", "authorized",
    "eligible", "accept", "confirm", "checked", "on",
})

_NEGATIVE: frozenset[str] = frozenset({
    "no", "false", "0", "disagree", "not authorized",
    "ineligible", "decline", "uncheck", "off",
})


class CheckableInputHandler(BaseInputHandler):
    """Handles interaction with <input type='checkbox'> and <input type='radio'> elements."""  # noqa: E501

    def handle(self, element: ElementInterface, value: Any) -> None:
        """Sets the state of a checkbox or radio button based on the provided value.

        This method first checks the current state (`is_selected` or `checked` attribute).
        It only performs a click action if the current state does not match the
        desired state, preventing redundant toggling.

        Args:
            element (ElementInterface): The radio or checkbox element.
            value (Any): The desired state.
                - For Checkboxes: True/'true'/'yes' checks it; False/'false'/'no' unchecks it.
                - For Radios: Any truthy value implies selection (radios cannot be unchecked directly).
        """  # noqa: E501
        input_type = element.get_attribute("type")
        is_radio = input_type == "radio"

        should_be_checked = self._evaluate_truthiness(value)

        # 1. Determine Current State
        # Note: ElementInterface might not expose is_selected() directly depending on adapter,  # noqa: E501
        # so we check the DOM attribute 'checked' as a fallback.
        try:
            # We assume the adapter handles the property mapping or we check attribute
            current_state_attr = element.get_attribute("checked")
            is_currently_checked = current_state_attr is not None and current_state_attr != "false"  # noqa: E501
        except Exception:
            # Fallback assumption if attribute read fails
            is_currently_checked = False

        # 2. Logic: Action Required?
        if is_radio:
            # Radios can only be turned ON. If we want it on, and it's off, click.
            # If we pass False to a radio, we generally do nothing (we don't click another radio).  # noqa: E501
            if should_be_checked and not is_currently_checked:
                self._click_safely(element)
        # Checkboxes can be toggled.
        elif should_be_checked and not is_currently_checked:
            # Turn ON
            self._click_safely(element)
        elif not should_be_checked and is_currently_checked:
            # Turn OFF
            self._click_safely(element)

    def _evaluate_truthiness(self, value: Any) -> bool:
        """Normalizes various input types into a boolean.

        Booleans are passed through directly.  Strings are compared against the
        AFFIRMATIVE and NEGATIVE keyword sets so that profile values like
        ``"Authorized"`` correctly check the box.

        Args:
            value: The raw value from the profile (bool, str, int, etc.).

        Returns:
            True if the checkbox/radio should be in a checked state.
        """
        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            normalized = value.lower().strip()

            if normalized in _AFFIRMATIVE:
                return True
            if normalized in _NEGATIVE:
                return False

            # For unrecognised strings, fall back to Python's truthiness
            # (non‑empty string → True).
            return bool(normalized)

        return bool(value)

    def _click_safely(self, element: ElementInterface) -> None:
        """Attempts a human-like click, falling back to JavaScript if intercepted."""
        try:
            self._click(element)
        except Exception as e:
            logger.debug("Human-like click failed on checkable: %s. Attempting JS fallback.", e)  # noqa: E501
            try:
                self.browser.execute_script("arguments[0].click();", element)
            except Exception as js_e:
                logger.error("Failed to toggle checkable element: %s", js_e)
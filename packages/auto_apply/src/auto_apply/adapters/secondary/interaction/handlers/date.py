"""Provides robust handling for date, datetime, and month input fields.

Date pickers often reject keyboard-typed text.  This handler tries three
strategies in order:

    1. JavaScript value injection + dispatch input/change events.
    2. send_keys() with the formatted date string.
    3. Clear-and-type character by character, then Tab to dismiss the picker.

All browsers (Selenium, Playwright) support these strategies through the
generic ElementInterface.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any

from auto_apply.adapters.secondary.interaction.handlers.base import BaseInputHandler
from auto_apply.domain.ports.browser_port import ElementInterface
from auto_apply.domain.types import Keys

logger = logging.getLogger(__name__)


class DateInputHandler(BaseInputHandler):
    """Handles <input type='date'>, 'datetime-local', 'month', and 'week'.

    Args:
        browser: The active BrowserInterface, used for execute_script.
    """

    # Common formats the handler normalises from.
    _ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    _US_DATE  = re.compile(r"^\d{2}/\d{2}/\d{4}$")

    def handle(self, element: ElementInterface, value: Any) -> None:
        """Fill a date-like input using the best available strategy.

        Args:
            element: The date/datetime/month input element.
            value: A date string — ISO‑8601 ("2026-01-15"), US ("01/15/2026"),
                   or any other format.  Falls back to today's date if the
                   string is unparseable.
        """
        formatted = self._normalise_date(str(value))
        logger.debug(
            "DateInputHandler: filling | value=%r formatted=%r",
            value,
            formatted,
        )

        # Strategy 1 — JavaScript value injection (most reliable).
        if self._try_js_injection(element, formatted):
            return

        # Strategy 2 — send_keys with the formatted value.
        if self._try_send_keys(element, formatted):
            return

        # Strategy 3 — clear and type character by character.
        self._try_clear_and_type(element, formatted)

    # ------------------------------------------------------------------
    # Strategy implementations
    # ------------------------------------------------------------------

    def _try_js_injection(self, element: ElementInterface, value: str) -> bool:
        """Inject *value* via JavaScript and fire input/change events.

        Returns True if the value was successfully set.
        """
        try:
            self.browser.execute_script(
                "arguments[0].value = arguments[1]; "
                "arguments[0].dispatchEvent(new Event('input', {bubbles: true})); "
                "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                element,
                value,
            )
            time.sleep(0.3)

            # Verify the value "stuck".
            current = self.browser.execute_script(
                "return arguments[0].value;", element
            )
            if current and current.strip():
                logger.debug("DateInputHandler: JS injection OK | value=%s", current)
                return True
        except Exception as exc:
            logger.debug("DateInputHandler: JS injection failed | %s", exc)

        return False

    def _try_send_keys(self, element: ElementInterface, value: str) -> bool:
        """Type the value via send_keys, then dismiss any calendar popup.

        Returns True if the element accepted the value.
        """
        try:
            element.click()
            time.sleep(0.2)
            element.send_keys(value)
            time.sleep(0.2)
            element.send_keys(Keys.TAB)  # Dismiss any date-picker overlay.
            logger.debug("DateInputHandler: send_keys OK | value=%s", value)
            return True
        except Exception as exc:
            logger.debug("DateInputHandler: send_keys failed | %s", exc)

        return False

    def _try_clear_and_type(self, element: ElementInterface, value: str) -> None:
        """Brute‑force fallback: select all, delete, type character by character."""
        try:
            element.click()
            time.sleep(0.15)
            # Select existing text and replace.
            element.send_keys(Keys.BACKSPACE * 20)
            for char in value:
                element.send_keys(char)
                time.sleep(0.05)
            element.send_keys(Keys.TAB)
            logger.debug("DateInputHandler: clear+type OK | value=%s", value)
        except Exception as exc:
            logger.warning("DateInputHandler: clear+type failed | %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_date(raw: str) -> str:
        """Convert a date string into MM/DD/YYYY for US forms.

        Accepts ISO‑8601 ("2026-01-15") and US ("01/15/2026") formats.
        Any unparseable string returns today's date.
        """
        if DateInputHandler._ISO_DATE.match(raw):
            try:
                dt = datetime.strptime(raw, "%Y-%m-%d")
            except ValueError:
                dt = datetime.now()
        elif DateInputHandler._US_DATE.match(raw):
            try:
                dt = datetime.strptime(raw, "%m/%d/%Y")
            except ValueError:
                dt = datetime.now()
        else:
            dt = datetime.now()

        return dt.strftime("%m/%d/%Y")
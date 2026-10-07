"""Typer — text entry and form-control value setting.

Keystroke rhythm comes from pacing; the focus click comes from the clicker.
A native <select>'s options are drawn by the operating system and cannot be
pointer-clicked cross-framework, so the value is set through the option list
(the driver's own option click where it works, then the recorded JS set with
the change events frameworks listen for).
"""
from __future__ import annotations

import logging
import time

from auto_apply.application.services.page_action.clicking import Clicker
from auto_apply.application.services.page_action.pacing import Pacing
from auto_apply.application.services.page_action.result import ActionResult
from auto_apply.application.services.page_action.state import PageActionContext
from auto_apply.domain.ports.browser_port import ElementInterface
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)


class Typer:
    """Types text and sets select/checkbox values through the tool."""

    def __init__(
        self,
        state: PageActionContext,
        pacing: Pacing,
        clicker: Clicker,
    ) -> None:
        self._state = state
        self._pacing = pacing
        self._clicker = clicker

    def type_text(self, element: ElementInterface, text: str) -> ActionResult:
        """Types text into a focused element character by character.

        Args:
            element: The input or textarea element to type into.
            text: The string to type. May include Keys.ENTER, Keys.TAB, etc.

        Returns:
            ActionResult. success=True if all text was typed.
        """
        try:
            self._clicker.click(element)
            for char in text:
                element.send_keys(char)
                if self._state.human_timing:
                    time.sleep(self._pacing.micro_delay(
                        peak_ms=self._state.micro_peak_ms,
                        randomness=0.45,
                    ))
            self._pacing.settle_pause()
            return ActionResult(True)
        except Exception as exc:
            logger.warning("type_text failed | %s", exc)
            return ActionResult(False, reason=str(exc))

    def clear_and_type(self, element: ElementInterface, text: str) -> ActionResult:
        """Clears an input field and types new text."""
        try:
            self._state.browser.execute_script(
                "arguments[0].value = ''; "
                "arguments[0].dispatchEvent(new Event('input', {bubbles: true})); "
                "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                element,
            )
            time.sleep(self._pacing.micro_delay(peak_ms=100))
            return self.type_text(element, text)
        except Exception as exc:
            logger.warning("clear_and_type failed | %s", exc)
            return ActionResult(False, reason=str(exc))

    def select_option(
        self,
        select_element: ElementInterface,
        *,
        by_value: str | None = None,
        by_text: str | None = None,
        by_index: int | None = None,
    ) -> ActionResult:
        """Selects an option in a <select> dropdown element.

        Exactly one keyword argument must be provided. The driver's own
        option click is tried first where the option list is live; the
        recorded JS set (selectedIndex + change event) is the fallback —
        OS-drawn option popups cannot be pointer-clicked cross-framework.
        """
        provided = sum(x is not None for x in (by_value, by_text, by_index))
        if provided != 1:
            raise ValueError(
                "select_option requires exactly one of: by_value, by_text, by_index"
            )

        try:
            options = select_element.find_elements(Locator.TAG_NAME, "option")

            if options:
                for i, opt in enumerate(options):
                    match = (
                        (by_value is not None and opt.get_attribute("value") == by_value)  # noqa: E501
                        or (by_text is not None and opt.text.strip() == by_text.strip())  # noqa: E501
                        or (by_index is not None and i == by_index)
                    )
                    if match:
                        opt.click()
                        self._pacing.settle_pause()
                        return ActionResult(True)

                available = [opt.text.strip() for opt in options[:10]]
                logger.warning(
                    "select_option: no match | "
                    "by_value=%r by_text=%r by_index=%r available=%s",
                    by_value, by_text, by_index, available,
                )

            if by_value is not None:
                self._state.browser.execute_script(
                    "var s=arguments[0],v=arguments[1];"
                    "for(var i=0;i<s.options.length;i++){"
                    "  if(s.options[i].value===v){"
                    "    s.selectedIndex=i;"
                    "    s.dispatchEvent(new Event('change',{bubbles:true}));"
                    "    break;"
                    "  }"
                    "}",
                    select_element, by_value,
                )
                self._pacing.settle_pause()
                return ActionResult(True)

            if by_text is not None:
                self._state.browser.execute_script(
                    "var s=arguments[0],t=arguments[1].trim();"
                    "for(var i=0;i<s.options.length;i++){"
                    "  if(s.options[i].text.trim()===t){"
                    "    s.selectedIndex=i;"
                    "    s.dispatchEvent(new Event('change',{bubbles:true}));"
                    "    break;"
                    "  }"
                    "}",
                    select_element, by_text,
                )
                self._pacing.settle_pause()
                return ActionResult(True)

            if by_index is not None:
                self._state.browser.execute_script(
                    "var s=arguments[0];"
                    "s.selectedIndex=arguments[1];"
                    "s.dispatchEvent(new Event('change',{bubbles:true}));",
                    select_element, by_index,
                )
                self._pacing.settle_pause()
                return ActionResult(True)

        except Exception as exc:
            logger.warning("select_option failed | %s", exc)
            return ActionResult(False, reason=str(exc))

        return ActionResult(False, reason="select_option: no strategy succeeded")

    def check_checkbox(
        self,
        element: ElementInterface,
        desired: bool = True,
    ) -> ActionResult:
        """Sets a checkbox to the desired checked state."""
        try:
            is_checked = self._state.browser.execute_script(
                "return arguments[0].checked;", element
            )
            if bool(is_checked) != desired:
                return self._clicker.click(element)
            return ActionResult(True)
        except Exception as exc:
            logger.warning("check_checkbox failed | %s", exc)
            return ActionResult(False, reason=str(exc))

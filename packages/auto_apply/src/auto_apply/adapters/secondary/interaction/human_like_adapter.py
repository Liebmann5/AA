"""Provides the centralized facade for all form element interactions.

This module acts as a Dispatcher/Facade. It analyzes a target DOM element's
properties (tag name, input type, ARIA roles) and routes the interaction request
to the appropriate specialized handler (Text, Select, File, Date, Checkable).

This abstraction allows the higher-level FSM strategies to simply call
`fill_input(element, value)` without needing to know the low-level details of
how a specific widget works.

Provides the execution engine for carrying out Interaction Plans.

This module implements 'The Executor' phase of the Scan-Plan-Act architecture.
It acts as the bridge between high-level logical intent (e.g., "Type 'Bruce'
into the First Name field") and low-level driver manipulation.

It relies on the `UnifiedInteractor` to handle specific widget nuances (Selects,
File Uploads, Date Pickers, Checkboxes) and `behavior` to ensure human-like
cadence and stealth.
"""

import logging
import time
from typing import Any, Protocol

from auto_apply.adapters.secondary.interaction.handlers.checkable import (
    CheckableInputHandler,
)
from auto_apply.adapters.secondary.interaction.handlers.date import DateInputHandler
from auto_apply.adapters.secondary.interaction.handlers.file import FileInputHandler
from auto_apply.adapters.secondary.interaction.handlers.select import SelectInputHandler
from auto_apply.adapters.secondary.interaction.handlers.text import TextInputHandler

# Core Models
from auto_apply.domain.exceptions import ApplicationError
from auto_apply.domain.models.ui import InteractionPlan, InteractionType, PlannedAction
from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface
from auto_apply.domain.ports.interaction_port import InteractionPort

logger = logging.getLogger(__name__)


class ExecutionStrategy(Protocol):
    """Protocol for interaction execution strategy (e.g. stealth vs. headless)."""


class UnifiedInteractor:
    """Dispatches interaction requests to specialized handlers based on element type.

    Routing table (evaluated in order):

        ====================== ============================================
        Condition              Handler
        ====================== ============================================
        ``<select>``           :class:`SelectInputHandler`
        ``role=combobox``      :class:`SelectInputHandler` (custom combobox)
        ``type=file``          :class:`FileInputHandler`
        ``type=checkbox/radio``:class:`CheckableInputHandler`
        ``type=date``          :class:`DateInputHandler`
        ``type=datetime-local``:class:`DateInputHandler`
        ``type=month``         :class:`DateInputHandler`
        ``type=week``          :class:`DateInputHandler`
        everything else        :class:`TextInputHandler`
        ====================== ============================================
    """

    # HTML input types that the date handler should receive.
    _DATE_TYPES: frozenset[str] = frozenset({"date", "datetime-local", "month", "week"})

    def __init__(
        self,
        browser: BrowserInterface,
        text_matcher=None,
        page_action=None,
        readiness=None,
    ):
        """Initializes the interactor and its component handlers.

        Args:
            browser (BrowserInterface): The active browser instance.
            text_matcher: Optional shared TextMatcher injected down into the
                handlers that need semantic matching (SelectInputHandler), so
                SpaCy is loaded once per session rather than per handler.
        """
        self.browser = browser
        self._text_matcher = text_matcher

        # Every handler receives the same two collaborators, so timing and
        # readiness have exactly one implementation across all widgets.
        _kw = {"page_action": page_action, "readiness": readiness}

        # Initialize strategies — one instance per handler type.
        self.text_handler = TextInputHandler(browser, **_kw)
        self.select_handler = SelectInputHandler(
            browser, text_matcher=self._text_matcher, **_kw
        )
        self.file_handler = FileInputHandler(browser, **_kw)
        self.checkable_handler = CheckableInputHandler(browser, **_kw)
        self.date_handler = DateInputHandler(browser, **_kw)

    def fill_input(self, element: ElementInterface, value: Any) -> None:
        """Analyzes the element and delegates interaction to the correct handler.

        This method employs a heuristic dispatch mechanism to identify the
        nature of the element (e.g., is it a native Select, a React Combobox,
        a Date picker, or a File input?) and ensures the data is entered correctly.

        Args:
            element (ElementInterface): The target DOM element.
            value (Any): The data to enter (string, bool, or file path).
        """
        try:
            # get_attribute returns str | None; an unreadable tag degrades to ""
            # and falls through to the text handler, never to an AttributeError.
            tag = (element.get_attribute("tagName") or "").lower()
            input_type = (element.get_attribute("type") or "").lower()
            role = (element.get_attribute("role") or "").lower()

            # 1. Select / Combobox Logic (Native <select> or ARIA combobox)
            if tag == "select" or role == "combobox" or self.select_handler._is_custom_combobox(element):  # noqa: E501
                self.select_handler.handle(element, str(value))
                return

            # 2. File Upload Logic
            if input_type == "file":
                self.file_handler.handle(element, str(value))
                return

            # 3. Radio / Checkbox Logic
            if input_type in ("radio", "checkbox"):
                self.checkable_handler.handle(element, value)
                return

            # 4. Date / Datetime / Month / Week picker
            if input_type in self._DATE_TYPES:
                self.date_handler.handle(element, str(value))
                return

            # 5. Default: Text Input Logic (Fallback for text, email, tel, textarea)
            # Note: We treat unknown types as text fields to attempt entry
            self.text_handler.handle(element, str(value))

        except Exception as e:
            logger.error("Interaction dispatch failed for element: %s", e)
            # We explicitly do not raise here to prevent a single bad field
            # from crashing the entire application flow. The FSM will verify
            # completion later.


class InteractionExecutor(InteractionPort):
    """Executes a sequence of planned actions on the browser.

    This class is responsible for the physical manifestation of the Agent's
    decisions. It handles error recovery for individual steps and ensures that
    logic-derived plans are translated into robust browser events.
    """

    def __init__(
        self,
        browser: BrowserInterface,
        strategy: ExecutionStrategy | None = None,
        text_matcher=None,
        page_action=None,
        readiness=None,
    ):
        """Initializes the executor.

        Args:
            browser (BrowserInterface): The active browser adapter.
            strategy: Optional execution strategy (stealth vs. instant).
            text_matcher: Optional shared TextMatcher passed down to the
                UnifiedInteractor and its handlers (single SpaCy load).
            page_action: The PageActionService tool. It owns every click, all
                pacing, and the seeded RNG; this class only delegates to it.
                Injected by the composition root whenever a driver exists.
                Passed positionally-free and defaulted to None so direct
                construction in tests still works, but ``click`` requires it.
        """
        self.browser = browser
        self.strategy = strategy    # e.g., StealthHumanStrategy || InstantHeadlessStrategy
        self._text_matcher = text_matcher
        self._page_action = page_action
        self._readiness = readiness

        # The UnifiedInteractor handles the specific "How-To" for inputs
        self.interactor = UnifiedInteractor(
            browser,
            text_matcher=self._text_matcher,
            page_action=page_action,
            readiness=readiness,
        )

    # ------------------------------------------------------------------
    # Public API — entry point used by ApplicationsWorkflow
    # ------------------------------------------------------------------

    def click(self, element: ElementInterface) -> None:
        """Clicks an element through the shared PageActionService tool.

        This method deliberately contains no mechanics. The tool owns the
        mouse path, the fingerprint decision, the settle pause and the seeded
        RNG, so every click in AA is paced by one config-driven implementation.

        Per the ``InteractionPort`` contract this returns None on success and
        raises on failure — the tool itself never raises (it returns a falsy
        ``ActionResult``), so the failure is converted here. Callers such as
        ``ApplicationsWorkflow._submit_application`` rely on that raise to
        record ``submit_clicked=False`` rather than reporting a click that
        never landed.

        Args:
            element: The element to click.

        Raises:
            ApplicationError: If no tool is available, or the tool reports the
                click did not complete.
        """
        if self._page_action is None:
            raise ApplicationError(
                "InteractionExecutor.click requires the PageActionService tool; "
                "none was injected (composition root supplies it whenever a "
                "driver is present)."
            )

        result = self._page_action.click(element)
        if not result:
            reason = getattr(result, "reason", "unknown")
            raise ApplicationError(f"click did not complete: {reason}")

    def simulate_idle(self, min_seconds: float, max_seconds: float) -> None:
        """Pauses for a human-scale interval between tasks.

        Delegates to the tool's macro pause so inter-task pacing comes from the
        same configured, seeded distribution as every other pause.

        Args:
            min_seconds: Minimum pause duration in seconds.
            max_seconds: Maximum pause duration in seconds.
        """
        if self._page_action is None:
            return
        self._page_action.macro_pause(min_seconds, max_seconds)

    def _settle(self) -> None:
        """Short post-action pause, delegated to the tool.

        Replaces the hardcoded ``time.sleep(0.5)`` that used to sit between
        plan steps. When no tool is present this is a no-op rather than a
        magic-number fallback: a second pacing implementation is exactly the
        duplication this stage removes.
        """
        if self._page_action is None:
            return
        self._page_action.settle()

    def fill(self, element: ElementInterface, value: Any) -> bool:
        """Fill a single form field, routing to the correct strategy.

        This is the comprehensive dispatcher that the ApplicationsWorkflow
        (and any other caller) should use.  It inspects the element's tag and
        HTML type attribute to select the appropriate fill strategy, then
        delegates to :class:`UnifiedInteractor.fill_input`.

        Args:
            element: The DOM element to interact with.
            value: The data to enter (str, bool, file path, etc.).

        Returns:
            True if filling completed without raising an exception.
        """
        try:
            self.interactor.fill_input(element, value)
            return True
        except Exception as exc:
            tag = (element.get_attribute("tagName") or "?").lower() if element else "?"
            input_type = (element.get_attribute("type") or "").lower() if element else "?"
            logger.warning(
                "InteractionExecutor.fill failed | tag=%s type=%s error=%s",
                tag, input_type, exc,
            )
            return False

    def execute_plan(self, plan: InteractionPlan) -> bool:
        """Iterates through an interaction plan and performs all actions.

        This method executes actions sequentially. If a critical action fails,
        the entire plan is aborted to prevent inconsistent state.

        Args:
            plan (InteractionPlan): The ordered sequence of actions to perform.

        Returns:
            bool: True if the critical path of the plan succeeded.
                  False if a critical action failed.
        """
        logger.info("Executor: Starting plan '%s' (%d steps).", plan.goal_description, len(plan.actions))  # noqa: E501

        for action in plan.actions:
            success = self._execute_single_action(action)

            if not success:
                logger.error("Executor: Action failed -> %s on %s", action.action_type.name, action.target_element_id)  # noqa: E501

                if action.is_critical:
                    logger.warning("Executor: Critical action failed. Aborting plan.")
                    return False
                else:
                    logger.info("Executor: Non-critical action failed. Continuing.")

            # Brief pause between actions to allow JS events to propagate and
            # to maintain human-like pacing. The duration is the tool's
            # config-driven, low-resource-clamped, seeded settle pause.
            self._settle()

        logger.info("Executor: Plan completed successfully.")
        return True

    def _execute_single_action(self, action: PlannedAction) -> bool:
        """Dispatches a single planned action to the appropriate handler.

        Args:
            action (PlannedAction): The specific instruction to execute.

        Returns:
            bool: True if the action completed without raising an exception.
        """
        try:
            # 1. Resolve Technical Reference
            # The logic engine (Solver) must have attached the live UIElement reference
            # to the action object before passing it here.
            if not hasattr(action, 'ui_element') or not action.ui_element:
                logger.error("Action %s missing UIElement reference. Logic error.", action.target_element_id)  # noqa: E501
                return False

            # Get the raw driver element (WebElement/Locator) from the wrapper
            try:
                element_ref = action.ui_element.get_reference()
            except ValueError:
                logger.error("UIElement %s has lost its browser reference (Stale?).", action.target_element_id)  # noqa: E501
                return False

            # 2. Log Intent (Masking sensitive data if needed)
            display_value = "***" if action.encrypted_value else action.value
            logger.debug("Act: %s -> %s (Val: %s)", action.action_type.name, action.target_element_id, display_value)  # noqa: E501

            # 3. Dispatch based on InteractionType
            if action.action_type == InteractionType.CLICK:
                self.click(element_ref)

            elif action.action_type in [InteractionType.TYPE, InteractionType.SELECT_OPTION, InteractionType.UPLOAD_FILE]:  # noqa: E501
                # Delegate complex inputs to the UnifiedInteractor
                self.interactor.fill_input(element_ref, action.value)

            elif action.action_type == InteractionType.HOVER:
                self.browser.move_mouse_to_element(element_ref)

            elif action.action_type == InteractionType.WAIT_FOR:
                # 'value' here represents seconds to wait
                wait_time = float(action.value) if action.value else 1.0
                time.sleep(wait_time)

            elif action.action_type == InteractionType.VERIFY_TEXT:
                # Validation step: Ensure text appeared (e.g. "Application Submitted")
                current_text = element_ref.text
                if not action.value or str(action.value) not in current_text:
                    logger.warning("Verification Failed. Expected '%s', found '%s'", action.value, current_text)  # noqa: E501
                    return False

            else:
                logger.warning("Unsupported action type: %s", action.action_type)
                return False

            return True

        except Exception as e:
            # Catch specific driver errors like StaleElementReferenceException
            # which imply the page changed under our feet.
            logger.warning("Action execution exception on %s: %s", action.target_element_id, e)  # noqa: E501
            return False
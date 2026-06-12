"""Provides the centralized facade for all form element interactions.

This module acts as a Dispatcher/Facade. It analyzes a target DOM element's
properties (tag name, input type, ARIA roles) and routes the interaction request
to the appropriate specialized handler (Text, Select, File, etc.).

This abstraction allows the higher-level FSM strategies to simply call
`fill_input(element, value)` without needing to know the low-level details of
how a specific widget works.

Provides the execution engine for carrying out Interaction Plans.

This module implements 'The Executor' phase of the Scan-Plan-Act architecture.
It acts as the bridge between high-level logical intent (e.g., "Type 'Bruce'
into the First Name field") and low-level driver manipulation.

It relies on the `UnifiedInteractor` to handle specific widget nuances (Selects,
File Uploads) and `behavior` to ensure human-like cadence and stealth.
"""

import logging
import time
from typing import Any, Protocol

from auto_apply.adapters.secondary.evasion.components import behavior
from auto_apply.adapters.secondary.interaction.handlers.checkable import (
    CheckableInputHandler,
)
from auto_apply.adapters.secondary.interaction.handlers.file import FileInputHandler
from auto_apply.adapters.secondary.interaction.handlers.select import SelectInputHandler
from auto_apply.adapters.secondary.interaction.handlers.text import TextInputHandler

# Core Models
from auto_apply.domain.models.ui import InteractionPlan, InteractionType, PlannedAction
from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface

logger = logging.getLogger(__name__)


class ExecutionStrategy(Protocol):
    """Protocol for interaction execution strategy (e.g. stealth vs. headless)."""


class UnifiedInteractor:
    """Dispatches interaction requests to specialized handlers based on element type."""

    def __init__(self, browser: BrowserInterface, text_matcher=None):
        """Initializes the interactor and its component handlers.

        Args:
            browser (BrowserInterface): The active browser instance.
            text_matcher: Optional shared TextMatcher injected down into the
                handlers that need semantic matching (SelectInputHandler), so
                SpaCy is loaded once per session rather than per handler.
        """
        self.browser = browser
        self._text_matcher = text_matcher

        # Initialize strategies
        self.text_handler = TextInputHandler(browser)
        self.select_handler = SelectInputHandler(browser, text_matcher=self._text_matcher)
        self.file_handler = FileInputHandler(browser)
        self.checkable_handler = CheckableInputHandler(browser)

    def fill_input(self, element: ElementInterface, value: Any) -> None:
        """Analyzes the element and delegates interaction to the correct handler.

        This method employs a heuristic dispatch mechanism to identify the
        nature of the element (e.g., is it a native Select, a React Combobox,
        or a File input?) and ensures the data is entered correctly.

        Args:
            element (ElementInterface): The target DOM element.
            value (Any): The data to enter (string, bool, or file path).
        """
        try:
            tag = element.get_attribute("tagName").lower()
            input_type = element.get_attribute("type")
            role = element.get_attribute("role")

            # 1. Select / Combobox Logic (Native <select> or ARIA combobox)
            if tag == "select" or role == "combobox" or self.select_handler._is_custom_combobox(element):  # noqa: E501
                self.select_handler.handle(element, str(value))
                return

            # 2. File Upload Logic
            if input_type == "file":
                self.file_handler.handle(element, str(value))
                return

            # 3. Radio / Checkbox Logic
            if input_type in ["radio", "checkbox"]:
                self.checkable_handler.handle(element, value)
                return

            # 4. Default: Text Input Logic (Fallback for text, email, tel, textarea)
            # Note: We treat unknown types as text fields to attempt entry
            self.text_handler.handle(element, str(value))

        except Exception as e:
            logger.error(f"Interaction dispatch failed for element: {e}")
            # We explicitly do not raise here to prevent a single bad field
            # from crashing the entire application flow. The FSM will verify
            # completion later.

class InteractionExecutor:
    """Executes a sequence of planned actions on the browser.

    This class is responsible for the physical manifestation of the Agent's
    decisions. It handles error recovery for individual steps and ensures that
    logic-derived plans are translated into robust browser events.
    """

    def __init__(self, browser: BrowserInterface, strategy: ExecutionStrategy | None = None, text_matcher=None):
        """Initializes the executor.

        Args:
            browser (BrowserInterface): The active browser adapter.
            strategy: Optional execution strategy (stealth vs. instant).
            text_matcher: Optional shared TextMatcher passed down to the
                UnifiedInteractor and its handlers (single SpaCy load).
        """
        self.browser = browser
        self.strategy = strategy    # e.g., StealthHumanStrategy || InstantHeadlessStrategy
        self._text_matcher = text_matcher

        # The UnifiedInteractor handles the specific "How-To" for inputs
        self.interactor = UnifiedInteractor(browser, text_matcher=self._text_matcher)

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
        logger.info(f"Executor: Starting plan '{plan.goal_description}' ({len(plan.actions)} steps).")  # noqa: E501

        for action in plan.actions:
            success = self._execute_single_action(action)

            if not success:
                logger.error(f"Executor: Action failed -> {action.action_type.name} on {action.target_element_id}")  # noqa: E501

                if action.is_critical:
                    logger.warning("Executor: Critical action failed. Aborting plan.")
                    return False
                else:
                    logger.info("Executor: Non-critical action failed. Continuing.")

            # Brief pause between actions to allow JS events to propagate
            # and to maintain human-like pacing.
            time.sleep(0.5)

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
                logger.error(f"Action {action.target_element_id} missing UIElement reference. Logic error.")  # noqa: E501
                return False

            # Get the raw driver element (WebElement/Locator) from the wrapper
            try:
                element_ref = action.ui_element.get_reference()
            except ValueError:
                logger.error(f"UIElement {action.target_element_id} has lost its browser reference (Stale?).")  # noqa: E501
                return False

            # 2. Log Intent (Masking sensitive data if needed)
            display_value = "***" if action.encrypted_value else action.value
            logger.debug(f"Act: {action.action_type.name} -> {action.target_element_id} (Val: {display_value})")  # noqa: E501

            # 3. Dispatch based on InteractionType
            if action.action_type == InteractionType.CLICK:
                behavior.human_like_click(self.browser, element_ref)

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
                    logger.warning(f"Verification Failed. Expected '{action.value}', found '{current_text}'")  # noqa: E501
                    return False

            else:
                logger.warning(f"Unsupported action type: {action.action_type}")
                return False

            return True

        except Exception as e:
            # Catch specific driver errors like StaleElementReferenceException
            # which imply the page changed under our feet.
            logger.warning(f"Action execution exception on {action.target_element_id}: {e}")  # noqa: E501
            return False

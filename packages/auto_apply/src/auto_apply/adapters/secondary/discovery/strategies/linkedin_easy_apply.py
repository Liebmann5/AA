"""Provides the advanced FSM strategy for LinkedIn Easy Apply.

This module implements a Finite State Machine to navigate the non-linear,
multi-step workflow of LinkedIn's application modal. It is robust against
dynamic DOM changes and variable question ordering.
"""

import logging
import time

from auto_apply.domain.applications.field_classifier import FieldClassifier
from auto_apply.domain.applications.fsm.base import BaseApplicationStrategy
from auto_apply.domain.applications.fsm.states import ApplicationState
from auto_apply.domain.applications.semantic_filler import SemanticFiller
from auto_apply.domain.ports.interaction_port import InteractionPort
from auto_apply.domain.ports.perception_port import PerceptionPort
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)


class LinkedInEasyApplyStrategy(BaseApplicationStrategy):
    """A state-machine based strategy for LinkedIn."""

    def __init__(self, browser, profile, job, perception: PerceptionPort, interactor: InteractionPort):
        super().__init__(browser, profile, job)
        self._perception = perception
        self._interactor = interactor
        self.classifier = FieldClassifier()
        self.filler = SemanticFiller(profile)
        self.max_steps = 15

    def apply(self) -> bool:
        """Executes the FSM loop."""
        logger.info("LinkedInStrategy: Starting FSM for %s", self.job.url)
        self.browser.get(self.job.url)
        time.sleep(3)

        step_count = 0
        while step_count < self.max_steps:
            state = self._perception.get_current_state()
            logger.info("Current State: %s", state.name)

            if state == ApplicationState.SUCCESS:
                logger.info("Application successfully submitted!")
                return True

            if state == ApplicationState.ALREADY_APPLIED:
                logger.info("Job was already applied to.")
                return True

            if state == ApplicationState.INITIAL_START:
                self._action_start_apply()

            elif state == ApplicationState.FORM_STEP:
                self._action_fill_step()
                self._action_next_step()

            elif state == ApplicationState.REVIEW_STEP:
                self._action_submit_application()

            elif state == ApplicationState.ERROR:
                logger.error("Validation errors detected. Attempting logic recovery...")
                return False

            elif state == ApplicationState.UNKNOWN:
                logger.warning("Unknown state detected. Waiting...")
                time.sleep(2)

            step_count += 1
            time.sleep(2)

        logger.error("Max steps reached. Workflow timed out.")
        return False

    def _find_active_modal(self):
        """Finds an active application modal (e.g., LinkedIn Easy Apply)."""
        selectors = [
            "div[role='dialog']",
            ".modal",
            "[class*='modal']",
            ".jobs-easy-apply-modal",
            "div[aria-modal='true']",
        ]
        for sel in selectors:
            try:
                elements = self.browser.find_elements(Locator.CSS_SELECTOR, sel)
                for element in elements:
                    if element.get_size()[0] > 0:
                        return element
            except Exception:
                continue
        return None

    def _action_start_apply(self):
        """Clicks the initial Easy Apply button."""
        btn = self.browser.find_element(
            Locator.CSS_SELECTOR, ".jobs-apply-button--top-card button"
        )
        if btn:
            self._interactor.click(btn)

    def _action_fill_step(self):
        """Identifies and fills all inputs in the current modal step."""
        modal = self._find_active_modal()
        if not modal:
            return

        inputs = modal.find_elements(Locator.CSS_SELECTOR, "input, select, textarea")

        for element in inputs:
            field_type = self.classifier.classify(element)
            value = self.filler.get_value_for_field(field_type, "")
            if value:
                self._interactor.fill(element, value)
                self._interactor.simulate_idle(0.5, 1.0)

    def _action_next_step(self):
        """Finds and clicks Next/Review."""
        modal = self._find_active_modal()
        if not modal:
            return

        btn = modal.find_element(
            Locator.CSS_SELECTOR,
            "button[aria-label='Continue to next step'], "
            "button[aria-label='Review your application']",
        )
        if btn:
            self._interactor.click(btn)

    def _action_submit_application(self):
        """Clicks the final Submit button."""
        modal = self._find_active_modal()
        if not modal:
            return

        btn = modal.find_element(
            Locator.CSS_SELECTOR, "button[aria-label='Submit application']"
        )
        if btn:
            self._interactor.click(btn)
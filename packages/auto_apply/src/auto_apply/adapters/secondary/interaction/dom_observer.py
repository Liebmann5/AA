"""Provides advanced DOM analysis to determine the current state of a form workflow.

This module implements the 'Observe' phase of the OODA loop. It uses heuristic
scoring and semantic analysis (ARIA roles, button text, DOM structure) to
classify the current UI state (e.g., Start, Form Filling, Review, Success).
It leverages the ContextManager to peer inside iframes and modals automatically,
ensuring that the application engine doesn't get stuck on embedded forms.
"""

import logging
import time
from enum import Enum, auto

from auto_apply.adapters.secondary.browser.context_manager import ContextManager
from auto_apply.adapters.secondary.browser.page_snapshot import browser_page_snapshot
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.services.page_assessment import assess_page
from auto_apply.domain.types import Locator, PageType

logger = logging.getLogger(__name__)


class FormState(Enum):
    """Represents the generic phases of a multi-step web form workflow.

    This Enum abstracts the specific state of any job application system (ATS)
    into a standardized set of phases that the FSM strategies can act upon.
    """
    UNKNOWN = auto()

    # Entry Points
    INITIAL_START = auto()       # "Apply", "Start", or "Easy Apply" button is visible

    # Active Interaction Phases
    FORM_STEP = auto()           # Active inputs (text, check, select) are present
    UPLOAD_STEP = auto()         # A file upload field is the primary focus
    REVIEW_STEP = auto()         # "Review", "Summary", or final "Submit" context

    # Passive/Processing Phases
    PROCESSING = auto()          # Loading state / spinners, "Sending...", overlay masks

    # Terminal States (End of Workflow)
    SUCCESS = auto()             # Confirmation text ("Success", "Thank you")
    ERROR = auto()               # Validation errors or alerts are visible
    ALREADY_APPLIED = auto()     # "You have already applied" indicator
    CLOSED = auto()              #"No longer accepting applications"


class DOMObserver:
    """Analyzes the DOM to determine the current FormState."""

    def __init__(
        self,
        browser: BrowserInterface,
        stability_timeout_s: float = 3.0,
        poll_interval_s: float = 0.25,
    ):
        """Initialise the observer.

        Args:
            browser: The active browser instance.
            stability_timeout_s: Budget for :meth:`wait_for_dom_stable`, from
                ``dom_stabilization_timeout_s``. Not a literal — the
                composition root passes the resolved config value.
            poll_interval_s: Gap between readiness samples, from
                ``dom_stabilization_poll_interval_s``.
        """
        self._stability_timeout_s = float(stability_timeout_s)
        self._poll_interval_s = float(poll_interval_s)
        self._init_browser(browser)

    def wait_for_dom_stable(self, timeout: float | None = None) -> bool:
        """Block until the DOM stops changing, or the budget expires.

        A real readiness poll, not a sleep: it samples a cheap fingerprint of
        the page and returns as soon as two consecutive samples agree, so a
        page that settles in 200ms costs 200ms rather than the whole budget.

        Args:
            timeout: Override for the configured budget, in seconds.

        Returns:
            True if the DOM settled within the budget, False if it did not.
            Never raises: a browser that cannot be sampled is a False, because
            a readiness check must not be able to abort a form fill.
        """
        budget = self._stability_timeout_s if timeout is None else float(timeout)
        deadline = time.monotonic() + budget
        previous: int | None = None

        while True:
            try:
                current = len(self.browser.page_source or "")
            except Exception as exc:
                logger.debug("DOMObserver: DOM sample failed | %s", exc)
                return False

            if previous is not None and current == previous:
                return True
            previous = current

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.debug(
                    "DOMObserver: DOM did not settle within %.2fs", budget
                )
                return False
            time.sleep(min(self._poll_interval_s, remaining))

    def _init_browser(self, browser: BrowserInterface):
        """Initializes the observer.

        Args:
            browser (BrowserInterface): The active browser instance.
        """
        self.browser = browser
        self.ctx_mgr = ContextManager(browser)

    def get_current_state(self) -> FormState:
        """Heuristically determines the current state of the application workflow.

        Returns:
            FormState: The detected state.
        """
        detected_state = FormState.UNKNOWN

        # This predicate is run inside every frame by the ContextManager
        def _analyze_context(browser: BrowserInterface) -> bool:
            nonlocal detected_state

            # 1. Check for Terminal States (Success/Closed/Applied)
            # These are definitive; if found, we stop looking.
            if self._detect_success(browser):
                detected_state = FormState.SUCCESS
                return True

            if self._detect_already_applied():
                detected_state = FormState.ALREADY_APPLIED
                return True

            if self._detect_closed(browser):
                detected_state = FormState.CLOSED
                return True

            # 2. Check for Workflow States (Modal/Form)
            # We look for a modal first as it often overlays the main page content.
            # If a modal exists, we narrow our heuristics to the modal element.
            context_root = self._find_active_modal(browser) or browser

            if self._detect_processing(context_root):
                detected_state = FormState.PROCESSING
                return True

            if self._detect_error_messages(context_root):
                detected_state = FormState.ERROR
                return True

            if self._detect_review_step(context_root):
                detected_state = FormState.REVIEW_STEP
                return True

            # Check for explicit file upload steps (common in ATS wizards)
            if self._detect_upload_step(context_root):
                detected_state = FormState.UPLOAD_STEP
                return True

            if self._detect_form_inputs(context_root):
                detected_state = FormState.FORM_STEP
                return True

            # 3. Check for Entry Point (Start Button)
            # This is usually on the main job description page
            if self._detect_start_button(browser):
                detected_state = FormState.INITIAL_START
                return True

            return False

        # Execute Deep Scan
        # This will switch the browser context to the frame where state was found.
        # It returns True if the predicate returned True.
        found = self.ctx_mgr.find_context_with_content(_analyze_context)

        if not found:
            # If nothing specific is found after scanning all frames, return Unknown.
            # The strategy handling this will likely wait and retry.
            return FormState.UNKNOWN

        return detected_state

    # --- Heuristics Implementations ---

    def _find_active_modal(self, context) -> object | None:
        """Finds an active application modal (e.g., LinkedIn Easy Apply)."""
        # Look for ARIA dialogs or common modal classes used in Single Page Apps
        selectors = [
            "div[role='dialog']",
            ".modal",
            "[class*='modal']",
            ".jobs-easy-apply-modal",
            "div[aria-modal='true']"
        ]
        for sel in selectors:
            try:
                elements = context.find_elements(Locator.CSS_SELECTOR, sel)
                for element in elements:
                    # Robustness check: Ensure it has size (is visible)
                    if element.get_size()[0] > 0:
                        return element
            except Exception:
                continue
        return None

    def _detect_form_inputs(self, context) -> bool:
        """Checks if the context contains interactive form fields."""
        try:
            # Look for visible inputs that aren't hidden fields
            inputs = context.find_elements(Locator.CSS_SELECTOR, "input:not([type='hidden']), select, textarea")  # noqa: E501
            return len(inputs) > 0
        except Exception:
            return False

    def _detect_upload_step(self, context) -> bool:
        """Checks if the current step is primarily about file upload (Resume/CV)."""
        try:
            file_inputs = context.find_elements(Locator.CSS_SELECTOR, "input[type='file']")  # noqa: E501
            return len(file_inputs) > 0
        except Exception:
            return False

    def _detect_review_step(self, context) -> bool:
        """Checks for 'Review' keywords or 'Submit' buttons in the absence of many inputs."""  # noqa: E501
        try:
            # Text check
            text = context.text.lower()
            if "review" in text and ("application" in text or "submit" in text):
                return True

            # Button check: "Submit Application" is a strong signal
            # We check both button elements and inputs of type submit
            submit_btns = context.find_elements(Locator.CSS_SELECTOR, "button, input[type='submit']")  # noqa: E501
            for btn in submit_btns:
                # get_attribute returns str | None; the value attribute may be
                # absent, so narrow it before .lower(). This call is inside
                # try/except already — the guard is for the type, not a crash.
                btn_text = btn.text.lower() or (btn.get_attribute("value") or "").lower()
                if "submit" in btn_text and "application" in btn_text:
                    return True
        except Exception:
            pass
        return False

    def _detect_success(self, context) -> bool:
        """Success is a page kind: ask the ONE verdict, keep no phrases here.

        The LinkedIn success-header phrase ("added to your applied jobs")
        lives in the locale-keyed confirmation table (page_phrases.py).
        The verdict reads the top-frame snapshot; a confirmation rendered
        entirely inside a frame is detected at the top frame. ``context``
        is kept for signature compatibility with the context-scan loop.
        """
        try:
            url, title, html = browser_page_snapshot(self.browser)
            return (
                assess_page(url=url, title=title, html=html).kind
                is PageType.SUCCESS_PAGE
            )
        except Exception:
            return False

    def _detect_already_applied(self) -> bool:
        """Already-applied is a page kind: ask the ONE verdict.

        The "application status" phrase this used to match is a nav link on
        posting pages and was dropped with the phrase-table curation.
        """
        try:
            url, title, html = browser_page_snapshot(self.browser)
            return (
                assess_page(url=url, title=title, html=html).kind
                is PageType.ALREADY_APPLIED
            )
        except Exception:
            return False

    def _detect_closed(self, context) -> bool:
        """Closed is a page kind: ask the ONE verdict, keep no phrases here.

        ``context`` is kept for signature compatibility with the scan loop.
        """
        try:
            url, title, html = browser_page_snapshot(self.browser)
            return (
                assess_page(url=url, title=title, html=html).kind
                is PageType.CLOSED
            )
        except Exception:
            return False

    def _detect_start_button(self, context) -> bool:
        """Checks if the 'Easy Apply' button is available."""
        try:
            #LinkedIn specific
            btns = self.browser.find_elements(Locator.CSS_SELECTOR, ".jobs-apply-button--top-card button")  # noqa: E501
            for btn in btns:
                if "easy apply" in btn.text.lower():
                    return True
        except Exception:
            pass
        return False
    def _detect_error_messages(self, context) -> bool:
        """Checks for validation errors blocking progress."""
        try:
            # ARIA alerts are the standard accessibility way to show errors
            alerts = context.find_elements(Locator.CSS_SELECTOR, "[role='alert']")
            if alerts:
                return True

            # Common error classes in Bootstrap/Tailwind/Material
            errors = context.find_elements(Locator.CSS_SELECTOR, ".error, .invalid-feedback, .alert-danger, .field-error")  # noqa: E501
            return len(errors) > 0
        except Exception:
            return False

    def _detect_processing(self, context) -> bool:
        """Checks for loading spinners or 'Sending...' text indicating background work."""  # noqa: E501
        try:
            # Heuristic: Text indicators
            text = context.text.lower()
            if "sending..." in text or "submitting..." in text or "loading..." in text:
                return True

            # Heuristic: Progress bars or ARIA busy states
            progress = context.find_elements(Locator.CSS_SELECTOR, "[role='progressbar'], [aria-busy='true']")  # noqa: E501
            if progress:
                return True
        except Exception:
            pass
        return False

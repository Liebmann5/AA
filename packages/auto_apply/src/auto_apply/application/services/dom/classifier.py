"""Classifies the current webpage into a known semantic type.

This module provides the `PageClassifier`. It uses a multi-layered analysis
strategy involving Metadata (JSON-LD), Security Signals, and DOM Heuristics
to strictly categorize the current page state.
"""

import logging
from typing import Protocol

from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.types import Locator, PageType

logger = logging.getLogger(__name__)


class _DetectionScanner(Protocol):
    """Minimal interface for detecting bot-detection challenges on the current page."""

    def is_challenge_present(self) -> bool: ...


class PageClassifier:
    """Analyzes browser state to determine the PageType."""

    def __init__(
        self,
        browser: BrowserInterface,
        detection_scanner: _DetectionScanner,
    ):
        self.browser = browser
        self.detection_scanner = detection_scanner

    def classify(self) -> PageType:
        """Determines the semantic type of the current page.

        Every check here is cheap: one detection scan, the page title, and
        three small ``execute_script``/``find_elements`` probes.

        A fourth check used to live at the end of this method. It ran a full
        ``miner.mine_jobs(source_name="classifier_probe")`` over the page and
        returned :attr:`PageType.SERP` when the mine yielded three or more
        cards. It was removed because its result could not reach a decision:
        the sole consumer of :meth:`classify` (``GenericSERPStrategy.execute``)
        branches only on ``{CAPTCHA_BLOCK, LOGIN_REQUIRED, ERROR_404}``, and
        that probe could only produce ``SERP`` or fall through to ``UNKNOWN``.
        Neither is in the abort set, so the mine's outcome changed nothing —
        while costing a complete duplicate extraction pass over the unscrolled
        page, immediately before the harvest loop mined that same page again.
        Measured on a live Google SERP: ~40 seconds, discarded.

        ``SERP`` is still reachable, via the JSON-LD check above, which is one
        ``execute_script`` rather than thousands of WebDriver round trips.

        Returns:
            The semantic :class:`PageType` of the current page.
        """

        # 1. CRITICAL: Security & Error Checks
        if self.detection_scanner.is_challenge_present():
            return PageType.CAPTCHA_BLOCK

        # 2. HTTP/Navigation Errors
        title = self.browser.title.lower()
        if "404" in title or "page not found" in title:
            return PageType.ERROR_404

        # 2. DEFINITIVE: Metadata Analysis (JSON-LD)
        if self._has_job_schema():
            return PageType.SERP  # Or JOB_DESCRIPTION, context dependent

        # 3. Auth Walls
        if self._is_login_page():
            return PageType.LOGIN_REQUIRED

        if "thank you" in title or "application submitted" in title:
            return PageType.SUCCESS_PAGE

        if self._has_application_form():
            return PageType.APPLICATION_FORM

        return PageType.UNKNOWN

    def _has_job_schema(self) -> bool:
        """Checks for the presence of 'JobPosting' schema in JSON-LD."""
        try:
            script = """
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                for (let s of scripts) {
                    if (s.textContent.includes("JobPosting")) return true;
                }
                return false;
            """  # noqa: E501
            return self.browser.execute_script(script)
        except Exception:
            return False

    def _is_login_page(self) -> bool:
        """Checks for authentication barriers."""
        try:
            if self.browser.find_elements(Locator.CSS_SELECTOR, "input[type='password']"):  # noqa: E501
                return True

            title = self.browser.title.lower()
            if "sign in" in title or "log in" in title:
                return True

        except Exception:
            pass
        return False

    def _has_application_form(self) -> bool:
        """Checks for Applicant Tracking System (ATS) indicators."""
        try:
            if self.browser.find_elements(Locator.CSS_SELECTOR, "input[type='file']"):
                return True

            ats_selector = "form[id*='application'], div[class*='application-form']"
            if self.browser.find_elements(Locator.CSS_SELECTOR, ats_selector):
                return True
        except Exception:
            pass
        return False
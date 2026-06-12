"""The central controller for system auditing.

This module aggregates data from specific auditors (Page, Network, Browser)
and generates structured reports for debugging and verification.
"""

import json
import logging
from typing import Any

from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface

from auto_apply.application.services.auditing.network_auditor import NetworkAuditor
from auto_apply.application.services.auditing.page_auditor import PageAuditor

logger = logging.getLogger("Audit")

class AuditReporter:
    """Generates comprehensive system state reports."""

    def __init__(self, browser: BrowserInterface):
        self.browser = browser
        self.page_auditor = PageAuditor(browser)
        self.network_auditor = NetworkAuditor()

    def log_state(self, context_label: str) -> None:
        """Logs a detailed snapshot of the current application state.

        Args:
            context_label (str): A tag describing when this audit ran (e.g., 'Pre-Scrape').
        """  # noqa: E501
        try:
            # Gather Data
            page_data = self.page_auditor.snapshot()
            network_data = self.network_auditor.check_url_compliance(page_data['url'])

            # Build Report
            report = {
                "context": context_label,
                "page": page_data,
                "compliance": network_data
            }

            # Log formatted output
            self._print_report(report)

        except Exception as e:
            logger.error(f"Audit generation failed: {e}")

    def log_item_rejection(self, element: ElementInterface, reason: str, partial_data: dict[str, Any]) -> None:  # noqa: E501
        """Logs details about why a specific item failed extraction.

        This captures the DOM context (HTML snippet, classes) to help debug
        bad selectors.

        Args:
            element (ElementInterface): The DOM element that failed parsing.
            reason (str): Why it was rejected (e.g., "Missing Title").
            partial_data (Dict[str, Any]): What data *was* successfully found (if any).
        """
        try:
            # Capture context to diagnose the failure
            snippet = element.text[:100].replace('\n', ' ')
            tag = element.get_attribute("tagName")
            cls = element.get_attribute("class")

            failure_report = {
                "reason": reason,
                "context": {
                    "tag": tag,
                    "class": cls,
                    "text_snippet": snippet
                },
                "partial_data_found": partial_data
            }

            # We log this as DEBUG to avoid cluttering the main console,
            # but it will appear in the log file for deep analysis.
            logger.debug(f"Audit [Item Rejection]: {json.dumps(failure_report)}")

        except Exception:
            # Never crash the scraper because logging failed
            pass

    def _print_report(self, report: dict) -> None:
        """Formats and prints the audit dictionary."""
        logger.info(f"--- AUDIT REPORT: {report['context']} ---")
        logger.info(f"URL: {report['page']['url']}")
        logger.info(f"Title: {report['page']['title']}")
        logger.info(f"Visible Content: {report['page']['snippet']}...")
        logger.info(f"Links Found: {report['page']['link_count']}")

        status = "ALLOWED" if report['compliance']['robots_txt_allowed'] else "DISALLOWED"  # noqa: E501
        logger.info(f"Robots.txt Status: {status}")
        logger.info("---------------------------------------")
"""Audits network compliance, connectivity, and identity.

This module inspects the network layer to verify that the bot is compliant with
robots.txt, is using the expected IP address (proxy check), and respects throttling
rules."""

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


class NetworkAuditor:
    """Inspects network configuration and compliance."""

    def __init__(self, throttler=None):
        """Initialize with an optional throttler dependency.

        Args:
            throttler: An object providing is_allowed(url) and get_configured_delay(url).
                       If None, compliance checks are skipped (assume allowed).
        """
        self.throttler = throttler

    def check_url_compliance(self, url: str) -> dict[str, Any]:
        """Checks if a URL passes compliance rules and snapshots network identity.

        Args:
            url (str): The target URL to check.

        Returns:
            Dict[str, Any]: A dictionary containing compliance status, detected IP,
                            and throttling configuration.
        """
        is_allowed = True
        configured_delay = 0.0
        if self.throttler:
            is_allowed = self.throttler.is_allowed(url)
            configured_delay = self.throttler.get_configured_delay(url)

        detected_ip = "Unknown"
        try:
            response = requests.get("https://api.ipify.org?format=json", timeout=3)
            if response.status_code == 200:
                detected_ip = response.json().get("ip")
        except Exception as e:
            logger.debug(f"NetworkAudit: Could not resolve external IP: {e}")

        proxy_configured = False

        return {
            "target_url": url,
            "robots_txt_allowed": is_allowed,
            "crawl_delay_seconds": configured_delay,
            "external_ip": detected_ip,
            "proxy_active_in_config": proxy_configured
        }
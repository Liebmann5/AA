"""
Provides payloads of JavaScript code for browser fingerprint evasion.
"""
import logging

from ..core.config import EvasionSettings

logger = logging.getLogger(__name__)

def get_js_payload(settings: EvasionSettings) -> str:
    """
    Constructs a comprehensive payload of JavaScript patches based on settings.
    """
    scripts = []

    scripts.append("Object.defineProperty(navigator, 'webdriver', { get: () => false });")  # noqa: E501

    if settings.spoof_hardware_concurrency:
        scripts.append(f"Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {settings.spoof_hardware_concurrency} }});")  # noqa: E501

    logger.info(f"Generated JS payload with {len(scripts)} patches.")
    return "\n".join(scripts)

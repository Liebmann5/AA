import logging
from typing import Optional
import requests

from packages.auto_apply.src.auto_apply.evasion import detection
from ..core.browser_interface import BrowserInterface
from ..core.browser_state import BrowserFingerprint, BrowserStateSnapshot, DOMMetrics, EvasionProfile, JSEnvironment, NetworkProfile
from ..config import settings

logger = logging.getLogger(__name__)

def _get_current_state(browser: BrowserInterface, evasion_settings) -> Optional[BrowserStateSnapshot]:
    """
    Gathers a snapshot of the browser's digital identity and the page's technical environment.

    This method performs a comprehensive, live audit of the browser's
    state by executing JavaScript to probe for bot-detection vectors and
    combining this with network-level information.

    Args:
        evasion_settings: The configuration object detailing the intended
            evasion settings for the current run.

    Returns:
        A BrowserStateSnapshot model containing the audit data, or None if
        a critical error occurs during the process.
    """
    try:
        audit_script = """
        const knownDetectors = {
            'Cloudflare': window._cf_chl_opt !== undefined, 'Akamai': window.akamai !== undefined,
            'DataDome': window.datadome !== undefined, 'PerimeterX': window._px !== undefined || window.px !== undefined
        };
        const t1 = window.performance.now(); const t2 = window.performance.now();
        const isConsistent = Math.abs(t2 - t1) < 1;
        return {
            webdriver: navigator.webdriver, plugins: navigator.plugins ? navigator.plugins.length : 0,
            screen: `${window.screen.width}x${window.screen.height}x${window.screen.colorDepth}`,
            fonts: document.fonts ? document.fonts.size : -1, consistentTimestamps: isConsistent,
            iframes: document.querySelectorAll('iframe').length, inputs: document.querySelectorAll('input, textarea, select').length,
            hidden: document.querySelectorAll('[style*="display: none"], [hidden]').length,
            botDetectors: Object.keys(knownDetectors).filter(key => knownDetectors[key])
        };
        """
        audit_data = browser.execute_script(audit_script)

        ip_info = requests.get('http://ip-api.com/json', timeout=5).json()
        network_profile = NetworkProfile(
            ip_address=ip_info.get("query", "N/A"),
            ip_geolocation={"country": ip_info.get("country"), "city": ip_info.get("city")},
            user_agent=browser.execute_script("return navigator.userAgent;")
        )
        browser_fingerprint = BrowserFingerprint(
            webdriver_flag=audit_data['webdriver'], plugins_count=audit_data['plugins'],
            screen_resolution=audit_data['screen'], font_count=audit_data['fonts'],
            has_consistent_timestamps=audit_data['consistentTimestamps']
        )
        dom_metrics = DOMMetrics(
            iframe_count=audit_data['iframes'], input_field_count=audit_data['inputs'],
            hidden_element_count=audit_data['hidden']
        )
        console_errors = []
        if browser.framework_name == "selenium":
            try:
                # This is a framework-specific detail, handled correctly in the high-level module
                console_errors = browser.get_raw_driver().get_log('browser')
            except Exception:
                logger.warning("Could not retrieve browser console logs for audit.")

        js_environment = JSEnvironment(
            known_bot_detectors=audit_data['botDetectors'], console_error_count=len(console_errors)
        )
        evasion_profile = EvasionProfile(
            enable_fingerprint_spoofing=evasion_settings.enable_fingerprint_spoofing,
            webgl_spoof_strategy=evasion_settings.webgl_spoof_strategy,
            canvas_spoof_strategy=evasion_settings.canvas_spoof_strategy,
            spoof_hardware_concurrency=evasion_settings.spoof_hardware_concurrency
        )
        return BrowserStateSnapshot(
            page_url=browser.current_url, is_captcha_present=detection.is_captcha_present(browser),
            network=network_profile, browser=browser_fingerprint, dom=dom_metrics,
            js_env=js_environment, evasion=evasion_profile
        )
    except Exception as e:
        logging.critical(f"A critical error occurred during state snapshot: {e}", exc_info=True)
        return None

def _display_audit_report(snapshot: BrowserStateSnapshot):
    """Logs the comprehensive audit in a clean, organized, and actionable format."""
    if not snapshot:
        logger.error("Could not generate a browser state snapshot for display.")
        return

    logger.info("====================== DIGITAL IDENTITY & ENVIRONMENT AUDIT ======================")
    logger.info(f"  URL: {snapshot.page_url}")
    logger.info(f"  [NETWORK] IP Address : {snapshot.network.ip_address} ({snapshot.network.ip_geolocation.get('city', 'N/A')}, {snapshot.network.ip_geolocation.get('country', 'N/A')})")
    logger.info(f"  [NETWORK] User Agent : {snapshot.network.user_agent}")
    logger.info(f"  [BROWSER] WebDriver Flag : {'DETECTED (FAIL)' if snapshot.browser.webdriver_flag else 'Hidden (PASS)'}")
    logger.info(f"  [BROWSER] Timestamps     : {'Consistent (PASS)' if snapshot.browser.has_consistent_timestamps else 'Inconsistent (FAIL)'}")
    logger.info(f"  [BROWSER] Fingerprint  : Screen({snapshot.browser.screen_resolution}), Plugins({snapshot.browser.plugins_count}), Fonts({snapshot.browser.font_count})")
    logger.info(f"  [DOM]     Complexity   : {snapshot.dom.iframe_count} iframes, {snapshot.dom.input_field_count} inputs, {snapshot.dom.hidden_element_count} hidden elements")
    detected_bots = ', '.join(snapshot.js_env.known_bot_detectors) if snapshot.js_env.known_bot_detectors else 'None (PASS)'
    logger.info(f"  [JS ENV]  Bot Detection: {detected_bots}")
    logger.info(f"  [JS ENV]  Console Errors : {snapshot.js_env.console_error_count}")
    logger.info(f"  [PAGE]    CAPTCHA      : {'DETECTED' if snapshot.is_captcha_present else 'Not Detected'}")
    logger.info("==================================================================================")

def audit_and_log_state(browser: BrowserInterface, context: str):
    """The main entry point for the auditing system."""
    logger.info(f"--- Performing audit at context: [{context}] ---")
    snapshot = _get_current_state(browser, settings.evasion)
    _display_audit_report(snapshot)
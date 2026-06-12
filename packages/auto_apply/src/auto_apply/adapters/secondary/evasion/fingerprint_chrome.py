"""A collection of functions to harden the fingerprint of Chromium-based browsers.

This module provides a suite of highly-specialized functions that use the
Chrome DevTools Protocol (CDP) to modify the browser's JavaScript environment
at the earliest possible moment. Each function targets a specific, known
fingerprinting vector that bot-detection scripts use to identify automated
browsers.

The core technique used is the CDP command `Page.addScriptToEvaluateOnNewDocument`,
which ensures our spoofing scripts are executed before any scripts on the
webpage, making them highly effective.
"""
import logging
import random
from typing import Literal

from selenium.webdriver.remote.webdriver import WebDriver

logger = logging.getLogger(__name__)

COMMON_WEBGL_RENDERERS = [
    "NVIDIA GeForce RTX 4090", "NVIDIA GeForce RTX 3080", "NVIDIA GeForce RTX 2060",
    "AMD Radeon RX 7900 XTX", "AMD Radeon RX 6800", "Apple M2 Pro", "Apple M1",
    "Intel(R) Iris(TM) Xe Graphics", "Intel HD Graphics 620"
]
COMMON_WEBGL_VENDORS = ["Google Inc. (NVIDIA)", "Google Inc. (AMD)", "Apple Inc.", "Google Inc. (Intel)"]  # noqa: E501

def _execute_cdp_script_on_new_document(driver: WebDriver, script: str) -> None:
    """A centralized helper to inject scripts using the Chrome DevTools Protocol.

    This function is the foundation of this module's effectiveness. It executes
    the `Page.addScriptToEvaluateOnNewDocument` command, which guarantees that
    the provided JavaScript `script` will be run in every new document (including
    iframes) before any of the page's own scripts can execute.

    Args:
        driver: The raw Selenium WebDriver for a Chromium-based browser.
        script: The JavaScript source code to inject.
    """
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})  # noqa: E501
    except Exception as e:
        logger.error(f"Failed to execute CDP script: {e}")

def remove_automation_artifacts(driver: WebDriver) -> None:
    """Removes JavaScript variables and properties that identify ChromeDriver.

    This function targets the most common and basic bot-detection checks:
    - Sets `navigator.webdriver` to `false`.
    - Deletes the `window.navigator.chrome.runtime` object.
    - Removes any `cdc_...` properties from the document object, which are
      remnants of the ChromeDriver executable.

    Args:
        driver: The raw Selenium WebDriver for a Chromium-based browser.
    """
    logger.info("Removing ChromeDriver automation artifacts (__cdc__ properties).")
    script = """
    (() => {
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        if (window.navigator.chrome) {
            delete window.navigator.chrome.runtime;
        }
        let objectToModify = window.document;
        for (const a in objectToModify) {
            if (a.includes("cdc_")) {
                delete objectToModify[a];
            }
        }
    })();
    """
    _execute_cdp_script_on_new_document(driver, script)

def spoof_webgl(driver: WebDriver, strategy: Literal["random", "custom"], vendor: str, renderer: str) -> None:  # noqa: E501
    """Spoofs the WebGL vendor and renderer strings.

    The combination of WebGL vendor and renderer is a highly unique identifier
    for a user's hardware. This function overwrites the browser's `getParameter`
    method for WebGL to return plausible, common hardware values instead of the
    real ones.

    Args:
        driver: The raw Selenium WebDriver for a Chromium-based browser.
        strategy: 'random' to pick from a list of common GPUs, or 'custom'.
        vendor: The custom vendor string to use if strategy is 'custom'.
        renderer: The custom renderer string to use if strategy is 'custom'.
    """
    if strategy == "random":
        vendor = random.choice(COMMON_WEBGL_VENDORS)
        renderer = random.choice(COMMON_WEBGL_RENDERERS)
    logger.info(f"Spoofing WebGL with Vendor: '{vendor}', Renderer: '{renderer}'")
    script = f"""
    (() => {{
        try {{
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {{
                if (parameter === 37445) return '{vendor}';
                if (parameter === 37446) return '{renderer}';
                return getParameter.apply(this, arguments);
            }};
        }} catch (e) {{}}
    }})();
    """
    _execute_cdp_script_on_new_document(driver, script)

def spoof_canvas(driver: WebDriver, strategy: Literal["noise", "random"]) -> None:
    """Defeats canvas fingerprinting by adding random noise to the image data.

    Canvas fingerprinting works by having the browser render a complex 2D graphic
    and generating a hash from the resulting image data. This function hooks into
    the `toDataURL` method and adds a tiny amount of random noise to the image
    data before it is returned, ensuring the hash is different on every run.

    Args:
        driver: The raw Selenium WebDriver for a Chromium-based browser.
        strategy: Currently only supports the 'noise' strategy.
    """
    logger.info(f"Spoofing Canvas fingerprinting with strategy: '{strategy}'")
    if strategy != "noise":
        return
    script = """
    (() => {
        const toDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function() {
            const context = this.getContext('2d');
            const imageData = context.getImageData(0, 0, this.width, this.height);
            for (let i = 0; i < imageData.data.length; i += 4) {
                const noise = Math.floor(Math.random() * 5 - 2);
                imageData.data[i] += noise;
                imageData.data[i + 1] += noise;
                imageData.data[i + 2] += noise;
            }
            context.putImageData(imageData, 0, 0);
            return toDataURL.apply(this, arguments);
        };
    })();
    """
    _execute_cdp_script_on_new_document(driver, script)

def spoof_hardware(driver: WebDriver, cores: int) -> None:
    """Injects JS to override the reported number of CPU cores.

    The `navigator.hardwareConcurrency` property reveals the number of logical
    CPU cores on the host machine. A high number can be a signal that the
    script is running on a server, not a typical user device. This function
    overwrites the property to return a more common value.

    Args:
        driver: The raw Selenium WebDriver for a Chromium-based browser.
        cores: The number of cores to report (e.g., 4, 8, 16).
    """
    logger.info(f"Spoofing hardwareConcurrency to: {cores}")
    script = f"Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {cores} }});"  # noqa: E501
    _execute_cdp_script_on_new_document(driver, script)

def spoof_timezone(driver: WebDriver, timezone: str = "America/New_York") -> None:
    """Spoofs the browser's timezone using a CDP command.

    A user's timezone can be a strong indicator of their geolocation. This
    evasion is critical when using proxies or VPNs, as it allows the browser's
    reported timezone to be aligned with the proxy's apparent location,
    avoiding a major detection inconsistency.

    Args:
        driver: The raw Selenium WebDriver for a Chromium-based browser.
        timezone: The timezone ID to set (e.g., "America/New_York", "Europe/London").
    """
    logger.info(f"Spoofing timezone to: {timezone}")
    try:
        driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": timezone})  # noqa: E501
    except Exception as e:
        logger.error(f"Failed to spoof timezone: {e}")

def harden_permissions_api(driver: WebDriver) -> None:
    """Makes the Permissions API less revealing by masking notification state.

    Websites can query the status of browser permissions (like notifications,
    geolocation, etc.). Automated browsers often have a unique, default set
    of permissions that can be used as a fingerprint. This function intercepts
    queries for 'notifications' and returns a common, generic "denied" state.

    Args:
        driver: The raw Selenium WebDriver for a Chromium-based browser.
    """
    logger.info("Hardening Permissions API (notifications).")
    script = """
    (() => {
        const originalQuery = navigator.permissions.query;
        navigator.permissions.query = (descriptor) => {
            if (descriptor.name === 'notifications') {
                return Promise.resolve({ state: 'denied', onchange: null });
            }
            return originalQuery.call(navigator.permissions, descriptor);
        };
    })();
    """
    _execute_cdp_script_on_new_document(driver, script)

def spoof_audio_context(driver: WebDriver) -> None:
    """Defeats AudioContext fingerprinting by adding random noise.

    AudioContext fingerprinting generates a unique signature by creating a
    low-frequency audio oscillator and hashing the resulting sound wave data.
    This function intercepts the process and adds a tiny amount of random
    noise to the audio buffer, which changes the final hash on every run.

    Args:
        driver: The raw Selenium WebDriver for a Chromium-based browser.
    """
    logger.info("Applying AudioContext fingerprinting defense.")
    script = """
    (() => {
        const originalGetChannelData = AudioBuffer.prototype.getChannelData;
        AudioBuffer.prototype.getChannelData = function() {
            const data = originalGetChannelData.apply(this, arguments);
            const noise = (Math.random() * 0.0001) - 0.00005;
            for (let i = 0; i < data.length; i++) {
                data[i] = data[i] + noise;
            }
            return data;
        };
    })();
    """
    _execute_cdp_script_on_new_document(driver, script)

def standardize_fonts(driver: WebDriver) -> None:
    """Defeats font fingerprinting by adding random jitter to font metrics.

    Font fingerprinting detects the unique set of fonts installed on a system
    by rendering text with a specific font and measuring its exact pixel dimensions.
    This function adds a tiny, random amount of "jitter" to the reported width
    of rendered text, making the measurements unreliable and the fingerprint unstable.

    Args:
        driver: The raw Selenium WebDriver for a Chromium-based browser.
    """
    logger.info("Applying font fingerprinting defense.")
    script = """
    (() => {
        const originalMeasureText = CanvasRenderingContext2D.prototype.measureText;
        CanvasRenderingContext2D.prototype.measureText = function(text) {
            const metrics = originalMeasureText.apply(this, arguments);
            metrics.width += (Math.random() * 0.02 - 0.01);
            return metrics;
        };
    })();
    """
    _execute_cdp_script_on_new_document(driver, script)

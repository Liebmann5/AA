"""A collection of functions to harden the fingerprint of Firefox browsers.

This module provides runtime JavaScript-based evasions specifically for Firefox.
Unlike Chromium, Firefox does not support the `Page.addScriptToEvaluateOnNewDocument`
CDP command. Therefore, the strategy is twofold:
1.  Critical evasions (like disabling `navigator.webdriver`) are set as
    `about:config` preferences in `core/browser_options.py` before the browser
    even launches.
2.  This module applies a comprehensive payload of additional JS patches at runtime
    to mask other common fingerprinting vectors.
"""
import logging

from selenium.webdriver.remote.webdriver import WebDriver

logger = logging.getLogger(__name__)

def _get_js_payload() -> str:
    """Constructs a comprehensive payload of JavaScript anti-fingerprinting patches.

    This function returns a single, large string of JavaScript code designed to
    be executed in the browser's context. Each patch targets a specific API or
    property that is commonly used by bot-detection scripts to fingerprint a
    browser. The patches overwrite these APIs to return standardized, common,
    or slightly randomized values, making the browser appear less unique and
    more like a standard user.

    Returns:
        A string containing the full JavaScript payload.
    """
    return """
    // --- Patch 1: Neutralize navigator.webdriver (The Classic) ---
    // The most basic and essential check. Overwrite the property that screams "I am automation!"
    if (navigator.webdriver) {
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
    }

    // --- Patch 2: Stabilize Screen Properties ---
    // Headless or virtualized environments often have inconsistent or unusual screen properties.
    // We enforce a common, plausible resolution (1920x1080).
    if (window.screen) {
        Object.defineProperty(window.screen, "availTop", { get: () => 0 });
        Object.defineProperty(window.screen, "availLeft", { get: () => 0 });
        Object.defineProperty(window.screen, "availWidth", { get: () => 1920 });
        Object.defineProperty(window.screen, "availHeight", { get: () => 1080 });
        Object.defineProperty(window.screen, "width", { get: () => 1920 });
        Object.defineProperty(window.screen, "height", { get: () => 1080 });
        Object.defineProperty(window.screen, "colorDepth", { get: () => 24 });
        Object.defineProperty(window.screen, "pixelDepth", { get: () => 24 });
    }

    // --- Patch 3: Mask Plugin & MimeType Enumeration ---
    // A sterile browser with no plugins is a huge red flag. We inject a plausible, common set.
    const fakePlugins = [
        { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
        { name: 'Chrome PDF Plugin', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: 'PDF Google Viewer' },
        { name: 'Native Client', filename: 'internal-nacl-plugin', description: 'Native Client' }
    ];
    const fakeMimeTypes = [
        { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
        { type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format' }
    ];
    if (navigator.plugins) { Object.defineProperty(navigator, 'plugins', { get: () => fakePlugins }); }
    if (navigator.mimeTypes) { Object.defineProperty(navigator, 'mimeTypes', { get: () => fakeMimeTypes }); }

    // --- Patch 4: Neutralize Performance Timestamps ---
    // High-resolution timestamps from performance.now() can be used to detect the precise,
    // machine-like timing of automated actions. We add random "jitter" to make it noisy.
    const originalNow = performance.now;
    let performanceDrift = Math.random() * 10;
    Object.defineProperty(window.performance, 'now', {
        get: () => () => {
            performanceDrift += Math.random() * 0.1;
            return originalNow() + performanceDrift;
        }
    });

    // --- Patch 5: Defend Against Font Fingerprinting ---
    // While we can't hide installed fonts via JS, we can disrupt the common detection
    // method: measuring the pixel width/height of rendered text. We add subtle noise.
    const originalMeasureText = CanvasRenderingContext2D.prototype.measureText;
    CanvasRenderingContext2D.prototype.measureText = function(text) {
        const metrics = originalMeasureText.apply(this, arguments);
        // Add a tiny, random fractional value.
        metrics.width += Math.random() * 0.02 - 0.01;
        return metrics;
    };

    // --- Patch 6: Mask Hardware Properties ---
    // Disclosing the exact number of CPU cores can help identify a high-end server vs. a standard user desktop.
    // We report a common value (e.g., 8).
    if (navigator.hardwareConcurrency) {
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
    }
    // Same for device memory.
    if (navigator.deviceMemory) {
        Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
    }

    // --- Patch 7: Neutralize the Battery Status API ---
    // The Battery API is a niche vector, but an easy giveaway (e.g., a "desktop" is always charging).
    // We override it to return a plausible "unplugged laptop" state.
    if (navigator.getBattery) {
        Object.defineProperty(navigator, 'getBattery', {
            get: () => () => Promise.resolve({
                charging: false,
                chargingTime: Infinity,
                dischargingTime: 3600 + Math.floor(Math.random() * 3600), // 1-2 hours remaining
                level: 0.7 + Math.random() * 0.2 // 70-90% charged
            })
        });
    }

    // --- Patch 8: Harden Permissions API ---
    // This prevents websites from detecting automation by querying permissions that are
    // often automatically denied in headless/automated environments (e.g., notifications).
    const originalPermissionsQuery = navigator.permissions.query;
    Object.defineProperty(navigator.permissions, 'query', {
        get: () => (descriptor) => {
            if (descriptor.name === 'notifications') {
                return Promise.resolve({ state: 'denied', onchange: null });
            }
            return originalPermissionsQuery.apply(navigator.permissions, arguments);
        }
    });
    """  # noqa: E501

def apply_firefox_hardening(driver: WebDriver) -> None:
    """Applies the comprehensive JavaScript payload to harden a running Firefox instance.

    This function should be called after the browser has navigated to its
    initial page. It executes the entire suite of JS patches defined in
    `_get_js_payload()` in one go, modifying the browser's runtime environment
    to resist fingerprinting.

    Args:
        driver: The raw Selenium WebDriver instance for Firefox.
    """  # noqa: E501
    logger.info("Applying multi-patch JavaScript payload for MAXIMUM Firefox elusiveness.")  # noqa: E501

    try:
        driver.execute_script(_get_js_payload())
        logger.info("Successfully applied fortress-level JavaScript evasion patches.")
    except Exception as e:
        logger.error(f"Could not apply JavaScript patches to Firefox: {e}", exc_info=True)  # noqa: E501
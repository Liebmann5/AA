"""Defines the Pydantic models for capturing a browser's state and identity.

This module contains a set of strongly-typed data models that are used to create a
comprehensive snapshot of the browser's digital fingerprint and current page
environment at a specific moment in time. This snapshot is primarily used by the
auditing system to evaluate the effectiveness of evasion techniques.
"""

import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class EvasionProfile(BaseModel):
    """A snapshot of the *intended* evasion settings for a specific run.

    This model documents the configuration that was supposed to be active,
    allowing for comparison against the actual detected state of the browser.

    Attributes:
        enable_fingerprint_spoofing: Master switch for static fingerprint mods.
        webgl_spoof_strategy: The configured strategy for WebGL spoofing.
        canvas_spoof_strategy: The configured strategy for Canvas spoofing.
        spoof_hardware_concurrency: The number of CPU cores to report.
    """
    enable_fingerprint_spoofing: bool
    webgl_spoof_strategy: str
    canvas_spoof_strategy: str
    spoof_hardware_concurrency: int | None

class NetworkProfile(BaseModel):
    """A snapshot of the browser's network-layer identity.

    Attributes:
        ip_address: The public IP address of the browser session.
        ip_geolocation: A dictionary containing location data from the IP.
        user_agent: The User-Agent string reported by the browser.
    """
    ip_address: str
    ip_geolocation: dict[str, Any] = Field(default_factory=dict)
    user_agent: str

class BrowserFingerprint(BaseModel):
    """A snapshot of the browser's JavaScript-detectable fingerprint properties.

    Attributes:
        webdriver_flag: The value of the `navigator.webdriver` flag.
        plugins_count: The number of plugins reported by `navigator.plugins`.
        screen_resolution: The screen dimensions and color depth.
        font_count: The number of fonts detected.
        has_consistent_timestamps: A flag indicating if performance timers are stable.
    """
    webdriver_flag: bool
    plugins_count: int
    screen_resolution: str
    font_count: int
    has_consistent_timestamps: bool

class DOMMetrics(BaseModel):
    """Metrics describing the structure and complexity of the current webpage's DOM.

    Attributes:
        iframe_count: The number of `<iframe>` elements on the page.
        input_field_count: The number of input, textarea, and select fields.
        hidden_element_count: The number of elements hidden via CSS or `hidden` attribute.
    """  # noqa: E501
    iframe_count: int
    input_field_count: int
    hidden_element_count: int

class JSEnvironment(BaseModel):
    """An analysis of the JavaScript environment for signs of bot detection.

    Attributes:
        known_bot_detectors: A list of names of known anti-bot vendor scripts detected.
        console_error_count: The number of errors present in the browser console.
    """
    known_bot_detectors: list[str] = Field(default_factory=list)
    console_error_count: int

class BrowserStateSnapshot(BaseModel):
    """The complete, top-level model for a digital identity and environment audit.

    This class aggregates all other models in this module to create a single,
    comprehensive snapshot object that can be passed between different domains
    of the application (e.g., from the browser core to the evasion auditor).

    Attributes:
        timestamp: An ISO 8601 formatted timestamp in UTC indicating when the
                   snapshot was taken.
        page_url: The URL of the page at the time of the snapshot.
        is_captcha_present: A boolean flag indicating if a CAPTCHA was detected.
        network: The network-layer identity profile.
        browser: The browser-layer fingerprint profile.
        dom: Metrics about the current page's DOM.
        js_env: Analysis of the JavaScript environment.
        evasion: The intended evasion settings for the run.
    """
    # Using a timezone-aware default (UTC) is a professional best practice.
    timestamp: str = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat())  # noqa: E501
    page_url: HttpUrl | None
    is_captcha_present: bool
    network: NetworkProfile
    browser: BrowserFingerprint
    dom: DOMMetrics
    js_env: JSEnvironment
    evasion: EvasionProfile

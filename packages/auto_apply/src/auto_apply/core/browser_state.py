import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, HttpUrl, Field

class EvasionProfile(BaseModel):
    """A snapshot of the *intended* evasion settings for this run."""
    enable_fingerprint_spoofing: bool
    webgl_spoof_strategy: str
    canvas_spoof_strategy: str
    spoof_hardware_concurrency: Optional[int]

class NetworkProfile(BaseModel):
    """A snapshot of the Network-Layer identity."""
    ip_address: str
    ip_geolocation: Dict[str, Any] = Field(default_factory=dict)
    user_agent: str

class BrowserFingerprint(BaseModel):
    """A snapshot of the Browser-Layer identity."""
    webdriver_flag: bool
    plugins_count: int
    screen_resolution: str
    font_count: int
    has_consistent_timestamps: bool

class DOMMetrics(BaseModel):
    """Metrics about the structure and complexity of the current page."""
    iframe_count: int
    input_field_count: int
    hidden_element_count: int

class JSEnvironment(BaseModel):
    """Analysis of the JavaScript environment for known anti-bot vendors."""
    known_bot_detectors: List[str] = Field(default_factory=list)
    console_error_count: int

class BrowserStateSnapshot(BaseModel):
    """The complete, professional-grade digital identity and environment audit."""
    timestamp: str = Field(default_factory=lambda: datetime.datetime.now().isoformat())
    page_url: Optional[HttpUrl]
    is_captcha_present: bool
    network: NetworkProfile
    browser: BrowserFingerprint
    dom: DOMMetrics
    js_env: JSEnvironment
    evasion: EvasionProfile
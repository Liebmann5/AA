"""
Defines the application's runtime configuration settings.

This module uses Pydantic's BaseSettings to create a strongly-typed,
validated configuration object. It centralizes all non-secret,
application-wide parameters, making them easy to manage and modify.

The 'settings' object is a singleton instance that can be imported
by any other module in the application to access configuration values.
"""
from pydantic import BaseModel, BaseSettings, Field
from typing import Literal, Optional, List

class ScrapingSettings(BaseModel):
    """Configuration specific to web scraping operations."""
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
    )
    default_timeout: int = 20
    retry_attempts: int = 3
    max_search_results: int = 500

WebGLSpoofStrategy = Literal["random", "custom", "off"]
CanvasSpoofStrategy = Literal["noise", "random", "off"]

class EvasionSettings(BaseModel):
    """
    The central control panel for all anti-bot-detection and evasion techniques.
    """
    enable_fingerprint_spoofing: bool = Field(
        True, description="Master switch for all static fingerprint modifications."
    )

    webgl_spoof_strategy: WebGLSpoofStrategy = Field(
        "random", description="'random': pick a common GPU on each run. 'custom': use the values below. 'off': do nothing."
    )
    custom_webgl_vendor: str = Field(
        "NVIDIA Corporation", description="Custom WebGL vendor to use if strategy is 'custom'."
    )
    custom_webgl_renderer: str = Field(
        "NVIDIA GeForce RTX 3080", description="Custom WebGL renderer to use if strategy is 'custom'."
    )

    canvas_spoof_strategy: CanvasSpoofStrategy = Field(
        "noise", description="'noise': add random noise to the canvas image. 'random': generate a new random image. 'off': do nothing."
    )

    spoof_hardware_concurrency: Optional[int] = Field(
        8, description="Number of CPU cores to report (e.g., 4, 8, 16). 'None' uses the real value."
    )

    standardize_fonts: bool = Field(
        True, description="If true, presents a common list of fonts instead of the system's actual list."
    )

    enable_behavior_humanization: bool = Field(
        True, description="Master switch for mimicking human-like actions (mouse, typing, delays)."
    )

    min_navigation_delay_seconds: float = Field(2.0, description="Minimum random delay between page loads.")
    max_navigation_delay_seconds: float = Field(5.0, description="Maximum random delay between page loads.")

    enable_idle_jitter: bool = Field(
        True, description="Allow the script to pause and perform small, random mouse movements."
    )

    enable_session_warming: bool = Field(
        False, description="If true, visits generic sites like google.com before the target to gather cookies. Slower but stealthier."
    )

    session_warmup_urls: List[str] = Field(
        default_factory=lambda: ["https://www.google.com/search?q=news", "https://www.bing.com"],
        description="A list of URLs to visit during the session warming phase."
    )

    set_random_referrer: bool = Field(
        True, description="Send a 'Referer' header to make navigation look like it came from another page."
    )

    enable_captcha_detection: bool = Field(
        True, description="If true, the scraper will check for common CAPTCHA elements on each page."
    )

    on_captcha_detected: Literal["retry", "skip", "stop"] = Field(
        "retry", description="'retry': get a new proxy/session and try again. 'skip': abandon this task and move to the next. 'stop': end the entire run."
    )

    max_retries_on_captcha: int = Field(
        3, description="Maximum number of times to retry a task if a CAPTCHA is detected."
    )

class AppSettings(BaseSettings):
    """The main application settings model."""
    form_field_synonyms: dict[str, list[str]] = {
        "first_name": ["first name", "given name", "forename"],
        "last_name": ["last name", "surname", "family name"],
        "email": ["email", "email address"],
        "phone": ["phone", "phone number", "mobile number", "cellphone"],
        "resume": ["resume", "cv", "curriculum vitae", "upload resume"],
    }

    scraping: ScrapingSettings = ScrapingSettings()
    evasion: EvasionSettings = EvasionSettings()

    class Config:
        case_sensitive = False

settings = AppSettings()
"""Defines primitive types, enumerations, and constants used across the application.

This module consolidates all static definitions to prevent circular imports
and provide a single source of truth for "Magic Values" like keys and page types.
"""

from enum import Enum, auto


class PageType(Enum):
    """Enumeration of recognized webpage states."""
    UNKNOWN = auto()
    SERP = auto()                # Search Results Page (Google/Bing/LinkedIn Jobs)
    JOB_DESCRIPTION = auto()     # The detailed view of a job
    APPLICATION_FORM = auto()    # The actual form to fill
    LOGIN_REQUIRED = auto()      # Auth wall / Login screen
    CAPTCHA_BLOCK = auto()       # Hard block / Cloudflare / CAPTCHA
    ERROR_404 = auto()           # HTTP 404 or generic "Not Found"
    SUCCESS_PAGE = auto()        # "Thank you for applying" confirmation

class JobStatus(Enum):
    """Enumeration for the status of a job in the application workflow."""
    FOUND = "found"
    VETTED = "vetted"
    REJECTED = "rejected"
    APPLICATION_IN_PROGRESS = "application_in_progress"
    APPLICATION_COMPLETED = "application_completed"
    APPLICATION_FAILED = "application_failed"

class Keys:
    """Platform-agnostic constants for keyboard interaction."""
    ENTER = "KEY_ENTER"
    RETURN = "KEY_RETURN"
    TAB = "KEY_TAB"
    ARROW_DOWN = "KEY_ARROW_DOWN"
    ARROW_UP = "KEY_ARROW_UP"
    ESCAPE = "KEY_ESCAPE"
    BACKSPACE = "KEY_BACKSPACE"
    SPACE = "KEY_SPACE"

class Locator:
    """Platform-agnostic constants for element location strategies."""
    ID = "id"
    XPATH = "xpath"
    LINK_TEXT = "link text"
    PARTIAL_LINK_TEXT = "partial link text"
    NAME = "name"
    TAG_NAME = "tag name"
    CLASS_NAME = "class name"
    CSS_SELECTOR = "css selector"

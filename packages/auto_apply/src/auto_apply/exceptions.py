"""
Defines custom exceptions for the application.

Using custom exceptions makes error handling more specific and clear.
Instead of catching a generic Exception, we can catch a more precise
ProfileConfigurationError, for example.
"""

class ApplicationError(Exception):
    """Base class for all custom exceptions in this application."""
    pass


class ProfileConfigurationError(ApplicationError):
    """Raised when there is an error loading or validating a user profile."""
    pass


class BrowserSetupError(ApplicationError):
    """Raised when no available browser can be set up."""
    pass


class ScrapingError(ApplicationError):
    """A generic error during the scraping phase."""
    pass


class HeuristicAnalysisError(ScrapingError):
    """Raised when the heuristic engine fails to find a target container."""
    pass


class CaptchaChallengeException(ScrapingError):
    """
    Raised specifically when a CAPTCHA is detected and cannot be solved,
    allowing the workflow to handle it gracefully.
    """
    pass
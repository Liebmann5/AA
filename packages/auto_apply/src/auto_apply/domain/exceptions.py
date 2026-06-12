"""Defines the custom exception hierarchy for the application.

Using specific exceptions allows the Agent to handle errors gracefully (e.g.,
retrying on a NetworkError vs. stopping on a ConfigurationError).
"""

class AutoApplyException(Exception):
    """Base class for all custom exceptions in the application."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)

class InfrastructureError(AutoApplyException):
    """Base class for errors in the Infrastructure layer (Drivers, I/O)."""
    pass

class BrowserInitError(InfrastructureError):
    """Raised when the browser fails to launch."""
    pass

class NetworkError(InfrastructureError):
    """Raised when internet connectivity is lost or a request fails."""
    pass

class ScrapingError(AutoApplyException):
    """Raised when the bot cannot interpret the webpage content."""
    pass

class CaptchaChallengeError(ScrapingError):
    """Raised when a bot detection challenge blocks execution."""
    pass

class LogicError(AutoApplyException):
    """Raised when the application reaches an impossible logical state."""
    pass












#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# COMMENTED OUT |  COMMENTED OUT |  COMMENTED OUT |  COMMENTED OUT |  COMMENTED OUT |
"""
Defines custom exceptions for the application.

Using custom exceptions makes error handling more specific and clear.
Instead of catching a generic Exception, we can catch a more precise
ProfileConfigurationError, for example.
"""

class AutoApplyException(Exception):
    """Base class for all custom exceptions in the AutoApply application.

    This exception should not be raised directly. Instead, subclass it to create
    more specific exceptions for different error conditions.

    Args:
        message (str): A clear and descriptive error message.
    """
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)

    def __str__(self) -> str:
        """Returns the string representation of the exception."""
        return f'{self.__class__.__name__}: {self.message}'


class BrowserException(AutoApplyException):
    """Raised for errors related to browser automation and management.

    This serves as a base class for more specific browser-related errors,
    such as driver setup failures or interaction timeouts.

    Args:
        message (str): The description of the browser-related error.
    """
    pass


class WebDriverError(BrowserException):
    """Raised when a WebDriver operation fails.

    This can occur if the WebDriver executable is not found, is incompatible
    with the browser version, or fails to initialize.

    Args:
        message (str): The description of the WebDriver error.
    """
    pass


class PlaywrightManagerError(BrowserException):
    """Raised for errors during Playwright browser management.

    This includes failures during the installation, update, or lookup of
    Playwright browser binaries.

    Args:
        message (str): The description of the Playwright manager error.
    """
    pass


class ConfigurationError(AutoApplyException):
    """Raised for errors related to application configuration.

    This includes issues like a missing, malformed, or invalid user profile
    or settings file.

    Args:
        message (str): The description of the configuration error.
    """
    pass


class ProfileNotFoundError(ConfigurationError):
    """Raised when the user profile file cannot be found.

    This is a specific type of configuration error that indicates the
    'profile.json' file is missing from its expected location.

    Args:
        path (str): The file path where the profile was expected.
    """
    def __init__(self, path: str):
        super().__init__(f"User profile not found at the specified path: {path}")


class DataManagementError(AutoApplyException):
    """Raised for errors related to data persistence and management.

    This includes issues with reading from or writing to data files like
    the job state or applied jobs logs.

    Args:
        message (str): The description of the data management error.
    """
    pass


class EvasionError(AutoApplyException):
    """Raised for errors within the anti-bot detection evasion framework.

    This can occur if an evasion technique fails or if a CAPTCHA cannot
    be solved.

    Args:
        message (str): The description of the evasion-related error.
    """
    pass


class JobDiscoveryError(AutoApplyException):
    """Raised for errors that occur during the job discovery phase.

    This includes failures in scraping job boards or parsing search results.

    Args:
        message (str): The description of the job discovery error.
    """
    pass


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

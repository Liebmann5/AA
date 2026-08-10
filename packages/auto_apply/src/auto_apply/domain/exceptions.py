"""Defines the custom exception hierarchy for the application.

Single-root hierarchy. R-9/S8j: this module previously defined
AutoApplyException and ScrapingError TWICE, with divergent hierarchies.
The second definitions silently won at import time, and CaptchaChallengeError
inherited from an orphaned first-block ScrapingError object — so a future
``except ScrapingError`` would never have caught it. The duplicates are gone.

The two ScrapingError families were renamed to describe what their
docstrings actually said (neither keeps the ambiguous name, per R-9):

    PageInterpretationError  — the bot cannot interpret the webpage content.
    ExtractionPhaseError     — a generic failure during the scraping phase.

Using specific exceptions allows the Agent to handle errors gracefully
(e.g., retrying on a NetworkError vs. stopping on a ConfigurationError).
"""


class AutoApplyException(Exception):
    """Base class for all custom exceptions in the AutoApply application.

    This exception should not be raised directly. Instead, subclass it to
    create more specific exceptions for different error conditions.

    Args:
        message (str): A clear and descriptive error message.
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)

    def __str__(self) -> str:
        """Returns the string representation of the exception."""
        return f"{self.__class__.__name__}: {self.message}"


# ── Infrastructure layer (drivers, I/O) ─────────────────────────────────────


class InfrastructureError(AutoApplyException):
    """Base class for errors in the Infrastructure layer (Drivers, I/O)."""
    pass


class BrowserInitError(InfrastructureError):
    """Raised when the browser fails to launch."""
    pass


class NetworkError(InfrastructureError):
    """Raised when internet connectivity is lost or a request fails."""
    pass


# ── Browser automation management ───────────────────────────────────────────


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


# ── Configuration & data ────────────────────────────────────────────────────


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
        super().__init__(
            f"User profile not found at the specified path: {path}"
        )


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


class LogicError(AutoApplyException):
    """Raised when the application reaches an impossible logical state."""
    pass


# ── Application runtime (separate root — preserved deliberately) ────────────


class ApplicationError(Exception):
    """Base class for runtime workflow errors (form filling, navigation).

    Deliberately NOT under AutoApplyException: it predates that hierarchy,
    is raised by the interaction and application paths, and nothing catches
    it via AutoApplyException today. Moving it would change live catch
    semantics — out of scope for R-9.
    """
    pass


class ProfileConfigurationError(ApplicationError):
    """Raised when there is an error loading or validating a user profile."""
    pass


class BrowserSetupError(ApplicationError):
    """Raised when no available browser can be set up."""
    pass


# ── Page interpretation & extraction (the renamed ScrapingError families) ───


class PageInterpretationError(AutoApplyException):
    """Raised when the bot cannot interpret the webpage content.

    Formerly the first-block ``ScrapingError`` (AutoApplyException
    hierarchy). Renamed per R-9 — neither duplicate keeps the ambiguous name.
    """
    pass


class CaptchaChallengeError(PageInterpretationError):
    """Raised when a bot detection challenge blocks page interpretation.

    Re-parented: it previously inherited from the orphaned first-block
    ScrapingError object, which no except clause could ever reach by name.
    """
    pass


class ExtractionPhaseError(ApplicationError):
    """A generic error during the scraping/extraction phase.

    Formerly the second-block ``ScrapingError`` (ApplicationError
    hierarchy). Renamed per R-9 — neither duplicate keeps the ambiguous name.
    """
    pass


class HeuristicAnalysisError(ExtractionPhaseError):
    """Raised when the heuristic engine fails to find a target container."""
    pass


class CaptchaChallengeException(ExtractionPhaseError):
    """Raised when a CAPTCHA is detected and cannot be solved, allowing the
    workflow to handle it gracefully."""
    pass

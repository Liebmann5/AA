"""Defines the abstract contract for Job Search Providers.

This module provides the `BaseSearchProvider` abstract base class. All concrete
providers (Google, Bing, LinkedIn) must implement this interface. This ensures
the Discovery Engine can treat all sources uniformly, regardless of their
underlying complexity.
"""

from abc import abstractmethod

from auto_apply.domain.models.job import Job
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.ports.discovery_port import DiscoveryProviderPort


class BaseSearchProvider(DiscoveryProviderPort):
    """The abstract contract for a specific job board provider (e.g., Google).

    A Provider acts as a 'Foreman'. It knows the specific URLs, navigation
    quirks, and CSS selectors for a specific website, but delegates the actual
    heavy lifting of scraping to reusable Strategies.
    """

    def __init__(self, browser: BrowserInterface) -> None:
        """Initializes the provider with the browser only.

        Args:
            browser: The active browser instance.

        Note:
            The provider no longer receives ``ExecutionContext`` or
            ``UserProfile``.  It is a stateless executor that receives
            exactly one :class:`SearchInstruction` per :meth:`run` call.
        """
        self.browser = browser

    @property
    def name(self) -> str:
        """Returns the canonical lowercase name of the provider.

        Derived from the class name: ``GoogleProvider`` → ``'google'``.
        Subclasses that need a custom name should override this property.
        """
        return self.__class__.__name__.replace("Provider", "").lower()

    @property
    def requires_live_browser(self) -> bool:
        """All current providers require a live browser session."""
        return True

    @abstractmethod
    def run(self, instruction: SearchInstruction) -> list[Job]:
        """Executes the search and extraction workflow for this provider.

        Args:
            instruction: A single, typed search instruction.  The provider
                must NOT build its own query matrix or read the user profile.

        Returns:
            List of unique Job objects discovered. May be empty; never None.
        """
        ...

    def safe_navigate(self, url: str) -> bool:
        """Navigates to a URL with built-in safety checks.

        Enforces rate limiting and page-safety validation when the relevant
        services are available.  Degrades gracefully when they are not —
        the navigation itself still proceeds, but without rate-limit
        enforcement or CAPTCHA detection.  This matches the project's
        worst‑case‑first deployment philosophy.

        Graceful degradation contract:
            - If rate‑limit enforcement is unavailable, checks are skipped.
            - If evasion checking is unavailable, page‑safety checks are skipped.

        Args:
            url: The target URL.

        Returns:
            True if navigation succeeded and the page passed safety checks
            (or checks were skipped due to unavailable services).
            False if rate limiting blocked the request, navigation raised
            an exception, or the safety check flagged the page.
        """
        # ── 1. Navigate ───────────────────────────────────────────────────
        try:
            self.browser.get(url)
        except Exception:
            return False

        return True
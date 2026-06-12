"""Defines the abstract contract for Job Search Providers.

This module provides the `BaseSearchProvider` abstract base class. All concrete
providers (Google, Bing, LinkedIn) must implement this interface. This ensures
the Discovery Engine can treat all sources uniformly, regardless of their
underlying complexity.

Refactoring Note:
    Providers are now 'Pure Logic' components. They receive an active
    BrowserInterface via dependency injection and must NOT close it.
"""

from abc import abstractmethod
from typing import Any

from auto_apply.application.agent.context import ExecutionContext
from auto_apply.domain.models.job import Job
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.ports.discovery_port import DiscoveryProviderPort


class BaseSearchProvider(DiscoveryProviderPort):
    """The abstract contract for a specific job board provider (e.g., Google).

    A Provider acts as a 'Foreman'. It knows the specific URLs, navigation
    quirks, and CSS selectors for a specific website, but delegates the actual
    heavy lifting of scraping to reusable Strategies.
    """

    def __init__(self, browser: BrowserInterface, context: ExecutionContext):
        """Initializes the provider with the shared context.

        Args:
            browser: The active browser instance.
            context: The shared session state (UserProfile + RuntimeProfile).
        """
        self.browser = browser
        self.context = context

        # Expose search preferences directly so subclasses can write
        # ``self.prefs.desired_job_titles`` instead of the full navigation
        # chain ``self.context.profile.search_preferences.desired_job_titles``.
        self.prefs = getattr(
            getattr(context, "profile", None), "search_preferences", None
        )

        # Rate limiter — controls per-domain request cadence.
        # Initialized to None for graceful degradation on low-resource
        # environments where the evasion infrastructure may not be present.
        # Assign a concrete DomainThrottler instance here or in a subclass
        # __init__ when available. See adapters/secondary/evasion/throttler.py.
        self.throttler: Any | None = None

        # Page safety checker — detects CAPTCHAs and bot-detection walls.
        # Same graceful-degradation contract as throttler above.
        # See adapters/secondary/evasion/detection.py.
        self.evasion: Any | None = None

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
    def run(self, override_criteria: dict | None = None) -> list[Job]:
        """Executes the search and extraction workflow for this provider.

        Args:
            override_criteria: Optional search parameters that supersede
                provider defaults. Recognised keys: ``'query'``, ``'location'``.

        Returns:
            List of unique Job objects discovered. May be empty; never None.
        """
        ...

    def safe_navigate(self, url: str) -> bool:
        """Navigates to a URL with built-in safety checks.

        Enforces rate limiting and page-safety validation when the relevant
        services are available. Degrades gracefully when they are not — the
        navigation itself still proceeds, but without rate-limit enforcement
        or CAPTCHA detection. This matches the project's worst-case-first
        deployment philosophy.

        Graceful degradation contract:
            - If ``self.throttler`` is None, rate-limit checks are skipped.
            - If ``self.evasion`` is None, page-safety checks are skipped.

        Args:
            url: The target URL.

        Returns:
            True if navigation succeeded and the page passed safety checks
            (or checks were skipped due to unavailable services).
            False if rate limiting blocked the request, navigation raised
            an exception, or the safety check flagged the page.
        """
        # ── 1. Rate limiting ──────────────────────────────────────────────
        # Skip gracefully when throttler is not wired. Providers on
        # low-resource environments may not have evasion infrastructure.
        if self.throttler is not None:
            if not self.throttler.is_allowed(url):
                return False
            self.throttler.wait_for_domain(url)

        # ── 2. Navigate ───────────────────────────────────────────────────
        try:
            self.browser.get(url)
        except Exception:
            return False

        # ── 3. Page safety check ──────────────────────────────────────────
        # Skip gracefully when evasion checker is not wired.
        if self.evasion is not None and not self.evasion.check_page_safety():
            return False

        return True
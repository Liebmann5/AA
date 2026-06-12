"""Defines the abstract interface for job discovery providers.

This port decouples the DiscoveryEngine (application layer) from any specific
search engine or job board implementation. Each provider (Google, Bing, Indeed,
LinkedIn, etc.) implements DiscoveryProviderPort, allowing the engine to run
whichever providers are available and injected at runtime.

Why This Port Exists:
    Before this port, DiscoveryEngine directly imported and instantiated
    GoogleProvider and BingProvider — an application-layer violation. The engine
    must not know which providers exist. Infrastructure's composition_root.py
    builds the provider list and injects it into the engine.

Graceful Degradation:
    The application layer calls run() on whatever providers it receives. If a
    provider requires a live browser and none is available, the infrastructure
    layer can simply not include that provider in the injected list. The engine
    degrades automatically without any conditional branching in application code.
"""

from abc import ABC, abstractmethod

from auto_apply.domain.models.job import Job


class DiscoveryProviderPort(ABC):
    """Abstract contract for a single job discovery provider.

    A provider represents one source of job listings — a search engine SERP,
    a job board, a company careers page parser, etc. Each provider is responsible
    for querying its source and returning a list of discovered Job objects.

    Adapters that implement this port live in:
        adapters/secondary/discovery/providers/

    Implementations:
        - GoogleProvider (adapters/secondary/discovery/providers/google.py)
        - BingProvider   (adapters/secondary/discovery/providers/bing.py)
        - IndeedProvider (adapters/secondary/discovery/providers/indeed.py)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The canonical name of this provider (e.g. ``'google'``, ``'bing'``).

        Used for logging and audit trails. Must be lowercase with no spaces.

        Returns:
            A short, lowercase string that uniquely identifies the provider.
        """
        ...

    @property
    @abstractmethod
    def requires_live_browser(self) -> bool:
        """Whether this provider needs a live browser session to operate.

        Providers that use plain HTTP fetching (e.g. a simple RSS reader)
        should return ``False``, allowing them to work in low-resource
        environments where no browser can be launched.

        The infrastructure layer uses this flag when building the provider list
        to exclude browser-dependent providers when only static fetch is
        available.

        Returns:
            ``True`` if a live browser must be available before calling
            :meth:`run`; ``False`` otherwise.
        """
        ...

    @abstractmethod
    def run(self, override_criteria: dict | None = None) -> list[Job]:
        """Execute a job search and return the discovered jobs.

        Implementations must be resilient: if the provider fails for any
        reason, it should return an empty list rather than propagate
        exceptions. The DiscoveryEngine provides an additional outer
        try-except safety net, but providers should not rely on it.

        Args:
            override_criteria: Optional mapping of search parameters that
                supersede the provider's defaults. Recognised keys:

                - ``'query'``: str — job title or search phrase.
                - ``'location'``: str — city, state, or ``'Remote'``.

                Pass ``None`` to use the criteria from the ``UserProfile``
                the provider was initialised with.

        Returns:
            A list of :class:`~auto_apply.domain.models.job.Job` instances
            found during this pass. May be empty; never ``None``.

        Example:
            >>> criteria = {"query": "Python Engineer", "location": "Remote"}
            >>> jobs = provider.run(override_criteria=criteria)
            >>> print(len(jobs), "jobs found from", provider.name)
        """
        ...

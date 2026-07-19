"""Defines the abstract interface for job discovery providers.

This port decouples DiscoveryWorkflow (application layer) from any specific
search engine or job board implementation.  Each provider (Google, Bing,
Indeed, etc.) implements DiscoveryProviderPort, allowing the engine to run
whichever providers are available and injected at runtime.

Why This Port Exists:
    Before this port, DiscoveryWorkflow directly imported and instantiated
    GoogleProvider and BingProvider — an application‑layer violation.  The
    engine must not know which providers exist.  Infrastructure's
    composition_root.py builds the provider list and injects it.

Graceful Degradation:
    The application layer calls ``run()`` on whatever providers it receives.
    If a provider requires a live browser and none is available, the
    infrastructure layer simply does not include that provider in the
    injected list.  The engine degrades automatically without any
    conditional branching in application code.

SearchInstruction Contract (v2):
    Each call to ``run()`` receives exactly one :class:`SearchInstruction`.
    The provider is a pure executor — it must NOT read the user profile to
    build its own search matrix.  Query resolution is the exclusive
    responsibility of :class:`DiscoveryWorkflow`.
"""

from abc import ABC, abstractmethod

from auto_apply.domain.models.job import Job
from auto_apply.domain.models.search_instruction import SearchInstruction


class DiscoveryProviderPort(ABC):
    """Abstract contract for a single job discovery provider.

    A provider represents one source of job listings — a search engine SERP,
    a job board, a company careers page parser, etc.  Each provider is
    responsible for executing a single search instruction and returning the
    discovered :class:`Job` objects.

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

        Used for logging and audit trails.  Must be lowercase with no spaces.

        Returns:
            A short, lowercase string that uniquely identifies the provider.
        """
        ...

    @property
    @abstractmethod
    def requires_live_browser(self) -> bool:
        """Whether this provider needs a live browser session to operate.

        Providers that use plain HTTP fetching (e.g. a simple RSS reader)
        should return ``False``, allowing them to work in low‑resource
        environments where no browser can be launched.

        The infrastructure layer uses this flag when building the provider
        list to exclude browser‑dependent providers when only static fetch
        is available.

        Returns:
            ``True`` if a live browser must be available before calling
            :meth:`run`; ``False`` otherwise.
        """
        ...

    @abstractmethod
    def run(self, instruction: SearchInstruction) -> list[Job]:
        """Execute a single search and return the discovered jobs.

        The provider receives exactly one :class:`SearchInstruction`.  It
        must NOT read the user profile or build its own query matrix —
        that is the workflow's responsibility.  The provider is a pure
        executor.

        Implementations must be resilient: if the provider fails for any
        reason, it should return an empty list rather than propagate
        exceptions.  DiscoveryWorkflow provides an additional outer
        try‑except safety net, but providers should not rely on it.

        Args:
            instruction: A single search instruction with title, location,
                workplace type, and optional ``raw_query_string`` and
                ``date_range``.

        Returns:
            A list of :class:`~auto_apply.domain.models.job.Job` instances
            found during this pass.  May be empty; never ``None``.

        Example:
            >>> from auto_apply.domain.models.search_instruction import SearchInstruction
            >>> instr = SearchInstruction(title="Python Engineer", location="Remote")
            >>> jobs = provider.run(instr)
            >>> print(len(jobs), "jobs found from", provider.name)
        """
        ...
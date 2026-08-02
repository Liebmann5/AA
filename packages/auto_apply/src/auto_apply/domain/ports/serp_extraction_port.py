"""Contract for turning the currently-loaded SERP into job listings.

One method, deliberately. ``GenericSERPStrategy``'s harvest loop calls exactly
``mine_jobs(source_name=...)`` and nothing else, so the port is that call and
no more — the same shape the S5a observer port took.

Implementations shipped:

``SemanticMiner``
    Walks the live DOM through WebDriver: every candidate container, then every
    child, then a size probe, then a cascade of CSS selector attempts. Measured
    on a live Google SERP at roughly 150 WebDriver round trips per second with
    a ~6 ms median round trip — thousands of round trips per harvest. Correct,
    exercised for years, and slow.

``PageUnderstandingExtractor``
    Delegates to a :class:`PageUnderstandingPort`, whose math adapter walks the
    whole DOM in a single ``execute_script``. Measured cost of that class of
    script on the same page: 4.5 ms median, 13-32 ms for a whole-page read.

``FallbackSerpExtractor``
    Composes the two. It does not replace the miner; it tries the fast path
    once and falls back to the miner for the rest of the page if the fast path
    raises or returns nothing.

Why a Protocol rather than a base class: ``SemanticMiner`` already has exactly
this method with exactly this signature, so it satisfies the port with no
changes, no wrapper, and no adapter shim. The type checker sees the contract;
the runtime object is the same object discovery has always used.
"""

from typing import Protocol, runtime_checkable

from auto_apply.domain.models.job import Job


@runtime_checkable
class SerpExtractionPort(Protocol):
    """Extracts job listings from whatever page the browser is showing."""

    def mine_jobs(self, source_name: str) -> list[Job]:
        """Return the job listings currently visible on the page.

        Implementations must not raise: discovery degrading to an empty harvest
        beats discovery dying. An empty list is a valid answer and means "no
        listings found here", not "something went wrong".

        Args:
            source_name: Provider tag stamped onto each :class:`Job` as its
                ``source`` (e.g. ``"Google"``), and used in audit records.

        Returns:
            Job listings found on the current page. May be empty.
        """
        ...

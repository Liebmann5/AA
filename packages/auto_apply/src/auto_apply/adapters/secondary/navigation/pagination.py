# RELOCATED from application/services/navigation/pagination.py (2026-08-07).
#
# This module drives a live browser through BrowserInterface / InteractionPort
# and returns domain types. It imports nothing from the application layer and
# never has. It was filed under application/services/ but is a secondary
# adapter by every structural test: discovery strategies — themselves secondary
# adapters — need it, and importing it across the layer boundary was flagged by
# tests/test_architecture.py::test_hexagonal_import_boundaries.
#
# Moved rather than wrapped in a port. Injecting it would have added a
# constructor parameter threaded through composition_root -> provider ->
# strategy with a Null default, and a Null default here means cookie banners
# silently stop being dismissed on live discovery — a wired-but-not-connected
# failure of exactly the kind this codebase already has eleven of. Relocation
# fixes the same violation with no behaviour change and nothing new to wire.
#
# No back-compat shim is left at the old path on purpose: a re-export in
# application/services/ would import from adapters/ and reintroduce the
# violation in the opposite direction.

"""The feed-scroll strategy, kept; the click strategies are retired (call 3).

KeywordPagination, ArrowPagination, NumberedPagination and PaginationHandler
were removed here: they matched English words ('next', 'more', 'continue'),
clicked the LAST match, verified nothing, and one shared NumberedPagination
leaked its page counter across queries and providers. Verified page advance
now lives in adapters/secondary/navigation/page_advancer.py — one stateless
advancer per query, advancing by a verified ladder.

InfiniteScrollStrategy stays: the composition root injects it as the
discovery loop's scroll collaborator (its next_page() delegates to the
interaction tool's measured scroll_to_bottom).
"""


import logging
from typing import Any
from abc import ABC, abstractmethod

from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.ports.interaction_port import InteractionPort

logger = logging.getLogger(__name__)

class PaginationStrategy(ABC):
    """The abstract base class (contract) for all pagination strategies."""

    def __init__(
        self,
        browser: BrowserInterface,
        interactor: InteractionPort | None = None,
        scroller=None,
    ):
        """Initializes the pagination strategy.

        Args:
            browser: The framework-agnostic browser adapter instance.
            interactor: Port for human-like interaction and pacing. Optional for
                        scroll-based strategies that operate entirely via JavaScript
                        and do not click DOM elements.
            scroller: The interaction tool's feed-scroll primitive. All settle
                        timing lives there (infinite_scroll_settle_s); this
                        strategy carries no timing of its own.
        """
        self.browser = browser
        # Annotated Any: every use is inside a try/except that already treats
        # a missing interactor as "this strategy cannot advance the page".
        self._interactor: Any = interactor
        self._scroller = scroller

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def next_page(self) -> bool:
        """Attempts to navigate to the next page of results.

        Returns:
            bool: True if navigation was triggered successfully.
                  False if the end of the list was reached or navigation failed.
        """
        ...

class InfiniteScrollStrategy(PaginationStrategy):
    """
    Handles 'Endless Scroll' pages (LinkedIn Feed, Google Jobs Widget).
    It scrolls down and checks if the DOM height increased.
    """

    def next_page(self) -> bool:
        """
        Scrolls down and waits to see if new content loads.
        Returns:
            True if the page grew (new content loaded).
            False if we hit the bottom, nothing happened, or no scroller is
            wired.

        The raw ``window.scrollTo`` fallback is retired (call 2): the
        composition root always injects the interaction tool as the
        scroller, and a second scroll implementation is exactly the
        duplication the tool removed. No scroller is an honest False, not
        a teleport.
        """
        if self._scroller is not None:
            # One implementation of 'scroll and see if the page grew'.
            return self._scroller.scroll_to_bottom()

        logger.debug(
            "%s: no scroller injected — cannot scroll; reporting end of feed",
            self.name,
        )
        return False


"""Contract for clearing whatever is standing between a page and its content.

Cookie banners, consent walls, interstitials, "continue" gates. Discovery
strategies (``serp_strategy``, ``navigators``) call this once per navigation
and ignore the result; they were importing the concrete
``adapters.secondary.navigation.interruption.InterruptionHandler``, an
adapter reaching up into application.

Same mechanic as the other tool ports: name the one-method surface in the
domain, inject the implementation from the composition root, and never
construct the concrete class adapter-side.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class InterruptionHandlerPort(Protocol):
    """Dismisses page-level interruptions that block content."""

    def handle_interruptions(self) -> None:
        """Detect and dismiss any interruption currently on the page."""
        ...


class NullInterruptionHandler:
    """Does nothing, silently.

    The default when no handler is injected. A strategy that cannot dismiss a
    cookie banner should still attempt extraction — it may find nothing, and
    that is a visible, diagnosable outcome. Raising here would turn a missing
    optional collaborator into a dead provider.
    """

    def handle_interruptions(self) -> None:
        """No-op."""
        return None

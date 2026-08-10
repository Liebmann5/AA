"""Publish-only contract for components that emit events but never consume them.

Why this exists
---------------
``BrowserHealthMonitor`` and ``NetworkMonitor`` are secondary adapters that
report what they observe. Both documented the rule already —
"communicates exclusively through the EventBus, NEVER touches the orchestrator
directly" — but both imported the concrete ``EventBus`` from the application
layer to say so in a type annotation, which is an adapter reaching up into
application in the one place the architecture test can see it.

The surface they actually use is one method. Naming that surface here lets the
annotation point down at the domain instead of up at a concrete collaborator,
and it states the asymmetry in the type: a monitor can publish and cannot
subscribe. ``EventBus`` satisfies this structurally; nothing had to change on
its side.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from auto_apply.domain.events import Event


@runtime_checkable
class EventPublisherPort(Protocol):
    """Anything that can publish a domain event.

    Deliberately does NOT expose ``subscribe``. A component typed against this
    port cannot grow a subscription without first widening its declared
    dependency, which is the point.
    """

    def publish(self, event: Event, payload: Any = None) -> None:
        """Deliver an event to all registered subscribers."""
        ...


class NullEventPublisher:
    """Discards every event. For tests and for degraded startup paths.

    A monitor constructed without a bus should stay silent rather than raise:
    losing health telemetry is a smaller failure than crashing the thing being
    monitored.
    """

    def publish(self, event: Event, payload: Any = None) -> None:
        """Accept and drop the event."""
        return None

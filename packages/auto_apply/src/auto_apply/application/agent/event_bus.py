"""Thread-safe publish-subscribe event bus for inter-component communication.

This module provides the EventBus class, which is the backbone of AA's
event-driven architecture. It allows components to communicate without
knowing about each other — publishers fire events into the bus, subscribers
react to events they care about, and neither side holds a reference to the other.

Why this design matters for AA:
    The main orchestrator loop runs in one thread. Health monitors (browser,
    network) run in separate daemon threads. Without a thread-safe bus, a
    monitor thread calling a handler that mutates orchestrator state would
    produce race conditions that are nearly impossible to reproduce and debug.

    The EventBus solves this by protecting the subscriber registry with a
    RLock (reentrant lock), ensuring that subscribe(), unsubscribe(), and
    publish() operations from any thread are safe.

Thread Safety Guarantees:
    - subscribe() and unsubscribe() are safe to call from any thread.
    - publish() is safe to call from any thread, including daemon threads.
    - Handlers are called on whichever thread called publish(). If a monitor
      thread publishes BROWSER_UNHEALTHY, the handler runs on that monitor
      thread. Handlers must therefore be thread-safe themselves. The
      orchestrator's handlers are designed with this in mind — they only set
      flags or enqueue work rather than mutating shared state directly.

Error Isolation:
    A handler that raises an exception will NOT crash the bus or prevent
    other handlers from receiving the same event. Errors are caught,
    logged, and the delivery continues. This is critical for worst-case
    reliability — a bug in the GUI's event handler must never bring down
    the orchestrator.

No Global Singleton:
    The previous implementation used a module-level bus = EventBus()
    singleton. This has been removed. The EventBus is constructed once by
    SessionController and injected into every component that needs it. This
    makes components testable (inject a mock bus) and makes the data flow
    explicit.

Example:
    >>> from auto_apply.application.agent.event_bus import EventBus
    >>> from auto_apply.domain.events import Event
    >>>
    >>> bus = EventBus()
    >>>
    >>> def on_jobs_found(payload: dict) -> None:
    ...     print(f"Found {payload['count']} jobs")
    >>>
    >>> bus.subscribe(Event.JOBS_DISCOVERED, on_jobs_found)
    >>> bus.publish(Event.JOBS_DISCOVERED, {"count": 42})
    Found 42 jobs
"""

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from auto_apply.domain.events import Event

logger = logging.getLogger(__name__)

# Type alias for event handler callbacks.
# A handler receives the event payload (any dict or None) and returns nothing.
EventHandler = Callable[[Any], None]


class EventBus:
    """Thread-safe publish-subscribe message bus.

    Components subscribe to Event types they care about and publish Event
    types when something significant happens. Neither side knows about the
    other — all coupling is through the Event enum.

    The bus is injected as a dependency, not accessed as a global. One bus
    instance is created per session by SessionController and shared across
    all components that need it.

    Attributes:
        _subscribers: Mapping from Event to list of registered handlers.
        _lock: Reentrant lock protecting all subscriber registry mutations.
        _publish_count: Total events published this session (for diagnostics).
        _error_count: Total handler exceptions caught (for diagnostics).

    Example:
        >>> bus = EventBus()
        >>> bus.subscribe(Event.NETWORK_UNHEALTHY, lambda data: print("Network down!"))
        >>> bus.publish(Event.NETWORK_UNHEALTHY, {"last_successful_check": "2025-01-01"})
        Network down!
    """  # noqa: E501

    def __init__(self) -> None:
        """Initializes an empty EventBus with no subscribers."""
        # defaultdict(list) means we never need to check if a key exists
        # before appending a handler — the list is auto-created on first access.
        self._subscribers: dict[Event, list[EventHandler]] = defaultdict(list)

        # RLock (reentrant lock) allows the same thread to acquire the lock
        # multiple times without deadlocking. This matters because a handler
        # called during publish() could itself call subscribe() or publish(),
        # which would deadlock with a standard Lock.
        self._lock = threading.RLock()

        # Diagnostic counters — not locked because minor inaccuracy is
        # acceptable and avoiding lock contention on the hot publish() path
        # is more valuable than perfect counts.
        self._publish_count: int = 0
        self._error_count: int = 0

    # =========================================================================
    # SUBSCRIPTION MANAGEMENT
    # =========================================================================

    def subscribe(self, event: Event, handler: EventHandler) -> None:
        """Registers a handler to be called when the given event is published.

        Safe to call from any thread, including before the session starts.
        The same handler can be registered for multiple events by calling
        subscribe() once per event type.

        Args:
            event: The Event type to listen for.
            handler: A callable that accepts one argument (the event payload).
                     The handler must not block for more than a few milliseconds
                     since it runs on the publisher's thread.

        Example:
            >>> bus.subscribe(Event.APPLICATION_SUBMITTED, record_application)
            >>> bus.subscribe(Event.APPLICATION_FAILED, log_failure)
        """
        with self._lock:
            self._subscribers[event].append(handler)

        logger.debug(
            "EventBus: subscribed | event=%s handler=%s",
            event.name,
            getattr(handler, "__qualname__", repr(handler)),
        )

    def unsubscribe(self, event: Event, handler: EventHandler) -> None:
        """Removes a previously registered handler for the given event.

        If the handler is not currently registered for this event, this
        method does nothing (no exception raised).

        Args:
            event: The Event type to stop listening to.
            handler: The exact handler instance that was passed to subscribe().

        Example:
            >>> bus.unsubscribe(Event.PROGRESS_UPDATE, update_progress_bar)
        """
        with self._lock:
            handlers = self._subscribers.get(event, [])
            try:
                handlers.remove(handler)
            except ValueError:
                # Handler was not registered; silently ignore.
                pass

    def unsubscribe_all(self, event: Event | None = None) -> None:
        """Removes all handlers for a specific event, or all events.

        Used during teardown to ensure no handlers hold references that
        would prevent garbage collection.

        Args:
            event: The specific event to clear, or None to clear everything.

        Example:
            >>> bus.unsubscribe_all()  # Clear all subscriptions (session end)
            >>> bus.unsubscribe_all(Event.PROGRESS_UPDATE)  # Clear one event
        """
        with self._lock:
            if event is not None:
                self._subscribers[event].clear()
            else:
                self._subscribers.clear()

    def subscriber_count(self, event: Event) -> int:
        """Returns the number of handlers currently subscribed to an event.

        Useful for testing and diagnostics.

        Args:
            event: The Event type to query.

        Returns:
            The number of registered handlers for this event.

        Example:
            >>> bus.subscriber_count(Event.BROWSER_UNHEALTHY)
            2
        """
        with self._lock:
            return len(self._subscribers.get(event, []))

    # =========================================================================
    # EVENT PUBLISHING
    # =========================================================================

    def publish(self, event: Event, payload: Any = None) -> None:
        """Delivers an event to all registered subscribers.

        Safe to call from any thread. Handlers are called synchronously on
        the calling thread in registration order. If any handler raises an
        exception it is caught, logged, and delivery continues to the
        remaining subscribers.

        Args:
            event: The Event type being published.
            payload: Optional data accompanying the event. Convention is a
                     dict, but any type is accepted. See core/events.py for
                     the documented payload shape of each event.

        Example:
            >>> bus.publish(Event.JOBS_DISCOVERED, {"count": 15, "source": "google"})
            >>> bus.publish(Event.SESSION_COMPLETE, {"session_id": "session_123"})
        """
        # Snapshot the handler list under the lock so we don't hold the lock
        # during handler execution (which could be slow or could itself call
        # subscribe/unsubscribe, risking deadlock even with RLock).
        with self._lock:
            handlers = list(self._subscribers.get(event, []))

        self._publish_count += 1

        if not handlers:
            # Log at DEBUG only — high-frequency events like PROGRESS_UPDATE
            # would flood the log at INFO if no one is listening.
            logger.debug("EventBus: no subscribers | event=%s", event.name)
            return

        logger.debug(
            "EventBus: publishing | event=%s subscribers=%d",
            event.name,
            len(handlers),
        )

        for handler in handlers:
            try:
                handler(payload)
            except Exception as exc:
                self._error_count += 1
                # Log the full traceback at ERROR level so bugs in handlers
                # are visible and diagnosable without crashing the bus.
                logger.error(
                    "EventBus: handler raised exception | event=%s handler=%s error=%s",
                    event.name,
                    getattr(handler, "__qualname__", repr(handler)),
                    exc,
                    exc_info=True,
                )
                # Delivery continues to remaining handlers.

    # =========================================================================
    # DIAGNOSTICS
    # =========================================================================

    def get_stats(self) -> dict[str, int]:
        """Returns diagnostic statistics for this bus instance.

        Returns:
            A dict with publish_count, error_count, and total_subscriptions.

        Example:
            >>> bus.get_stats()
            {'publish_count': 1247, 'error_count': 0, 'total_subscriptions': 12}
        """
        with self._lock:
            total_subs = sum(len(handlers) for handlers in self._subscribers.values())

        return {
            "publish_count": self._publish_count,
            "error_count": self._error_count,
            "total_subscriptions": total_subs,
        }

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"EventBus("
            f"published={stats['publish_count']}, "
            f"errors={stats['error_count']}, "
            f"subscriptions={stats['total_subscriptions']})"
        )
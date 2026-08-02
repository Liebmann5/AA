
"""Narrow protocols for the two collaborators a form handler may touch.

A handler's job is widget mechanics: which element to operate and in what
order. It must own no timing, no pacing constants and no RNG — those live in
the PageActionService tool, in one place, config-driven and seeded.

Two protocols, deliberately tiny, so the seam cannot widen into a back door:

    * :class:`PageActionPrimitives` — exactly three verbs on the tool.
    * :class:`DomReadinessPort` — exactly one method on the observer.

Anything a handler needs beyond these is a signal that the work belongs in the
tool, not in the handler. ``tests/adapters/test_handler_protocol.py`` pins both
surfaces and fails if either grows a method.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PageActionPrimitives(Protocol):
    """The only tool methods a handler may call.

    Implemented by ``PageActionService``. Each verb already applies the tool's
    own settle pause, which is why handlers need no sleeps of their own.
    """

    def click(self, element: Any) -> Any:
        """Click an element, with the tool's movement and pacing."""
        ...

    def type_text(self, element: Any, text: str) -> Any:
        """Type text into an element, with the tool's keystroke rhythm."""
        ...

    def settle(self) -> None:
        """Short post-action pause from the tool's configured range."""
        ...


@runtime_checkable
class PageNavigationPort(Protocol):
    """The only navigation method an engine may call.

    Implemented by ``PageActionService``. Kept separate from
    :class:`PageActionPrimitives` on purpose: handlers operate elements and
    must never be able to move the page, so navigation lives behind its own
    one-method port rather than widening the three-verb seam.
    """

    def navigate(self, url: str) -> Any:
        """Load a URL, with the tool's bounded retries and warmup pause."""
        ...


@runtime_checkable
class DomReadinessPort(Protocol):
    """The only readiness method a handler may call.

    Readiness is not pacing: it answers "has the page finished reacting?",
    which a fixed sleep can only guess at. Implemented by ``DOMObserver``.
    """

    def wait_for_dom_stable(self, timeout: float | None = None) -> bool:
        """Block until the DOM stops changing, or the budget expires.

        Returns:
            True if the DOM settled, False if the timeout was reached.
            Never raises — an unusable browser is a False, not an exception.
        """
        ...

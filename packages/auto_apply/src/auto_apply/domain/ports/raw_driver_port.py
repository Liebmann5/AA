"""Narrow escape-hatch protocols for framework-specific raw handles.

BrowserInterface is the framework-agnostic contract and must stay that way:
a port widened until it matches its callers is just a copy of its single
implementation. But a handful of legitimate sites genuinely need the concrete
driver (Chrome DevTools Protocol commands, Selenium window handles, Playwright
pages). Those are escape hatches by nature — they belong to one framework and
are useless on another.

These tiny @runtime_checkable protocols formalize the hatch. Callers
isinstance-check before reaching, so:
  * mypy sees the access (no more attr-defined errors), and
  * on the wrong framework the call degrades to None instead of raising.

ResilientDriver forwards unknown attributes through ``__getattr__``, and
``hasattr`` resolves through the forwarder, so isinstance checks pass for
the wrapped Selenium/Playwright adapters exactly as they would for the
adapters directly.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SupportsRawDriver(Protocol):
    """A browser wrapper that exposes the underlying Selenium-style driver."""

    def get_raw_driver(self) -> Any:
        """Return the raw framework driver (e.g., selenium WebDriver)."""
        ...


@runtime_checkable
class SupportsRawPage(Protocol):
    """A browser wrapper that exposes the underlying Playwright Page."""

    def get_raw_page(self) -> Any:
        """Return the raw Playwright Page object."""
        ...

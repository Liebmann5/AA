"""Defines the contract for ATS platform identification and description.

``ATSDescriptor`` is the single source of truth for every platform-specific
selector and signal that the ApplicationEngine needs. Descriptors are loaded
at startup from ``resources/ats/*.yaml`` by the ``ATSRegistry`` adapter.

``ATSPort`` is the per-platform Protocol.  The registry is not itself an
``ATSPort``; it is a collection of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ATSDescriptor:
    """Immutable description of a single ATS platform.

    Attributes:
        name: Canonical platform name, lowercase (e.g. ``"greenhouse"``).
        url_patterns: Glob-style patterns matched against the stripped URL
            (scheme removed).  ``*`` matches any run of characters including
            path separators.
        login_wall_signals: Lower-cased text snippets that indicate the page
            requires authentication before showing the application form.
        success_signals: Lower-cased text snippets that indicate the
            application was successfully submitted.
        form_root_selector: CSS selector for the element that roots the
            application form.  Used by ApplicationEngine to scope field
            searches.
        submit_button_selector: CSS selector for the final submit / next
            button on each form step.
        multi_step: ``True`` if the platform uses a wizard with multiple
            pages or steps before a final submission.
    """

    name: str
    url_patterns: tuple[str, ...]
    login_wall_signals: tuple[str, ...]
    success_signals: tuple[str, ...]
    form_root_selector: str
    submit_button_selector: str
    multi_step: bool

    def __repr__(self) -> str:
        return (
            f"ATSDescriptor(name={self.name!r}, "
            f"multi_step={self.multi_step}, "
            f"patterns={len(self.url_patterns)})"
        )


@runtime_checkable
class ATSPort(Protocol):
    """Contract for a single-platform ATS adapter.

    A concrete implementation wraps exactly one ``ATSDescriptor`` and
    answers whether a given URL belongs to that platform.

    The ``ATSRegistry`` aggregates multiple ``ATSPort`` implementations
    (one per YAML file) and exposes a single ``match(url)`` entry-point.
    """

    def matches(self, url: str) -> bool:
        """Returns ``True`` if *url* belongs to this ATS platform."""
        ...

    def descriptor(self) -> ATSDescriptor:
        """Returns the full descriptor for this ATS platform."""
        ...

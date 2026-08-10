"""Narrow contract for reading the detected environment capabilities.

Why this is its own port rather than a method on ``RegistryPort``.

``PolicyEnforcement`` needs exactly one thing from the capabilities registry:
the ``EnvironmentCapabilities`` snapshot, which it mutates to purge tools an
admin policy forbids. It was reaching into the concrete registry's private
``_capabilities`` attribute to get it, which is both an encapsulation break and
an adapter importing infrastructure.

Typing it against the full ``RegistryPort`` would fix the import direction
while leaving the dependency badly overstated: seven methods declared, one
used. Interface segregation is the point of having ports at all — a
collaborator's declared needs should be readable as its actual needs.

``CapabilitiesRegistry`` satisfies this structurally through its existing
public ``get_environment_capabilities()``; nothing had to change on its side,
and ``RegistryPort`` is untouched.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from auto_apply.domain.models.environment import EnvironmentCapabilities


@runtime_checkable
class EnvironmentCapabilitiesProvider(Protocol):
    """Supplies the environment snapshot detected at startup."""

    def get_environment_capabilities(self) -> EnvironmentCapabilities:
        """Return the detected environment capabilities.

        The returned object is the registry's live snapshot, not a copy:
        ``PolicyEnforcement`` mutates ``available_tools`` on it to strip
        admin-blocked entries. That aliasing is deliberate and is why this
        accessor is on a contract at all instead of being read off a private
        attribute.
        """
        ...

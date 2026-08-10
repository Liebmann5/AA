"""Contract for a session whose liveness can be polled.

``BrowserHealthMonitor`` calls exactly one method on the driver it watches:
``is_alive()``. It was annotated against the concrete
``infrastructure.resilient_driver.ResilientDriver``, which is both an adapter
reaching into infrastructure and a far wider dependency than the one method
justifies.

Kept separate from ``BrowserInterface`` on purpose. A health monitor should not
be able to drive the browser it is watching — a monitor that can navigate is a
monitor that can perturb the thing it measures.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LivenessPort(Protocol):
    """A resource that can be asked whether it is still usable."""

    def is_alive(self) -> bool:
        """Return True if the underlying session still responds."""
        ...

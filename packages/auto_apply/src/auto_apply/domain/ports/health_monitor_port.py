"""Port interface for background health monitors.

Health monitors run as daemon threads and publish events to the EventBus when
they detect problems. The orchestrator starts them in run() and stops them in
_teardown(). The Protocol here defines the minimal interface the orchestrator
depends on — implementations live in adapters/secondary.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class HealthMonitor(Protocol):
    """Common interface for background health-checking daemon threads.

    Implementations must be safe to call from any thread. run() is the
    daemon-thread entry point; stop() signals it to exit; is_healthy()
    returns the current health status as a boolean.
    """

    def run(self) -> None:
        """Blocking loop — passed as the target to threading.Thread."""
        ...

    def stop(self) -> None:
        """Signals the run() loop to exit. Non-blocking, thread-safe."""
        ...

    def is_healthy(self) -> bool:
        """Returns True if the monitored resource is currently usable."""
        ...

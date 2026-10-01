"""Pins for the browser lifecycle contract: one owner, one explicit release,
reachable on every exit path.

Measured on 8281571 (2026-10-01), before the fix this file pins: the browser
was acquired by build_session_controller and released only when the
orchestrator's run() loop reached _teardown. A controller built and never
run, or a process that exited while stop()'s 10-second thread join was still
waiting on a busy task, leaked the browser out of AA entirely — and because
every browser in a process shares one --user-data-dir, the next launch was
then REFUSED ("session not created").

Each test class states its label (teeth / differential / guard) and how it
fails on the pre-fix tree.

Run:
    uv run pytest tests/integration/test_browser_lifecycle.py -v
"""

from __future__ import annotations

import gc
import threading
import weakref
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def headless_profile():
    """A minimal valid profile that launches any real browser headless.

    A headed launch needs a display; headless keeps the boot path real on CI
    runners and display-less machines alike (same pattern as
    tests/integration/test_static_mode.py).
    """
    from auto_apply.domain.models.profile import UserProfile

    return UserProfile.model_validate({
        "profile_name": "browser-lifecycle-test",
        "personal_info": {
            "first_name": "Test",
            "last_name": "User",
            "email": "test@example.com",
            "phone_number": "555-000-1234",
            "street_address": "123 Main St",
            "city": "Testville",
            "state": "CA",
            "zip_code": "90210",
        },
        "links": {},
        "career_summary": (
            "Experienced software engineer with Python and automation background. "
            "Five years building production systems and open-source tools."
        ),
        "search_preferences": {
            "desired_job_titles": ["Software Engineer"],
            "preferred_locations": ["Remote"],
        },
        "politeness_settings": {},
        "app_config": {"headless_mode": True},
    })


class TestDoubleBuildAfterShutdown:
    """TEETH + DIFFERENTIAL — real browser, skips cleanly without one.

    Pre-fix tree: fails with AttributeError (SessionController had no
    shutdown), and the equivalent release-less sequence — build, stop,
    build — was measured REFUSED on 2026-10-01 because the first browser
    still held the shared profile directory. Passes only when a built
    controller can be explicitly shut down and a second build then succeeds
    in the same process.
    """

    def test_build_shutdown_build_shutdown(self, headless_profile, tmp_path, monkeypatch):
        monkeypatch.setenv("AA_DATA_DIR", str(tmp_path))

        from auto_apply.domain.exceptions import BrowserSetupError
        from auto_apply.infrastructure.composition_root import build_session_controller

        try:
            first = build_session_controller(headless_profile)
        except BrowserSetupError as exc:
            pytest.skip(f"No launchable browser on this machine: {exc}")

        assert first.orchestrator._driver is not None, (
            "the cascade produced no driver — the test would be vacuous"
        )
        first.shutdown()
        assert first.orchestrator._driver is None, (
            "shutdown() must release the browser: the next build reuses the "
            "same --user-data-dir and is refused while it is held"
        )

        second = build_session_controller(headless_profile)
        try:
            assert second.orchestrator._driver is not None
        finally:
            second.shutdown()


class TestOrchestratorShutdownUnit:
    """GUARD — no browser. Pre-fix tree: AttributeError (AgentOrchestrator
    had no shutdown).

    Uses the partial-instance pattern the orchestrator's own docstring
    points at: only the attributes _teardown touches are injected.
    """

    def _make_orchestrator(self):
        from auto_apply.application.agent.orchestrator import AgentOrchestrator

        orch = object.__new__(AgentOrchestrator)
        orch._shutdown_lock = threading.Lock()
        orch._shutdown_complete = False
        orch._workflows = {}
        orch.state_machine = MagicMock()
        orch._browser_monitor = None
        orch._network_monitor = None
        orch._watchdog = None
        orch.checkpoint_manager = MagicMock()
        orch.event_bus = MagicMock()
        orch._driver = MagicMock()
        orch._session_report = MagicMock()
        orch.context = MagicMock()
        return orch

    def test_shutdown_closes_driver_without_run(self):
        """The driver is closed even when run() was never called."""
        orch = self._make_orchestrator()
        driver = orch._driver

        orch.shutdown()

        assert driver.close.call_count == 1
        assert orch._driver is None

    def test_shutdown_is_idempotent(self):
        """A second shutdown() — run()'s exit after a controller-level
        release, or a window close after a finished session — closes nothing
        twice, so the final checkpoint and session report are written
        exactly once."""
        orch = self._make_orchestrator()
        driver = orch._driver

        orch.shutdown()
        orch.shutdown()

        assert driver.close.call_count == 1


class TestSessionControllerShutdownUnit:
    """GUARD — no browser. Pre-fix tree: AttributeError (SessionController
    had no shutdown)."""

    def _make_controller(self):
        from auto_apply.application.services.session_controller import SessionController

        controller = object.__new__(SessionController)
        controller.orchestrator = MagicMock()
        controller._agent_thread = None
        return controller

    def test_shutdown_stops_then_releases(self):
        controller = self._make_controller()

        controller.shutdown()

        controller.orchestrator.stop.assert_called_once_with()
        controller.orchestrator.shutdown.assert_called_once_with()

    def test_shutdown_releases_even_when_stop_raises(self):
        """The release lives in a finally: a stop() that raises must not
        strand the browser."""
        controller = self._make_controller()
        controller.orchestrator.stop.side_effect = RuntimeError("join exploded")

        with pytest.raises(RuntimeError):
            controller.shutdown()

        controller.orchestrator.shutdown.assert_called_once_with()

    def test_shutdown_after_a_stop_does_not_wait_again(self):
        """TEETH: a stop() that already waited out its join is not repeated.

        cli/startup.py calls stop() in its inner finally and shutdown() in its
        outer finally. With a task stuck mid-flight each stop() blocks for its
        full 10-second join, so Ctrl+C took ~18 s to release the browser
        (measured through CLIStartup.run() with a real Chrome) and a second
        Ctrl+C in that window aborted the release. Fails before the change:
        the join is called twice.
        """
        controller = self._make_controller()
        thread = MagicMock()
        thread.is_alive.return_value = True   # a task stuck mid-flight
        controller._agent_thread = thread

        controller.stop()
        controller.shutdown()

        assert thread.join.call_count == 1
        controller.orchestrator.stop.assert_called_once_with()
        controller.orchestrator.shutdown.assert_called_once_with()

    def test_start_rearms_the_stop_for_shutdown(self):
        """GUARD: start() clears the record of an earlier stop(), so the next
        shutdown() asks the NEW run to stop before releasing the browser.
        """
        controller = self._make_controller()
        controller.stop()
        controller.start()   # orchestrator.run is a MagicMock: the thread ends at once
        controller.shutdown()

        assert controller.orchestrator.stop.call_count == 2
        controller.orchestrator.shutdown.assert_called_once_with()


class TestCLIPathReleasesController:
    """DIFFERENTIAL — no browser. Drives cli/startup.py's run() with the
    monitor loop raising SystemExit, the exact shape main.py's SIGINT
    handler produces on the main thread.

    Pre-fix tree: fails because controller.shutdown is never called
    (call_count stays 0) — startup.py's only finally called stop(), which
    never released the browser. This pin does NOT claim SIGINT bypasses
    stop(): stop() is still called (asserted below). It asserts that the
    release stop() never provided now happens on the same unwind path.
    """

    def test_system_exit_in_monitor_loop_still_shuts_down(self, monkeypatch):
        from auto_apply.adapters.primary.cli import startup as startup_module

        monkeypatch.setattr("getpass.getpass", lambda *args, **kwargs: "")

        repo = MagicMock(name="profile_repo")
        repo.load_profile.return_value = MagicMock(name="profile")
        monkeypatch.setattr(
            startup_module, "autonomy_enabled_for_profile", lambda profile: False
        )

        session_config = SimpleNamespace(
            execution_mode=SimpleNamespace(includes_application=False)
        )

        class FakeWizard:
            def run(self):
                return session_config

        monkeypatch.setattr(startup_module, "CLIWizard", FakeWizard)

        controller = MagicMock(name="controller")
        controller.initialize_session.return_value = 1
        monkeypatch.setattr(
            startup_module,
            "build_session_controller",
            lambda profile, profile_repo=None: controller,
        )

        class FakeDashboard:
            def __init__(self, ctrl):
                pass

            def run_monitor_loop(self):
                raise SystemExit(0)

        monkeypatch.setattr(startup_module, "CLIDashboard", FakeDashboard)

        cli = startup_module.CLIStartup(
            profile_repo_factory=lambda **kwargs: repo,
            profile_override="test-profile",
        )
        with pytest.raises(SystemExit):
            cli.run()

        assert controller.stop.call_count == 1
        assert controller.shutdown.call_count == 1


class TestExitShutdownRegistration:
    """GUARD for the weak atexit net (the point-6 ruling). Pre-fix tree:
    AttributeError — composition_root had no _register_exit_shutdown.
    """

    def test_live_controller_is_shut_down_at_exit(self, monkeypatch):
        from auto_apply.infrastructure import composition_root

        registered = []
        monkeypatch.setattr("atexit.register", registered.append)

        controller = MagicMock(name="controller")
        composition_root._register_exit_shutdown(controller)

        assert len(registered) == 1
        registered[0]()
        controller.shutdown.assert_called_once_with()

    def test_dead_controller_is_not_pinned(self, monkeypatch):
        """The registration must be WEAK: a strong one would hold the
        controller — and its live browser, against the shared
        --user-data-dir — until process exit, turning a dropped,
        never-shut-down controller from a case garbage collection currently
        rescues into a guaranteed refusal of the next build."""
        from auto_apply.infrastructure import composition_root

        registered = []
        monkeypatch.setattr("atexit.register", registered.append)

        class _Box:
            def __init__(self):
                self.shutdown = MagicMock()

        box = _Box()
        box_ref = weakref.ref(box)
        composition_root._register_exit_shutdown(box)
        del box
        gc.collect()

        assert box_ref() is None, (
            "the atexit registration pinned the controller — a strong "
            "reference defeats the GC rescue that is today's only cleanup "
            "on a forgotten controller"
        )
        registered[0]()  # must be a safe no-op on a collected controller

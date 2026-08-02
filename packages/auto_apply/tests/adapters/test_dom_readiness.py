
"""Pins for DOM readiness — the primitive that never existed (Stage 2a).

``ApplicationsWorkflow`` called ``self._dom_observer.wait_for_dom_stable(...)``
behind ``if hasattr(self._dom_observer, "wait_for_dom_stable")``. ``DOMObserver``
never defined that method, so the guard was never once true and the wait never
ran. The call sites, the guard and the config key all existed; only the method
was missing.

The pins that matter most here are the two poll-behaviour ones. A method that
"watches the DOM" must be provably a poll and not a disguised fixed sleep, so:

    * when the DOM settles, it must return **materially faster than the
      budget** — a hidden ``time.sleep(budget)`` cannot pass this;
    * when the DOM never settles, it must return at the budget and **not
      raise** — a readiness check must never be able to abort a form fill.
"""
import time

import pytest
from unittest.mock import MagicMock, patch


def _observer(page_sources, *, timeout, poll):
    """Build a DOMObserver over a browser whose page_source follows a script.

    Args:
        page_sources: A callable returning the current page source.
        timeout: Stability budget in seconds.
        poll: Gap between samples in seconds.
    """
    from auto_apply.adapters.secondary.interaction.dom_observer import DOMObserver

    browser = MagicMock()
    type(browser).page_source = property(lambda _self: page_sources())
    return DOMObserver(
        browser=browser, stability_timeout_s=timeout, poll_interval_s=poll
    )


# ─────────────────────────────────────────────────────────────────────────────
# Poll behaviour
# ─────────────────────────────────────────────────────────────────────────────


def test_returns_as_soon_as_two_samples_agree_not_at_the_budget():
    """A settled DOM must cost a poll or two, never the whole budget.

    This is the pin that stops the method regressing into a fixed sleep: the
    budget is 5 seconds, the poll is 10ms, and a stable page must be detected
    in a small fraction of that. An implementation that slept the budget and
    then reported success would pass a naive "returns True" assertion and fail
    this one.
    """
    samples = {"n": 0}

    def _constant():
        samples["n"] += 1
        return "<html><body>stable</body></html>"

    observer = _observer(_constant, timeout=5.0, poll=0.01)

    started = time.monotonic()
    result = observer.wait_for_dom_stable()
    elapsed = time.monotonic() - started

    assert result is True
    assert elapsed < 1.0, (
        f"settled DOM took {elapsed:.2f}s against a 5.0s budget — this looks "
        f"like a sleep, not a poll"
    )
    assert samples["n"] >= 2, (
        "the DOM was sampled fewer than twice; stability cannot have been "
        "observed, only assumed"
    )


def test_returns_at_the_budget_without_raising_when_the_dom_never_settles():
    """A churning page ends the wait cleanly, with False — never an exception."""
    counter = {"n": 0}

    def _always_changing():
        counter["n"] += 1
        return "x" * counter["n"]

    observer = _observer(_always_changing, timeout=0.3, poll=0.02)

    started = time.monotonic()
    result = observer.wait_for_dom_stable()
    elapsed = time.monotonic() - started

    assert result is False
    assert elapsed >= 0.3, "returned before the budget was spent"
    assert elapsed < 2.0, "overran the budget"


def test_an_unusable_browser_is_a_false_not_an_exception():
    """Readiness must never be able to abort a form fill."""
    from auto_apply.adapters.secondary.interaction.dom_observer import DOMObserver

    browser = MagicMock()
    type(browser).page_source = property(
        lambda _self: (_ for _ in ()).throw(RuntimeError("driver gone"))
    )
    observer = DOMObserver(browser=browser, stability_timeout_s=1.0, poll_interval_s=0.01)

    assert observer.wait_for_dom_stable() is False


def test_the_timeout_argument_overrides_the_configured_budget():
    """Call sites may pass an explicit budget; both are values, not literals."""
    counter = {"n": 0}

    def _always_changing():
        counter["n"] += 1
        return "y" * counter["n"]

    observer = _observer(_always_changing, timeout=30.0, poll=0.02)

    started = time.monotonic()
    assert observer.wait_for_dom_stable(timeout=0.2) is False
    assert time.monotonic() - started < 2.0


def test_both_budgets_come_from_the_constructor_not_from_literals():
    """The two 1.0s the handlers used to sleep are eliminated, not relocated."""
    import inspect

    from auto_apply.adapters.secondary.interaction.dom_observer import DOMObserver

    source = inspect.getsource(DOMObserver.wait_for_dom_stable)
    assert "self._stability_timeout_s" in source
    assert "self._poll_interval_s" in source
    assert "1.0" not in source, "a literal second survived inside the observer"


# ─────────────────────────────────────────────────────────────────────────────
# The workflow's dead guard
# ─────────────────────────────────────────────────────────────────────────────


def test_the_workflow_calls_readiness_unconditionally():
    """No hasattr probe may stand between the workflow and the wait.

    The guard was never true for two years of call sites. A None check is fine
    — that is a wiring question — but a capability probe for a method the
    codebase owns is how a call silently goes uncalled.
    """
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "src"
        / "auto_apply"
        / "application"
        / "workflows"
        / "applications_workflow.py"
    ).read_text(encoding="utf-8", errors="ignore")

    assert 'hasattr(self._dom_observer, "wait_for_dom_stable")' not in source
    assert source.count("self._dom_observer.wait_for_dom_stable(") >= 2


# ─────────────────────────────────────────────────────────────────────────────
# Composition-root wiring — one observer, built early, nothing else shifted
# ─────────────────────────────────────────────────────────────────────────────


def test_one_observer_is_constructed_and_shared():
    """The workflow and the handlers must hold the same instance.

    Two DOMObserver constructions would mean two readiness budgets and two
    places to configure — the duplication this stage exists to remove.
    """
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "src"
        / "auto_apply"
        / "infrastructure"
        / "composition_root.py"
    ).read_text(encoding="utf-8", errors="ignore")

    assert source.count("DOMObserver(") == 1, (
        "DOMObserver is constructed more than once; the observer must be built "
        "once and shared"
    )
    assert "_dom_observer = dom_readiness" in source
    assert "readiness=dom_readiness" in source


def test_the_observer_budgets_are_read_from_config():
    """No literal budgets at the wiring site either."""
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "src"
        / "auto_apply"
        / "infrastructure"
        / "composition_root.py"
    ).read_text(encoding="utf-8", errors="ignore")

    assert "dom_stabilization_timeout_s" in source
    assert "dom_stabilization_poll_interval_s" in source


def test_static_mode_still_builds_with_no_driver_and_no_observer():
    """Behaviour-preserving: the reorder must not break the zero-browser path."""
    from auto_apply.infrastructure.composition_root import build_orchestrator
    from auto_apply.infrastructure.registry import CapabilitiesRegistry

    from tests.infrastructure.test_reproducibility import _minimal_profile

    registry = CapabilitiesRegistry.build(user_profile=_minimal_profile())

    with patch(
        "auto_apply.infrastructure.composition_root.BrowserCascade.acquire_driver",
        return_value=None,
    ):
        orchestrator = build_orchestrator(registry)

    assert orchestrator is not None

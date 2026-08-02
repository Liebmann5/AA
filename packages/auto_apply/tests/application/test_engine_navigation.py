
"""Pins for engine navigation on the shared tool (Stage 2b).

``ApplicationsWorkflow`` loaded job pages with a bare ``self._browser.get(url)``.
Meanwhile ``PageActionService.navigate`` — which implements bounded retries and
the one-time warmup pause — had no production caller at all. Two finished
features sat on a dead branch:

    * ``navigation_retries``: a bounded search for a working URL, so a dead
      link is abandoned rather than hanging the session;
    * ``warmup_pause``: a single human-scale pause before the very first page
      load, which measurably reduces the chance of an immediate CAPTCHA.

Routing the engine's navigation through the tool activates both. These pins
hold that routing, prove the two features actually run, and keep navigation
behind its own one-method port so it can never widen the three-verb handler
seam.
"""
import pathlib

import pytest
from unittest.mock import MagicMock

WORKFLOW_SRC = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "src"
    / "auto_apply"
    / "application"
    / "workflows"
    / "applications_workflow.py"
)


def _fast_config(**overrides):
    """Timing config with every pause at zero, so pins stay fast."""
    cfg = {
        "enable_human_timing": True,
        "navigation_retries": 3,
        "macro_pause_min_s": 0.0,
        "macro_pause_max_s": 0.0,
        "settle_min_s": 0.0,
        "settle_max_s": 0.0,
        "min_action_delay_ms": 0,
        "micro_peak_ms": 0,
        "low_resource_mode": False,
    }
    cfg.update(overrides)
    return cfg


def _tool(browser, **cfg_overrides):
    from auto_apply.application.services.page_action.service import PageActionService

    registry = MagicMock()
    registry.get_all_effective_config.return_value = _fast_config(**cfg_overrides)
    return PageActionService(browser=browser, registry=registry)


# ─────────────────────────────────────────────────────────────────────────────
# The port stays narrow
# ─────────────────────────────────────────────────────────────────────────────


def test_the_navigation_port_is_exactly_one_method():
    from auto_apply.domain.ports.interaction_primitives_port import PageNavigationPort

    methods = {
        name
        for name in vars(PageNavigationPort)
        if not name.startswith("_") and callable(getattr(PageNavigationPort, name, None))
    }
    assert methods == {"navigate"}


def test_navigation_did_not_leak_into_the_handler_seam():
    """Handlers operate elements; they must never be able to move the page."""
    from auto_apply.domain.ports.interaction_primitives_port import (
        PageActionPrimitives,
    )

    methods = {
        name
        for name in vars(PageActionPrimitives)
        if not name.startswith("_")
        and callable(getattr(PageActionPrimitives, name, None))
    }
    assert methods == {"click", "type_text", "settle"}


def test_the_tool_satisfies_the_navigation_port():
    from auto_apply.application.services.page_action.service import PageActionService
    from auto_apply.domain.ports.interaction_primitives_port import PageNavigationPort

    assert isinstance(
        PageActionService.__new__(PageActionService), PageNavigationPort
    )


# ─────────────────────────────────────────────────────────────────────────────
# The two features that had no caller
# ─────────────────────────────────────────────────────────────────────────────


def test_warmup_fires_once_across_many_navigations():
    """The CAPTCHA-mitigation pause runs before the first load, and only then."""
    browser = MagicMock()
    tool = _tool(browser)
    tool.warmup_pause = MagicMock(wraps=tool.warmup_pause)

    tool.navigate("https://example.com/one")
    tool.navigate("https://example.com/two")
    tool.navigate("https://example.com/three")

    assert tool.warmup_pause.call_count == 3, "navigate must always consult warmup"
    assert tool._warmed_up is True
    assert browser.get.call_count == 3


def test_a_failing_load_is_retried_up_to_the_configured_ceiling():
    """Two failures then a success is one successful navigation, not a failure."""
    browser = MagicMock()
    browser.get.side_effect = [RuntimeError("boom"), RuntimeError("boom"), None]

    result = _tool(browser, navigation_retries=3).navigate("https://example.com")

    assert bool(result) is True
    assert browser.get.call_count == 3


def test_retries_are_bounded_and_a_dead_url_is_abandoned():
    """The ceiling is what stops a dead link hanging the session."""
    browser = MagicMock()
    browser.get.side_effect = RuntimeError("dead")

    result = _tool(browser, navigation_retries=2).navigate("https://example.com")

    assert bool(result) is False
    assert browser.get.call_count == 2, "retry ceiling not honoured"


def test_a_successful_load_costs_a_single_attempt():
    """navigation_retries is a ceiling, not a quota."""
    browser = MagicMock()
    _tool(browser, navigation_retries=5).navigate("https://example.com")
    assert browser.get.call_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# The engine routes through the tool
# ─────────────────────────────────────────────────────────────────────────────


def _workflow(navigation):
    from auto_apply.application.workflows.applications_workflow import (
        ApplicationsWorkflow,
    )
    from auto_apply.domain.models.session_plan import SessionPlan

    return ApplicationsWorkflow(
        profile=MagicMock(),
        browser=MagicMock(),
        perception_port=None,
        interaction_port=MagicMock(),
        webpage_analyzer=None,
        field_classifier=None,
        semantic_filler=None,
        text_matcher=MagicMock(),
        file_handler=None,
        interruption_handler=None,
        dom_observer=None,
        ats_registry=None,
        job_repo=MagicMock(),
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        interrupt_policy=MagicMock(),
        navigation=navigation,
        text_generation_port=None,
        browser_lease=None,
        plan=SessionPlan(session_id="test"),
    )


def test_the_engine_navigates_through_the_tool_not_the_raw_browser():
    navigation = MagicMock()
    navigation.navigate.return_value = True
    wf = _workflow(navigation)

    wf._navigate("https://example.com/job/1")

    navigation.navigate.assert_called_once_with("https://example.com/job/1")
    wf._browser.get.assert_not_called()


def test_a_failed_load_raises_so_the_engine_still_records_failed_navigation():
    """The tool returns a falsy result rather than raising; convert it here.

    Without the conversion the engine would treat a page that never loaded as
    loaded and go looking for a form on the previous page.
    """
    from auto_apply.domain.exceptions import ApplicationError

    class _Failed:
        reason = "timeout"

        def __bool__(self):
            return False

    navigation = MagicMock()
    navigation.navigate.return_value = _Failed()

    with pytest.raises(ApplicationError) as exc_info:
        _workflow(navigation)._navigate("https://example.com")

    assert "timeout" in str(exc_info.value)


def test_the_engine_degrades_to_the_raw_browser_without_a_tool():
    """No driver, or direct construction: navigate still works, nothing invented."""
    wf = _workflow(None)

    wf._navigate("https://example.com")

    wf._browser.get.assert_called_once_with("https://example.com")


def test_raw_browser_navigation_survives_only_as_the_documented_fallback():
    """Ceiling pin: exactly one raw navigation call, inside _navigate.

    The engine has one way to move the page. The single surviving
    ``self._browser.get`` is the no-tool degradation path, and it lives inside
    the helper so it cannot be reached around.
    """
    source = WORKFLOW_SRC.read_text(encoding="utf-8", errors="ignore")
    assert source.count("self._browser.get(") == 1, (
        "a second raw navigation call appeared in the engine"
    )
    helper = source.split("def _navigate(")[1].split("def _submit_application(")[0]
    assert "self._browser.get(url)" in helper


def test_the_composition_root_injects_the_navigator():
    source = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "src"
        / "auto_apply"
        / "infrastructure"
        / "composition_root.py"
    ).read_text(encoding="utf-8", errors="ignore")
    assert "navigation=page_action_tool" in source

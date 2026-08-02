
"""Pins for the click-target occlusion guard (Stage 6c).

`behavior.human_like_click` carried an `elementFromPoint` check that raised on a
suspected trap. It never ran on any live path, and its own source says it was
"too aggressive and causing false positives" — so Stage 1 deliberately did not
port it, and ADR-012 held it open as a pre-real-site decision.

This is the tightened port. The predecessor's fatal flaw was its error handling:

    except Exception:
        logger.warning("...assuming it's a trap")
        return True          # <- every probe failure blocked the click

Combined with `getBoundingClientRect()` returning viewport-relative coordinates,
any element below the fold sampled a point that was not it — and was called a
honeypot. A guard that refuses to click because it could not look is worse than
no guard, which is exactly how the original ended up disabled.

So the probe has three outcomes and **undetermined proceeds**. The pins below
exist mostly to hold that property.
"""
import pytest
from unittest.mock import MagicMock

from auto_apply.application.services.page_action.service import PageActionService


def _tool(verdict, *, guard=True, verdicts=None):
    """A tool whose reachability probe returns a scripted verdict."""
    browser = MagicMock()
    calls = {"n": 0}

    def _exec(script, *args):
        if "elementFromPoint" not in script:
            return None
        calls["n"] += 1
        if verdicts is not None:
            return verdicts[min(calls["n"] - 1, len(verdicts) - 1)]
        if isinstance(verdict, Exception):
            raise verdict
        return verdict

    browser.execute_script.side_effect = _exec

    registry = MagicMock()
    registry.get_all_effective_config.return_value = {
        "enable_human_timing": False,
        "occlusion_guard": guard,
        "macro_pause_min_s": 0.0,
        "macro_pause_max_s": 0.0,
        "settle_min_s": 0.0,
        "settle_max_s": 0.0,
        "min_action_delay_ms": 0,
        "low_resource_mode": False,
    }
    tool = PageActionService(browser=browser, registry=registry)
    tool.probe_calls = calls
    return tool


# ─────────────────────────────────────────────────────────────────────────────
# UNDETERMINED PROCEEDS — the property the original got wrong
# ─────────────────────────────────────────────────────────────────────────────


def test_a_failing_probe_does_not_block_the_click():
    """The predecessor assumed a trap on error. That is why it was disabled."""
    tool = _tool(RuntimeError("script blew up"))
    element = MagicMock()

    result = tool.click(element)

    assert bool(result) is True
    element.click.assert_called_once()


def test_an_offscreen_target_does_not_block_the_click():
    """Below the fold, elementFromPoint samples a point that is not the target.

    Treating that as a trap is the single biggest false-positive source in the
    original check.
    """
    tool = _tool("offscreen")
    element = MagicMock()

    assert bool(tool.click(element)) is True
    element.click.assert_called_once()


def test_an_empty_verdict_does_not_block_the_click():
    tool = _tool(None)
    element = MagicMock()

    assert bool(tool.click(element)) is True
    element.click.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# IT STILL CATCHES THE THINGS WORTH CATCHING
# ─────────────────────────────────────────────────────────────────────────────


def test_a_covered_target_is_not_clicked():
    """A banner or modal over the button means the click lands on the banner."""
    tool = _tool("occluded:div")
    element = MagicMock()

    result = tool.click(element)

    assert bool(result) is False
    assert "occluded:div" in result.reason
    element.click.assert_not_called()


def test_a_hidden_or_zero_sized_target_is_not_clicked():
    """display:none and 1x1 elements are the classic honeypot shape."""
    tool = _tool("hidden")
    element = MagicMock()

    assert bool(tool.click(element)) is False
    element.click.assert_not_called()


def test_the_refusal_reason_names_what_was_in_the_way():
    tool = _tool("occluded:iframe")
    result = tool.click(MagicMock())

    assert "iframe" in result.reason


# ─────────────────────────────────────────────────────────────────────────────
# SCROLL-THEN-RECHECK
# ─────────────────────────────────────────────────────────────────────────────


def test_occlusion_that_a_scroll_resolves_still_clicks():
    """Sticky headers are the common case; look again before refusing."""
    tool = _tool(None, verdicts=["occluded:header", "ok"])
    element = MagicMock()

    result = tool.click(element)

    assert bool(result) is True
    element.click.assert_called_once()
    assert tool.probe_calls["n"] == 2, "the guard did not re-check after scrolling"


def test_persistent_occlusion_is_refused_after_the_retry():
    tool = _tool("occluded:div")
    element = MagicMock()

    assert bool(tool.click(element)) is False
    assert tool.probe_calls["n"] == 2
    element.click.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# THE PROBE ITSELF
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "verdict,expected",
    [
        ("ok", True),
        ("hidden", False),
        ("occluded:div", False),
        ("offscreen", None),
        (None, None),
        ("", None),
    ],
)
def test_the_probe_classifies_three_ways(verdict, expected):
    tool = _tool(verdict)
    assert tool._click_target_reachable(MagicMock())[0] is expected


def test_the_script_treats_descendants_and_ancestors_as_the_target():
    """A <span> inside a <button> must not read as an occluder.

    Both walks matter: up from the topmost element (span -> button) and up from
    the target (button -> a wrapping label that is itself topmost).
    """
    script = PageActionService._REACHABILITY_SCRIPT

    assert "for (var e = top; e; e = e.parentElement)" in script
    assert "for (var a = elem; a; a = a.parentElement)" in script
    assert "elementFromPoint" in script


def test_the_guard_can_be_switched_off_entirely():
    """A config escape hatch, because this check has a history."""
    tool = _tool("occluded:div", guard=False)
    element = MagicMock()

    assert bool(tool.click(element)) is True
    element.click.assert_called_once()
    assert tool.probe_calls["n"] == 0, "the probe ran despite being disabled"


def test_the_guard_ships_switched_on():
    import pathlib

    yaml_text = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "src"
        / "auto_apply"
        / "resources"
        / "config"
        / "runtime_defaults.yaml"
    ).read_text(encoding="utf-8")

    assert "occlusion_guard: true" in yaml_text


def test_the_adr_records_the_item_as_closed():
    import pathlib

    adr = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "docs"
        / "adr"
        / "012_fail_closed_submission_gate.md"
    ).read_text(encoding="utf-8")

    assert "occlusion guard — DONE" in adr
    assert "undetermined proceeds" in adr

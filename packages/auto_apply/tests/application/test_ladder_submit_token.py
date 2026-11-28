"""The click ladder re-verifies the submit token's target (Phase 0, P0-4;
AA_ENGINE_MATH.md §3a, decision 7). On its own probe — the last read before
any rung can act — and before anything can dispatch.

TEETH: against the pre-Phase-0 ladder, an irreversible click with no token,
with a different control, or with an unreadable probe went straight to the
pointer rung.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from auto_apply.domain.services.submit_token import ControlIdentity

from .test_mouse_tool import BOX, _probe, _tool

SUBMIT = ControlIdentity(tag="button", name="apply", id="submit-1")


def _rungs_fired(tool, element) -> bool:
    return bool(tool._browser.execute_motion.called or element.click.called
                or element.send_keys.called)


def test_an_irreversible_click_without_a_token_is_refused_before_any_rung() -> None:
    tool = _tool([_probe(box=BOX)])
    element = MagicMock()
    result = tool.click(element, irreversible=True)
    assert not result and result.rung == "probe"
    assert "without a submit token" in result.reason
    assert not _rungs_fired(tool, element)


def test_a_different_control_is_refused_before_any_rung() -> None:
    tool = _tool([_probe(box=BOX)])
    element = MagicMock()
    other = ControlIdentity(tag="button", name="apply", id="submit-2")
    result = tool.click(element, irreversible=True, expect=other)
    assert not result and result.rung == "probe"
    assert result.reason == "token-target-mismatch: id"
    assert not _rungs_fired(tool, element)


def test_an_unreadable_probe_is_refused_for_an_irreversible_click() -> None:
    """Undetermined proceeds on an ordinary click; never on one that may submit."""
    tool = _tool([_probe(box=BOX)], probe_raises=True)
    element = MagicMock()
    result = tool.click(element, irreversible=True, expect=SUBMIT)
    assert not result and result.rung == "probe"
    assert not _rungs_fired(tool, element)


def test_the_planned_control_is_clicked() -> None:
    tool = _tool([_probe(box=BOX)])
    element = MagicMock()
    result = tool.click(element, irreversible=True, expect=SUBMIT)
    assert result and result.rung == "pointer"


def test_an_ordinary_click_needs_no_token() -> None:
    tool = _tool([_probe(box=BOX)])
    assert tool.click(MagicMock())

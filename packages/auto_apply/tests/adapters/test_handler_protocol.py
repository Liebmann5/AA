
"""Pins for the handler seam — two collaborators, no wider (Stage 2a).

A handler owns widget mechanics: which element, in what order. It owns no
timing, no pacing constants and no RNG. Those live in the PageActionService
tool, once, config-driven and seeded.

The seam is deliberately tiny and these pins keep it that way:

    * exactly three verbs on the tool — click, type_text, settle;
    * exactly one method on the readiness port — wait_for_dom_stable;
    * handlers may reach nothing else on either collaborator;
    * no handler contains a sleep, a pacing constant, or an evasion import.

If a handler needs something outside this seam, the work belongs in the tool.
Widening either protocol is how that rule quietly stops being true.
"""
import ast
import pathlib

import pytest
from unittest.mock import MagicMock

HANDLERS = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "src"
    / "auto_apply"
    / "adapters"
    / "secondary"
    / "interaction"
    / "handlers"
)


def _protocol_methods(cls) -> set[str]:
    """Public method names declared on a Protocol class."""
    return {
        name
        for name in vars(cls)
        if not name.startswith("_") and callable(getattr(cls, name, None))
    }


# ─────────────────────────────────────────────────────────────────────────────
# The two protocols may not widen
# ─────────────────────────────────────────────────────────────────────────────


def test_the_tool_protocol_is_exactly_three_verbs():
    """click / type_text / settle — nothing more, or this is a back door."""
    from auto_apply.domain.ports.interaction_primitives_port import (
        PageActionPrimitives,
    )

    assert _protocol_methods(PageActionPrimitives) == {
        "click",
        "type_text",
        "settle",
    }


def test_the_readiness_protocol_is_exactly_one_method():
    """A single-method port, so handlers cannot reach the whole DOMObserver."""
    from auto_apply.domain.ports.interaction_primitives_port import DomReadinessPort

    assert _protocol_methods(DomReadinessPort) == {"wait_for_dom_stable"}


def test_the_real_collaborators_satisfy_their_protocols():
    """The protocols describe the shipped objects, not an aspiration."""
    from auto_apply.adapters.secondary.interaction.dom_observer import DOMObserver
    from auto_apply.application.services.page_action.service import PageActionService
    from auto_apply.domain.ports.interaction_primitives_port import (
        DomReadinessPort,
        PageActionPrimitives,
    )

    for verb in _protocol_methods(PageActionPrimitives):
        assert hasattr(PageActionService, verb), f"tool is missing {verb}"
    for method in _protocol_methods(DomReadinessPort):
        assert hasattr(DOMObserver, method), f"observer is missing {method}"

    assert isinstance(
        PageActionService.__new__(PageActionService), PageActionPrimitives
    )
    assert isinstance(DOMObserver.__new__(DOMObserver), DomReadinessPort)


# ─────────────────────────────────────────────────────────────────────────────
# Handlers may reach nothing else on either collaborator
# ─────────────────────────────────────────────────────────────────────────────


def _attribute_calls(source: str, receiver: str) -> set[str]:
    """Names accessed on ``self.<receiver>`` anywhere in a module."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Attribute):
            continue
        inner = node.value
        if (
            isinstance(inner, ast.Attribute)
            and inner.attr == receiver
            and isinstance(inner.value, ast.Name)
            and inner.value.id == "self"
        ):
            found.add(node.attr)
    return found


def test_handlers_touch_only_the_three_tool_verbs():
    """AST-checked across every handler module, including the base."""
    reached: set[str] = set()
    for path in sorted(HANDLERS.glob("*.py")):
        reached |= _attribute_calls(path.read_text(encoding="utf-8"), "_act")

    assert reached <= {"click", "type_text", "settle"}, (
        f"handlers reached beyond the three-verb protocol: "
        f"{sorted(reached - {'click', 'type_text', 'settle'})}"
    )


def test_handlers_touch_only_the_one_readiness_method():
    reached: set[str] = set()
    for path in sorted(HANDLERS.glob("*.py")):
        reached |= _attribute_calls(path.read_text(encoding="utf-8"), "_ready")

    assert reached <= {"wait_for_dom_stable"}, (
        f"handlers reached beyond the readiness port: "
        f"{sorted(reached - {'wait_for_dom_stable'})}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Handlers are timing-free
# ─────────────────────────────────────────────────────────────────────────────


def test_no_handler_sleeps_or_imports_the_evasion_module():
    offenders = []
    for path in sorted(HANDLERS.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "time.sleep" in text or "import time" in text:
            offenders.append(f"{path.name}: timing")
        if "human_like" in text or "components import behavior" in text:
            offenders.append(f"{path.name}: evasion")
    assert not offenders, f"handlers still own timing: {offenders}"


def test_the_two_one_second_waits_are_gone():
    """select.py's filter wait and file.py's upload wait were the fork.

    They were readiness, not pacing, and settle would have shortened them —
    on a combobox that means matching against a stale option list and
    submitting the wrong value to a real employer.
    """
    for name in ("select.py", "file.py"):
        text = (HANDLERS / name).read_text(encoding="utf-8")
        assert "time.sleep(1.0)" not in text
        assert "_await_dom_ready()" in text, f"{name} lost its readiness wait"


# ─────────────────────────────────────────────────────────────────────────────
# Degradation — direct construction must not explode
# ─────────────────────────────────────────────────────────────────────────────


def test_handlers_work_without_either_collaborator():
    """Worst-case/static: no tool and no observer, no crash, no invented pacing."""
    from auto_apply.adapters.secondary.interaction.handlers.text import (
        TextInputHandler,
    )

    handler = TextInputHandler(browser=MagicMock())
    element = MagicMock()

    handler._click(element)
    element.click.assert_called_once()

    handler._type(element, "hello")
    element.send_keys.assert_called_once_with("hello")

    handler._settle()
    assert handler._await_dom_ready() is True


def test_handlers_delegate_to_the_collaborators_when_present():
    from auto_apply.adapters.secondary.interaction.handlers.text import (
        TextInputHandler,
    )

    tool, readiness, element = MagicMock(), MagicMock(), MagicMock()
    readiness.wait_for_dom_stable.return_value = True

    handler = TextInputHandler(
        browser=MagicMock(), page_action=tool, readiness=readiness
    )

    handler._click(element)
    handler._type(element, "hi")
    handler._await_dom_ready()

    tool.click.assert_called_once_with(element)
    tool.type_text.assert_called_once_with(element, "hi")
    readiness.wait_for_dom_stable.assert_called_once()
    element.click.assert_not_called()
    element.send_keys.assert_not_called()


def test_every_handler_receives_both_collaborators_from_the_interactor():
    from auto_apply.adapters.secondary.interaction.human_like_adapter import (
        UnifiedInteractor,
    )

    tool, readiness = MagicMock(), MagicMock()
    interactor = UnifiedInteractor(
        browser=MagicMock(), page_action=tool, readiness=readiness
    )

    for attr in (
        "text_handler",
        "select_handler",
        "file_handler",
        "checkable_handler",
        "date_handler",
    ):
        handler = getattr(interactor, attr)
        assert handler._act is tool, f"{attr} did not receive the tool"
        assert handler._ready is readiness, f"{attr} did not receive readiness"


# ─────────────────────────────────────────────────────────────────────────────
# Boundary
# ─────────────────────────────────────────────────────────────────────────────


def test_the_select_handler_no_longer_imports_across_the_boundary():
    """TextMatcher is injected through the domain port, not constructed here."""
    text = (HANDLERS / "select.py").read_text(encoding="utf-8")
    assert "application.services.text_matching" not in text
    assert "TextMatcher()" not in text

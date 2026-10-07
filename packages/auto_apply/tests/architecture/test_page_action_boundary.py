"""Boundary pins for the interaction-tool split (call 2).

`page_action/service.py` grew to ~1,720 lines and 54 methods — navigation,
waiting, the probe, the click ladder, hover, typing, select/checkbox, four
scroll primitives, pacing and fidgets in one class. It is now a thin facade
over one module per concern. These pins hold the split:

    * the facade stays thin — no probe JS, no component internals in it;
    * no component reaches into another component's internals (they share
      ONLY the injected PageActionContext and each other's public methods);
    * the facade constructs each component exactly once;
    * the public surface every caller was built against is preserved;
    * the facade still satisfies the narrow ports.
"""
from __future__ import annotations

import ast
import pathlib

_PKG_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PAGE_ACTION = (
    _PKG_ROOT
    / "src"
    / "auto_apply"
    / "application"
    / "services"
    / "page_action"
)
_SERVICE_SRC = _PAGE_ACTION / "service.py"

_COMPONENT_MODULES = ("probe.py", "pacing.py", "scrolling.py", "clicking.py", "text_input.py")
_COMPONENT_ATTRS = ("_probe", "_pacing", "_scroller", "_clicker", "_typer")

#: The surface every caller was built against before the split.
_PUBLIC_SURFACE = frozenset({
    "navigate", "navigate_back", "navigate_to_blank",
    "current_url", "page_title", "page_source",
    "find", "find_all", "wait_for", "wait_for_any", "is_present",
    "click", "click_by", "hover",
    "type_text", "clear_and_type", "select_option", "check_checkbox",
    "scroll_to", "scroll_into_view", "scroll_container", "scroll_to_bottom",
    "reveal_page",
    "settle", "macro_pause", "warmup_pause",
    "execute_script",
})


def _service_text() -> str:
    return _SERVICE_SRC.read_text(encoding="utf-8", errors="ignore")


def test_the_component_modules_exist_and_the_facade_imports_them() -> None:
    for name in _COMPONENT_MODULES + ("result.py", "state.py"):
        assert (_PAGE_ACTION / name).is_file(), f"missing component: {name}"
    text = _service_text()
    for dotted in ("probe", "pacing", "scrolling", "clicking", "text_input", "result", "state"):
        assert f"page_action.{dotted} import" in text, (
            f"the facade does not import page_action.{dotted}"
        )


def test_the_facade_stays_thin() -> None:
    """No probe JS and no component internals may live in service.py."""
    text = _service_text()
    assert "elementFromPoint" not in text, "the probe JS is back in the facade"
    for forbidden in (
        "def _wheel_toward",
        "def _micro_delay",
        "def _settle_pause",
        "def _idle_with_fidgets",
        "def _approach_path",
        "def _probe(",
        "def scroll_page",
    ):
        assert forbidden not in text, f"component internal in the facade: {forbidden}"


def test_no_component_reaches_into_another_components_internals() -> None:
    """AST: components may use each other's PUBLIC methods only.

    `self._state.*` is exempt BY DESIGN — the context is the shared state
    object, not a component. Anything else private on an injected component
    (self._probe/self._pacing/self._scroller/self._clicker/self._typer) is a
    boundary violation.
    """
    violations: list[str] = []
    for name in _COMPONENT_MODULES:
        path = _PAGE_ACTION / name
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or not node.attr.startswith("_"):
                continue
            inner = node.value
            if (
                isinstance(inner, ast.Attribute)
                and inner.attr in _COMPONENT_ATTRS
                and isinstance(inner.value, ast.Name)
                and inner.value.id == "self"
            ):
                violations.append(f"{name}:{node.lineno} self.{inner.attr}.{node.attr}")
    assert not violations, (
        "component internals reached across the boundary:\n" + "\n".join(violations)
    )


def test_the_facade_constructs_each_component_exactly_once() -> None:
    text = _service_text()
    for call in (
        "PageActionContext(",
        "TargetProbe(self._state)",
        "Pacing(self._state)",
        "Scroller(self._state",
        "Clicker(self._state",
        "Typer(self._state",
    ):
        assert text.count(call) == 1, f"expected exactly one {call!r} in the facade"


def test_the_public_surface_is_preserved() -> None:
    from auto_apply.application.services.page_action.service import PageActionService

    missing = [name for name in sorted(_PUBLIC_SURFACE) if not hasattr(PageActionService, name)]
    assert not missing, f"the facade lost public methods in the split: {missing}"


def test_the_facade_still_satisfies_the_narrow_ports() -> None:
    from auto_apply.application.services.page_action.service import (
        ActionResult,
        PageActionService,
    )
    from auto_apply.domain.ports.interaction_primitives_port import (
        PageActionPrimitives,
        PageNavigationPort,
    )

    assert isinstance(PageActionService.__new__(PageActionService), PageActionPrimitives)
    assert isinstance(PageActionService.__new__(PageActionService), PageNavigationPort)
    # ActionResult stays importable from the facade (the old import path).
    assert ActionResult.__name__ == "ActionResult"
    # And the guard's pinned contract is intact.
    assert "elementFromPoint" in PageActionService._PROBE_SCRIPT
    assert "pane-clip" in PageActionService._PROBE_SCRIPT

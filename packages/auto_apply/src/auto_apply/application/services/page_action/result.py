"""ActionResult — the shared currency of every tool operation.

Kept in its own module so every component (probe, pacing, scrolling,
clicking, typing) and the facade import it from exactly one place.
"""
from __future__ import annotations

from auto_apply.domain.ports.browser_port import ElementInterface


class ActionResult:
    """Typed result from every PageActionService operation.

    Evaluates as bool (True = success) for concise `if page.click(btn):` usage,
    while also carrying `reason` for diagnostic logging on failure.

    Attributes:
        success: True if the operation completed as intended.
        reason:  Human-readable description of why it failed, or "ok".
        element: The element acted on, if the operation produced one.
        rung:    Which ladder rung produced the outcome ("" when not a
            ladder operation): "probe" | "pointer" | "keyboard" | "native" |
            "js" | "wheel" | "js-scroll" | "none".
        effect:  Observed page effect after the action, for callers that
            decide retries: "navigation" | "dom-change" | "focus-change" |
            "none" | "".
    """

    __slots__ = ("success", "reason", "element", "rung", "effect")

    def __init__(
        self,
        success: bool,
        reason: str = "ok",
        element: ElementInterface | None = None,
        rung: str = "",
        effect: str = "",
    ) -> None:
        self.success = success
        self.reason = reason
        self.element = element
        self.rung = rung
        self.effect = effect

    def __bool__(self) -> bool:
        return self.success

    def __repr__(self) -> str:
        return f"ActionResult(success={self.success}, reason={self.reason!r})"

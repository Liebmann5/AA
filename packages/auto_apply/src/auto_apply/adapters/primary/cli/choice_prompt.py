"""Ask a multiple-choice question in the terminal (``choice_field`` rules).

The terminal twin of ``gui/choice_widget.ChoiceBox``: the choices are
printed one per line with their numbers (screen-reader friendly — no
drawing), Enter keeps the current choice, and the answer may be the number,
the value or a unique beginning of it ("jr" for "Jr."). A wrong answer is
refused with the list, never guessed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from auto_apply.application.services.choice_field import (
    Choice,
    choice_index,
    parse_choice,
)


def ask_choice(question: str, choices: Sequence[Choice], current: object = None, *,
               ask: Callable[[str], str] | None = None,
               say: Callable[[str], None] | None = None) -> str | None:
    """Ask ``question``; returns the chosen stored value (None for "(none)").

    Ctrl+C or the end of input keeps the current choice. ``ask``/``say``
    default to ``input``/``print`` looked up at call time.
    """
    ask = ask or input
    say = say or print
    choices = tuple(choices)
    keep = choice_index(choices, current)
    say(f"  {question}")
    for i, c in enumerate(choices, 1):
        mark = "  (current)" if i - 1 == keep else ""
        say(f"    {i}. {c.label}{mark}")
    while True:
        try:
            raw = ask(f"  Choice [{keep + 1}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            say("")
            return choices[keep].value if choices else None
        if not raw:
            return choices[keep].value if choices else None
        try:
            return parse_choice(choices, raw)
        except ValueError as exc:
            say(f"  {exc}")


__all__ = ["ask_choice"]

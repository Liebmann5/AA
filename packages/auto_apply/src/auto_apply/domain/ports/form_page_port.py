"""Ports of the step engine: the live form page, and answer sources.

``FormPagePort`` is everything the engine needs from a live application
page and nothing more: read the current step, read controls back, and
resolve a control to an element the shared interaction tool can operate.
The framework-specific work (Selenium or Playwright, shadow roots, native
selects, file inputs) lives in the adapter that implements it
(``adapters/secondary/perception/pagecomp_form.py``), in one place, so the
engine is the same on every browser and every framework.

``AnswerSourcePort`` is the extension point for answers. AA ships sources
that answer only from what the person declared (the profile, saved
answers, earlier answers in the session). Any other tool — a local model,
a browser extension bridge, an assistant the person trusts — joins by
implementing ``propose`` and being named in ``applications.answer_sources``;
the engine never needs to change. A source returns ``None`` when it has no
answer; it never raises into the engine (the engine contains it anyway).

Contracts:

* every method of ``FormPagePort`` returns a value and never raises: a
  browser error is "not found", an empty list, or ``False``;
* ``read_states`` returns one state per ref, in order; a control that could
  not be found reads ``present=False``;
* ``locate`` checks the control's identity (tag, and name/id when known)
  before returning it, so a stale reading can never steer an action onto a
  different element.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol, runtime_checkable

from auto_apply.domain.applications.answers import Answer, AnswerContext
from auto_apply.domain.applications.form_model import (
    ControlRef,
    ControlState,
    FormQuestion,
    FormStep,
)
from auto_apply.domain.ports.browser_port import ElementInterface


@runtime_checkable
class FormPagePort(Protocol):
    """The live application page, as the step engine needs it."""

    def read_step(self) -> FormStep | None:
        """Read the page and return its application-form step (None: no read)."""
        ...

    def read_states(self, refs: Sequence[ControlRef]) -> list[ControlState]:
        """Read each control back: presence, visibility, value, validity."""
        ...

    def locate(self, ref: ControlRef) -> ElementInterface | None:
        """The live element for ``ref``, identity-checked, or None."""
        ...

    def listbox_options(self, ref: ControlRef) -> list[str]:
        """Visible option texts of the popup a custom combobox has open."""
        ...

    def locate_option(self, ref: ControlRef, index: int) -> ElementInterface | None:
        """The element of option ``index`` in :meth:`listbox_options` order."""
        ...

    def choose_native_option(self, ref: ControlRef, index: int) -> bool:
        """Select option ``index`` of a native ``<select>`` (OS-drawn list)."""
        ...

    def set_files(self, ref: ControlRef, path: str) -> bool:
        """Give a file input one file, without opening the OS file dialog."""
        ...

    def set_value_by_script(self, ref: ControlRef, value: str) -> bool:
        """The recorded last resort: set a value by script, with the events
        frameworks listen for. Used only when trusted typing could not set
        the value and ``applications.script_fill_fallback`` allows it."""
        ...

    def focus(self, ref: ControlRef) -> bool:
        """Give a control the keyboard focus, without scrolling (the
        interaction tool scrolls; ``ControlActuator.focus_question``), so a
        person asked to answer it in the browser — with a screen reader, a
        magnifier or the keyboard alone — lands on it. True when the control
        holds the focus afterwards."""
        ...

    def control_census(self) -> int:
        """A fingerprint of which form controls are shown now and the words
        that name them, never their values (a cheap change signal: equal while
        the same questions are shown, different when a choice hides one
        question and shows another, or a re-rendered control asks something
        else under the same element)."""
        ...

    def quiet_detector(self, quiet: int, t_max: float) -> Callable[[object, float], str]:
        """A fresh change-settling detector for one wait.

        Call it with each new signature of the controls and the seconds since
        the wait began; it answers ``"settled"`` after ``quiet`` equal
        readings in a row, ``"timeout"`` once ``t_max`` has passed, and
        ``"settling"`` otherwise. The engine owns the polling and the clock;
        the reading library's algorithm stays behind this port.
        """
        ...


@runtime_checkable
class AnswerSourcePort(Protocol):
    """One place answers come from."""

    name: str

    def propose(self, question: FormQuestion, context: AnswerContext) -> Answer | None:
        """An answer to ``question``, or None when this source has none."""
        ...


__all__ = ["AnswerSourcePort", "FormPagePort"]

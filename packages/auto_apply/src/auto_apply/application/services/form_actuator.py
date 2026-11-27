"""Operating one question's widget, then proving the value took. Application layer.

The actuator is the "act and verify" half of the step engine. For each
widget shape it does what a person does, through the shared interaction tool
(``PageActionService``: trusted pointer movement, keystroke rhythm, pacing,
the occlusion guard), and then reads the control back through the page port.
A fill counts only when the read-back shows the value (E2E-A6): a fill that
raised nothing but left the field empty is a failed fill.

Widget recipes (the actuator owns order, never timing):

* text / textarea / contenteditable — click into the field, type the value
  (single-line fields never receive a newline: Enter in a text input submits
  the form); a field that already holds text is cleared first. Long answers
  are typed in word chunks so a 1,500-character summary does not take
  minutes. Read back; a masked field (a phone formatted by the page)
  compares as digits.
* native select — the option list is drawn by the operating system and
  cannot be pointer-clicked on every framework, so the adapter selects the
  option index; read back the selected text.
* custom combobox (ARIA ``combobox``, react-select and kin) — click to
  open, type a filter when it accepts typing, read the visible options,
  choose one by the matching ladder, click it; read back the shown value.
* radio / checkbox — click the option (its label when the input itself is
  visually replaced); read back ``checked``.
* file — the adapter gives the input the file (no OS dialog), then the page
  is given time to process the upload.
* native date input — set by script with the input events (recorded),
  because typing into it depends on the operating system's date format.

The script fallback (``set_value_by_script``) is used only when trusted
typing failed its read-back and ``applications.script_fill_fallback`` is on;
every use is recorded on the outcome (``rung="script"``) for research.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from auto_apply.domain.applications.answers import Answer
from auto_apply.domain.applications.form_model import (
    ControlRef,
    ControlState,
    FormButton,
    FormOption,
    FormQuestion,
    QuestionKind,
)
from auto_apply.domain.applications.option_matching import (
    match_option,
    normalize,
    same_value,
    shows_choice,
)
from auto_apply.domain.ports.browser_port import ElementInterface
from auto_apply.domain.ports.form_page_port import FormPagePort
from auto_apply.domain.types import Keys

logger = logging.getLogger(__name__)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class FormTool(Protocol):
    """The interaction-tool verbs the actuator uses (``PageActionService``)."""

    def click(self, element: ElementInterface, *, irreversible: bool = False) -> Any: ...

    def type_text(self, element: ElementInterface, text: str) -> Any: ...

    def clear_and_type(self, element: ElementInterface, text: str) -> Any: ...

    def settle(self) -> None: ...

    def scroll_into_view(self, element: ElementInterface) -> Any: ...

    def macro_pause(self, min_s: float | None = None, max_s: float | None = None) -> None: ...


@dataclass(frozen=True)
class ActuatorSettings:
    script_fallback: bool = True
    chunk_threshold: int = 240
    chunk_words: int = 6
    option_threshold: float = 0.6
    combobox_reads: int = 6
    #: Reads (one settle apart) to wait for a radio or checkbox that updates
    #: its state late, before its label is clicked as a fallback.
    option_settle_reads: int = 3


@dataclass(frozen=True)
class FillOutcome:
    """What one fill did. ``observed`` is the read-back, never logged."""

    ok: bool
    rung: str
    reason: str = ""
    chosen: str = ""
    observed: str = ""

    @property
    def verified(self) -> bool:
        return self.ok


def _ok(result: Any) -> bool:
    """A tool result: None means "no detail" (success), else truthiness."""
    return result is None or bool(result)


class ControlActuator:
    """Acts on one question through the tool and verifies through the page."""

    def __init__(
        self,
        page: FormPagePort,
        tool: FormTool,
        settings: ActuatorSettings | None = None,
        wait_ready: Callable[[float], Any] | None = None,
    ) -> None:
        self._page = page
        self._tool = tool
        self._s = settings or ActuatorSettings()
        self._wait_ready = wait_ready

    # ------------------------------------------------------------------
    def fill(self, q: FormQuestion, answer: Answer) -> FillOutcome:
        try:
            if q.kind == QuestionKind.FILE:
                return self._file(q, answer)
            if q.kind == QuestionKind.SELECT:
                return self._native_select(q, answer)
            if q.kind == QuestionKind.MULTI_SELECT:
                return self._native_multi(q, answer)
            if q.kind == QuestionKind.COMBOBOX:
                return self._combobox(q, answer)
            if q.kind == QuestionKind.RADIO:
                return self._radio(q, answer)
            if q.kind == QuestionKind.CHECKBOX:
                return self._checkbox(q, answer)
            if q.kind == QuestionKind.CHECKBOX_GROUP:
                return self._checkbox_group(q, answer)
            if q.kind == QuestionKind.DATE:
                return self._date(q, answer)
            if q.kind in (QuestionKind.TEXT, QuestionKind.TEXTAREA):
                return self._text(q, answer)
        except Exception as exc:  # contained: one widget never ends the step
            logger.debug("actuator: %s raised %s", q.primary.describe(), type(exc).__name__)
            return FillOutcome(False, "error", f"{type(exc).__name__}")
        return FillOutcome(False, "none", f"unsupported widget: {q.kind}")

    def focus_question(self, q: FormQuestion) -> bool:
        """Scroll a question into view (through the interaction tool, the one
        place AA scrolls) and give its control the keyboard focus, so a
        person asked to answer it in the browser lands on it. A radio or
        checkbox drawn by a styled label over a hidden input is scrolled to by
        its label and focused on its input. Never raises."""
        ref = q.primary
        shown = ref
        if q.options and q.options[0].control is not None:
            ref = q.options[0].control
            shown = ref
            state = self._state(ref)
            own = state.own_visible if state.own_visible is not None else state.visible
            if not own and q.options[0].click_target is not None:
                shown = q.options[0].click_target
        try:
            el = self._page.locate(shown)
            if el is not None:
                self._tool.scroll_into_view(el)
            return bool(self._page.focus(ref))
        except Exception as exc:
            logger.debug("actuator: focus failed: %s", type(exc).__name__)
            return False

    def click_button(self, button: FormButton, *,
                     confirmed: bool = False) -> tuple[bool | None, Any]:
        """Click a control that moves the form on (Next/Continue).

        The one place the engine clicks a button, so the one place the
        no-submit rule is enforced: a button that may submit
        (:attr:`FormButton.may_submit`) is refused unless the person (or their
        autonomous-submission setting) confirmed this click. The final submit
        is never clicked here; the workflow clicks it after its gate.

        Returns ``(ok, detail)``: ``ok`` True — the tool clicked; False — no
        click happened (refused, not found, or the tool said it did not
        click); None — the tool raised mid-click, so the click may or may not
        have reached the page.
        """
        if button.may_submit and not confirmed:
            logger.warning("actuator: refused to click %r: it may submit the application",
                           button.text[:40])
            return False, "refused-may-submit"
        el = self._page.locate(button.control)
        if el is None:
            return False, "not-found"
        try:
            result = self._tool.click(el)
        except Exception as exc:
            logger.warning("actuator: the click on %r raised %s; it may have happened",
                           button.text[:40], type(exc).__name__)
            return None, "click-raised"
        return _ok(result), result

    def locate(self, ref: ControlRef) -> ElementInterface | None:
        return self._page.locate(ref)

    # ------------------------------------------------------------------
    def _state(self, ref: ControlRef) -> ControlState:
        states = self._page.read_states([ref])
        return states[0] if states else ControlState(present=False)

    def _text(self, q: FormQuestion, answer: Answer) -> FillOutcome:
        value = answer.text
        if not value:
            return FillOutcome(False, "none", "empty-answer")
        if q.kind == QuestionKind.TEXT:
            value = " ".join(value.split())
        if q.max_length and len(value) > q.max_length:
            value = value[: q.max_length].rstrip()
        ref = q.primary
        el = self._page.locate(ref)
        if el is None:
            return FillOutcome(False, "none", "not-found")
        before = self._state(ref)
        if before.value.strip():
            ok = _ok(self._tool.clear_and_type(el, value))
            rung = "clear-and-type"
        elif len(value) > self._s.chunk_threshold:
            ok = self._type_chunked(el, value)
            rung = "type-chunked"
        else:
            ok = _ok(self._tool.type_text(el, value))
            rung = "type"
        after = self._state(ref)
        if ok and same_value(after.value, value):
            return FillOutcome(True, rung, observed=after.value)
        if self._s.script_fallback and self._page.set_value_by_script(ref, value):
            self._tool.settle()
            again = self._state(ref)
            if same_value(again.value, value):
                return FillOutcome(True, "script", "typing-did-not-take", observed=again.value)
            return FillOutcome(False, "script", "value-did-not-take", observed=again.value)
        return FillOutcome(False, rung, "read-back-mismatch", observed=after.value)

    def _type_chunked(self, el: ElementInterface, value: str) -> bool:
        """Long text: focus with the tool, then send it a few words at a time,
        pausing with the tool between chunks (the tool owns timing)."""
        if not _ok(self._tool.click(el)):
            return False
        words = re.split(r"(\s+)", value)
        chunk: list[str] = []
        count = 0
        for part in words:
            chunk.append(part)
            if part.strip():
                count += 1
            if count >= self._s.chunk_words:
                el.send_keys("".join(chunk))
                self._tool.settle()
                chunk, count = [], 0
        if chunk:
            el.send_keys("".join(chunk))
        self._tool.settle()
        return True

    def _native_select(self, q: FormQuestion, answer: Answer) -> FillOutcome:
        labels = [o.label for o in q.options]
        m = match_option(answer.wordings(), labels, threshold=self._s.option_threshold,
                         values=[o.value for o in q.options])
        if not m.found:
            return FillOutcome(False, "none", "no-matching-option")
        chosen = labels[m.index]
        if not self._page.choose_native_option(q.primary, m.index):
            return FillOutcome(False, "native-select", "select-failed", chosen=chosen)
        self._tool.settle()
        after = self._state(q.primary)
        if same_value(after.value, chosen) or shows_choice(after.value, chosen):
            return FillOutcome(True, "native-select", m.rung, chosen=chosen, observed=after.value)
        return FillOutcome(False, "native-select", "read-back-mismatch", chosen=chosen,
                           observed=after.value)

    def _native_multi(self, q: FormQuestion, answer: Answer) -> FillOutcome:
        """Select every wanted option; succeed only if the read-back shows all."""
        labels = [o.label for o in q.options]
        items: list[Sequence[str]] = (
            [(m,) for m in answer.many] if answer.many else [answer.wordings()]
        )
        picked: list[str] = []
        for wordings in items:
            m = match_option(wordings, labels, threshold=self._s.option_threshold,
                             values=[o.value for o in q.options])
            if m.found and labels[m.index] not in picked and \
                    self._page.choose_native_option(q.primary, m.index):
                picked.append(labels[m.index])
        if not picked:
            return FillOutcome(False, "native-select", "no-matching-option")
        self._tool.settle()
        after = self._state(q.primary)
        shown = all(shows_choice(after.value, p) or same_value(after.value, p) for p in picked)
        ok = shown and len(picked) == len(items)
        return FillOutcome(ok, "native-select", "" if ok else
                           ("partial" if shown else "read-back-mismatch"),
                           chosen=", ".join(picked), observed=after.value)

    def _combobox(self, q: FormQuestion, answer: Answer) -> FillOutcome:
        ref = q.primary
        el = self._page.locate(ref)
        if el is None:
            return FillOutcome(False, "none", "not-found")
        wordings = answer.wordings()
        if not wordings:
            return FillOutcome(False, "none", "empty-answer")
        typeable = ref.tag == "input" or ref.type in ("contenteditable", "role:textbox")
        if not _ok(self._tool.click(el)):
            return FillOutcome(False, "pointer", "could-not-open")
        typed = ""
        if typeable:
            typed = wordings[0][:40]
            self._tool.type_text(el, typed)
        options = self._await_options(ref)
        m = match_option(wordings, options, threshold=self._s.option_threshold)
        if not m.found and typeable and typed:
            # A long filter can hide the option ("United States" vs "USA"):
            # erase it and filter on the first word instead.
            for _ in range(len(typed)):
                el.send_keys(Keys.BACKSPACE)
            first = typed.split()[0] if typed.split() else ""
            if first and first != typed:
                self._tool.type_text(el, first)
            options = self._await_options(ref)
            m = match_option(wordings, options, threshold=self._s.option_threshold)
        if not m.found:
            try:
                el.send_keys(Keys.ESCAPE)
            except Exception:
                pass
            return FillOutcome(False, "combobox", "no-matching-option")
        chosen = options[m.index]
        opt_el = self._page.locate_option(ref, m.index)
        if opt_el is None or not _ok(self._tool.click(opt_el)):
            return FillOutcome(False, "combobox", "option-click-failed", chosen=chosen)
        self._tool.settle()
        after = self._state(ref)
        if shows_choice(after.value, chosen) or same_value(after.value, chosen):
            return FillOutcome(True, "combobox", m.rung, chosen=chosen, observed=after.value)
        return FillOutcome(False, "combobox", "read-back-mismatch", chosen=chosen,
                           observed=after.value)

    def _await_options(self, ref: ControlRef) -> list[str]:
        options: list[str] = []
        for _ in range(max(1, self._s.combobox_reads)):
            options = self._page.listbox_options(ref)
            if options:
                break
            self._tool.settle()
        return options

    def _click_option(self, option: FormOption) -> bool:
        """Click a radio or checkbox the way a person does: on the input when
        the input itself is shown, otherwise on its label (a styled label over
        a hidden input).

        When a click on the input did not visibly change it, AA waits (a
        bounded number of settles) for a widget that updates its state a
        moment later, and clicks the label only if the input definitely did
        not change — a second click on a widget whose first click is merely
        late would undo it."""
        control = option.control
        if control is None:
            return False
        before = self._state(control)
        own = before.own_visible if before.own_visible is not None else before.visible
        label = option.click_target
        target = control if own or label is None else label
        el = self._page.locate(target)
        clicked = el is not None and _ok(self._tool.click(el))
        if target is control and label is not None and clicked:
            if not self._changed_after_wait(control, before.checked):
                el = self._page.locate(label)
                clicked = el is not None and _ok(self._tool.click(el))
        return clicked

    def _changed_after_wait(self, ref: ControlRef, checked_before: bool | None) -> bool:
        """Has the control's checked state left ``checked_before`` within
        ``option_settle_reads`` settles? (False only when it never did.)"""
        for i in range(max(1, self._s.option_settle_reads)):
            if i:
                self._tool.settle()
            if self._state(ref).checked != checked_before:
                return True
        return False

    def _radio(self, q: FormQuestion, answer: Answer) -> FillOutcome:
        labels = [o.label for o in q.options]
        m = match_option(answer.wordings(), labels, threshold=self._s.option_threshold,
                         values=[o.value for o in q.options])
        if not m.found:
            return FillOutcome(False, "none", "no-matching-option")
        option = q.options[m.index]
        if option.control is None or not self._click_option(option):
            return FillOutcome(False, "pointer", "click-failed", chosen=option.label)
        after = self._state(option.control)
        if after.checked:
            return FillOutcome(True, "pointer", m.rung, chosen=option.label, observed="checked")
        return FillOutcome(False, "pointer", "not-checked-after-click", chosen=option.label)

    def _checkbox(self, q: FormQuestion, answer: Answer) -> FillOutcome:
        desired = True if answer.checked is None else bool(answer.checked)
        option = q.options[0] if q.options else FormOption(label=q.label, control=q.primary)
        control = option.control or q.primary
        before = self._state(control)
        if bool(before.checked) == desired:
            return FillOutcome(True, "none", "already", observed=str(desired).lower())
        if not self._click_option(FormOption(option.label, option.value, control,
                                             option.click_target)):
            return FillOutcome(False, "pointer", "click-failed")
        after = self._state(control)
        if bool(after.checked) == desired:
            return FillOutcome(True, "pointer", observed=str(desired).lower())
        return FillOutcome(False, "pointer", "state-unchanged-after-click")

    def _checkbox_group(self, q: FormQuestion, answer: Answer) -> FillOutcome:
        """Tick every wanted option, then read the whole group back once.

        Each wanted item is one answer (``answer.many``), or the single answer
        with its alternative wordings. Success is decided by the final read of
        the group, not by each click: a widget that unticks an earlier box
        while a later one is ticked is caught.
        """
        labels = [o.label for o in q.options]
        items: list[Sequence[str]] = (
            [(m,) for m in answer.many] if answer.many else [answer.wordings()]
        )
        targets: list[FormOption] = []
        for wordings in items:
            m = match_option(wordings, labels, threshold=self._s.option_threshold,
                             values=[o.value for o in q.options])
            if m.found and q.options[m.index].control is not None:
                option = q.options[m.index]
                if option not in targets:
                    targets.append(option)
        if not targets:
            return FillOutcome(False, "pointer", "no-matching-option")
        for option in targets:
            assert option.control is not None
            if not self._state(option.control).checked:
                self._click_option(option)
        final = self._page.read_states([o.control for o in targets if o.control is not None])
        picked = [o.label for o, st in zip(targets, final) if st.checked]
        complete = len(picked) == len(items) == len(targets)
        return FillOutcome(complete, "pointer", "" if complete else "partial",
                           chosen=", ".join(picked))

    def _file(self, q: FormQuestion, answer: Answer) -> FillOutcome:
        if not answer.file_path:
            return FillOutcome(False, "none", "no-file")
        if not self._page.set_files(q.primary, answer.file_path):
            return FillOutcome(False, "set-files", "set-files-failed")
        if self._wait_ready is not None:
            try:
                self._wait_ready(8.0)
            except Exception:
                pass
        after = self._state(q.primary)
        if after.files >= 1:
            return FillOutcome(True, "set-files", observed=f"{after.files} file(s)")
        return FillOutcome(False, "set-files", "no-file-after-set")

    def _date(self, q: FormQuestion, answer: Answer) -> FillOutcome:
        value = (answer.text or "").strip()
        if not _ISO_DATE.match(value):
            return FillOutcome(False, "none", "date-not-iso")
        if not self._s.script_fallback:
            return FillOutcome(False, "none", "script-fallback-off")
        if not self._page.set_value_by_script(q.primary, value):
            return FillOutcome(False, "script", "date-set-failed")
        after = self._state(q.primary)
        ok = normalize(after.value) == normalize(value)
        return FillOutcome(ok, "script", "" if ok else "read-back-mismatch", observed=after.value)

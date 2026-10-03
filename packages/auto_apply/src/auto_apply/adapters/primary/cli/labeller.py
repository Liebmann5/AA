"""The terminal labelling tool: ``python -m auto_apply --label`` (item 5).

Owns the user-facing text and keystrokes; everything it knows comes through
LabellingPort, so a GUI can offer the same studies over the same service.

How a session feels:
* a menu shows every study with a progress bar;
* a page opens in the browser as a safe copy (no scripts, no network);
* questions take a number, several numbers for "pick all that apply", or a
  word; ``s`` skips (it comes back later), ``o`` re-opens, ``q`` saves and
  quits — every answer is saved the moment it is given;
* only AFTER an answer is saved does AA show what it concluded, so the label
  is blind and the reveal is the reward;
* milestones and an insights screen show what the labels have proved so far.
"""

from __future__ import annotations

import time
import webbrowser
from collections.abc import Callable
from pathlib import Path

from auto_apply.domain.models.annotation import AnswerValue, Item, Question
from auto_apply.domain.ports.annotation_port import LabellingPort, StudyProgress

__all__ = ["CliLabeller"]

_BAR = 20


class _Quit(Exception):
    """The person asked to stop."""


class _Skip(Exception):
    """The person skipped this item."""


def _bar(done: int, total: int) -> str:
    if total <= 0:
        return "░" * _BAR
    filled = round(_BAR * done / total)
    return "▓" * filled + "░" * (_BAR - filled)


def _open_in_browser(path: Path) -> bool:
    try:
        return bool(webbrowser.open(path.resolve().as_uri()))
    except Exception:  # noqa: BLE001 — no browser is not an error
        return False


class CliLabeller:
    """Interactive labelling over a LabellingPort."""

    def __init__(
        self,
        port: LabellingPort,
        read: Callable[[str], str] = input,
        write: Callable[[str], None] = print,
        open_page: Callable[[Path], bool] = _open_in_browser,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._port = port
        self._read = read
        self._write = write
        self._open = open_page
        self._clock = clock

    # ── plumbing ────────────────────────────────────────────────────────

    def _ask(self, prompt: str) -> str:
        try:
            return self._read(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            raise _Quit from None

    def _say(self, text: str = "") -> None:
        self._write(text)

    # ── entry ───────────────────────────────────────────────────────────

    def run(self) -> int:
        self._say()
        self._say("  AA Labelling — teach AA to see what you see")
        self._say("  Every answer is saved the moment you give it.")
        try:
            while True:
                progress = self._port.progress()
                self._menu(progress)
                choice = self._ask("  Choose: ").lower()
                if choice in ("q", "quit", "exit", ""):
                    break
                if choice == "i":
                    self._insights(progress)
                    continue
                if choice.isdigit() and 1 <= int(choice) <= len(progress):
                    entry = progress[int(choice) - 1]
                    if entry.open_ended:
                        self._log_loop(entry)
                    else:
                        self._queue_loop(entry)
                    continue
                self._say("  Type a number from the list, i or q.")
        except _Quit:
            pass
        self._say()
        self._say("  Saved. See you next time.")
        return 0

    def _menu(self, progress: tuple[StudyProgress, ...]) -> None:
        self._say()
        for number, p in enumerate(progress, start=1):
            if p.open_ended:
                status = f"{p.done} logged"
            else:
                status = f"{_bar(p.done, p.total)}  {p.done} / {p.total} labelled"
            self._say(f"  {number}) {p.study.title:<34} {status}")
            self._say(f"     {p.study.purpose}")
        self._say("  i) Insights    q) Save and quit")

    # ── a queue study (block pages) ─────────────────────────────────────

    def _queue_loop(self, entry: StudyProgress) -> None:
        study = entry.study
        if entry.total == 0:
            self._say(f"\n  No {study.item_noun}s to label yet for {study.title}.")
            return
        while True:
            item = self._port.next_item(study.id)
            if item is None:
                self._say(f"\n  ★ Every {study.item_noun} is labelled. ★")
                self._show_insights(study.id)
                return
            progress = next(p for p in self._port.progress() if p.study.id == study.id)
            position = progress.done + 1
            self._say()
            self._say(
                f"  {study.item_noun.capitalize()} {position} of {progress.total}  "
                f"{_bar(progress.done, progress.total)}"
            )
            self._say(f"  {item.title}")
            for key, value in item.display:
                self._say(f"     {key}: {value}")
            self._show_page(item)
            started = self._clock()
            try:
                answers = self._answer(study.questions, item)
            except _Skip:
                self._port.skip(item)
                self._say("  Skipped — it will come back at the end.")
                continue
            self._save(item, answers, self._clock() - started)
            self._milestone(progress.done + 1, progress.total)

    def _show_page(self, item: Item) -> None:
        view = self._port.view_path(item)
        if view is None:
            self._say("  (no saved copy to open)")
            return
        if self._open(view):
            self._say(
                "  A safe copy is open in your browser (no scripts, nothing loads)."
            )
        else:
            self._say(f"  Open this file in your browser: {view}")

    # ── an open-ended study (my applications) ──────────────────────────

    def _log_loop(self, entry: StudyProgress) -> None:
        study = entry.study
        while True:
            self._say()
            self._say(f"  Log an {study.item_noun} — {entry.done} so far.")
            url = self._ask("  Posting link (or Enter to go back): ")
            if not url:
                return
            title = self._ask("  Job title (Enter to skip): ")
            item = self._port.log_item(study.id, url, title)
            started = self._clock()
            try:
                answers = self._answer(study.questions, item)
            except _Skip:
                self._say("  Not saved.")
                return
            self._save(item, answers, self._clock() - started)
            entry = next(p for p in self._port.progress() if p.study.id == study.id)
            self._milestone_logged(entry.done)
            again = self._ask("  Log another? [Y/n] ").lower()
            if again in ("n", "no"):
                return

    # ── answering ──────────────────────────────────────────────────────

    def _answer(
        self, questions: tuple[Question, ...], item: Item
    ) -> dict[str, AnswerValue]:
        answers: dict[str, AnswerValue] = {}
        for q in questions:
            if not q.applies(answers):
                continue
            value = self._ask_one(q, item)
            if value is not None:
                answers[q.id] = value
        return answers

    def _ask_one(self, q: Question, item: Item) -> AnswerValue | None:
        self._say()
        self._say(f"  {q.prompt}")
        if q.help:
            self._say(f"  ({q.help})")
        for number, c in enumerate(q.choices, start=1):
            hint = f" — {c.hint}" if c.hint else ""
            self._say(f"    {number:>2}) {c.label}{hint}")
        controls = "[s] skip  [q] save & quit"
        if item.open_path:
            controls = "[o] open again  " + controls
        self._say(f"  {controls}")
        while True:
            raw = self._ask("  > ")
            low = raw.lower()
            if low == "q":
                raise _Quit
            if low == "s":
                raise _Skip
            if low == "o":
                self._show_page(item)
                continue
            parsed, error = self._parse(q, raw)
            if error:
                self._say(f"  {error}")
                continue
            return parsed

    @staticmethod
    def _parse(q: Question, raw: str) -> tuple[AnswerValue | None, str]:
        if q.kind == "text":
            return (raw if raw else None), ""
        if q.kind == "number":
            if not raw:
                return None, "" if not q.required else "A number, please (e.g. 15)."
            try:
                value = float(raw)
            except ValueError:
                return None, "A number, please (e.g. 15)."
            if value < 0:
                return None, "It can't be negative."
            return value, ""
        keys = q.choice_keys()

        def one(token: str) -> str | None:
            if token.isdigit() and 1 <= int(token) <= len(keys):
                return keys[int(token) - 1]
            return token if token in keys else None

        if q.kind == "one":
            key = one(raw.lower())
            if key is None:
                return None, f"Pick 1–{len(keys)}."
            return key, ""
        tokens = [t for t in raw.replace(",", " ").lower().split() if t]
        picked: list[str] = []
        for token in tokens:
            key = one(token)
            if key is None:
                return None, f"'{token}' isn't on the list — use numbers 1–{len(keys)}."
            if key not in picked:
                picked.append(key)
        if not picked:
            return None, "Pick at least one (numbers separated by spaces or commas)."
        alone = [c.key for c in q.choices if c.exclusive and c.key in picked]
        if alone and len(picked) > 1:
            return None, "'None of these' can't be combined with other choices."
        return tuple(picked), ""

    # ── saving and the reveal ──────────────────────────────────────────

    def _save(
        self, item: Item, answers: dict[str, AnswerValue], seconds: float
    ) -> None:
        problems = self._port.record(item, answers, seconds)
        if problems:
            self._say("  Not saved: " + "; ".join(problems))
            return
        self._say()
        self._say("  ✓ Saved.")
        for line in self._port.reveal(item, answers):
            self._say(f"  {line}")

    def _milestone(self, done: int, total: int) -> None:
        """At most one line, the first time a quarter mark is crossed."""
        if total <= 0 or done >= total:
            return
        marks = (
            (0.75, "Three quarters — nearly there."),
            (0.5, "Halfway there."),
            (0.25, "A quarter done."),
        )
        for share, text in marks:
            if done / total >= share > (done - 1) / total:
                self._say(f"  ── {text} ──")
                return

    def _milestone_logged(self, done: int) -> None:
        if done in (1, 10, 25, 50, 100):
            notes = {
                1: "Your first logged application — the human side of the audit has begun.",
                10: "Ten logged. The gate rates mean something now; check Insights.",
                25: "Twenty-five. Halfway to the audit's lower target of 50.",
                50: "Fifty: the audit's minimum. Every one from here tightens it.",
                100: "One hundred. That's the full audit.",
            }
            self._say(f"  ── {notes[done]} ──")

    # ── insights ────────────────────────────────────────────────────────

    def _insights(self, progress: tuple[StudyProgress, ...]) -> None:
        for p in progress:
            self._show_insights(p.study.id)

    def _show_insights(self, study_id: str) -> None:
        study = next(p.study for p in self._port.progress() if p.study.id == study_id)
        self._say()
        self._say(f"  ── {study.title}: what your labels show ──")
        for line in self._port.insights(study_id):
            self._say(f"  {line}")

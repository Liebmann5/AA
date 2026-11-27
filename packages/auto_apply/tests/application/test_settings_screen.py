"""The terminal settings screen (GUI+CLI parity, ruling C) and the suffix fix."""

from __future__ import annotations

from typing import Any

from auto_apply.adapters.primary.cli.settings_screen import run_settings_screen
from auto_apply.domain.models.profile import UserProfile

from .test_motion_settings import _profile_dict


class _Person:
    """Answers by what was last shown: the menu, a labelled choice, a box."""

    def __init__(self, menu: list[str], by_label: dict[str, str]) -> None:
        self.menu = list(menu)
        self.by_label = by_label
        self.shown: list[str] = []
        self.last = ""

    def say(self, text: str) -> None:
        self.shown.append(text)
        if text.startswith("  ") and not text.startswith("    "):
            self.last = text.strip()

    def ask(self, prompt: str) -> str:
        if prompt.startswith("Select option"):
            return self.menu.pop(0)
        label = prompt.strip() if not prompt.strip().startswith("Choice") else self.last
        for key, answer in self.by_label.items():
            if label.lower().startswith(key.lower()):
                return answer
        return ""


def _run(person: _Person, profile: UserProfile | None = None) -> tuple[UserProfile, list]:
    saved: list[UserProfile] = []
    profile = profile or UserProfile.model_validate(_profile_dict())
    out = run_settings_screen(profile, saved.append, ask=person.ask, say=person.say)
    return out, saved


def test_about_you_saves_with_no_suffix_chosen() -> None:
    """The reported bug: leaving Suffix alone must not stop the save."""
    out, saved = _run(_Person(["1", "s"], {"City": "Tacoma"}))
    assert saved and out.personal_info.city == "Tacoma"
    assert out.personal_info.suffix is None


def test_a_typed_suffix_is_read_forgivingly_and_can_be_cleared() -> None:
    out, saved = _run(_Person(["1", "s"], {"Suffix": "jr"}))
    assert out.personal_info.suffix == "Jr."
    out2, _ = _run(_Person(["1", "s"], {"Suffix": "none"}), out)
    assert out2.personal_info.suffix is None


def test_an_unknown_suffix_is_refused_with_the_list_and_asked_again() -> None:
    answers = ["Junior", "2"]
    person = _Person(["1", "s"], {})
    plain = person.ask
    in_suffix = [False]

    def ask(prompt: str) -> str:
        if person.last.lower().startswith("suffix"):
            in_suffix[0] = True
        if prompt.strip().startswith("Choice") and in_suffix[0] and answers:
            return answers.pop(0)
        return plain(prompt)

    person.ask = ask  # type: ignore[method-assign]
    out, _ = _run(person)
    assert out.personal_info.suffix == "Sr."
    assert any("choice" in line.lower() for line in person.shown)


def test_answer_settings_from_the_menu_are_saved_on_the_profile() -> None:
    person = _Person(["2", "s"], {})
    replies = iter(["3", "each", "n"])
    plain = person.ask

    def ask(prompt: str) -> str:
        return plain(prompt) if prompt.startswith("Select option") else next(replies)

    person.ask = ask  # type: ignore[method-assign]
    out, saved = _run(person)
    prefs: Any = out.answer_preferences
    assert saved and (prefs.trust, prefs.review_timing) == ("matched", "each")


def test_going_back_without_saving_changes_nothing() -> None:
    out, saved = _run(_Person(["1", "q"], {"City": "Tacoma"}))
    assert saved == [] and out.personal_info.city == ""

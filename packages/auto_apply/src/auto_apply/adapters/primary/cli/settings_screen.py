"""Edit a profile's settings in the terminal — the CLI twin of GUI Settings.

Ruling C (GUI and CLI first-class): what the GUI's Settings window lets a
person change, the terminal lets them change too, with the same field
lists and the same choice rules:

* **About you** — the same fields as the GUI's About-you tab
  (``ui_schema.about_you_field_keys``); a field with listed values (a name
  suffix) is a numbered choice with "(none)" for an optional one
  (``choice_field``), never free text the profile would refuse.
* **Answers** — which answers AA may send without showing you first, and
  when it shows them (``answer_settings``; docs/adr/026).
* **Accessibility** — time limits, answering in AA, focus, plain terminal
  text (docs/adr/024).

Nothing is written until the whole profile validates; a refused value is
explained in plain words and nothing is saved.

Plain, linear output: one line per choice, no drawing — usable with a
screen reader.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError

from auto_apply.adapters.primary.cli.choice_prompt import ask_choice
from auto_apply.application.services.answer_settings import (
    effective_answer_settings,
    save_answer_settings,
    timing_choices,
    trust_choices,
)
from auto_apply.application.services.choice_field import Choice, choices_for
from auto_apply.application.services.i18n import get_text
from auto_apply.application.services.ui_schema import (
    UIField,
    about_you_field_keys,
    build_ui_schema,
)
from auto_apply.domain.models.profile import UserProfile

Ask = Callable[[str], str]
Say = Callable[[str], None]

#: The time-limit choices, as the GUI's Accessibility tab words them.
TIME_LIMIT_CHOICES: tuple[Choice, ...] = (
    Choice("1x", "Standard (1x)"), Choice("3x", "3 times as long (3x)"),
    Choice("10x", "10 times as long (10x)"), Choice("20x", "20 times as long (20x)"),
    Choice("off", "No time limit"),
)


def _io(ask: Ask | None, say: Say | None) -> tuple[Ask, Say]:
    return ask or input, say or print


def _yes(ask: Ask, question: str, current: bool) -> bool:
    try:
        raw = ask(f"  {question} ({'Y/n' if current else 'y/N'}): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return current
    if not raw:
        return current
    return raw.startswith("y")


def ask_answer_settings(prefs: Any, applications: Mapping[str, Any] | None = None, *,
                        ask: Ask | None = None, say: Say | None = None) -> None:
    """Ask the answer-review settings and write them onto ``prefs``."""
    ask, say = _io(ask, say)
    now = effective_answer_settings(applications, prefs)
    say("")
    say(get_text("settings.answers_heading"))
    say("  " + get_text("settings.answers_intro"))
    trust = ask_choice(get_text("settings.answer_trust"), trust_choices(), now["trust"],
                       ask=ask, say=say)
    say("  " + get_text("settings.answer_trust_note"))
    timing = ask_choice(get_text("settings.review_timing"), timing_choices(),
                        now["review_timing"], ask=ask, say=say)
    drafts = _yes(ask, get_text("settings.drafts_enabled") + "?", now["drafts_enabled"])
    save_answer_settings(prefs, applications, trust=str(trust or "never"),
                         review_timing=str(timing or "end"), drafts_enabled=drafts)


def _fields() -> dict[str, UIField]:
    try:
        return {f.key: f for f in build_ui_schema(UserProfile, "en")}
    except Exception:
        return {}


def _get(profile: UserProfile, key: str) -> Any:
    node: Any = profile
    for part in key.split("."):
        node = getattr(node, part, None)
        if node is None:
            return None
    return node


def _set(data: dict[str, Any], key: str, value: Any) -> None:
    node = data
    parts = key.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def edit_about_you(profile: UserProfile, *, ask: Ask | None = None,
                   say: Say | None = None) -> UserProfile | None:
    """Walk the About-you fields; returns the validated profile, or None
    when a value was refused (nothing is changed then)."""
    ask, say = _io(ask, say)
    fields = _fields()
    data = profile.model_dump(by_alias=True)
    say("")
    say("About you — press Enter to keep a value; type - to clear an optional one.")
    for key in about_you_field_keys():
        field = fields.get(key)
        label = field.label if field else key.rsplit(".", 1)[-1].replace("_", " ")
        current = _get(profile, key)
        if field is not None and field.kind == "select" and field.options:
            value: Any = ask_choice(label, choices_for(
                field, none_label=get_text("settings.choice_none")), current,
                ask=ask, say=say)
        elif isinstance(current, bool) or (field is not None and field.kind == "bool"):
            value = _yes(ask, label + "?", bool(current))
        else:
            shown = ", ".join(map(str, current)) if isinstance(current, list) else (
                "" if current is None else str(current))
            try:
                raw = ask(f"  {label}" + (f" [{shown}]" if shown else "") + ": ").strip()
            except (EOFError, KeyboardInterrupt):
                raw = ""
            if not raw:
                continue
            if raw == "-":
                value = [] if isinstance(current, list) else None
            elif isinstance(current, list) or (field is not None
                                               and field.kind == "multiselect"):
                value = [t.strip() for t in raw.split(",") if t.strip()]
            else:
                value = raw
        _set(data, key, value)
    try:
        return UserProfile.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        where = " → ".join(str(p) for p in first.get("loc", ())) or "profile"
        say(f"  Not saved — {where}: {first.get('msg', 'invalid value')}")
        return None


def edit_accessibility(prefs: Any, accessibility: Mapping[str, Any] | None = None, *,
                       ask: Ask | None = None, say: Say | None = None) -> None:
    """Ask the accessibility settings and write them onto ``prefs``
    (an ``AccessibilityPreferences``); unchanged defaults stay inherited."""
    ask, say = _io(ask, say)
    defaults = dict(accessibility or {})
    say("")
    say("Accessibility — these change how AA works with you. AA never asks why,")
    say("never stores a reason, and never uses them to answer an application.")
    current = prefs.time_limits or str(defaults.get("time_limits") or "1x")
    limit = ask_choice("How long should AA wait for your answers?", TIME_LIMIT_CHOICES,
                       current, ask=ask, say=say)
    values = {
        "time_limits": limit or "1x",
        "answer_in_aa": _yes(ask, "Answer questions AA cannot answer in AA's own window?",
                             bool(prefs.answer_in_aa if prefs.answer_in_aa is not None
                                  else defaults.get("answer_in_aa", False))),
        "focus_asked_field": _yes(ask, "Move the keyboard focus to questions AA asks about?",
                                  bool(prefs.focus_asked_field
                                       if prefs.focus_asked_field is not None
                                       else defaults.get("focus_asked_field", True))),
        "screen_reader_mode": _yes(ask, "Plain, linear text in this terminal (screen readers)?",
                                   bool(prefs.screen_reader_mode)),
    }
    builtin = {"time_limits": "1x", "answer_in_aa": False, "focus_asked_field": True}
    for key, value in values.items():
        default = defaults.get(key, builtin.get(key))
        if key == "screen_reader_mode" or getattr(prefs, key) is not None or value != default:
            setattr(prefs, key, value)


def run_settings_screen(profile: UserProfile, save: Callable[[UserProfile], object], *,
                        applications: Mapping[str, Any] | None = None,
                        accessibility: Mapping[str, Any] | None = None,
                        ask: Ask | None = None, say: Say | None = None) -> UserProfile:
    """The settings menu. Returns the profile as saved (or unchanged)."""
    ask, say = _io(ask, say)
    working = profile.model_copy(deep=True)
    changed = False
    while True:
        say("")
        say(f"Settings — {working.profile_name}")
        say("  1. About you")
        say("  2. " + get_text("settings.answers_heading"))
        say("  3. Accessibility")
        say("  s. Save and go back")
        say("  q. Go back without saving")
        try:
            choice = ask("Select option: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "q"
        if choice == "1":
            updated = edit_about_you(working, ask=ask, say=say)
            if updated is not None:
                working, changed = updated, True
        elif choice == "2":
            ask_answer_settings(working.answer_preferences, applications, ask=ask, say=say)
            changed = True
        elif choice == "3":
            edit_accessibility(working.accessibility_preferences, accessibility,
                               ask=ask, say=say)
            changed = True
        elif choice == "s":
            if not changed:
                say("  Nothing changed.")
                return profile
            try:
                validated = UserProfile.model_validate(working.model_dump(by_alias=True))
                save(validated)
            except Exception as exc:
                say(f"  Not saved: {exc}")
                continue
            say("  Saved.")
            return validated
        elif choice == "q":
            return profile
        else:
            say(f"  There is no option {choice!r}.")


__all__ = ["ask_answer_settings", "edit_about_you", "edit_accessibility",
           "run_settings_screen"]

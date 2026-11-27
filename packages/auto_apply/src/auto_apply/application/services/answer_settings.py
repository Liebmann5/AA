"""The answer-review settings as both surfaces show them (docs/adr/026).

One definition of the choices, their plain-language labels, and how a
choice is saved, so the GUI's Answers tab, the GUI's first-run setup, the
CLI's setup wizard and the CLI's settings screen cannot say or save
different things.

Saving follows the profile's inherit rule: a choice equal to AA's default
(``applications`` in runtime_defaults.yaml) is stored as None — the profile
keeps inheriting — unless the person had already pinned a value.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from auto_apply.application.services.choice_field import Choice
from auto_apply.application.services.i18n import get_text
from auto_apply.domain.applications.answer_review import (
    DEFAULT_TIMING,
    DEFAULT_TRUST,
    REVIEW_TIMINGS,
    TRUST_LEVELS,
    normal_timing,
    normal_trust,
)


def trust_choices() -> tuple[Choice, ...]:
    """The trust levels, strictest first, each in plain words."""
    return tuple(Choice(v, get_text(f"settings.answer_trust_{v}")) for v in TRUST_LEVELS)


def timing_choices() -> tuple[Choice, ...]:
    return tuple(Choice(v, get_text(f"settings.review_timing_{v}")) for v in REVIEW_TIMINGS)


def effective_answer_settings(applications: Mapping[str, Any] | None,
                              prefs: Any = None) -> dict[str, Any]:
    """What is in force: the profile's choices over AA's defaults."""
    apps = applications if isinstance(applications, Mapping) else {}
    trust = getattr(prefs, "trust", None) or apps.get("answer_trust")
    timing = getattr(prefs, "review_timing", None) or apps.get("review_timing")
    drafts = getattr(prefs, "drafts_enabled", None)
    if drafts is None:
        drafts = bool(apps.get("generated_answers", False))
    return {"trust": normal_trust(trust), "review_timing": normal_timing(timing),
            "drafts_enabled": bool(drafts)}


def save_answer_settings(prefs: Any, applications: Mapping[str, Any] | None, *,
                         trust: str, review_timing: str, drafts_enabled: bool) -> None:
    """Write the person's choices onto ``prefs`` (an ``AnswerPreferences``)."""
    apps = applications if isinstance(applications, Mapping) else {}
    defaults = {"trust": normal_trust(apps.get("answer_trust") or DEFAULT_TRUST),
                "review_timing": normal_timing(apps.get("review_timing") or DEFAULT_TIMING),
                "drafts_enabled": bool(apps.get("generated_answers", False))}
    chosen = {"trust": normal_trust(trust), "review_timing": normal_timing(review_timing),
              "drafts_enabled": bool(drafts_enabled)}
    for key, value in chosen.items():
        if getattr(prefs, key) is not None or value != defaults[key]:
            setattr(prefs, key, value)


__all__ = ["effective_answer_settings", "save_answer_settings", "timing_choices",
           "trust_choices"]

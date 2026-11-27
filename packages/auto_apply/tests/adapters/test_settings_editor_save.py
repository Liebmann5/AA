"""The Settings window saves with no suffix chosen, and saves the Answers tab.

Builds the real window; skipped where there is no display (headless CI).
"""

from __future__ import annotations

from typing import Any, get_args
from unittest.mock import MagicMock

import pytest

tk = pytest.importorskip("tkinter")

from auto_apply.adapters.primary.gui import settings_editor as mod  # noqa: E402
from auto_apply.domain.models.profile import BrowserType, UserProfile  # noqa: E402

from ..application.test_motion_settings import _profile_dict  # noqa: E402


@pytest.fixture()
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    r.withdraw()
    yield r
    r.destroy()


def _editor(root: Any, profile: UserProfile, monkeypatch: pytest.MonkeyPatch):
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(mod.messagebox, "showinfo", lambda t, m, **k: shown.append((t, m)))
    monkeypatch.setattr(mod.messagebox, "showerror", lambda t, m, **k: shown.append((t, m)))
    registry = MagicMock()
    registry.get_active_profile.return_value = profile
    registry.get_admin_policy.return_value = None
    registry.get_effective_config.side_effect = lambda key, default=None: default
    registry.get_allowed_browsers.return_value = list(get_args(BrowserType))
    repo = MagicMock()
    editor = mod.SettingsEditor(root, registry, on_save=lambda: None, profile_repo=repo)
    return editor, repo, shown


def test_saving_with_no_suffix_chosen_succeeds(root: Any, monkeypatch: pytest.MonkeyPatch
                                               ) -> None:
    profile = UserProfile.model_validate(_profile_dict())
    editor, repo, shown = _editor(root, profile, monkeypatch)
    box = editor._choices["personal_info.suffix"]  # noqa: SLF001
    assert box.get() is None, "an empty suffix shows as (none)"
    editor._save_changes()  # noqa: SLF001
    assert shown and shown[0][0] == "Saved", shown
    assert repo.save_profile.call_args.args[0].personal_info.suffix is None


def test_a_chosen_suffix_and_answer_settings_are_saved(root: Any,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    profile = UserProfile.model_validate(_profile_dict())
    editor, repo, shown = _editor(root, profile, monkeypatch)
    editor._choices["personal_info.suffix"].set_value("Jr.")  # noqa: SLF001
    editor._choices["answers.trust"].set_value("own_words")  # noqa: SLF001
    editor._choices["answers.review_timing"].set_value("page")  # noqa: SLF001
    editor._save_changes()  # noqa: SLF001
    saved = repo.save_profile.call_args.args[0]
    assert shown[0][0] == "Saved", shown
    assert saved.personal_info.suffix == "Jr."
    assert (saved.answer_preferences.trust, saved.answer_preferences.review_timing) == (
        "own_words", "page")

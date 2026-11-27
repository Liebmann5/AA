"""Cross-cutting pins for the accessibility (ADR-024) and multilingual-form
(ADR-025) work: every word AA says to the person exists in every shipped
language; AA's accessibility settings can never become an answer on an
application form; option matching reads codes and any-language yes/no."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_apply.application.services.i18n import _LocaleState, option_label
from auto_apply.domain.applications.answers import AnswerContext, ProfileAnswerSource
from auto_apply.domain.applications.form_model import FormQuestion, QuestionKind
from auto_apply.domain.applications.option_matching import match_option, same_value
from auto_apply.domain.models.profile import AccessibilityPreferences

_SRC = Path(__file__).resolve().parents[2] / "src" / "auto_apply"
_LOCALES = _SRC / "resources" / "locales"
_SPEAKERS = (
    "application/services/form_engine.py",
    "application/workflows/applications_workflow.py",
    "adapters/primary/cli/dashboard.py",
    "adapters/primary/gui/dashboard.py",
)
#: Every approval option the engine and the workflow offer.
_OPTION_TOKENS = (
    "done", "skip", "continue", "signed in", "click it", "submit", "solved", "stop",
    "it was submitted", "it was not submitted", "answer in the browser", "tick it",
    "leave it unticked",
)


def _flat(d: dict, prefix: str = "") -> set[str]:
    out: set[str] = set()
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out |= _flat(v, key + ".")
        else:
            out.add(key)
    return out


def _bundle(code: str) -> set[str]:
    return _flat(json.loads((_LOCALES / f"{code}.json").read_text(encoding="utf-8")))


def _keys_used() -> set[str]:
    used: set[str] = set()
    for rel in _SPEAKERS:
        tree = ast.parse((_SRC / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "get_text" \
                    and node.args and isinstance(node.args[0], ast.Constant):
                used.add(str(node.args[0].value))
    return used


@pytest.mark.parametrize("code", ["en", "es"])
def test_every_word_aa_says_exists_in_every_shipped_language(code: str) -> None:
    used = _keys_used()
    assert len(used) > 30
    missing = sorted(used - _bundle(code))
    assert not missing, f"{code}.json lacks {missing}"


@pytest.mark.parametrize("code", ["en", "es"])
def test_every_option_aa_offers_has_a_label(code: str) -> None:
    bundle = _bundle(code)
    missing = [t for t in _OPTION_TOKENS if "options." + "_".join(t.split()) not in bundle]
    assert not missing


def test_a_form_s_own_option_is_shown_as_it_is() -> None:
    assert option_label("Vereinigte Staaten") == "Vereinigte Staaten"


def test_a_key_is_never_shown_to_a_person_even_when_unconfigured() -> None:
    state = _LocaleState()
    assert state.get_string("form_engine.where_page") == "this page"


def test_the_answer_sources_never_read_accessibility_settings() -> None:
    """AA stores the accommodations a person chooses, never the reason —
    and never lets a setting become an answer ("uses a screen reader" must
    never answer a disability question). Structural: the answer sources do
    not mention the accessibility settings at all."""
    tree = ast.parse((_SRC / "domain/applications/answers.py").read_text(encoding="utf-8"))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    strings = {str(n.value) for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not any("accessib" in x.lower() for x in names | strings)


def test_a_profile_with_accessibility_settings_does_not_answer_a_disability_question() -> None:
    profile = SimpleNamespace(
        accessibility_preferences=AccessibilityPreferences(screen_reader_mode=True,
                                                           answer_in_aa=True),
        eeo_info=None, legal_info=None, personal_info=None,
    )
    q = FormQuestion(key="d", label="Do you have a disability?", kind=QuestionKind.RADIO,
                     field_type="disability", controls=())
    assert ProfileAnswerSource(profile).propose(q, AnswerContext()) is None


# ── option matching: codes and any-language yes/no ────────────────────────


def test_a_country_is_matched_by_its_iso_code_in_any_language() -> None:
    m = match_option("United States", ["Deutschland", "Vereinigte Staaten", "Frankreich"],
                     values=["DE", "US", "FR"])
    assert m.found and m.index == 1


@pytest.mark.parametrize(("want", "options", "index"), [
    ("Yes", ["Ja", "Nein"], 0), ("No", ["Oui", "Non"], 1), ("No", ["はい", "いいえ"], 1),
    ("Yes", ["Sí", "No"], 0),
])
def test_a_yes_or_no_answer_matches_in_any_language(want: str, options: list[str],
                                                   index: int) -> None:
    m = match_option(want, options)
    assert m.found and m.index == index


def test_read_back_reads_any_digits() -> None:
    assert same_value("٠١٢٣٤٥٦٧٨٩", "0123456789")
    assert same_value("５５５-１２３４", "5551234")

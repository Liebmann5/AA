"""Pins for the words of application forms (``form_lexicon.py``).

The lexicon is data a translator edits; these pins keep it well-formed and
keep the two properties the engine's safety rests on: no word means yes in
one language and no in another, and every word pagecomp's reader treats as
navigation or submission is known to AA's own rules too (so the reader can
never call a control safe that AA's submit rule would not also see).
"""

from __future__ import annotations

import re

import pytest

from auto_apply.domain.applications import form_localization
from auto_apply.domain.applications.answers import PROTECTED_TYPES
from auto_apply.domain.applications.form_language import fold, says, which
from auto_apply.domain.applications.form_lexicon import (
    FIELD_TYPES,
    LANGUAGE_ALIASES,
    LEXICON,
    LEXICON_VERSION,
    PERMISSIVE_CLASSES,
    REVIEW,
    SAFETY_CLASSES,
    SCRIPT_LANGUAGES,
)
from pagecomp.tools import forms

_KNOWN = SAFETY_CLASSES | PERMISSIVE_CLASSES | {f"field.{t}" for t in FIELD_TYPES}


def _terms(value: str) -> list[str]:
    return [t for t in value.split("|") if t.strip()]


def test_the_version_is_dated_and_stamped() -> None:
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", LEXICON_VERSION)


def test_safety_and_permissive_classes_do_not_overlap() -> None:
    assert not SAFETY_CLASSES & PERMISSIVE_CLASSES


@pytest.mark.parametrize("loc", sorted(LEXICON))
def test_every_language_uses_only_known_classes_and_is_reviewed(loc: str) -> None:
    assert len(loc) == 2 and loc.isalpha() and loc.islower()
    assert loc in REVIEW and REVIEW[loc] in ("baseline", "unreviewed", "reviewed")
    unknown = set(LEXICON[loc]) - _KNOWN
    assert not unknown, f"{loc}: unknown classes {sorted(unknown)}"


@pytest.mark.parametrize("loc", sorted(LEXICON))
def test_every_term_is_well_formed(loc: str) -> None:
    for cls, value in LEXICON[loc].items():
        for raw in _terms(value):
            t = raw.strip()
            assert t == raw, f"{loc}.{cls}: stray space in {raw!r}"
            assert "**" not in t and not (t.startswith("*") and not t.endswith("*")), \
                f"{loc}.{cls}: a leading * needs a trailing * ({t!r})"
            core = t.lstrip("!=").strip("*")
            assert fold(core), f"{loc}.{cls}: {t!r} folds to nothing"


def test_no_word_is_both_yes_and_no_in_any_two_languages() -> None:
    yes = {fold(t) for c in LEXICON.values() for t in _terms(c.get("yes", ""))}
    no = {fold(t) for c in LEXICON.values() for t in _terms(c.get("no", ""))}
    assert not yes & no, sorted(yes & no)


def test_every_reader_navigation_or_submit_word_is_known_to_aa() -> None:
    """pagecomp's reader classifies buttons with its own small vocabulary;
    AA's rules must know every one of those words in the same sense."""
    for word in forms._SUBMIT:
        assert says(word, "submit"), f"pagecomp submit word {word!r} unknown to AA"
    for word in forms._BACK:
        assert says(word, "back"), f"pagecomp back word {word!r} unknown to AA"
    for word in forms._NEXT:
        assert which(word, "next") is not None, f"pagecomp next word {word!r} unknown to AA"


def test_aliases_and_scripts_point_at_lexicons() -> None:
    for target in LANGUAGE_ALIASES.values():
        assert target in LEXICON or target == "yi"
    for langs in SCRIPT_LANGUAGES.values():
        assert all(loc in LEXICON for loc in langs)


def test_the_protected_types_lists_agree() -> None:
    """``form_localization`` mirrors ``answers.PROTECTED_TYPES`` (it cannot
    import answers without a cycle); the two must stay equal."""
    assert form_localization._PROTECTED_TYPES == PROTECTED_TYPES

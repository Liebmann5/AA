"""Pins for applying AA's language knowledge to a step (``form_localization``)
and for the accessibility barriers a step shows (``form_barriers``)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from auto_apply.domain.applications.form_barriers import (
    NO_INPUT_PURPOSE,
    NO_PAGE_LANGUAGE,
    PLACEHOLDER_ONLY,
    REQUIRED_NOT_PROGRAMMATIC,
    UNLABELLED,
    barrier_signals,
)
from auto_apply.domain.applications.form_localization import localize_step
from auto_apply.domain.applications.form_model import (
    FILL,
    OPTIONAL,
    REQUIRED,
    TRAP,
    UNKNOWN,
    ControlRef,
    FormButton,
    FormQuestion,
    FormStep,
    QuestionKind,
)


def _ref(name: str) -> ControlRef:
    return ControlRef(path=(0,), tag="input", type="text", name=name)


def _q(label: str, *, ftype: str = "text", src: str = "default", required: str = UNKNOWN,
       evidence: tuple[str, ...] = (), autocomplete: str = "", label_source: str = "label-for",
       kind: QuestionKind = QuestionKind.TEXT) -> FormQuestion:
    return FormQuestion(key=label or label_source, label=label, kind=kind, field_type=ftype,
                        type_source=src, required=required, required_evidence=evidence,
                        decision=FILL, sensitive=False, controls=(_ref(label),),
                        autocomplete=autocomplete, label_source=label_source)


def _b(text: str, role: str, *, final: bool, btype: str = "submit") -> FormButton:
    return FormButton(role=role, text=text, control=_ref(text), final=final, button_type=btype)


def _step(questions: tuple[FormQuestion, ...], buttons: tuple[FormButton, ...] = (), *,
          lang: str = "", texts: tuple[str, ...] = ()) -> FormStep:
    return FormStep(url="https://jobs.example/apply", title="Apply", purpose="application",
                    questions=questions, buttons=buttons, fingerprint="fp", language=lang,
                    step_texts=texts)


# ── buttons ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("text", "lang"), [("Avanti", "it"), ("Далее", "ru"), ("次へ", "ja")])
def test_a_next_word_in_the_page_s_language_makes_a_step_control(text: str, lang: str) -> None:
    """The reader called it ``submit`` only by its HTML type (a ``<button>``
    with no type): in the page's language it says "next"."""
    step = localize_step(_step((_q("x"),), (_b(text, "submit", final=True),), lang=lang))
    b = step.buttons[0]
    assert (b.role, b.final, b.role_source) == ("next", False, f"lexicon({lang})")
    assert not b.may_submit


def test_a_next_word_outside_the_page_s_languages_changes_nothing() -> None:
    step = localize_step(_step((_q("First name"),), (_b("Avanti", "submit", final=True),),
                               lang="en"))
    assert step.buttons[0].role == "submit" and step.buttons[0].may_submit


@pytest.mark.parametrize(("text", "lang"), [("Weiter und absenden", "de"),
                                          ("Continuar y enviar", "es")])
def test_a_control_that_also_says_it_sends_is_never_made_a_next(text: str, lang: str) -> None:
    step = localize_step(_step((_q("x"),), (_b(text, "other", final=True, btype="button"),),
                               lang=lang))
    assert step.buttons[0].may_submit


def test_a_review_word_keeps_the_reader_s_verdict() -> None:
    step = localize_step(_step((_q("Vorname"),), (_b("Überprüfen", "submit", final=True),),
                               lang="de"))
    assert step.buttons[0].role == "submit" and step.buttons[0].may_submit


def test_a_submit_role_from_words_is_not_downgraded() -> None:
    """Round-3 (ChatGPT, MAJOR #2): role=submit always may submit."""
    b = _b("Review", "submit", final=False, btype="button")
    assert b.may_submit
    assert localize_step(_step((_q("x"),), (b,), lang="en")).buttons[0].may_submit


# ── field types ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("labels", "lang", "types"), [
    (("Prénom", "Nom"), "fr", ("first_name", "last_name")),
    (("Nombre", "Apellidos"), "es", ("first_name", "last_name")),
    (("Nome", "Cognome"), "it", ("first_name", "last_name")),
    (("Vorname", "Name"), "de", ("first_name", "last_name")),
    (("Nom complet",), "fr", ("full_name",)),
])
def test_a_bare_name_beside_its_other_half_is_that_half(labels: tuple[str, ...], lang: str,
                                                       types: tuple[str, ...]) -> None:
    step = localize_step(_step(tuple(_q(lb) for lb in labels), lang=lang))
    assert tuple(q.field_type for q in step.questions) == types


def test_structure_is_never_overridden_by_words() -> None:
    q = _q("Nachname", ftype="email", src="autocomplete=email")
    assert localize_step(_step((q,), lang="de")).questions[0].field_type == "email"


def test_provenance_unknown_is_not_provenance_weak() -> None:
    q = _q("Vorname", ftype="text", src="")
    assert localize_step(_step((q,), lang="de")).questions[0].field_type == "text"


def test_a_long_label_stays_a_question() -> None:
    q = _q("Bitte beschreiben Sie Ihren Vornamen und warum er Ihnen gefällt")
    assert localize_step(_step((q,), lang="de")).questions[0].field_type == "text"


def test_a_protected_type_found_by_words_is_marked_sensitive() -> None:
    q = localize_step(_step((_q("Geschlecht", ftype="choice", src="type=select",
                                kind=QuestionKind.SELECT),), lang="de")).questions[0]
    assert q.field_type == "gender" and q.sensitive


# ── requiredness ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("label", "lang", "req"), [
    ("Telefon (Pflichtfeld)", "de", REQUIRED),
    ("Téléphone (facultatif)", "fr", OPTIONAL),
    ("電話番号 必須", "ja", REQUIRED),
    ("Phone", "en", UNKNOWN),
])
def test_required_and_optional_words(label: str, lang: str, req: str) -> None:
    q = localize_step(_step((_q(label),), lang=lang)).questions[0]
    assert q.required == req


def test_a_reading_that_already_decided_requiredness_is_kept() -> None:
    q = _q("Telefon (optional)", required=REQUIRED, evidence=("native-required",))
    assert localize_step(_step((q,), lang="de")).questions[0].required == REQUIRED


# ── step position, idempotence ──────────────────────────────────────────────


def test_step_position_from_texts_in_any_language() -> None:
    step = localize_step(_step((_q("Vorname"),), lang="de", texts=("Schritt 2 von 4",)))
    assert (step.step_now, step.step_total, step.step_label) == (2, 4, "Schritt 2 von 4")


def test_localizing_twice_changes_nothing() -> None:
    raw = _step((_q("Prénom"), _q("Nom"), _q("Téléphone (facultatif)")),
                (_b("Suivant", "submit", final=True),), lang="fr", texts=("Étape 1 sur 3",))
    once = localize_step(raw)
    assert localize_step(once) == once


# ── accessibility barriers ──────────────────────────────────────────────────


def test_barrier_signals_are_counted_by_criterion() -> None:
    step = _step((
        _q("", label_source="none"),
        _q("Email", ftype="email", label_source="placeholder"),
        _q("Phone", ftype="phone", required=REQUIRED, evidence=("asterisk",),
           autocomplete="tel"),
        _q("City", ftype="city", required=REQUIRED, evidence=("native-required",),
           autocomplete="address-level2"),
    ))
    found = barrier_signals(step)
    assert found == {NO_PAGE_LANGUAGE: 1, UNLABELLED: 1, PLACEHOLDER_ONLY: 1,
                     NO_INPUT_PURPOSE: 1, REQUIRED_NOT_PROGRAMMATIC: 1}


def test_a_well_made_step_shows_no_signals_and_that_is_not_a_verdict() -> None:
    step = _step((_q("City", ftype="city", required=REQUIRED, evidence=("native-required",),
                     autocomplete="address-level2"),), lang="en")
    assert barrier_signals(step) == {}


def test_signals_never_carry_words_or_values() -> None:
    step = _step((_q("Ada Quill's phone", ftype="phone", label_source="placeholder"),))
    assert all("Ada" not in k and ":" in k for k in barrier_signals(step))


def test_traps_and_non_application_pages_are_not_counted() -> None:
    trap = replace(_q("", label_source="none"), decision=TRAP)
    assert UNLABELLED not in barrier_signals(_step((trap,), lang="en"))
    assert barrier_signals(replace(_step((_q("x", label_source="none"),)),
                                   purpose="review")) == {}

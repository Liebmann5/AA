"""Pins for reading application forms in any language (``form_language.py``)."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from auto_apply.domain.applications.form_language import (
    field_type_of,
    fold,
    is_decline,
    is_placeholder,
    polar_word,
    polarity,
    primary_tag,
    resolve,
    says,
    step_position,
    which,
)

# ── folding ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("raw", "folded"), [
    ("Straße", "strasse"),
    ("Prénom", "prenom"),
    ("ＥＭＡＩＬ", "email"),                 # full-width
    ("ﬁle", "file"),                     # ligature
    ("İstanbul", "istanbul"),                 # Turkish dotted capital I
    ("Ёлка", "елка"),                         # Russian ё read as е
    ("d'accord", "d accord"),
    ("שלום\u200f", "שלום"),                  # bidi mark dropped
    ("إعاقة", "اعاقة"),                       # Arabic hamza seat removed
    ("ガイド", "ガイド"),                     # Japanese voicing mark KEPT
    ("नहीं", "नहीं"),                         # Devanagari signs KEPT
    ("  Vor-   und  Nachname ", "vor und nachname"),
])
def test_folding(raw: str, folded: str) -> None:
    assert fold(raw) == folded


@pytest.mark.parametrize(("tag", "key"), [
    ("de-CH", "de"), ("en_US", "en"), ("no", "nb"), ("nn", "nb"), ("zh-Hant-TW", "zh"),
    ("iw", "he"), ("", ""), ("x-klingon", ""), ("123", ""),
])
def test_language_tags(tag: str, key: str) -> None:
    assert primary_tag(tag) == key


# ── safety classes: every language at once ─────────────────────────────────


@pytest.mark.parametrize("text", [
    "Submit application", "Envoyer", "Absenden", "Enviar solicitud", "送信する", "提交",
    "Отправить", "Wyślij", "Invia candidatura", "إرسال", "שלח", "Gönder",
])
def test_a_control_that_sends_is_seen_in_every_language(text: str) -> None:
    assert says(text, "submit")


@pytest.mark.parametrize("text", ["Next", "Weiter", "Avanti", "次へ", "다음", "Далее"])
def test_navigation_words_do_not_say_submit(text: str) -> None:
    assert not says(text, "submit")


@pytest.mark.parametrize("label", [
    "Are you legally eligible to work in the United States?",
    "When were you born?",
    "Are you over 18 years of age?",
    "Do you require a reasonable accommodation for the interview process?",
    "Gender identity",
    "Relationship status",
    "Staatsangehörigkeit",
    "Haben Sie eine Schwerbehinderung?",         # German compound
    "¿Tiene alguna discapacidad?",
    "Appartenenza alle categorie protette",       # Italian protected categories
    "Você é PcD?",                                # Brazilian disability question
    "障害の有無",                                  # Japanese, unspaced
    "Pohlaví",
    "الجنسية",
])
def test_questions_only_the_person_answers_are_protected_in_any_language(label: str) -> None:
    assert says(label, "protected")


@pytest.mark.parametrize("label", [
    "City", "Stadt", "المدينة", "Experience with medical devices", "Years of experience",
    "Email address", "Where did you see this job?",
])
def test_ordinary_questions_are_not_protected(label: str) -> None:
    assert not says(label, "protected")


def test_us_the_pronoun_is_company_relative_but_us_the_country_is_not() -> None:
    assert says("How did you hear about us?", "company_relative")
    assert not says("Are you a US citizen?", "company_relative")
    assert says("Warum möchten Sie bei uns arbeiten?", "company_relative")
    assert says("What do you know about the company?", "company_relative")


# ── yes / no / decline / placeholders ──────────────────────────────────────


@pytest.mark.parametrize(("text", "pol"), [
    ("Yes, I am authorized", True), ("No, I will require sponsorship", False),
    ("Ja", True), ("Nein", False), ("Oui", True), ("Non", False), ("Sí", True),
    ("Não", False), ("Tak", True), ("Nie", False), ("はい", True), ("いいえ", False),
    ("是的", True), ("否", False), ("예", True), ("아니요", False), ("Да", True),
    ("Нет", False), ("Evet", True), ("Hayır", False), ("Maybe", None), ("", None),
])
def test_polarity(text: str, pol: bool | None) -> None:
    assert polarity(text) is pol


def test_only_a_whole_yes_or_no_word_is_a_pure_answer() -> None:
    assert polar_word("Nein") is False and polar_word("Yes") is True
    assert polar_word("No, I will require sponsorship") is None


@pytest.mark.parametrize("text", [
    "Prefer not to say", "Keine Angabe", "Je préfère ne pas répondre", "Prefiero no responder",
    "回答しない", "不愿透露",
])
def test_decline_in_any_language(text: str) -> None:
    assert is_decline(text)


@pytest.mark.parametrize("label", [
    "", "--", "...", "Select...", "-- Bitte wählen --", "Sélectionnez", "Seleccione",
    "請選擇", "選択してください", "선택하세요",
])
def test_placeholders_in_any_language(label: str) -> None:
    assert is_placeholder(label)


@pytest.mark.parametrize("label", ["Germany", "Deutschland", "選択肢A", "Selected works"])
def test_real_options_are_not_placeholders(label: str) -> None:
    assert not is_placeholder(label)


# ── step indicators ────────────────────────────────────────────────────────


@pytest.mark.parametrize(("text", "pos"), [
    ("Step 2 of 4", (2, 4)), ("Schritt 2 von 4", (2, 4)), ("Étape 3 sur 5", (3, 5)),
    ("Paso 1 de 3", (1, 3)), ("第2步，共4步", (2, 4)), ("4단계 중 2단계", (2, 4)),
    ("全4ステップ中2", (2, 4)), ("ステップ 2/4", (2, 4)), ("Шаг 2 из 3", (2, 3)),
    ("Step ٢ of ٤", (2, 4)),                         # Arabic-Indic digits
    ("Step ２ of ４", (2, 4)),                       # full-width digits
])
def test_step_indicators_in_any_language(text: str, pos: tuple[int, int]) -> None:
    found = step_position([text])
    assert found is not None and found[:2] == pos


@pytest.mark.parametrize("text", [
    "Step 2: 4 questions",            # no connector between the numbers
    "2 of 4 jobs",                    # no step word
    "Schritt 2 of 4",                 # step word and connector of different languages
    "Step 2 of 99",                   # implausible total
    "Step 1 of 2 — page 3 of 4",      # more than two numbers
])
def test_texts_that_are_not_step_indicators(text: str) -> None:
    assert step_position([text]) is None


# ── languages of a step ─────────────────────────────────────────────────────


def test_a_wrong_declared_language_is_outvoted_by_the_page_s_own_words() -> None:
    ctx = resolve("en", ["Vorname", "Nachname", "E-Mail", "Weiter", "Lebenslauf"])
    assert ctx.locales == ("en", "de")  # declared first, then the page's own words
    assert ctx.declared == "en" and ctx.primary == "en"


def test_words_shared_by_many_languages_prove_nothing() -> None:
    ctx = resolve("", ["Email", "CV", "Name", "Telefon"])
    assert ctx.locales == ("en",)


def test_candidate_languages_are_ordered_declared_first_english_last() -> None:
    ctx = resolve("es", ["Continuar", "Nome completo", "Telefone celular",
                         "Endereço de e-mail"])
    assert ctx.locales == ("es", "pt", "en")


def test_a_word_two_candidates_share_is_attributed_the_same_on_every_run() -> None:
    """Research evidence must not depend on PYTHONHASHSEED: "Continuar" is
    Spanish and Portuguese, and the declared Spanish wins on every run.
    (Before: a frozenset made it "es" on 4 of 10 seeds and "pt" on 6.)"""
    code = ("from auto_apply.domain.applications.form_language import resolve, which\n"
            "c = resolve('es', ['Continuar', 'Nome completo', 'Telefone celular',"
            " 'Endereço de e-mail'])\n"
            "print(c.locales, which('Continuar', 'next', c.locales))")
    seen = set()
    for seed in ("0", "1", "2", "3", "4", "5"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                             text=True, check=True).stdout.strip()
        seen.add(out)
    assert seen == {"('es', 'pt', 'en') es"}


def test_the_writing_system_names_its_languages() -> None:
    assert "ko" in resolve("", ["이메일 주소", "전화번호"]).locales
    assert "ja" in resolve("", ["メールアドレス"]).locales


def test_permissive_words_are_matched_only_in_candidate_languages() -> None:
    # A German "next" word on a page AA has no reason to read as German:
    assert which("Weiter", "next", ["en"]) is None
    assert which("Weiter", "next", ["en", "de"]) == "de"


@pytest.mark.parametrize(("label", "langs", "ftype"), [
    ("Vorname", ["de"], "first_name"), ("Nachname", ["de"], "last_name"),
    ("Code postal", ["fr"], "postal_code"), ("Correo electrónico", ["es"], "email"),
    ("会社名", ["ja"], "employer"),          # 名 inside a longer word is not "first name"
    ("名", ["ja"], "first_name"),
    ("名前", ["ja"], "full_name"),
    ("Previous step", ["en"], None),          # not a field
])
def test_field_types_by_label(label: str, langs: list[str], ftype: str | None) -> None:
    hit = field_type_of(label, langs)
    assert (hit[0] if hit else None) == ftype


def test_a_furigana_field_is_not_typed_as_a_name() -> None:
    assert field_type_of("名（フリガナ）", ["ja"]) is None

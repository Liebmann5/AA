"""Assessments and required external steps (ADR-026): recognised, reported,
never followed or taken."""

from __future__ import annotations

from auto_apply.domain.applications.external_steps import (
    external_steps,
    is_assessment_host,
    is_test_step,
)
from auto_apply.domain.applications.form_model import (
    REQUIRED,
    ControlRef,
    FormLink,
    FormQuestion,
    FormStep,
    QuestionKind,
)


def _step(*links: FormLink, questions: tuple[FormQuestion, ...] = (),
          signals: tuple[str, ...] = ()) -> FormStep:
    return FormStep("https://jobs.acme.example/apply", "Apply", "application", questions, (),
                    "fp", links=links, test_signals=signals)


def test_a_known_assessment_platform_is_an_assessment_by_its_host() -> None:
    found = external_steps(_step(FormLink("https://acme.hackerrank.com/tests/1", "Start",
                                          "Our first step")))
    assert [(e.kind, e.host, e.required, e.evidence) for e in found] == [
        ("assessment", "acme.hackerrank.com", False, "host")]
    assert is_assessment_host("acme.hackerrank.com") and not is_assessment_host("rank.com")
    assert is_assessment_host("aon.maptq.com") and not is_assessment_host("www.aon.com")
    for look_alike in ("hackerrank.com.evil.example", "nothackerrank.com"):
        assert not is_assessment_host(look_alike), look_alike


def test_required_wording_in_any_language_makes_it_a_condition() -> None:
    found = external_steps(_step(FormLink(
        "https://tests.example.org/x", "Zum Test",
        "Bitte absolvieren Sie den Eignungstest. Bewerbungen ohne Test werden nicht "
        "berücksichtigt.")))
    assert [(e.kind, e.required) for e in found] == [("assessment", True)]


def test_another_form_the_page_says_must_be_done_first() -> None:
    found = external_steps(_step(FormLink(
        "https://forms.example.org/extra", "this form",
        "You must complete this form before submitting, or we cannot review your "
        "application.")))
    assert [(e.kind, e.required) for e in found] == [("external_form", True)]


def test_ordinary_links_are_not_external_steps() -> None:
    assert external_steps(_step(
        FormLink("https://jobs.acme.example/privacy", "Privacy policy", "Read our policy"),
        FormLink("https://www.acme.example/about", "About us", "Learn more about us"),
    )) == ()


def test_a_question_that_names_a_required_assessment_without_a_link() -> None:
    q = FormQuestion(key="q", label="I have completed the coding test (required)",
                     kind=QuestionKind.CHECKBOX, field_type="checkbox",
                     controls=(ControlRef(path=(("c", 1),), tag="input"),), required=REQUIRED)
    found = external_steps(_step(questions=(q,)))
    assert [(e.kind, e.required) for e in found] == [("assessment", True)]


def test_only_structure_makes_a_page_a_test() -> None:
    assert is_test_step(_step(signals=("role=timer",))) == ("role=timer",)
    assert is_test_step(_step(signals=("something-else",))) == ()
    words_only = _step(FormLink("https://x.example/y", "Assessment", "Our assessment centre"))
    assert is_test_step(words_only) == ()


def test_a_page_on_an_assessment_platform_is_a_test_page() -> None:
    """A redirect from the application straight into the test."""
    on_platform = FormStep("https://acme.hackerrank.com/tests/1/login", "Test", "application",
                           (), (), "fp")
    assert is_test_step(on_platform) == ("assessment-host",)


def test_the_forms_own_required_note_does_not_make_a_link_a_condition() -> None:
    assert external_steps(_step(FormLink(
        "https://careers-policies.example.net/privacy", "privacy policy",
        "Required fields are marked *. See our privacy policy."))) == ()


def test_a_required_question_about_past_assessments_is_not_a_condition() -> None:
    q = FormQuestion(key="q", label="Have you taken an assessment with us before? *",
                     kind=QuestionKind.RADIO, field_type="x",
                     controls=(ControlRef(path=(("c", 1),), tag="input"),), required=REQUIRED)
    assert external_steps(_step(questions=(q,))) == ()

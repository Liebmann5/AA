"""Pins for where application answers come from, and what the policy does with them.

Rulings these hold (owner, standing): sensitive answers come only from what
the person declared; AA never guesses a demographic, legal or open-ended
answer; an optional box (job alerts, keep-my-data) is left unticked; a value
already in a field is kept; a configured résumé that cannot be found is
reported, never silently skipped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from auto_apply.domain.applications.answers import (
    Answer,
    AnswerContext,
    ProfileAnswerSource,
    SessionAnswerMemory,
    TemplateAnswerSource,
    is_protected,
)
from auto_apply.domain.applications.fill_policy import (
    ASK,
    FILL_ACTION,
    LEAVE,
    FillSettings,
    decide,
)
from auto_apply.domain.applications.form_model import (
    HIDDEN,
    OPTIONAL,
    REQUIRED,
    TRAP,
    UNKNOWN,
    ControlRef,
    ControlState,
    FormOption,
    FormQuestion,
    QuestionKind,
)
from auto_apply.domain.models.profile import UserProfile

_CTX = AnswerContext(job_title="Data Analyst", company="Northwind", host="jobs.example")
_REF = ControlRef(path=(("c", 0),), tag="input", type="text", name="x", id="x")


def _q(label: str, field_type: str, kind: str = QuestionKind.TEXT, *, required: str = UNKNOWN,
       options: tuple[str, ...] = (), sensitive: bool = False, decision: str = "FILL") -> FormQuestion:
    return FormQuestion(
        key=label, label=label, kind=kind, field_type=field_type, controls=(_REF,),
        required=required, sensitive=sensitive, decision=decision,
        options=tuple(FormOption(o) for o in options),
    )


def _profile(tmp_path: Path, **over: Any) -> UserProfile:
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n")
    data: dict[str, Any] = {
        "profile_name": "Test Person",
        "personal_info": {
            "first_name": "Ada", "last_name": "Quill", "email": "ada@example.org",
            "phone_number": "5551234567", "street_address": "1 Main St",
            "city": "Chicago", "state": "IL",
            "zip_code": "60601", "country": "United States", "resume_path": str(resume),
        },
        "links": {},
        "search_preferences": {"desired_job_titles": ["Data Analyst"]},
        "career_summary": "Analyst with five years of logistics data experience.",
        "legal_info": {"has_work_authorization": True, "requires_sponsorship": False},
    }
    data.update(over)
    return UserProfile(**data)


@pytest.fixture()
def source(tmp_path: Path) -> ProfileAnswerSource:
    return ProfileAnswerSource(_profile(tmp_path))


# ── Profile answers ──────────────────────────────────────────────────────────


def test_contact_fields_come_from_the_profile(source: ProfileAnswerSource) -> None:
    assert source.propose(_q("First name", "first_name"), _CTX).text == "Ada"  # type: ignore[union-attr]
    assert source.propose(_q("Email", "email"), _CTX).text == "ada@example.org"  # type: ignore[union-attr]
    assert source.propose(_q("Full name", "full_name"), _CTX).text == "Ada Quill"  # type: ignore[union-attr]


def test_a_place_carries_the_wordings_a_picker_lists(source: ProfileAnswerSource) -> None:
    a = source.propose(_q("Location (city)", "location", QuestionKind.COMBOBOX), _CTX)
    assert a is not None
    assert a.text == "Chicago, IL"
    assert "Chicago, Illinois" in a.wordings()


def test_the_resume_is_a_resolved_file(source: ProfileAnswerSource, tmp_path: Path) -> None:
    a = source.propose(_q("Resume", "resume", QuestionKind.FILE), _CTX)
    assert a is not None and Path(a.file_path).name == "resume.pdf"


def test_a_configured_resume_that_is_missing_is_reported(tmp_path: Path) -> None:
    prof = _profile(tmp_path)
    (tmp_path / "resume.pdf").unlink()
    a = ProfileAnswerSource(prof).propose(_q("Resume", "resume", QuestionKind.FILE), _CTX)
    assert a is not None and a.file_path == "" and a.source.endswith("_missing")
    # ...and the policy asks rather than skipping it, even when optional.
    d = decide(_q("Resume", "resume", QuestionKind.FILE, required=OPTIONAL),
               ControlState(present=True, visible=True), a, FillSettings())
    assert d.action == ASK and d.reason == "document-missing"


def test_legal_answers_are_flagged_and_can_be_turned_off(tmp_path: Path) -> None:
    q = _q("Are you legally authorized to work in the United States?", "work_authorization",
           QuestionKind.RADIO, options=("Yes", "No"), sensitive=True)
    a = ProfileAnswerSource(_profile(tmp_path)).propose(q, _CTX)
    assert a is not None and a.text == "Yes" and a.sensitive and a.review
    assert ProfileAnswerSource(_profile(tmp_path), legal_from_profile=False).propose(q, _CTX) is None


def test_legal_questions_about_another_country_are_not_answered(source: ProfileAnswerSource) -> None:
    q = _q("Are you legally authorized to work in Canada?", "work_authorization",
           QuestionKind.RADIO, options=("Yes", "No"), sensitive=True)
    assert source.propose(q, _CTX) is None


def test_a_negatively_phrased_legal_question_is_left_to_the_person(source: ProfileAnswerSource) -> None:
    q = _q("Are you NOT authorized to work in the US?", "work_authorization",
           QuestionKind.RADIO, options=("Yes", "No"), sensitive=True)
    assert source.propose(q, _CTX) is None


@pytest.mark.parametrize("label", [
    "Sind Sie berechtigt, in den USA zu arbeiten?",
    "Êtes-vous autorisé à travailler aux États-Unis ?",
])
def test_a_legal_question_in_another_language_is_left_to_the_person(
        source: ProfileAnswerSource, label: str) -> None:
    """docs/adr/025: the negative-phrasing and country rules are English; a
    yes/no on work authorisation is never guessed in another language."""
    q = _q(label, "work_authorization", QuestionKind.RADIO, options=("Ja", "Nein"),
           sensitive=True)
    assert source.propose(q, _CTX) is None


def test_on_a_form_in_another_language_english_loanwords_do_not_make_a_legal_question_english(
        source: ProfileAnswerSource) -> None:
    """"Visa-Sponsoring" is an English word in a German question: the
    question's negation ("kein") is German, which the English rule cannot
    read. On a form that may be German, the person answers."""
    q = _q("Benötigen Sie jetzt oder künftig ein Visa-Sponsoring?", "sponsorship",
           QuestionKind.RADIO, options=("Ja", "Nein"), sensitive=True)
    german = AnswerContext(company="Northwind", form_locales=("de", "en"))
    assert source.propose(q, german) is None
    english = _q("Will you now or in the future require visa sponsorship?", "sponsorship",
                 QuestionKind.RADIO, options=("Yes", "No"), sensitive=True)
    a = source.propose(english, AnswerContext(company="Northwind", form_locales=("en",)))
    assert a is not None and a.source == "profile:legal_info.requires_sponsorship"


def test_demographics_are_never_guessed(source: ProfileAnswerSource) -> None:
    for t in ("gender", "ethnicity", "veteran", "disability"):
        assert source.propose(_q(t, t, QuestionKind.SELECT, sensitive=True), _CTX) is None


def test_declared_demographics_are_used_and_flagged(tmp_path: Path) -> None:
    src = ProfileAnswerSource(_profile(tmp_path, eeo_info={"gender": "Female"}))
    a = src.propose(_q("Gender", "gender", QuestionKind.SELECT, sensitive=True), _CTX)
    assert a is not None and a.text == "Female" and a.sensitive and a.review


def test_open_questions_are_not_invented(source: ProfileAnswerSource) -> None:
    q = _q("Why do you want to work at Northwind?", "text", QuestionKind.TEXTAREA)
    assert source.propose(q, _CTX) is None
    summary = _q("Tell us about yourself", "text", QuestionKind.TEXTAREA)
    a = source.propose(summary, _CTX)
    assert a is not None and a.source == "profile:career_summary" and a.review


def test_passwords_are_never_answered(source: ProfileAnswerSource) -> None:
    assert source.propose(_q("Password", "password", QuestionKind.PASSWORD), _CTX) is None


# ── Saved answers and session memory ────────────────────────────────────────


def test_a_saved_template_answers_free_text_only(tmp_path: Path) -> None:
    prof = _profile(tmp_path, custom_answer_templates=[
        {"keywords": ["hear about"], "answer": "A friend who works there told me.",
         "max_length": 0},
    ])
    src = TemplateAnswerSource(prof)
    a = src.propose(_q("How did you hear about us?", "text"), _CTX)
    assert a is not None and a.text == "A friend who works there told me."
    assert a.source == "saved" and a.review
    assert src.propose(_q("How did you hear about us?", "text", QuestionKind.SELECT), _CTX) is None
    # Literal on purpose: a phrase never matches a question missing one of its words.
    assert src.propose(_q("Where did you find this posting?", "text"), _CTX) is None


def test_session_memory_reuses_a_general_answer_across_companies() -> None:
    mem = SessionAnswerMemory()
    q = _q("Are you willing to relocate?", "text", QuestionKind.RADIO, options=("Yes", "No"))
    mem.remember(q, "Yes", company="Northwind")
    assert mem.propose(q, AnswerContext(company="Contoso")).text == "Yes"  # type: ignore[union-attr]
    legal = _q("Are you legally authorized to work in the US?", "work_authorization",
               QuestionKind.RADIO, options=("Yes", "No"), sensitive=True)
    mem.remember(legal, "Yes", company="Northwind")
    assert mem.propose(legal, AnswerContext(company="Contoso")) is not None, (
        '"the US" is the country, not "us" the employer'
    )


@pytest.mark.parametrize("label", [
    "Why do you want to work here?",          # the reviewer's example
    "What motivates you to apply?",           # open-ended, names nothing
])
def test_a_single_line_open_answer_never_reaches_another_company(label: str) -> None:
    """Review finding: an open question rendered as <input type=text>."""
    mem = SessionAnswerMemory()
    q = _q(label, "text", QuestionKind.TEXT)
    mem.remember(q, "Building tools for warehouses.", company="Northwind")
    assert mem.propose(q, AnswerContext(company="Contoso")) is None
    assert mem.propose(q, AnswerContext(company="Northwind")) is not None


@pytest.mark.parametrize(("label", "value"), [
    ("Have you worked here before?", "No"),                 # about "here"
    ("How did you hear about us?", "LinkedIn"),             # about "us"
    ("Who referred you to this position?", "Sam"),          # about "this position"
    ("Referral source", "Jane, a manager at Northwind"),    # the answer names the employer
    ("Portfolio notes", "x" * 81),                          # long prose
])
def test_company_specific_answers_stay_with_their_company(label: str, value: str) -> None:
    mem = SessionAnswerMemory()
    q = _q(label, "text")
    mem.remember(q, value, company="Northwind")
    assert mem.propose(q, AnswerContext(company="Contoso")) is None
    assert mem.propose(q, AnswerContext(company="Northwind")) is not None


def test_a_company_specific_answer_without_a_company_is_not_kept() -> None:
    mem = SessionAnswerMemory()
    q = _q("Why do you want to work here?", "text")
    mem.remember(q, "Because.", company="")
    assert len(mem) == 0


# ── Protected questions, whatever the reader classified ──────────────────────


@pytest.mark.parametrize(("label", "field_type", "sensitive", "expected"), [
    ("Explain your current work authorization", "text", False, True),
    ("Will you now or in the future require visa sponsorship?", "text", False, True),
    ("Are you Hispanic or Latino?", "text", False, True),
    ("Gender", "gender", True, True),
    ("Anything", "work_authorization", False, True),   # the type alone suffices
    ("First name", "first_name", False, False),
    ("Language skills", "text", False, False),          # "age" only as a whole word
])
def test_protected_questions_are_recognised(label: str, field_type: str, sensitive: bool,
                                            expected: bool) -> None:
    assert is_protected(_q(label, field_type, sensitive=sensitive)) is expected


def test_no_source_but_the_person_fills_a_misclassified_protected_question(tmp_path: Path) -> None:
    """Review finding: protection must not depend on the reader's sensitive flag."""
    q = _q("Explain your current work authorization status", "text", QuestionKind.TEXTAREA)
    prof = _profile(tmp_path, custom_answer_templates=[
        {"keywords": ["work authorization"], "answer": "I am authorized to work here.", "max_length": 0},
    ])
    assert TemplateAnswerSource(prof).propose(q, _CTX) is None
    assert ProfileAnswerSource(prof).propose(q, _CTX) is None
    about = _q("Tell us about yourself and your visa status", "text", QuestionKind.TEXTAREA)
    assert ProfileAnswerSource(prof).propose(about, _CTX) is None, (
        "the career summary is never used for a protected question"
    )


def test_a_required_protected_box_is_asked_not_ticked() -> None:
    q = _q("I am authorized to work in the United States", "checkbox", QuestionKind.CHECKBOX,
           required=REQUIRED)
    assert decide(q, _VISIBLE, None, FillSettings()).action == ASK


def test_session_memory_never_sends_an_open_answer_to_another_company() -> None:
    """An answer written for one employer must never reach another."""
    mem = SessionAnswerMemory()
    q = _q("Why do you want to work here?", "text", QuestionKind.TEXTAREA)
    mem.remember(q, "Because Northwind builds great tools.", company="Northwind")
    assert mem.propose(q, AnswerContext(company="Contoso")) is None
    assert mem.propose(q, AnswerContext(company="Northwind")) is not None
    mem.remember(q, "unscoped", company="")
    assert mem.propose(q, AnswerContext(company="")) is None


# ── The fill policy ──────────────────────────────────────────────────────────

_VISIBLE = ControlState(present=True, visible=True)
_ANSWER = Answer(text="x", source="profile:test", confidence=0.95)


@pytest.mark.parametrize("decision", [TRAP, HIDDEN, "SKIP"])
def test_traps_and_skips_are_never_touched(decision: str) -> None:
    q = _q("Website", "website", decision=decision)
    assert decide(q, _VISIBLE, _ANSWER, FillSettings()).action == LEAVE


def test_an_invisible_control_is_not_on_this_step() -> None:
    d = decide(_q("Name", "first_name"), ControlState(present=True, visible=False), _ANSWER,
               FillSettings())
    assert d.action == LEAVE and d.reason == "not-on-this-step"


def test_a_prefilled_value_is_kept_unless_overwriting_is_on() -> None:
    state = ControlState(present=True, visible=True, value="Ada")
    assert decide(_q("Name", "first_name"), state, _ANSWER, FillSettings()).reason == "prefilled"
    assert decide(_q("Name", "first_name"), state, _ANSWER,
                  FillSettings(overwrite_prefilled=True)).action == FILL_ACTION


def test_a_required_acknowledgement_is_ticked_and_an_optional_box_is_not() -> None:
    cert = _q("I certify the above is true", "checkbox", QuestionKind.CHECKBOX, required=REQUIRED)
    alerts = _q("Send me job alerts", "checkbox", QuestionKind.CHECKBOX, required=OPTIONAL)
    d = decide(cert, _VISIBLE, None, FillSettings())
    assert d.action == FILL_ACTION and d.answer is not None and d.answer.checked is True
    assert decide(cert, _VISIBLE, None, FillSettings(acknowledge_required=False)).action == ASK
    assert decide(alerts, _VISIBLE, None, FillSettings()).reason == "optional-checkbox-left-unticked"


def test_a_sensitive_required_box_is_asked_not_ticked() -> None:
    q = _q("I have a disability", "disability", QuestionKind.CHECKBOX, required=REQUIRED,
           sensitive=True)
    assert decide(q, _VISIBLE, None, FillSettings()).action == ASK


def test_no_answer_asks_only_when_required() -> None:
    assert decide(_q("Q", "text", required=REQUIRED), _VISIBLE, None, FillSettings()).action == ASK
    assert decide(_q("Q", "text", required=OPTIONAL), _VISIBLE, None, FillSettings()).action == LEAVE
    assert decide(_q("Q", "text", required=UNKNOWN), _VISIBLE, None, FillSettings()).action == LEAVE


def test_a_low_confidence_answer_is_not_used() -> None:
    weak = Answer(text="maybe", source="generated", confidence=0.5)
    d = decide(_q("Q", "text", required=OPTIONAL), _VISIBLE, weak, FillSettings())
    assert d.action == LEAVE and d.reason == "low-confidence-answer-not-used"

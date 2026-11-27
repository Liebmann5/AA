"""Where answers come from. Pure: the profile and what the person said.

An :class:`Answer` is a proposal with its provenance. Sources are consulted
in a configured order and the first answer at or above the confidence bar
wins (``application/services/form_engine.py``). Every source here answers
only from what the person declared — the profile, their saved answers, or
what they typed into a form earlier in the same session. None of them
invents a fact:

* a field the profile does not hold gets no answer (the engine leaves it, or
  asks the person when it is required);
* sensitive questions (work authorisation, sponsorship, demographic and
  disability questions) are answered only from what the profile states: the
  ``LegalInfo`` pair (unless ``legal_from_profile`` is off, when the person is
  asked in place), and a non-empty ``EEOInfo`` field for the demographic ones
  — an empty one is never guessed. Every such answer is flagged for the
  pre-submit review;
* a long question is never answered with a short field's value: a question
  that merely mentions "name" is not a name field (pagecomp's reader already
  keeps long questions away from short field types).

The career summary is used only where the question asks for a summary of
the person (a textarea labelled "summary", "about you", "tell us about
yourself"); it is never pasted into an unknown field (E2E-A3).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from auto_apply.domain.applications.form_language import says, which
from auto_apply.domain.applications.form_model import FormQuestion, QuestionKind
from auto_apply.domain.applications.option_matching import (
    COUNTRY_FAMILIES,
    US_STATES,
    content_tokens,
    normalize,
)
from auto_apply.domain.models.documents import is_document_path


@dataclass(frozen=True)
class Answer:
    """A proposed answer and where it came from.

    Attributes:
        text: The text to type, or the preferred wording of a choice.
        choices: Further equivalent wordings for option matching.
        many: Several options to tick (a checkbox group, a multi-select).
        checked: The desired state of a single checkbox.
        file_path: An absolute path for a file upload.
        source: Provenance, e.g. ``profile:personal_info.email``,
            ``saved``, ``session``, ``human``, ``generated``,
            ``acknowledgement``.
        confidence: 0..1; below the engine's bar the answer is not used.
        sensitive: The answer is personal in the protected sense; it is
            never remembered beyond the session and never logged.
        review: Worth pointing out at the pre-submit review.
    """

    text: str = ""
    choices: tuple[str, ...] = ()
    many: tuple[str, ...] = ()
    checked: bool | None = None
    file_path: str = ""
    source: str = ""
    confidence: float = 1.0
    sensitive: bool = False
    review: bool = False

    def wordings(self) -> tuple[str, ...]:
        """Every phrasing that means this answer, preferred first."""
        out = [self.text] if self.text else []
        out.extend(c for c in self.choices if c and c not in out)
        return tuple(out)


@dataclass(frozen=True)
class AnswerContext:
    """What the engine knows about the application being filled."""

    job_title: str = ""
    company: str = ""
    host: str = ""
    #: The languages the step's words may be in (``FormStep.locales``: the
    #: declared language, languages whose own words the step shows, and
    #: English). Empty when unknown. A rule that reads a question's wording in
    #: one language (the English legal rule) applies only when the form can
    #: be in no other (docs/adr/025).
    form_locales: tuple[str, ...] = ()


def question_text(q: FormQuestion) -> str:
    """The question as a person reads it: label, then any description."""
    return f"{q.label} {q.description}".strip()


#: Canonical field types whose answers are protected: only the person's own
#: declaration (their profile's explicit field, or their answer in place)
#: may fill them. pagecomp's reader marks most of these ``sensitive``.
PROTECTED_TYPES = frozenset({
    "work_authorization", "sponsorship", "gender", "ethnicity", "race", "veteran",
    "disability", "pronouns", "birth_date", "age", "criminal_history",
    "sexual_orientation", "religion", "marital_status",
})


def is_protected(q: FormQuestion) -> bool:
    """Is this a question only the person's own declaration may answer?

    Holds whatever the perception classified: the reader's ``sensitive``
    flag, the canonical type, or the question's own words — its label and
    description, in **any** language (``form_lexicon`` class ``protected``:
    work authorisation and visas, nationality, sex and gender, pronouns,
    race and ethnicity, veteran status, disability and accommodation
    requests, age and birth date, criminal history, religion, marital and
    family status, pregnancy, health conditions). Every answer source and
    the acknowledgement rule ask this, not ``q.sensitive`` alone. A false
    positive only means AA asks the person.
    """
    return bool(q.sensitive or q.field_type in PROTECTED_TYPES
                or says(question_text(q), "protected"))


def company_specific(q: FormQuestion, value: str, company: str) -> bool:
    """Would reusing this answer at another employer risk sending one
    employer's answer to another? Fail closed, in any language: open-ended
    questions ("why", "describe", "warum"), questions about this employer
    ("here", "us", "the company", "bei uns", "chez nous"), answers that
    address the employer ("your team", "votre entreprise"), questions or
    answers that name it, and long prose are all company-specific, whatever
    widget they use."""
    label = q.label or ""
    name = normalize(company)
    return bool(
        q.kind == QuestionKind.TEXTAREA
        or says(label, "open_ended")
        or says(label, "company_relative")
        or says(value, "answer_company_relative")
        or (name and (name in normalize(label) or name in normalize(value)))
        or len(value) > 80
    )


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def _country_family(text: str) -> frozenset[str] | None:
    n = f" {normalize(text)} "
    for fam in COUNTRY_FAMILIES:
        for member in sorted(fam, key=len, reverse=True):
            if len(member) > 3 and f" {member} " in n:
                return fam
    return None


def _yes_no(value: bool, *, sensitive: bool, source: str) -> Answer:
    return Answer(
        text="Yes" if value else "No",
        choices=("yes",) if value else ("no",),
        checked=value,
        source=source,
        confidence=0.95,
        sensitive=sensitive,
        review=True,
    )


class ProfileAnswerSource:
    """Answers from the user's profile, by canonical field type and question.

    Deterministic: the same profile and question give the same answer.
    """

    name = "profile"

    #: Protected types this source answers, each from its explicit field.
    _PROTECTED_HANDLED = frozenset({
        "work_authorization", "sponsorship", "gender", "ethnicity", "veteran",
        "disability", "pronouns",
    })

    def __init__(self, profile: Any, *, legal_from_profile: bool = True) -> None:
        self._p = profile
        self._legal_from_profile = legal_from_profile

    # -- helpers ----------------------------------------------------------
    def _text(self, value: Any, source: str, *, confidence: float = 0.95,
              review: bool = False) -> Answer | None:
        if value is None:
            return None
        s = str(value).strip()
        if not s:
            return None
        return Answer(text=s, source=source, confidence=confidence, review=review)

    def _pi(self, field: str) -> Any:
        return getattr(getattr(self._p, "personal_info", None), field, None)

    def _current_job(self) -> Any | None:
        for exp in getattr(self._p, "work_experience", None) or []:
            end = str(getattr(exp, "end_date", "") or "").strip().lower()
            if end in ("", "present", "current", "now", "none"):
                return exp
        return None

    def _education(self) -> Any | None:
        items = list(getattr(self._p, "education", None) or [])
        return items[0] if items else None

    # -- the one entry point ----------------------------------------------
    def propose(self, q: FormQuestion, ctx: AnswerContext) -> Answer | None:
        t = q.field_type
        text = normalize(question_text(q))
        if q.kind == QuestionKind.PASSWORD or t in ("password", "username", "otp", "birth_date"):
            return None
        if is_protected(q) and t not in self._PROTECTED_HANDLED:
            # A protected question the reader did not type as one of the
            # declared fields below: never answered from a generic field.
            return None

        if t == "resume" and q.kind == QuestionKind.FILE:
            return self._file("resume")
        if t == "cover_letter":
            if q.kind == QuestionKind.FILE:
                return self._file("cover_letter")
            letter = self._pi("cover_letter")
            if isinstance(letter, str) and letter.strip() and not is_document_path(letter):
                return Answer(text=letter, source="profile:personal_info.cover_letter",
                              confidence=0.95, review=True)
            return None
        if q.kind == QuestionKind.FILE:
            return None

        simple: Mapping[str, tuple[str, str]] = {
            "first_name": ("first_name", "personal_info.first_name"),
            "last_name": ("last_name", "personal_info.last_name"),
            "middle_name": ("middle_name", "personal_info.middle_name"),
            "email": ("email", "personal_info.email"),
            "phone": ("phone_number", "personal_info.phone_number"),
            "address": ("street_address", "personal_info.street_address"),
            "postal_code": ("zip_code", "personal_info.zip_code"),
        }
        if t in ("city", "location"):
            return self._place(t)
        if t in simple:
            field, src = simple[t]
            if t == "first_name" and _has(text, r"\bpreferred\b"):
                # "Preferred name": the first name, a little less certain.
                return self._text(self._pi("first_name"), "profile:" + src, confidence=0.85)
            return self._text(self._pi(field), "profile:" + src)
        if t == "full_name":
            first, last = self._pi("first_name"), self._pi("last_name")
            if first and last:
                return Answer(text=f"{first} {last}", source="profile:personal_info.name",
                              confidence=0.95)
            return None
        if t == "region":
            state = self._pi("state")
            if not state:
                return None
            return Answer(text=str(state), choices=(str(state),),
                          source="profile:personal_info.state", confidence=0.95)
        if t == "country":
            country = self._pi("country")
            return self._text(country, "profile:personal_info.country")
        if t in ("linkedin", "github", "website"):
            links = getattr(self._p, "links", None)
            attr = {"linkedin": "linkedin_url", "github": "github_url",
                    "website": "portfolio_url"}[t]
            value = getattr(links, attr, None)
            if value is None and t == "website" and _has(text, r"\bgithub\b"):
                value = getattr(links, "github_url", None)
            return self._text(value, f"profile:links.{attr}")
        if t == "employer":
            if _has(text, r"\b(previous|past|former)\b"):
                return None
            job = self._current_job()
            if job is None:
                return None
            return self._text(getattr(job, "company", None), "profile:work_experience.company",
                              confidence=0.85)
        if t == "job_title":
            if _has(text, r"\b(current|recent|present|latest)\b"):
                job = self._current_job()
                if job is None:
                    return None
                return self._text(getattr(job, "title", None), "profile:work_experience.title",
                                  confidence=0.85)
            if _has(text, r"\b(applying|applied|interested in|desired)\b") and ctx.job_title:
                return Answer(text=ctx.job_title, source="context:job_title", confidence=0.8)
            return None
        if t == "school":
            edu = self._education()
            return self._text(getattr(edu, "school", None), "profile:education.school",
                              confidence=0.85) if edu else None
        if t == "degree":
            edu = self._education()
            if edu is None:
                return None
            if _has(text, r"\b(major|discipline|field of study|subject|concentration)\b"):
                return self._text(getattr(edu, "discipline", None), "profile:education.discipline",
                                  confidence=0.85)
            return self._text(getattr(edu, "degree", None), "profile:education.degree",
                              confidence=0.8)
        if t == "salary":
            prefs = getattr(self._p, "search_preferences", None)
            salary = getattr(prefs, "expected_salary", None)
            if salary is None:
                return None
            return Answer(text=str(salary), source="profile:search_preferences.expected_salary",
                          confidence=0.9, review=True)
        if t == "start_date":
            prefs = getattr(self._p, "application_preferences", None)
            return self._text(getattr(prefs, "earliest_start_date", None),
                              "profile:application_preferences.earliest_start_date",
                              confidence=0.85, review=True)
        if t == "work_authorization":
            return self._legal("has_work_authorization", text, ctx)
        if t == "sponsorship":
            return self._legal("requires_sponsorship", text, ctx)
        if t in ("gender", "ethnicity", "veteran", "disability", "pronouns"):
            return self._demographic(t, text, q)
        if t == "relocation":
            return None
        # Summary-type open questions: the person's own summary, verbatim.
        if q.kind == QuestionKind.TEXTAREA and _has(
            text,
            r"\b(summary|about (you|yourself)|tell us about yourself|introduce yourself|"
            r"professional background|your background)\b",
        ):
            summary = str(getattr(self._p, "career_summary", "") or "").strip()
            if summary:
                return Answer(text=summary, source="profile:career_summary",
                              confidence=0.8, review=True)
        return None

    # -- families ---------------------------------------------------------
    def _place(self, t: str) -> Answer | None:
        """City or "City, State": typed as written, with the wordings a
        place picker lists ("Chicago, IL", "Chicago, Illinois") for choosing."""
        city = str(self._pi("city") or "").strip()
        state = str(self._pi("state") or "").strip()
        if not city:
            return None
        state_name = US_STATES.get(state.upper(), state) if state else ""
        wordings = [f"{city}, {state}"] if state else []
        if state_name and state_name != state:
            wordings.append(f"{city}, {state_name}")
        if t == "location" and state:
            return Answer(text=f"{city}, {state}", choices=tuple(wordings[1:]) + (city,),
                          source="profile:personal_info.city_state", confidence=0.85)
        return Answer(text=city, choices=tuple(wordings), source="profile:personal_info.city",
                      confidence=0.95)

    def _file(self, role: str) -> Answer | None:
        pi = getattr(self._p, "personal_info", None)
        if pi is None:
            return None
        resolver = getattr(
            pi, "get_resolved_resume_path" if role == "resume" else "get_resolved_cover_letter_path",
            None,
        )
        stored = getattr(pi, "resume_path" if role == "resume" else "cover_letter", None)
        if not stored or not callable(resolver):
            return None
        try:
            resolved = resolver()
        except Exception:
            resolved = None
        if resolved is None:
            # Configured but missing: the engine reports it; never a guess.
            return Answer(file_path="", source=f"profile:personal_info.{role}_missing",
                          confidence=0.0)
        return Answer(file_path=str(resolved), source=f"profile:personal_info.{role}",
                      confidence=1.0)

    def _legal(self, field: str, text: str, ctx: AnswerContext) -> Answer | None:
        legal = getattr(self._p, "legal_info", None)
        if legal is None or not self._legal_from_profile:
            return None
        if which(text, "protected", ["en"]) is None or any(
                loc != "en" for loc in ctx.form_locales):
            # A legal question AA cannot read in English, or on a form that
            # may be in another language (where an English word such as
            # "Visa-Sponsoring" can sit in a question whose negation AA cannot
            # read): the negative-phrasing and country rules below are
            # English, and a yes/no on work authorisation is too costly to
            # guess. The person answers it.
            return None
        if _has(text, r"\bnot\b.*\b(authori[sz]ed|eligible|require)") and not _has(
            text, r"\b(now or in the future|currently)\b"
        ):
            # A question phrased in the negative is answered by the person.
            return None
        asked = _country_family(text)
        home = _country_family(str(self._pi("country") or "")) or _country_family("united states")
        if asked is not None and asked != home:
            return None
        value = bool(getattr(legal, field, False))
        return _yes_no(value, sensitive=True, source=f"profile:legal_info.{field}")

    def _demographic(self, t: str, text: str, q: FormQuestion) -> Answer | None:
        eeo = getattr(self._p, "eeo_info", None)
        if t == "pronouns":
            value = self._pi("pronouns")
            if not value:
                return None
            return Answer(text=str(value), source="profile:personal_info.pronouns",
                          confidence=0.9, sensitive=True, review=True)
        if eeo is None:
            return None
        if t == "gender":
            value = getattr(eeo, "gender", None)
            return self._sensitive_choice(value, "eeo_info.gender")
        if t == "veteran":
            value = getattr(eeo, "veteran_status", None)
            return self._sensitive_choice(value, "eeo_info.veteran_status")
        if t == "disability":
            value = getattr(eeo, "disability_status", None)
            if value is None:
                return None
            return _yes_no(bool(value), sensitive=True, source="profile:eeo_info.disability_status")
        # ethnicity: a race question, or the separate "Hispanic or Latino?" yes/no
        race = getattr(eeo, "race_ethnicity", None)
        if not race:
            return None
        option_words = " ".join(normalize(o.label) for o in q.options)
        yes_no_only = bool(q.options) and all(
            normalize(o.label).split(" ", 1)[0] in ("yes", "no", "decline", "i")
            for o in q.options
        ) and ("yes" in option_words)
        if yes_no_only and _has(text, r"\b(hispanic|latino|latina|latinx)\b"):
            if "decline" in normalize(str(race)):
                return Answer(text=str(race), source="profile:eeo_info.race_ethnicity",
                              confidence=0.9, sensitive=True, review=True)
            return _yes_no(str(race).startswith("Hispanic"), sensitive=True,
                           source="profile:eeo_info.race_ethnicity")
        return self._sensitive_choice(race, "eeo_info.race_ethnicity")

    @staticmethod
    def _sensitive_choice(value: Any, field: str) -> Answer | None:
        if value is None or not str(value).strip():
            return None
        return Answer(text=str(value), source=f"profile:{field}", confidence=0.9,
                      sensitive=True, review=True)


class TemplateAnswerSource:
    """The person's pre-written answers (``UserProfile.custom_answer_templates``).

    A template answers a question when every content word of one of its
    keyword phrases appears in the question. Deterministic: ties go to the
    template listed first. Only free-text questions are answered this way.
    """

    name = "saved"

    def __init__(self, profile: Any) -> None:
        self._templates = list(getattr(profile, "custom_answer_templates", None) or [])

    def propose(self, q: FormQuestion, ctx: AnswerContext) -> Answer | None:
        if q.kind not in (QuestionKind.TEXT, QuestionKind.TEXTAREA) or is_protected(q):
            return None
        words = content_tokens(question_text(q))
        for tpl in self._templates:
            for phrase in getattr(tpl, "keywords", None) or []:
                need = content_tokens(str(phrase))
                if need and need <= words:
                    answer = str(getattr(tpl, "answer", "") or "")
                    limit = int(getattr(tpl, "max_length", 0) or 0)
                    if q.max_length:
                        limit = min(limit, q.max_length) if limit else q.max_length
                    if limit and len(answer) > limit:
                        answer = answer[:limit].rstrip()
                    if answer:
                        return Answer(text=answer, source="saved", confidence=0.85,
                                      review=True)
        return None


class SessionAnswerMemory:
    """Answers the person gave in place earlier in this session.

    Kept in memory only, for the life of the session; nothing is written to
    disk. Keyed by the normalised question text and widget shape, so the same
    question on the next application is answered the way the person
    answered it — and a differently worded question is not.

    An answer that is company-specific (:func:`company_specific`: open-ended
    questions in any widget, questions about "here"/"us", anything naming the
    employer, long prose) is kept for the company it was given for only; an
    answer written for one employer is never sent to another. Short,
    general facts ("Are you willing to relocate?") are reused everywhere.
    """

    name = "session"

    def __init__(self) -> None:
        self._answers: dict[tuple[str, str, str], Answer] = {}

    @staticmethod
    def key_of(q: FormQuestion, scope: str = "") -> tuple[str, str, str]:
        shape = "choice" if q.is_choice else q.kind
        return normalize(q.label)[:200], shape, normalize(scope)

    def remember(self, q: FormQuestion, value: str, *, many: tuple[str, ...] = (),
                 checked: bool | None = None, company: str = "") -> None:
        if not (value or many or checked is not None) or not normalize(q.label):
            return
        scope = ""
        if company_specific(q, " ".join((value, *many)), company):
            if not normalize(company):
                return  # company-specific, and no company to keep it for
            scope = company
        self._answers[self.key_of(q, scope)] = Answer(
            text=value, many=many, checked=checked, source="session", confidence=0.9,
            sensitive=is_protected(q), review=True,
        )

    def propose(self, q: FormQuestion, ctx: AnswerContext) -> Answer | None:
        if q.kind in (QuestionKind.FILE, QuestionKind.PASSWORD):
            return None
        if normalize(ctx.company):
            mine = self._answers.get(self.key_of(q, ctx.company))
            if mine is not None:
                return mine
        return self._answers.get(self.key_of(q, ""))

    def __len__(self) -> int:
        return len(self._answers)

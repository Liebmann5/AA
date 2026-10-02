"""Human labelling for AA's own measurements — the typed vocabulary.

Item 5 asks a person to say what is true about pages and applications AA
has already judged: was this "blocked" page really blocking, which gates did
this application really have. Those answers are the ground truth every
detector's error rate is measured against, so they are kept as carefully as
the research rows themselves.

The vocabulary is general on purpose. A Study is a question set with a
version; an Item is one thing to judge, carrying what AA concluded about it
(``aa_facts``) but never showing that to the labeller until after they
answer; an Annotation is one person's answers to one item under one study
version. New studies — detector signals, location ground truth, form
friction — are new Study values, not new code paths.

Pure data and validation: no I/O, standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "Choice",
    "Question",
    "Study",
    "Item",
    "Annotation",
    "AnswerValue",
    "answers_problems",
]

#: What one answer can be: a choice key, several keys, a number, or text.
AnswerValue = str | tuple[str, ...] | float

QuestionKind = Literal["one", "many", "number", "text"]


@dataclass(frozen=True)
class Choice:
    """One option. ``key`` is what is stored; never change a key once data
    exists — add a new one and retire the old one in a new study version."""

    key: str
    label: str
    hint: str = ""
    #: For a "many" question: this choice cannot be combined with others
    #: ("None of these").
    exclusive: bool = False


@dataclass(frozen=True)
class Question:
    """One question in a study.

    ``ask_if`` makes a question conditional: (question id, choice keys); it
    is asked only when that earlier answer is one of those keys.
    """

    id: str
    prompt: str
    kind: QuestionKind
    choices: tuple[Choice, ...] = ()
    required: bool = True
    help: str = ""
    ask_if: tuple[str, tuple[str, ...]] | None = None

    def applies(self, answers: dict[str, AnswerValue]) -> bool:
        """Whether this question is asked, given the answers so far."""
        if self.ask_if is None:
            return True
        source, keys = self.ask_if
        given = answers.get(source)
        if isinstance(given, tuple):
            return any(k in keys for k in given)
        return given in keys

    def choice_keys(self) -> tuple[str, ...]:
        return tuple(c.key for c in self.choices)


@dataclass(frozen=True)
class Study:
    """A versioned question set about one kind of item.

    Bump ``version`` whenever a question's meaning or its choices change;
    annotations record the version they answered, so analyses never mix
    answers to different questions.
    """

    id: str
    title: str
    purpose: str
    version: int
    questions: tuple[Question, ...]
    item_noun: str = "item"

    def question(self, question_id: str) -> Question:
        for q in self.questions:
            if q.id == question_id:
                return q
        raise KeyError(question_id)


@dataclass(frozen=True)
class Item:
    """One thing to judge.

    ``item_id`` is stable across runs (a content digest for a saved page),
    so a label made today still attaches to the same item next month.
    ``aa_facts`` is what AA concluded — shown only AFTER the person answers,
    so the label is blind. ``display`` is what the person is shown first.
    ``open_path`` is a local file the surface may open for viewing.
    """

    study_id: str
    item_id: str
    title: str
    display: tuple[tuple[str, str], ...] = ()
    aa_facts: tuple[tuple[str, str], ...] = ()
    open_path: str = ""


@dataclass(frozen=True)
class Annotation:
    """One person's answers to one item, as recorded. Append-only: a revised
    answer is a new Annotation and the latest one per (item, annotator)
    counts; earlier ones stay on disk as the record of the revision."""

    study_id: str
    study_version: int
    item_id: str
    annotator: str
    answers: tuple[tuple[str, AnswerValue], ...]
    recorded_at: str
    seconds_spent: float = 0.0
    skipped: bool = False
    notes: dict[str, str] = field(default_factory=dict)

    def answer(self, question_id: str) -> AnswerValue | None:
        for key, value in self.answers:
            if key == question_id:
                return value
        return None


def answers_problems(study: Study, answers: dict[str, AnswerValue]) -> list[str]:
    """Everything wrong with a set of answers for a study; empty when valid.

    Checks that every applicable required question is answered, that choice
    answers use the question's keys, that numbers are non-negative numbers,
    and that no answer is given to a question that does not apply or does
    not exist.
    """
    problems: list[str] = []
    known = {q.id for q in study.questions}
    for key in answers:
        if key not in known:
            problems.append(f"{key}: not a question in {study.id} v{study.version}")
    for q in study.questions:
        given = answers.get(q.id)
        if not q.applies(answers):
            if given is not None:
                problems.append(f"{q.id}: answered but does not apply")
            continue
        if given is None or given == "" or given == ():
            if q.required:
                problems.append(f"{q.id}: required")
            continue
        if q.kind == "one":
            if not isinstance(given, str) or given not in q.choice_keys():
                problems.append(f"{q.id}: {given!r} is not one of {q.choice_keys()}")
        elif q.kind == "many":
            if not isinstance(given, tuple) or any(
                k not in q.choice_keys() for k in given
            ):
                problems.append(
                    f"{q.id}: {given!r} is not a subset of {q.choice_keys()}"
                )
            elif len(set(given)) != len(given):
                problems.append(f"{q.id}: {given!r} repeats a choice")
            else:
                alone = {c.key for c in q.choices if c.exclusive}
                if len(given) > 1 and alone & set(given):
                    problems.append(
                        f"{q.id}: {sorted(alone & set(given))} cannot be combined"
                    )
        elif q.kind == "number":
            if (
                isinstance(given, bool)
                or not isinstance(given, (int, float))
                or given < 0
            ):
                problems.append(f"{q.id}: {given!r} is not a non-negative number")
        elif q.kind == "text":
            if not isinstance(given, str):
                problems.append(f"{q.id}: {given!r} is not text")
    return problems

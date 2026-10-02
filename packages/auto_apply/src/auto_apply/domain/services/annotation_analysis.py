"""What the labels say (item 5): the reveal after each answer, and insights.

Pure functions over Items and Annotations. Every rate is shown with its
count, its denominator and a 95% Wilson interval, because a labelling set
is small and a bare percentage from twenty pages would overstate itself.
Items marked "can't tell" are counted and reported, never silently dropped
from a denominator.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from statistics import median

from auto_apply.domain.models.annotation import AnswerValue, Annotation, Item, Study
from auto_apply.domain.services.annotation_studies import (
    BLOCK_PAGES,
    BLOCKING_KINDS,
    GATE_CHOICES,
    MY_APPLICATIONS,
    NOT_BLOCKING_KINDS,
)
from auto_apply.domain.services.posting_observation import (
    LAW_JURISDICTIONS,
    infer_jurisdiction,
    infer_metro_area,
)
from auto_apply.domain.services.research_statistics import wilson_score_interval

__all__ = ["current_labels", "rate", "reveal_lines", "insight_lines"]


def current_labels(
    study: Study, annotations: Iterable[Annotation]
) -> dict[str, Annotation]:
    """The latest annotation per item for this study's CURRENT version.

    Later records replace earlier ones (a revised answer); answers to an
    older version of the questions are not mixed in.
    """
    latest: dict[str, Annotation] = {}
    for a in annotations:
        if a.study_id == study.id and a.study_version == study.version:
            latest[a.item_id] = a
    return latest


def rate(count: int, of: int) -> str:
    """'n of N (p%, 95% CI lo–hi%)', or 'n of 0' when there is nothing."""
    if of <= 0:
        return f"{count} of 0"
    lo, hi = wilson_score_interval(count, of)
    return (
        f"{count} of {of} ({count / of * 100:.0f}%, "
        f"95% CI {lo * 100:.0f}–{hi * 100:.0f}%)"
    )


def _facts(item: Item) -> dict[str, str]:
    return dict(item.aa_facts)


def _label(study: Study, question_id: str, key: AnswerValue | None) -> str:
    if key is None:
        return "—"
    q = study.question(question_id)
    by_key = {c.key: c.label for c in q.choices}
    if isinstance(key, tuple):
        return ", ".join(by_key.get(k, k) for k in key) or "—"
    return by_key.get(str(key), str(key))


# ── reveal ───────────────────────────────────────────────────────────────────


def reveal_lines(
    study: Study, item: Item, answers: dict[str, AnswerValue]
) -> tuple[str, ...]:
    """What AA concluded, set against the answer just given."""
    if study.id == BLOCK_PAGES.id:
        return _reveal_block(item, answers)
    if study.id == MY_APPLICATIONS.id:
        return _reveal_application(answers)
    return ()


def _reveal_block(item: Item, answers: dict[str, AnswerValue]) -> tuple[str, ...]:
    facts = _facts(item)
    quick = facts.get("quick_scan", "?")
    weighted = facts.get("weighted_check", "?")
    what = answers.get("what")
    lines = [
        f"AA's quick scan said: {quick}.  Its weighted check said: {weighted}.",
    ]
    if what in BLOCKING_KINDS:
        lines.append("You saw a real block, so the quick scan was right on this one.")
    elif what in NOT_BLOCKING_KINDS:
        lines.append("You saw no block, so the weighted check was right on this one.")
    else:
        lines.append("You couldn't tell, so this page counts for neither check.")
    return tuple(lines)


def _reveal_application(answers: dict[str, AnswerValue]) -> tuple[str, ...]:
    location = answers.get("location")
    if not isinstance(location, str) or not location.strip():
        return (
            "Logged. Add the location next time and AA will check its own reader against it.",
        )
    jurisdiction = infer_jurisdiction(location)
    metro = infer_metro_area(location)
    lines = [
        f"AA reads that location as: pay-law jurisdiction {jurisdiction or 'none'}, "
        f"metro {metro or 'none'}.",
    ]
    if jurisdiction in LAW_JURISDICTIONS and answers.get("pay_shown") == "none":
        lines.append(
            f"No pay shown where a pay-transparency law ({jurisdiction}) covers the "
            "posting: that is exactly the case AA's ST-01 detector looks for."
        )
    lines.append(
        "If AA read the location wrong, say so in the note — it becomes a test case."
    )
    return tuple(lines)


# ── insights ─────────────────────────────────────────────────────────────────


def insight_lines(
    study: Study, items: list[Item], annotations: Iterable[Annotation]
) -> tuple[str, ...]:
    """The study's findings so far, every rate with its denominator."""
    labels = current_labels(study, annotations)
    answered = {i: a for i, a in labels.items() if not a.skipped}
    if study.id == BLOCK_PAGES.id:
        return _insight_block(items, answered)
    if study.id == MY_APPLICATIONS.id:
        return _insight_applications(answered)
    return ()


def _insight_block(
    items: list[Item], answered: dict[str, Annotation]
) -> tuple[str, ...]:
    known = {i.item_id for i in items}
    rows = [a for i, a in answered.items() if i in known]
    kinds = Counter(str(a.answer("what")) for a in rows)
    blocking = sum(kinds[k] for k in BLOCKING_KINDS)
    not_blocking = sum(kinds[k] for k in NOT_BLOCKING_KINDS)
    decided = blocking + not_blocking
    lines = [
        f"Pages labelled: {len(rows)} of {len(items)}.",
        "On every one of these pages the quick scan said BLOCKED and the "
        "weighted check said NOT BLOCKED.",
    ]
    if decided:
        lines.append(f"The quick scan was right on {rate(blocking, decided)}.")
        lines.append(f"The weighted check was right on {rate(not_blocking, decided)}.")
    if kinds["unsure"]:
        lines.append(f"Couldn't tell: {kinds['unsure']} (left out of both rates).")
    passable = Counter(
        str(a.answer("passable")) for a in rows if a.answer("what") in BLOCKING_KINDS
    )
    if blocking:
        lines.append(
            f"Real blocks a person could get past by hand: {rate(passable['yes'], blocking)}."
        )
    breakdown = ", ".join(
        f"{_label(BLOCK_PAGES, 'what', k)} {n}" for k, n in kinds.most_common()
    )
    if breakdown:
        lines.append(f"What the pages were: {breakdown}.")
    if decided and decided < 30:
        lines.append(
            f"With {decided} decided pages the intervals are wide; every page "
            "you add narrows them."
        )
    return tuple(lines)


def _insight_applications(answered: dict[str, Annotation]) -> tuple[str, ...]:
    rows = list(answered.values())
    n = len(rows)
    if not n:
        return ("No applications logged yet.",)
    lines = [f"Applications logged: {n}."]
    gate_counts: Counter[str] = Counter()
    for a in rows:
        gates = a.answer("gates")
        if isinstance(gates, tuple):
            gate_counts.update(gates)
    labels = {c.key: c.label for c in GATE_CHOICES}
    for key, count in gate_counts.most_common():
        if key == "none":
            continue
        lines.append(f"  {labels.get(key, key)}: {rate(count, n)}")
    if gate_counts["none"]:
        lines.append(f"  No gates at all: {rate(gate_counts['none'], n)}")
    minutes = [
        float(m)
        for a in rows
        if isinstance((m := a.answer("minutes")), (int, float))
        and not isinstance(m, bool)
    ]
    if minutes:
        lines.append(
            f"Time per application: median {median(minutes):.0f} min, "
            f"total {sum(minutes):.0f} min."
        )
    outcomes = Counter(str(a.answer("outcome")) for a in rows)
    lines.append(f"Submitted: {rate(outcomes['submitted'], n)}.")
    pay = Counter(str(a.answer("pay_shown")) for a in rows)
    lines.append(f"Pay shown: {rate(pay['range'] + pay['single'], n)}.")
    covered = [
        a
        for a in rows
        if isinstance(a.answer("location"), str)
        and infer_jurisdiction(str(a.answer("location"))) in LAW_JURISDICTIONS
    ]
    if covered:
        hidden = sum(1 for a in covered if a.answer("pay_shown") == "none")
        lines.append(
            f"No pay shown where a pay-transparency law applies: {rate(hidden, len(covered))}."
        )
    return tuple(lines)

"""The day-one research record (Phase 0, P0-6; AA_ENGINE_MATH.md §12).

One row per answer decision (§5's approve/edit labels), per outcome channel's
first firing after a submit click (§6), and per validation flag (§4) — and
never a value, a label or page text. TEETH: the tables and the engine's
record did not exist.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from auto_apply.domain.applications.review_log import ReviewEvent, ValidationEvent
from tests.application.test_answer_review_and_external_steps import _open_page, _saved_template
from tests.application.test_form_engine import Form, _ctx, _engine

SECRET = "I like the mission."   # the saved answer's value; must appear nowhere


@pytest.fixture
def db(tmp_path, monkeypatch):
    import auto_apply.adapters.secondary.persistence.database as db_module

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "aa.db")
    db_module.DatabaseManager._instance = None
    try:
        yield db_module.DatabaseManager()
    finally:
        db_module.DatabaseManager._instance = None


def _all_rows(db) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    with db.get_connection() as conn:
        for table in ("field_review_log", "outcome_channel_log", "validation_event_log"):
            rows.extend(tuple(r) for r in conn.execute(f"SELECT * FROM {table}"))
    return rows


def test_the_engine_records_one_decision_per_answer_and_no_value() -> None:
    events: list[ReviewEvent] = []
    form = Form()
    _open_page(form)
    ctx = _ctx(lambda q, o, **k: "approve")
    ctx.on_review = events.append
    _engine(form, sources=[_saved_template(SECRET)]).run(ctx)
    decisions = {e.question_key: e.decision for e in events}
    assert decisions == {"First name *": "unreviewed", "Why this role? *": "approved"}
    assert SECRET not in repr(events)


def test_the_rows_are_written_hashed_and_carry_no_value_or_label(db) -> None:
    db.log_field_review(session_id="s", attempt_id="s:1", question_key="Why this role? *",
                        field_kind="textarea", ats_family="greenhouse", form_language="en",
                        trust_level="never", decision="approved", source="saved",
                        confidence_bucket=8, step_index=0)
    db.log_outcome_channel(attempt_id="s:1", channel="confirmation_phrase",
                           first_firing_ms=1200)
    db.log_validation_event(attempt_id="s:1", question_key="Why this role? *",
                            page_index=0, message_present=True)
    rows = _all_rows(db)
    assert len(rows) == 3
    flat = repr(rows)
    assert "Why this role" not in flat, "question keys hold label text: stored hashed"
    assert SECRET not in flat
    with db.get_connection() as conn:
        version = conn.execute("SELECT schema_version FROM field_review_log").fetchone()[0]
    assert version == 1


def test_the_schema_opens_twice(db, tmp_path, monkeypatch) -> None:
    import auto_apply.adapters.secondary.persistence.database as db_module

    db_module.DatabaseManager._instance = None
    again = db_module.DatabaseManager()
    again.log_outcome_channel(attempt_id="a", channel="url_change", first_firing_ms=5)


def test_a_validation_flag_is_reported_without_the_message() -> None:
    from auto_apply.application.services.form_engine import FormStepEngine

    flags: list[ValidationEvent] = []
    form = Form()
    _open_page(form)
    engine = _engine(form)
    ctx = _ctx()
    ctx.on_validation = flags.append
    step = engine._read()
    assert step is not None
    q = step.questions[0]
    live = form.state(q.primary)
    live.invalid, live.message = True, "Enter your real name, Ada"
    FormStepEngine._errors(engine, step, ctx=ctx, index=2)
    assert flags and flags[0].step_index == 2 and flags[0].message_present is True
    assert "Ada" not in repr(flags)


def test_a_private_question_keeps_its_values_out_of_the_log_and_the_feed(caplog) -> None:
    from tests.application.test_ui_port_conformance import _controller

    controller = _controller()
    caplog.set_level(logging.INFO)
    question = "AA would write 1 answer:\n  - Why this role?: " + SECRET
    controller.request_approval(question, ["approve", "skip"], checkpoint="ANSWER_REVIEW",
                                timeout=0.05, private=True)
    assert SECRET not in caplog.text
    feed = " ".join(str(getattr(r, "text", r)) for r in controller._recent_events)
    assert SECRET not in feed and "AA would write 1 answer" in feed

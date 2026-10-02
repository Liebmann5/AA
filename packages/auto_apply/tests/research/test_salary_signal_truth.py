"""Pins for the salary-extraction / ST-01 truth change.

Each pin names what it proves and what it fails against on the pre-change
tree:

* TEETH vs P1 — a posting that SHOWS its pay range in a covered state
  produces no ST-01, through the real observation builder (the vetting
  path) AND through replay. Before: posting_observation hard-coded the
  salary fields to None, so ST-01 fired on every posting.
* TEETH for wording, GUARD for firing — a no-pay posting in a covered
  state still produces ST-01, but severity-graded and worded by what AA
  can actually know. Before: severity was always "violation" with
  "requires disclosure since" wording.
* TEETH vs P3 — a posting captured before its law's effective date
  produces nothing. Before: no date was read.
* TEETH vs P2 — ST-02 fires on a disclosed range wider than its
  threshold (before: it returned early on the always-None fields), and
  the aggregator records a salary observation when pay is present
  (before: the corpus branch never ran).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from auto_apply.adapters.secondary.research.warc_page_store import WarcPageStore
from auto_apply.adapters.secondary.research.warc_replay_corpus import WarcReplayCorpus
from auto_apply.application.services.page_copier import PageCopier
from auto_apply.domain.constants import (
    SEVERITY_CONCERN,
    SEVERITY_FLAG,
    SEVERITY_VIOLATION,
)
from auto_apply.domain.models.page_copy import PostingFacts, derive_nonce
from auto_apply.domain.services.posting_context import (
    posting_detection_context,
    posting_observation,
)
from auto_apply.domain.services.replay import replay_corpus
from auto_apply.domain.services.signal_detectors import (
    run_all_detectors,
    salary_detectors,
)
from auto_apply.domain.services.signal_detectors.base import DetectionContext
from auto_apply.domain.services.signal_detectors.salary_detectors import (
    SalaryTransparencyLegalViolationDetector,
)

#: Public on purpose: test copies prove nothing about any contributor.
_FIXTURE_KEY = b"aa-salary-truth-fixture-key (public, not a research key)"

_PAY_PAGE = (
    "<!DOCTYPE html><html><head><title>Software Engineer</title></head><body>"
    "<main><h1>Software Engineer</h1>"
    "<p>Pay range: $90,000 - $110,000 per year.</p>"
    "<ul><li>3+ years of Python</li></ul></main></body></html>"
)
_NO_PAY_PAGE = (
    "<!DOCTYPE html><html><head><title>Data Analyst</title></head><body>"
    "<main><h1>Data Analyst</h1>"
    "<p>Competitive salary, commensurate with experience.</p>"
    "</main></body></html>"
)


def _observation(description: str, location: str = "Denver, CO"):
    """The real builder vetting uses — the live path's observation."""
    return posting_observation(
        job_title="Software Engineer",
        job_description=description,
        # No company: it only feeds the anonymous company code, which needs
        # the research key — absent in a plain test run — and has no bearing
        # on salary.
        company_name=None,
        location=location,
        platform="greenhouse",
        url="https://example.test/jobs/1",
        seen_on=date(2026, 9, 10),
    )


# ── (i) a pay range in a covered state produces no ST-01 ─────────────────


def test_disclosed_range_means_no_st01_through_the_real_builder() -> None:
    """TEETH vs P1 (live path). Fails before: ST-01 fired on every posting."""
    ctx = posting_detection_context(
        _observation("Pay range: $90,000 - $110,000 per year."),
        current_date=date(2026, 9, 10),
    )
    assert SalaryTransparencyLegalViolationDetector().detect(ctx) == []
    assert not any(s.signal_type == "ST-01" for s in run_all_detectors(ctx).signals)


def test_replay_of_a_pay_showing_page_has_no_st01(tmp_path: Path) -> None:
    """TEETH vs P1 (replay path): two kept pages, one showing pay, one not;
    replayed, only the no-pay page carries ST-01, at the new severity."""
    store = WarcPageStore(tmp_path)
    for url, captured_at, html, title in (
        ("https://example.test/jobs/pay", "2026-09-10T09:00:00Z", _PAY_PAGE, "Software Engineer"),
        ("https://example.test/jobs/nopay", "2026-09-11T09:00:00Z", _NO_PAY_PAGE, "Data Analyst"),
    ):
        copier = PageCopier(
            store,
            clock=lambda captured_at=captured_at: captured_at,
            nonce=lambda content: derive_nonce(_FIXTURE_KEY, content),
        )
        copy_id = copier.copy(
            "job_posting",
            url,
            lambda html=html: html,
            PostingFacts(job_title=title, location="Sacramento, CA", platform="greenhouse"),
        )
        assert copy_id is not None, url

    out = replay_corpus(WarcReplayCorpus(tmp_path).read(), aa_version="0.0.0-test")
    records = [json.loads(line) for line in out.records.splitlines()]
    by_title = {r["observation"]["job_title"]: r for r in records}

    pay_signals = by_title["Software Engineer"]["signals"]
    assert all(s["signal_type"] != "ST-01" for s in pay_signals)

    st01 = [s for s in by_title["Data Analyst"]["signals"] if s["signal_type"] == "ST-01"]
    assert len(st01) == 1
    assert st01[0]["severity"] == "concern"  # CA's threshold is 15
    assert "cannot know employer size" in st01[0]["evidence_text"]


# ── (ii) no pay in a covered state: honest severity and wording ──────────


def test_no_pay_in_california_is_a_concern_with_honest_wording() -> None:
    """TEETH for wording: before, this was severity 'violation' claiming
    'requires disclosure since…'."""
    ctx = DetectionContext(
        job_title="Engineer",
        job_description="Great role on a great team.",
        jurisdiction="CA",
        current_date=date(2026, 1, 15),
    )
    signals = SalaryTransparencyLegalViolationDetector().detect(ctx)
    assert len(signals) == 1
    assert signals[0].severity == SEVERITY_CONCERN
    assert "cannot know employer size" in signals[0].evidence_text
    assert "not a legal finding" in signals[0].evidence_text


def test_no_pay_in_colorado_is_a_violation_law_covers_every_employer() -> None:
    """GUARD: where the threshold is 1, employer size is not in question,
    so the violation claim survives — with its caveats in the text."""
    ctx = DetectionContext(
        job_title="Engineer",
        job_description="Great role on a great team.",
        jurisdiction="CO",
        current_date=date(2026, 1, 15),
    )
    signals = SalaryTransparencyLegalViolationDetector().detect(ctx)
    assert len(signals) == 1
    assert signals[0].severity == SEVERITY_VIOLATION
    assert "every employer" in signals[0].evidence_text
    assert "image-only" in signals[0].evidence_text


# ── (iii) the effective date is honoured ──────────────────────────────────


def test_posting_captured_before_the_law_took_effect_produces_nothing() -> None:
    """TEETH vs P3: CO's law took effect 2021-01-01; a posting captured in
    2020 is not a finding. Fails before: no date was read."""
    ctx = DetectionContext(
        job_title="Engineer",
        job_description="Great role.",
        jurisdiction="CO",
        current_date=date(2020, 6, 1),
    )
    assert SalaryTransparencyLegalViolationDetector().detect(ctx) == []


def test_ri_never_fires_disclosure_only_on_request() -> None:
    """TEETH: RI's law requires a range only on request, so non-disclosure
    is not a finding. Fails before: requires_range was never read."""
    ctx = DetectionContext(
        job_title="Engineer",
        job_description="Great role.",
        jurisdiction="RI",
        current_date=date(2026, 1, 15),
    )
    assert SalaryTransparencyLegalViolationDetector().detect(ctx) == []


def test_posting_captured_on_the_effective_day_is_covered() -> None:
    """GUARD on the boundary: a law is in effect ON its effective date
    (CO: 2021-01-01), not only after it."""
    ctx = DetectionContext(
        job_title="Engineer",
        job_description="Great role.",
        jurisdiction="CO",
        current_date=date(2021, 1, 1),
    )
    assert len(SalaryTransparencyLegalViolationDetector().detect(ctx)) == 1


def test_unreadable_effective_date_suppresses_the_finding(monkeypatch) -> None:
    """GUARD: law data that cannot be parsed must not fabricate a finding."""
    monkeypatch.setattr(salary_detectors, "_PAY_TRANSPARENCY_LAWS", {
        "CO": salary_detectors.PayTransparencyLaw(
            "CO", "Colorado", "not-a-date", 1, True, 500
        ),
    })
    ctx = DetectionContext(
        job_title="Engineer",
        job_description="Great role.",
        jurisdiction="CO",
        current_date=date(2026, 1, 15),
    )
    assert SalaryTransparencyLegalViolationDetector().detect(ctx) == []


# ── requires_range: a single figure is a separate, weaker finding ─────────


def test_single_disclosed_figure_where_a_range_is_required_is_a_flag() -> None:
    """TEETH: one figure where the law says RANGE — recorded, but as a
    flag that refuses to adjudicate."""
    ctx = posting_detection_context(
        _observation("starting at $90,000"),
        current_date=date(2026, 9, 10),
    )
    signals = SalaryTransparencyLegalViolationDetector().detect(ctx)
    assert len(signals) == 1
    assert signals[0].severity == SEVERITY_FLAG
    assert "RANGE" in signals[0].evidence_text
    assert "does not decide" in signals[0].evidence_text


def test_equal_min_and_max_is_one_figure_not_a_range() -> None:
    """GUARD: "$90,000 - $90,000" names one figure; it is flagged like one."""
    ctx = DetectionContext(
        job_title="Engineer",
        job_description="Great role.",
        jurisdiction="CO",
        salary_min=90000,
        salary_max=90000,
        current_date=date(2026, 1, 15),
    )
    signals = SalaryTransparencyLegalViolationDetector().detect(ctx)
    assert [s.severity for s in signals] == [SEVERITY_FLAG]


def test_disclosed_range_where_required_produces_nothing() -> None:
    """GUARD: a real range in a covered state is compliance-shaped — no row."""
    ctx = DetectionContext(
        job_title="Engineer",
        job_description="Great role.",
        jurisdiction="CO",
        salary_min=90000,
        salary_max=110000,
        current_date=date(2026, 1, 15),
    )
    assert SalaryTransparencyLegalViolationDetector().detect(ctx) == []


# ── (iv) ST-02 can fire now ───────────────────────────────────────────────


def test_st02_fires_on_a_wide_disclosed_range_through_the_real_builder() -> None:
    """TEETH vs P2: $90,000–$250,000 is a 2.8x spread — over the concern
    threshold. Fails before: the salary fields were always None."""
    ctx = posting_detection_context(
        _observation("Salary range: $90,000 – $250,000 per year.", location="New York, NY"),
        current_date=date(2026, 9, 10),
    )
    signals = run_all_detectors(ctx).signals
    st02 = [s for s in signals if s.signal_type == "ST-02"]
    assert len(st02) == 1
    assert st02[0].severity == SEVERITY_CONCERN
    assert not any(s.signal_type == "ST-01" for s in signals)


# ── (v) the salary corpus starts filling ──────────────────────────────────


def test_aggregator_records_a_salary_observation_for_a_posting_with_pay(aggregator) -> None:
    """TEETH vs P2: a posting with pay lands in salary_observations with
    its as-stated span. Fails before: the corpus branch never ran."""
    aggregator.observe_job_posting(
        _observation("Pay range: $90,000 - $110,000 per year.", location="Sacramento, CA")
    )
    conn = sqlite3.connect(str(aggregator._db_path))
    try:
        rows = conn.execute(
            "SELECT salary_min, salary_max, source_text FROM salary_observations"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0][0] == 90000
    assert rows[0][1] == 110000
    assert rows[0][2] and "$90,000" in rows[0][2]

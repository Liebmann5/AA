"""Persistence-path tests for detector outcome accounting (item 5).

Covers what test_signal_detectors.py cannot: that the accounting produced by
run_all_detectors survives the adapter — one detector_examinations row per
detection pass, detector_outcomes rows for non-clean outcomes only, the
denominator readable back from a fresh connection (M6), C2's no-exception-text
rule at the database layer, and both tables' inclusion in the export bundle.

The registry is patched to three synthetic detectors (fires / cleans / bombs)
so these tests pin the ACCOUNTING, not the behaviour of any real detector.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from auto_apply.adapters.secondary.research.research_exporter import ResearchExporter
from auto_apply.adapters.secondary.research.signal_aggregator import (
    ResearchSignalAggregator,
)
from auto_apply.domain.services import signal_detectors as sd
from auto_apply.domain.services.signal_detectors.base import (
    DetectionContext,
    ResearchSignal,
)

SENTINEL = "SENTINEL_COMPANY_ACME_SECRET"


class _Fires:
    signal_type = "TEST-FIRE"

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        return [
            ResearchSignal.create(
                signal_type="TEST-FIRE",
                severity="flag",
                confidence=0.5,
                evidence_text="synthetic",
            )
        ]


class _Cleans:
    signal_type = "TEST-CLEAN"

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        return []


class _Bombs:
    signal_type = "TEST-BOMB"

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        raise RuntimeError(SENTINEL)


@pytest.fixture
def accounting_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[ResearchSignalAggregator, Path]]:
    """An enabled aggregator against the patched registry, on a tmp database."""
    monkeypatch.setenv("AA_RESEARCH_SALT", "item5-test-salt")
    monkeypatch.setattr(sd, "ALL_DETECTORS", [_Fires(), _Cleans(), _Bombs()])
    db_path = tmp_path / "research.db"
    aggregator = ResearchSignalAggregator(
        db_path=db_path,
        consent_version="item5-test",
        flush_interval_seconds=0.05,
        # The signer writes a real private key on the first flushed batch;
        # inject its path so the test never touches the real data directory.
        provenance_key_path=tmp_path / "provenance_key.pem",
    )
    yield aggregator, db_path
    aggregator.stop()


def _read(db_path: Path, sql: str, args: tuple[object, ...] = ()) -> list[sqlite3.Row]:
    """Read through a FRESH connection — the M6 check is that the record
    survives the process that wrote it, not just the writer's own handle."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _submit_one(aggregator: ResearchSignalAggregator, posting_hash: str) -> None:
    """Submit one context and flush deterministically: stop()'s sentinel
    plus the daemon's final drain writes everything still queued."""
    aggregator.start()
    aggregator.submit_context(
        DetectionContext(
            job_title="Engineer",
            job_description="A role.",
            posting_hash=posting_hash,
        )
    )
    aggregator.stop()


def test_examination_and_outcomes_persisted(accounting_db) -> None:
    aggregator, db_path = accounting_db
    _submit_one(aggregator, "ph-1")

    exams = _read(db_path, "SELECT * FROM detector_examinations")
    assert len(exams) == 1
    exam = exams[0]
    assert exam["detectors_run"] == 3
    assert json.loads(exam["detectors_roster"]) == [
        "TEST-FIRE", "TEST-CLEAN", "TEST-BOMB",
    ]
    assert exam["detectors_fired"] == 1
    assert exam["detectors_raised"] == 1
    assert exam["signals_fired"] == 1
    assert exam["posting_hash"] == "ph-1"

    outcomes = _read(
        db_path,
        "SELECT * FROM detector_outcomes WHERE examination_id = ?"
        " ORDER BY signal_type",
        (exam["examination_id"],),
    )
    # Non-clean only: fired and raised are rows; clean is derivable.
    assert [(o["signal_type"], o["outcome"]) for o in outcomes] == [
        ("TEST-BOMB", "raised"),
        ("TEST-FIRE", "fired"),
    ]
    raised = next(o for o in outcomes if o["outcome"] == "raised")
    assert raised["error_class"] == "RuntimeError"
    assert raised["signals_count"] == 0
    # The derivation the design stands on: roster minus recorded == clean.
    recorded = {o["signal_type"] for o in outcomes}
    roster = set(json.loads(exam["detectors_roster"]))
    assert roster - recorded == {"TEST-CLEAN"}


def test_exception_text_never_reaches_the_database(accounting_db) -> None:
    """C2 at the persistence layer: the sentinel appears in no column of
    any table the examination path writes."""
    aggregator, db_path = accounting_db
    aggregator.start()
    aggregator.submit_context(
        DetectionContext(
            job_title="x",
            job_description=SENTINEL,
            posting_hash="ph-2",
        )
    )
    aggregator.stop()

    # Table names here are literals in this test file, not user input.
    for table in ("detector_examinations", "detector_outcomes", "research_signals"):
        for row in _read(db_path, f"SELECT * FROM {table}"):
            assert SENTINEL not in str(tuple(row))


def test_signals_still_written_alongside_accounting(accounting_db) -> None:
    """The accounting is additive: the signal path is unchanged."""
    aggregator, db_path = accounting_db
    _submit_one(aggregator, "ph-3")
    rows = _read(db_path, "SELECT signal_type FROM research_signals")
    assert [r["signal_type"] for r in rows] == ["TEST-FIRE"]


def test_statistics_summary_exposes_denominator_and_failures(accounting_db) -> None:
    aggregator, db_path = accounting_db
    _submit_one(aggregator, "ph-4")
    summary = aggregator.get_statistics_summary()
    assert summary["examinations"] == 1
    assert summary["detectors_fired"] == 1
    assert summary["detectors_raised"] == 1
    assert summary["accounting_failures"] == {}


def test_export_bundle_includes_accounting_tables(
    accounting_db, tmp_path: Path
) -> None:
    aggregator, db_path = accounting_db
    _submit_one(aggregator, "ph-5")

    result = ResearchExporter(
        db_path=db_path, export_root=tmp_path / "exports"
    ).export(fmt="csv")

    files = {p.name for p in result.directory.iterdir()}
    assert "detector_examinations.csv" in files
    assert "detector_outcomes.csv" in files

    index = json.loads((result.directory / "index.json").read_text(encoding="utf-8"))
    tables = {t["table"]: t for t in index["tables"]}
    assert tables["detector_examinations"]["rows"] == 1
    assert tables["detector_outcomes"]["rows"] == 2

    exam_csv = (
        (result.directory / "detector_examinations.csv")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(exam_csv) == 2  # header + one examination row

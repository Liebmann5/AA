"""Pins for the consent-gated sampling frame (research schema v5).

Teeth against the pre-change tree (no table, no observation type, no write
path). Mutations caught: query text reaching the frame; the frame written
without consent; the table missing from exports.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from pathlib import Path

import pytest

from auto_apply.adapters.secondary.research import signal_aggregator
from auto_apply.adapters.secondary.research.research_exporter import ResearchExporter
from auto_apply.adapters.secondary.research.signal_aggregator import (
    ResearchSignalAggregator,
)
from auto_apply.domain.constants import CURRENT_CONSENT_VERSION, RESEARCH_SCHEMA_VERSION
from auto_apply.domain.ports.research_port import SearchPlanObservation


def _frame() -> SearchPlanObservation:
    return SearchPlanObservation(
        engines=("bing", "google"),
        platforms=("jobvite",),
        queries_planned=2,
        per_engine=(("bing", 1), ("google", 1)),
        per_platform=(("jobvite", 2),),
        dropped_count=1,
        notes_info=1,
        notes_warning=0,
        budget_before=5,
        budget_after=3,
    )


def _aggregator(db_path: Path, monkeypatch: pytest.MonkeyPatch, consent: bool):
    monkeypatch.setattr(
        signal_aggregator, "resolve_research_salt", lambda: "test-salt"
    )
    agg = ResearchSignalAggregator(
        db_path=db_path,
        consent_version=CURRENT_CONSENT_VERSION if consent else None,
        flush_interval_seconds=0.05,
        macro_signal_interval_seconds=3600.0,
        provenance_key_path=db_path.parent / "provenance_key.pem",
    )
    agg.start()
    return agg


def test_the_frame_persists_names_and_counts(tmp_path, monkeypatch):
    db = tmp_path / "research" / "r.db"
    agg = _aggregator(db, monkeypatch, consent=True)
    agg.observe_search_plan(_frame())
    agg.stop()
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute("SELECT * FROM search_plan_frames").fetchall()
        assert len(rows) == 1
        cols = [d[1] for d in conn.execute("PRAGMA table_info(search_plan_frames)")]
        row = dict(zip(cols, rows[0], strict=True))
        assert json.loads(row["engines"]) == ["bing", "google"]
        assert json.loads(row["per_platform"]) == {"jobvite": 2}
        assert row["queries_planned"] == 2
        assert row["budget_before"] == 5
        assert row["budget_after"] == 3
        assert row["dropped_count"] == 1
        assert row["schema_version"] == RESEARCH_SCHEMA_VERSION
    finally:
        conn.close()


def test_the_frame_has_no_field_that_could_carry_query_text():
    """Structural: the observation cannot hold a query, title or location."""
    names = {f.name for f in dataclasses.fields(SearchPlanObservation)}
    for forbidden in (
        "query", "raw_query_string", "title", "location", "search_query",
    ):
        assert forbidden not in names


def test_no_frame_is_written_without_consent(tmp_path, monkeypatch):
    db = tmp_path / "research" / "r.db"
    agg = _aggregator(db, monkeypatch, consent=False)
    agg.observe_search_plan(_frame())
    agg.stop()
    assert not db.exists()


def test_the_frame_reaches_the_export_bundle(tmp_path, monkeypatch):
    db = tmp_path / "research" / "r.db"
    agg = _aggregator(db, monkeypatch, consent=True)
    agg.observe_search_plan(_frame())
    agg.stop()
    result = ResearchExporter(
        db_path=db,
        export_root=tmp_path / "exports",
        provenance_key_path=tmp_path / "research" / "provenance_key.pem",
    ).export("csv")
    index = json.loads((result.directory / "index.json").read_text(encoding="utf-8"))
    by_table = {entry["table"]: entry for entry in index["tables"]}
    assert by_table["search_plan_frames"]["rows"] == 1
    assert (result.directory / by_table["search_plan_frames"]["file"]).exists()


def test_schema_version_is_at_least_five():
    """The frame table's introduction bumped the schema to 5."""
    assert RESEARCH_SCHEMA_VERSION >= 5

"""Pagination evidence: the new discovery_pages columns, and old databases.

The four pagination columns are added to the CREATE TABLE for new databases
and through _ADDED_COLUMNS ALTERs for old ones. A database written before
this change must keep loading, keep its rows, and accept new paginated
writes — that is the release criterion for research data.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from auto_apply.adapters.secondary.research import signal_aggregator
from auto_apply.adapters.secondary.research.signal_aggregator import (
    ResearchSignalAggregator,
)
from auto_apply.domain.constants import RESEARCH_SCHEMA_VERSION
from auto_apply.domain.ports.research_port import DiscoveryObservation

_OLD_PAGES_DDL = """
CREATE TABLE discovery_pages (
    page_id              TEXT PRIMARY KEY,
    provider             TEXT,
    page_host            TEXT,
    page_state           TEXT,
    blocked              INTEGER DEFAULT 0,
    architecture         TEXT,
    card_count           INTEGER,
    resolved_count       INTEGER,
    multi_route_count    INTEGER,
    deferred_count       INTEGER,
    no_destination_count INTEGER,
    sponsored_card_count INTEGER,
    activation_attempts  INTEGER,
    activation_resolved  INTEGER,
    learned_identity     TEXT,
    observed_date        TEXT NOT NULL,
    schema_version       INTEGER DEFAULT 2
);
"""


@pytest.fixture(autouse=True)
def _bypass_research_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same narrow stand-in as test_discovery_observation_persistence.py."""
    monkeypatch.setattr(signal_aggregator, "resolve_research_salt", lambda: "test-salt")


def _observation() -> DiscoveryObservation:
    return DiscoveryObservation(
        provider="TestProvider",
        page_host="serp.example.com",
        card_count=7,
        page_index=-1,
        advance_method="numbered",
        stop_reason="no-next-control",
        page_count=2,
    )


def _write(db_path: Path, observation: DiscoveryObservation) -> None:
    aggregator = ResearchSignalAggregator(
        db_path=db_path,
        consent_version="v1.0",
        flush_interval_seconds=0.05,
        macro_signal_interval_seconds=3600.0,
    )
    aggregator.start()
    try:
        aggregator.observe_discovery(observation)
    finally:
        aggregator.stop()


def test_pagination_fields_are_persisted(tmp_path: Path) -> None:
    db = tmp_path / "r.db"
    _write(db, _observation())
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM discovery_pages").fetchone()
        assert row is not None
        assert row["page_index"] == -1
        assert row["advance_method"] == "numbered"
        assert row["stop_reason"] == "no-next-control"
        assert row["page_count"] == 2
    finally:
        conn.close()


def test_a_database_from_before_the_columns_keeps_loading(tmp_path: Path) -> None:
    """TEETH: without the _ADDED_COLUMNS entries the ALTER never runs and the
    first paginated write fails on the old schema."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.execute(_OLD_PAGES_DDL)
    conn.execute(
        "INSERT INTO discovery_pages (page_id, provider, observed_date) "
        "VALUES ('p0', 'OldProvider', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    _write(db, _observation())

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(discovery_pages)")}
        assert {"page_index", "advance_method", "stop_reason", "page_count"} <= columns
        rows = conn.execute(
            "SELECT provider, page_count FROM discovery_pages ORDER BY rowid"
        ).fetchall()
        # The old row survives; columns it predates read NULL ("not recorded",
        # which is true of it). The new row carries its evidence.
        assert [(r["provider"], r["page_count"]) for r in rows] == [
            ("OldProvider", None),
            ("TestProvider", 2),
        ]
    finally:
        conn.close()


def test_new_rows_carry_the_current_schema_version(tmp_path: Path) -> None:
    db = tmp_path / "r.db"
    _write(db, _observation())
    conn = sqlite3.connect(str(db))
    try:
        version = conn.execute(
            "SELECT schema_version FROM discovery_pages"
        ).fetchone()[0]
        assert version == RESEARCH_SCHEMA_VERSION
    finally:
        conn.close()


def test_research_schema_version_counts_the_pagination_columns() -> None:
    """Guard: adding the four pagination columns bumped the research schema
    to 4; older rows (2 and 3) stay valid through the column migration."""
    assert RESEARCH_SCHEMA_VERSION >= 4

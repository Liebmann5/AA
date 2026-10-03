"""Persistence pins for discovery-surface observations (item 4c).

T1  An observation emitted through the real aggregator survives the process:
    enqueued on the discovery thread, written by the flush daemon, readable
    from a fresh connection afterwards. This is the defect; this is the proof.
T2  C4's floor: a sentinel search query and a sentinel full search URL,
    pushed through a real observation, appear in NO persisted column of any
    table and in NO log record.
T3  The new tables reach a recipient through item 4b's bundle exporter.
T4  Card and candidate rows join back to their page row — exercised as a
    join, per the R2/R3 rulings.
T5  Consent off persists nothing.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sqlite3
from pathlib import Path

import pytest

from auto_apply.adapters.secondary.research import signal_aggregator
from auto_apply.adapters.secondary.research.research_exporter import ResearchExporter
from auto_apply.adapters.secondary.research.signal_aggregator import ResearchSignalAggregator
from auto_apply.domain.ports.research_port import (
    DiscoveryCandidateObservation,
    DiscoveryCardObservation,
    DiscoveryObservation,
)

#: Tokens a substring search cannot false-positive on. The destination host
#: deliberately differs from the query token, so persisting a HOST (allowed
#: under R1) cannot mask a query leak (forbidden under C4).
SENTINEL_QUERY = "ZqSentinel9917"
SENTINEL_URL = f"https://zq-sentinel-9917.example.invalid/search?q={SENTINEL_QUERY}&r=zz9"


@pytest.fixture(autouse=True)
def _bypass_research_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep item-4a salt resolution out of these tests (C3).

    The aggregator's __init__ resolves the research salt when consent is
    active. How the wider suite provisions that salt is not verified here;
    patching the aggregator module's imported reference is the narrowest
    stand-in and modifies none of the pinned 4a files.
    """
    monkeypatch.setattr(
        signal_aggregator, "resolve_research_salt", lambda: "test-salt"
    )


def _observation() -> DiscoveryObservation:
    """One normal page with one resolved card and one selected candidate."""
    return DiscoveryObservation(
        provider="TestProvider",
        page_host="serp.example.com",
        page_state="normal",
        blocked=False,
        architecture="anchorful",
        card_count=1,
        resolved_count=1,
        multi_route_count=0,
        deferred_count=0,
        no_destination_count=0,
        sponsored_card_count=0,
        activation_attempts=0,
        activation_resolved=0,
        learned_identity=("data-job-ref",),
        cards=(
            DiscoveryCardObservation(
                card_index=0,
                title="Pipeline Engineer",
                resolution_state="resolved",
                selected_host="boards.example.org",
                candidates=(
                    DiscoveryCandidateObservation(
                        original_url="https://serp.example.com/out?u=zz",
                        resolved_url="https://boards.example.org/jobs/2",
                        resolved_host="boards.example.org",
                        anchor_text="Apply for this role",
                        source="revealed",
                        outcome="selected",
                        rejection_reason="",
                        ad_evidence=(),
                        apply_intent=True,
                        title_overlap=0.0,
                        method="no decodable payload; wrapper kept as navigable",
                    ),
                ),
            ),
        ),
    )


def _sentinel_observation() -> DiscoveryObservation:
    """The same page, with the sentinel query/URL riding the two candidate
    fields R1 forbids persisting."""
    observation = _observation()
    card = observation.cards[0]
    sentinel_candidate = DiscoveryCandidateObservation(
        original_url=SENTINEL_URL,
        resolved_url=SENTINEL_URL,
        resolved_host="zq-sentinel-9917.example.invalid",
        anchor_text="Apply",
        source="static",
        outcome="candidate",
    )
    return dataclasses.replace(
        observation,
        cards=(dataclasses.replace(card, candidates=(sentinel_candidate,)),),
    )


def _run_aggregator(db_path: Path, observation: DiscoveryObservation) -> None:
    """Emit one observation through the real aggregator and shut down.

    stop() joins the daemon only after its final flush, so when this returns
    the write has either happened or failed loudly in the logs.
    """
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


def _all_text_cells(db_path: Path) -> list[str]:
    """Every non-NULL cell of every table, as text — the T2 search space."""
    conn = sqlite3.connect(str(db_path))
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        ]
        cells: list[str] = []
        for table in tables:
            for row in conn.execute(f"SELECT * FROM {table}").fetchall():
                cells.extend(str(value) for value in row if value is not None)
        return cells
    finally:
        conn.close()


def test_discovery_observation_survives_the_process(tmp_path: Path) -> None:
    """T1 — the defect itself: collected every run, destroyed every run."""
    db_path = tmp_path / "research.db"
    _run_aggregator(db_path, _observation())

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        pages = conn.execute("SELECT * FROM discovery_pages").fetchall()
        assert len(pages) == 1
        page = pages[0]
        assert page["provider"] == "TestProvider"
        assert page["page_host"] == "serp.example.com"
        assert page["architecture"] == "anchorful"
        assert page["card_count"] == 1
        assert json.loads(page["learned_identity"]) == ["data-job-ref"]

        cards = conn.execute("SELECT * FROM discovery_cards").fetchall()
        assert len(cards) == 1
        assert cards[0]["title"] == "Pipeline Engineer"
        assert cards[0]["resolution_state"] == "resolved"

        candidates = conn.execute("SELECT * FROM discovery_candidates").fetchall()
        assert len(candidates) == 1
        assert candidates[0]["resolved_host"] == "boards.example.org"
        assert candidates[0]["anchor_text"] == "Apply for this role"
        assert candidates[0]["apply_intent"] == 1
    finally:
        conn.close()


def test_no_search_url_or_query_is_persisted_or_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """T2 — C4's floor, with sentinels a substring search cannot invent."""
    db_path = tmp_path / "research.db"
    with caplog.at_level(logging.DEBUG):
        _run_aggregator(db_path, _sentinel_observation())

    cells = _all_text_cells(db_path)
    assert cells, "nothing persisted — this test would prove nothing"
    for cell in cells:
        assert SENTINEL_QUERY not in cell
        assert SENTINEL_URL not in cell
    assert SENTINEL_QUERY not in caplog.text
    assert SENTINEL_URL not in caplog.text


def test_discovery_tables_reach_the_export_bundle(tmp_path: Path) -> None:
    """T3 — a recipient sees the new tables, populated, via item 4b."""
    db_path = tmp_path / "research.db"
    _run_aggregator(db_path, _observation())

    result = ResearchExporter(
        db_path=db_path, export_root=tmp_path / "exports"
    ).export("csv")
    index = json.loads(
        (result.directory / "index.json").read_text(encoding="utf-8")
    )
    by_table = {entry["table"]: entry for entry in index["tables"]}
    for name in ("discovery_pages", "discovery_cards", "discovery_candidates"):
        assert name in by_table, f"{name} missing from index.json"
        assert by_table[name]["rows"] == 1
        assert (result.directory / by_table[name]["file"]).exists()

    pages_csv = (
        result.directory / by_table["discovery_pages"]["file"]
    ).read_text(encoding="utf-8")
    assert "TestProvider" in pages_csv
    candidates_csv = (
        result.directory / by_table["discovery_candidates"]["file"]
    ).read_text(encoding="utf-8")
    assert "boards.example.org" in candidates_csv


def test_child_rows_join_back_to_their_page(tmp_path: Path) -> None:
    """T4 — the R2/R3 join, exercised as an actual join."""
    db_path = tmp_path / "research.db"
    _run_aggregator(db_path, _observation())

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            """SELECT p.provider, p.page_host, c.title, c.resolution_state,
                      cand.resolved_host, cand.outcome
               FROM discovery_candidates AS cand
               JOIN discovery_cards AS c ON c.card_id = cand.card_id
               JOIN discovery_pages AS p ON p.page_id = c.page_id"""
        ).fetchall()
        assert rows == [
            (
                "TestProvider",
                "serp.example.com",
                "Pipeline Engineer",
                "resolved",
                "boards.example.org",
                "selected",
            )
        ]
    finally:
        conn.close()


def test_consent_off_persists_nothing(tmp_path: Path) -> None:
    """T5 — no consent: no rows, and the database is never even created."""
    db_path = tmp_path / "research.db"
    aggregator = ResearchSignalAggregator(
        db_path=db_path,
        consent_version=None,
        flush_interval_seconds=0.05,
    )
    aggregator.start()
    try:
        aggregator.observe_discovery(_observation())
    finally:
        aggregator.stop()
    assert not db_path.exists()

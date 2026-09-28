"""Teeth for research_identity and the aggregator's handling of the salt.

T1: one construction, identical across both call paths, pinned against a
    hand-computed HMAC (and against the retired concatenating form).
T2: an unset salt is fatal at aggregator construction — observable, named.
T3: blank salts are unset; the literal "default_dev_salt" is a legal salt.
T4: an absent company needs no salt at all.
T5: legacy company_id values are nulled exactly once; empty/absent databases
    migrate cleanly.
"""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from auto_apply.adapters.secondary.research.signal_aggregator import (
    _SCHEMA_SQL,
    ResearchSignalAggregator,
)
from auto_apply.domain.services.research_identity import (
    ResearchSaltError,
    compute_company_id,
    resolve_research_salt,
)
from auto_apply.domain.services.signal_detectors.base import ResearchSignal

SALT = "unit-test-salt"


# ── T1: one construction, both paths, pinned against a hand-computed HMAC ────


def test_company_id_is_identical_across_call_paths(monkeypatch) -> None:
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)

    expected = hmac.new(SALT.encode(), b"acme corp", hashlib.sha256).hexdigest()[:16]
    direct = compute_company_id("Acme Corp")
    assert direct == expected, (
        "the construction drifted — company_id must remain "
        "HMAC-SHA256(key=salt, msg=name.lower())[:16]"
    )

    signal = ResearchSignal.create(
        signal_type="GJ-01",
        severity="flag",
        confidence=0.5,
        evidence_text="evidence",
        company_name="Acme Corp",
    )
    assert signal.company_id == direct, (
        "the detector path and the direct path disagree — the fork item 4a "
        "closed has reopened"
    )


def test_company_id_never_matches_the_retired_concat_scheme(monkeypatch) -> None:
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)
    retired = hashlib.sha256(b"acme corp" + SALT.encode()).hexdigest()[:16]
    assert compute_company_id("Acme Corp") != retired


# ── T2: an unset salt is fatal at construction, observably ───────────────────


def test_unset_salt_is_fatal_at_aggregator_construction(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("AA_RESEARCH_SALT", raising=False)
    with pytest.raises(ResearchSaltError, match="AA_RESEARCH_SALT"):
        ResearchSignalAggregator(db_path=tmp_path / "research.db", consent_version="2.1")


def test_disabled_research_needs_no_salt(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("AA_RESEARCH_SALT", raising=False)
    agg = ResearchSignalAggregator(db_path=tmp_path / "research.db", consent_version=None)
    assert not agg.is_enabled


# ── T3: blank is unset; the published literal is not magic ───────────────────


@pytest.mark.parametrize("blank", ["", "   ", "\t \n"])
def test_blank_salt_is_treated_as_unset(monkeypatch, blank: str) -> None:
    monkeypatch.setenv("AA_RESEARCH_SALT", blank)
    with pytest.raises(ResearchSaltError):
        resolve_research_salt()


def test_default_dev_salt_literal_is_not_special_cased(monkeypatch) -> None:
    monkeypatch.setenv("AA_RESEARCH_SALT", "default_dev_salt")
    assert resolve_research_salt() == "default_dev_salt"


# ── T4: absence of a company is not a company named "" ───────────────────────


def test_absent_company_returns_none_without_a_salt(monkeypatch) -> None:
    monkeypatch.delenv("AA_RESEARCH_SALT", raising=False)
    assert compute_company_id(None) is None
    assert compute_company_id("") is None


# ── T5: the one-time migration ────────────────────────────────────────────────


def _seed_legacy_rows(db_path: Path) -> None:
    """Build a pre-item-4a database: schema present, migration not yet run."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.execute(
            "INSERT INTO research_signals "
            "(signal_id, signal_type, severity, confidence, detected_date, company_id) "
            "VALUES (?,?,?,?,?,?)",
            ("sig-1", "GJ-01", "flag", 0.9, date.today().isoformat(), "legacyhmac1234567"),
        )
        conn.execute(
            "INSERT INTO application_outcomes "
            "(outcome_id, platform, submitted_date, company_id) VALUES (?,?,?,?)",
            ("out-1", "linkedin", date.today().isoformat(), "legacyconcat4567"),
        )
        conn.commit()
    finally:
        conn.close()


def test_legacy_company_ids_are_nulled_and_new_rows_survive(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)
    db = tmp_path / "research.db"
    _seed_legacy_rows(db)

    ResearchSignalAggregator(db_path=db, consent_version="2.1")
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute(
            "SELECT company_id FROM research_signals WHERE signal_id='sig-1'"
        ).fetchone()[0] is None
        assert conn.execute(
            "SELECT company_id FROM application_outcomes WHERE outcome_id='out-1'"
        ).fetchone()[0] is None
        # Only the dishonest field was made absent; the row itself survives.
        assert conn.execute(
            "SELECT signal_type FROM research_signals WHERE signal_id='sig-1'"
        ).fetchone()[0] == "GJ-01"
        # A post-migration row must survive a second construction untouched.
        conn.execute(
            "INSERT INTO research_signals "
            "(signal_id, signal_type, severity, confidence, detected_date, company_id) "
            "VALUES (?,?,?,?,?,?)",
            ("sig-2", "ST-01", "concern", 0.8, date.today().isoformat(), "newschemeid12345"),
        )
        conn.commit()
    finally:
        conn.close()

    ResearchSignalAggregator(db_path=db, consent_version="2.1")
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute(
            "SELECT company_id FROM research_signals WHERE signal_id='sig-2'"
        ).fetchone()[0] == "newschemeid12345"
    finally:
        conn.close()


def test_migration_is_a_noop_on_an_absent_database(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)
    db = tmp_path / "fresh.db"
    ResearchSignalAggregator(db_path=db, consent_version="2.1")
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        conn.close()

"""Pins for the single research data home (M1–M6, 2026-10-01).

The defects these pins hold against:

M1  the collector wrote USER_DATA_DIR/research_signals.db while the exporter
    read RESEARCH_DIR/research_signals.db — two files, so --export-research
    could never export anything the collector wrote.
M4  the consent purge hard-coded 5 of the schema's 11 tables.
M5  purged bytes could outlive the purge in the WAL.
M3/M6  the private signing key sat where a "share your research data"
    instruction could ship it, survived every purge, and a live aggregator
    never re-stored the public key once _public_key_stored latched.

Every test here is RED against the tree that had those defects; each
docstring says how. No production path is touched: every database, key and
consent file lives under tmp_path.
"""
from __future__ import annotations

import ast
import inspect
import sqlite3
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

import auto_apply.domain.config as domain_config
from auto_apply.adapters.secondary.research.signal_aggregator import (
    ResearchSignalAggregator,
)
from auto_apply.adapters.secondary.research.sqlite_consent_repository import (
    SqliteConsentRepository,
)
from auto_apply.domain.constants import RESEARCH_SCHEMA_VERSION
from auto_apply.domain.services.signal_detectors import ResearchSignal

SALT = "data-home-test-salt"


@pytest.fixture
def home(tmp_path, monkeypatch) -> SimpleNamespace:
    """A hermetic research home mirroring domain.config's layout."""
    monkeypatch.setenv("AA_RESEARCH_SALT", SALT)
    return SimpleNamespace(
        db=tmp_path / "research" / "research_signals.db",
        key=tmp_path / "provenance_key.pem",
        consent=tmp_path / "research_consent.db",
        root=tmp_path,
    )


def _tables(db: Path) -> list[str]:
    conn = sqlite3.connect(str(db))
    try:
        return [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
    finally:
        conn.close()


def _seed_one_marker_row_per_table(db: Path) -> dict[str, str]:
    """Insert one row into EVERY table the schema has, each with a marker.

    The table list comes from sqlite_master, so a table added to the schema
    later is seeded and checked automatically — the purge cannot outrun the
    schema the way the old five-table literal did (M4).
    """
    conn = sqlite3.connect(str(db))
    markers: dict[str, str] = {}
    try:
        for table in _tables(db):
            cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
            marker = f"ZZMARKER-{table}-zz9"
            names: list[str] = []
            values: list[object] = []
            for _cid, name, ctype, _notnull, _dflt, pk in cols:
                if pk and "INT" in (ctype or "").upper():
                    continue  # rowid alias — let SQLite assign it
                names.append(name)
                ct = (ctype or "").upper()
                if "INT" in ct:
                    values.append(1)
                elif "REAL" in ct or "FLOA" in ct or "DOUB" in ct:
                    values.append(1.0)
                else:
                    values.append(marker)
            conn.execute(
                f"INSERT INTO {table} ({', '.join(names)}) "
                f"VALUES ({', '.join('?' for _ in names)})",
                values,
            )
            markers[table] = marker
        conn.commit()
    finally:
        conn.close()
    return markers


def _make_aggregator(home) -> ResearchSignalAggregator:
    return ResearchSignalAggregator(
        db_path=home.db,
        consent_version="2.1",
        provenance_key_path=home.key,
    )


def _make_repo(home) -> SqliteConsentRepository:
    return SqliteConsentRepository(
        consent_db_path=home.consent,
        research_db_path=home.db,
        provenance_key_path=home.key,
    )


def _signal() -> ResearchSignal:
    return ResearchSignal(
        signal_id="sig-home-1",
        signal_type="GJ-01",
        severity="violation",
        confidence=0.9,
        evidence_text="evidence",
        platform="indeed",
        jurisdiction="CA",
        company_id=None,
        job_category=None,
        detected_date=date(2026, 10, 1),
        schema_version=RESEARCH_SCHEMA_VERSION,
        posting_hash="posting-hash",
    )


# ── M1: one path, consumed by collector and exporter ─────────────────────────


def test_export_reads_the_database_the_collector_writes(home, monkeypatch, tmp_path):
    """DIFFERENTIAL (M1): a row written by the real aggregator must come back
    out through main.py's real _handle_export_research.

    RED today two ways: domain.config has no RESEARCH_DB_PATH (the setattr
    raises AttributeError), and even with the constant defined the exporter
    read RESEARCH_DIR / <file> while the collector wrote one level up — the
    export exited 1 with 'unable to open database file'.
    """
    reports = tmp_path / "reports"
    monkeypatch.setattr(domain_config, "RESEARCH_DB_PATH", home.db)
    monkeypatch.setattr(domain_config, "REPORTS_DIR", reports)

    aggregator = _make_aggregator(home)
    aggregator._write_batch([_signal()])
    assert home.db.exists()

    from auto_apply.main import _handle_export_research

    with pytest.raises(SystemExit) as excinfo:
        _handle_export_research(SimpleNamespace(export_format="csv"))
    assert excinfo.value.code == 0, (
        "the exporter could not read the database the collector wrote"
    )

    bundles = list(reports.iterdir())
    assert len(bundles) == 1
    csv_text = (bundles[0] / "research_signals.csv").read_text(encoding="utf-8")
    assert "GJ-01" in csv_text
    assert "sig-home-1" in csv_text


def test_composition_root_and_main_consume_the_one_name():
    """GUARD (M1, binding): both consumers reference the config constant —
    checked on the AST, not on substrings.

    RED today: composition_root binds _signals_db to a USER_DATA_DIR BinOp
    and main passes a RESEARCH_DIR BinOp to ResearchExporter.
    """
    import auto_apply.infrastructure.composition_root as composition_root
    import auto_apply.main as main_module

    cr_tree = ast.parse(inspect.getsource(composition_root))
    assert any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "_signals_db" for t in node.targets
        )
        and isinstance(node.value, ast.Name)
        and node.value.id == "RESEARCH_DB_PATH"
        for node in ast.walk(cr_tree)
    ), "composition_root must bind _signals_db from RESEARCH_DB_PATH"

    main_tree = ast.parse(inspect.getsource(main_module))
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ResearchExporter"
        and any(
            kw.arg == "db_path"
            and isinstance(kw.value, ast.Name)
            and kw.value.id == "RESEARCH_DB_PATH"
            for kw in node.keywords
        )
        for node in ast.walk(main_tree)
    ), "main must hand RESEARCH_DB_PATH to ResearchExporter"


def test_the_filename_is_spelled_in_exactly_one_src_file():
    """GUARD/RATCHET (M1): the filename literal appears in domain/config.py
    and nowhere else under src/, so no second spelling can drift.

    RED today: composition_root.py and main.py both spell it (three files).
    """
    src_pkg = Path(domain_config.__file__).resolve().parent.parent
    hits = sorted(
        p
        for p in src_pkg.rglob("*.py")
        if "research_signals.db" in p.read_text(encoding="utf-8")
    )
    assert hits == [Path(domain_config.__file__).resolve()]


# ── M4/M5: the purge deletes everything, bytes included ──────────────────────


def test_purge_empties_every_table_and_removes_the_files(home):
    """TEETH (M4): after the purge, every table the schema has is gone with
    the files — and the returned count counts them.

    RED today: the purge deleted 5 tables by literal name, returned 5, and
    left discovery_pages, discovery_cards, discovery_candidates,
    detector_examinations, detector_outcomes and research_provenance holding
    their rows.
    """
    _make_aggregator(home)  # constructor creates the schema
    markers = _seed_one_marker_row_per_table(home.db)
    assert len(markers) >= 11

    deleted = _make_repo(home).purge_research_data()

    assert deleted >= len(markers)
    assert not home.db.exists(), "the database file itself must be gone"
    assert not Path(str(home.db) + "-wal").exists()
    assert not Path(str(home.db) + "-shm").exists()


def test_no_marker_survives_in_any_file_after_purge(home):
    """TEETH (M5): once every connection is closed, no purged marker exists
    in ANY file anywhere under the data home — not in the .db, not in a WAL.

    RED today: the six un-purged tables' markers remain in the .db file's
    bytes (measured 2026-10-01), and even the five 'purged' ones survive in
    the WAL while another connection is open.
    """
    _make_aggregator(home)
    markers = _seed_one_marker_row_per_table(home.db)

    _make_repo(home).purge_research_data()

    scanned = 0
    for path in home.root.rglob("*"):
        if not path.is_file():
            continue
        scanned += 1
        data = path.read_bytes()
        for marker in markers.values():
            assert marker.encode() not in data, f"{marker} survived in {path}"
    assert scanned > 0  # the consent db exists — the scan must not be vacuous


def test_purge_falls_back_to_row_deletion_when_unlink_fails(home, monkeypatch):
    """TEETH (M4/M5, degraded path): a Windows lock on the main file must not
    strand the user's data. With unlink blocked, the purge falls back to
    deleting every row in every table, then checkpoint+VACUUM scrubs the
    bytes — verified here with no concurrent reader, the only case the
    fallback promises byte-erasure for.

    RED today: no fallback existed, and the literal list left six tables.
    """
    _make_aggregator(home)
    markers = _seed_one_marker_row_per_table(home.db)

    real_unlink = Path.unlink

    def blocked_unlink(self, *args, **kwargs):
        if self == home.db:
            raise PermissionError("simulated Windows file lock")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", blocked_unlink)
    deleted = _make_repo(home).purge_research_data()

    assert deleted >= len(markers)
    assert home.db.exists(), "the fallback deletes rows, not the file"
    for table in _tables(home.db):
        conn = sqlite3.connect(str(home.db))
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()
        assert count == 0, f"{table} still holds rows after the fallback purge"

    for path in home.root.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        for marker in markers.values():
            assert marker.encode() not in data, f"{marker} survived in {path}"


def test_fallback_scrubs_bytes_while_a_connection_stays_open(home, monkeypatch):
    """TEETH (M5, the Windows path): Windows refuses to unlink a file any
    connection holds open, so this is the purge a Windows user gets while AA
    still has the database open. An IDLE connection (no transaction) is held
    across the purge and is STILL OPEN when the disk is read: the purge must
    have scrubbed the bytes itself, not left it to the last close.

    Every connection here starts with secure_delete OFF - SQLite's default
    and the setting of the SQLite bundled with Windows CPython. Some Linux
    builds compile it ON, which hid this on Linux; forcing OFF makes the pin
    mean the same thing on every platform.

    Fails (measured 2026-10-01) if the fallback's PRAGMA secure_delete = ON
    is removed - on Windows the purged rows' bytes then stay in
    research_signals.db for as long as any connection is open - and fails
    if its PRAGMA wal_checkpoint(TRUNCATE) is removed. Every other purge pin
    reads the disk after all connections close, so none of them sees this.
    """
    real_connect = sqlite3.connect

    def connect_like_default_build(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.execute("PRAGMA secure_delete = OFF")
        return conn

    monkeypatch.setattr(sqlite3, "connect", connect_like_default_build)
    _make_aggregator(home)
    markers = _seed_one_marker_row_per_table(home.db)

    idle = sqlite3.connect(str(home.db))
    try:
        idle.execute("SELECT COUNT(*) FROM research_signals").fetchone()

        real_unlink = Path.unlink

        def blocked_unlink(self, *args, **kwargs):
            if self.name.startswith(home.db.name):
                raise PermissionError("simulated Windows lock on an open database")
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", blocked_unlink)
        deleted = _make_repo(home).purge_research_data()
        monkeypatch.setattr(Path, "unlink", real_unlink)

        assert deleted >= len(markers)
        for path in home.root.rglob("*"):
            if not path.is_file():
                continue
            data = path.read_bytes()
            for marker in markers.values():
                assert marker.encode() not in data, (
                    f"{marker} still on disk in {path} while a connection is open"
                )
    finally:
        idle.close()


# ── M3/M6: the key — location, rotation, and the _public_key_stored trap ─────


def test_provenance_key_lives_outside_the_research_and_reports_dirs():
    """GUARD (M3): no instruction that names the research folder or the
    reports folder can sweep the private key along.

    RED today: domain.config has no PROVENANCE_KEY_PATH (AttributeError),
    and the key was resolved as RESEARCH_DIR / 'provenance_key.pem' — inside
    what this change makes the data home.
    """
    key = domain_config.PROVENANCE_KEY_PATH
    assert domain_config.RESEARCH_DIR not in key.parents
    assert domain_config.REPORTS_DIR not in key.parents


def test_purge_deletes_the_key(home):
    """TEETH (M6): a purge rotates the installation's research identity.

    RED today: the key survived every purge.
    """
    aggregator = _make_aggregator(home)
    assert aggregator._ensure_signer() is not None
    assert home.key.exists()

    _make_repo(home).purge_research_data()

    assert not home.key.exists()


def test_aggregator_rekeys_when_the_key_vanishes_under_it(home):
    """TEETH (M6, the _public_key_stored trap): a live aggregator whose key
    was rotated under it must generate a fresh key AND re-store its public
    half, or later rows leave exports with no verification.json.

    RED today: _ensure_signer returned the cached signer unconditionally, so
    no new key was generated and research_provenance stayed empty.
    """
    aggregator = _make_aggregator(home)
    signer1 = aggregator._ensure_signer()
    assert signer1 is not None and home.key.exists()

    home.key.unlink()
    with aggregator._get_connection() as conn:
        conn.execute("DELETE FROM research_provenance")

    signer2 = aggregator._ensure_signer()
    assert signer2 is not None
    assert signer2.public_key_hex != signer1.public_key_hex
    assert home.key.exists()
    with aggregator._get_connection() as conn:
        row = conn.execute(
            "SELECT public_key_hex FROM research_provenance WHERE id = 1"
        ).fetchone()
    assert row is not None
    assert row[0] == signer2.public_key_hex


# ── FORK 3: the legacy path is named, never touched ──────────────────────────


def test_legacy_db_warning_names_both_paths(tmp_path, monkeypatch, caplog):
    """GUARD (FORK 3, option b): a pre-relocation database produces a warning
    naming both paths, and AA does not move or delete it.

    RED today: composition_root has no _warn_if_legacy_research_db.
    """
    import auto_apply.infrastructure.composition_root as composition_root

    monkeypatch.setattr(
        composition_root,
        "RESEARCH_DB_PATH",
        tmp_path / "research" / "research_signals.db",
    )
    legacy = tmp_path / "research_signals.db"
    legacy.write_bytes(b"old data")

    with caplog.at_level(
        "WARNING", logger="auto_apply.infrastructure.composition_root"
    ):
        composition_root._warn_if_legacy_research_db()

    assert str(legacy) in caplog.text
    assert str(tmp_path / "research" / "research_signals.db") in caplog.text
    assert legacy.read_bytes() == b"old data"

    legacy.unlink()
    caplog.clear()
    composition_root._warn_if_legacy_research_db()
    assert caplog.text == ""

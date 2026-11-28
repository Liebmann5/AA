"""Every database durable for its medium (Phase 0, P0-7/P0-8; AA_ENGINE_MATH.md §10).

TEETH: against the pre-Phase-0 tree, ten modules opened SQLite directly,
three hard-coded WAL in their schema, and the main database set
``synchronous`` on one connection only.
"""

from __future__ import annotations

import ast
import pathlib
import sqlite3

import pytest

from auto_apply.adapters.secondary.persistence import durable_sqlite as ds

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "auto_apply"


@pytest.fixture(autouse=True)
def _reset_policy():
    ds.configure_durability("auto", frozen=False)
    yield
    ds.configure_durability("auto", frozen=False)


def _modes(conn: sqlite3.Connection) -> tuple[str, int]:
    return (str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
            int(conn.execute("PRAGMA synchronous").fetchone()[0]))


def test_a_removable_medium_gets_a_delete_journal_and_extra_sync(tmp_path) -> None:
    ds.configure_durability("removable")
    conn = ds.connect(tmp_path / "a.db")
    try:
        assert _modes(conn) == ("delete", 3), "DELETE journal, synchronous=EXTRA (3)"
    finally:
        conn.close()


def test_a_fixed_disk_keeps_wal(tmp_path) -> None:
    ds.configure_durability("fixed")
    conn = ds.connect(tmp_path / "a.db")
    try:
        assert _modes(conn) == ("wal", 1)
    finally:
        conn.close()


def test_a_medium_aa_cannot_identify_takes_the_safe_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ds, "resolve_medium", lambda path: "unknown")
    conn = ds.connect(tmp_path / "a.db")
    try:
        assert _modes(conn) == ("delete", 3)
    finally:
        conn.close()


def test_every_connection_gets_the_sync_setting_not_only_the_first(tmp_path) -> None:
    ds.configure_durability("removable")
    ds.connect(tmp_path / "a.db").close()
    second = ds.connect(tmp_path / "a.db")
    try:
        assert _modes(second)[1] == 3
    finally:
        second.close()


def test_a_wal_database_is_checkpointed_and_its_data_survives_the_switch(tmp_path) -> None:
    path = tmp_path / "old.db"
    raw = sqlite3.connect(str(path))
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("CREATE TABLE t (v TEXT)")
    raw.execute("INSERT INTO t VALUES ('kept')")
    raw.commit()
    raw.close()
    ds.configure_durability("removable")
    conn = ds.connect(path)
    try:
        assert _modes(conn)[0] == "delete"
        assert conn.execute("SELECT v FROM t").fetchall() == [("kept",)]
    finally:
        conn.close()
    assert not (tmp_path / "old.db-wal").exists(), "no committed page left in a -wal file"


def test_a_portable_build_counts_as_removable(tmp_path) -> None:
    ds.configure_durability("auto", frozen=True)
    assert ds.resolve_medium(tmp_path) == "removable"


def test_unknown_settings_read_as_auto() -> None:
    assert ds.configure_durability("usb-ish") == "auto"


def test_only_one_module_in_src_opens_sqlite() -> None:
    sites = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "connect"
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "sqlite3"):
                sites.append(path.relative_to(SRC).as_posix())
    assert set(sites) == {"adapters/secondary/persistence/durable_sqlite.py"}, sites


def test_no_shipped_schema_hard_codes_a_journal_mode() -> None:
    offenders = [p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py")
                 if p.name != "durable_sqlite.py"
                 and "journal_mode" in p.read_text(encoding="utf-8").replace(" ", "")
                 and "PRAGMAjournal_mode" in p.read_text(encoding="utf-8").replace(" ", "")]
    assert offenders == []

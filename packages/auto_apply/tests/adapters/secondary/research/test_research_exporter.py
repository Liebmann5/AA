"""Tests for the research export boundary (item 4b).

The first coverage this code has ever had. The suite pins:

  T1  a recipient can verify a row signature using ONLY the export
  T2  the same database exported twice is byte-identical, including rows
      that share a date (the case the old non-total ORDER BY broke)
  T3  a read failure leaves no artifact behind
  T4  every table in the live schema has an export path — asserted from
      sqlite_master, so a seventh table added without a TableSpec fails
  T5  a missing optional dependency degrades the format, never the export
  T6  an empty corpus and a populated corpus produce clearly different,
      both-complete artifacts
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from auto_apply.adapters.secondary.research import research_exporter
from auto_apply.adapters.secondary.research.research_exporter import (
    TABLE_SPECS,
    ExportError,
    ResearchExporter,
)
from auto_apply.adapters.secondary.research.signal_aggregator import (
    ResearchSignalAggregator,
)
from auto_apply.domain.constants import RESEARCH_SCHEMA_VERSION
from auto_apply.domain.services.signal_detectors import ResearchSignal


def _make_aggregator(
    db_path: Path, research_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> ResearchSignalAggregator:
    """Build a real, enabled aggregator against throwaway paths.

    The salt env var must be set before construction (item 4a: the
    constructor raises without it). The provenance key path is injected so
    the signer writes into the tmp tree instead of the real data directory.
    """
    monkeypatch.setenv("AA_RESEARCH_SALT", "exporter-test-salt")
    return ResearchSignalAggregator(
        db_path=db_path,
        consent_version="test-consent",
        macro_signal_interval_seconds=999_999.0,
        provenance_key_path=research_dir / "provenance_key.pem",
    )


def _signal(
    signal_id: str, detected: date, posting_hash: str = "posting-hash"
) -> ResearchSignal:
    return ResearchSignal(
        signal_id=signal_id,
        signal_type="GJ-01",
        severity="violation",
        confidence=0.9,
        evidence_text="evidence",
        platform="indeed",
        jurisdiction="CA",
        company_id=None,
        job_category=None,
        detected_date=detected,
        schema_version=RESEARCH_SCHEMA_VERSION,
        posting_hash=posting_hash,
    )


def _export(db_path: Path, export_root: Path, fmt: str, key_path: Path | None = None):
    # A tmp provenance key path is injected by every caller, so an export
    # in a test never mints a key in the developer's real data folder.
    return ResearchExporter(
        db_path=db_path,
        export_root=export_root,
        provenance_key_path=key_path,
    ).export(fmt)  # type: ignore[arg-type]


# ── T1: the export is self-verifying ──────────────────────────────────────────


def test_exported_signature_verifies_against_exported_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "research.db"
    agg = _make_aggregator(db, tmp_path / "research_cfg", monkeypatch)
    agg._write_batch([_signal("sig-001", date(2026, 1, 15))])

    result = _export(
        db, tmp_path / "exports", "ndjson", tmp_path / "research_cfg" / "provenance_key.pem"
    )
    assert result.verification_status == "ok"

    bundle = result.directory
    verification = json.loads((bundle / "verification.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (bundle / "research_signals.ndjson")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(rows) == 1
    row = rows[0]

    # The recipe below uses ONLY what the bundle contains.
    payload = {
        field: (row[field] if row[field] is not None else "")
        for field in verification["signed_fields"]
    }
    canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
    digest_hex = hashlib.sha256(canonical).hexdigest()
    assert digest_hex == row["content_hash"]

    public_key = Ed25519PublicKey.from_public_bytes(
        bytes.fromhex(verification["public_key_hex"])
    )
    # Raises InvalidSignature if the signature does not verify.
    public_key.verify(
        bytes.fromhex(row["provenance_signature"]), digest_hex.encode("utf-8")
    )


# ── T2: byte-identity for a fixed database ────────────────────────────────────


def test_same_database_exports_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "research.db"
    agg = _make_aggregator(db, tmp_path / "research_cfg", monkeypatch)
    # Two rows sharing a date, inserted with ids out of order: the case the
    # old non-total ORDER BY made nondeterministic.
    agg._write_batch(
        [_signal("sig-b", date(2026, 2, 1)), _signal("sig-a", date(2026, 2, 1))]
    )

    export_root = tmp_path / "exports"
    for fmt in ("csv", "ndjson"):
        first = _export(db, export_root, fmt, tmp_path / "research_cfg" / "provenance_key.pem")
        snapshot = {p.name: p.read_bytes() for p in sorted(first.directory.iterdir())}
        second = _export(db, export_root, fmt, tmp_path / "research_cfg" / "provenance_key.pem")
        assert second.directory == first.directory
        assert {
            p.name: p.read_bytes() for p in sorted(second.directory.iterdir())
        } == snapshot

    lines = [
        json.loads(line)
        for line in (first.directory / "research_signals.ndjson")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [r["signal_id"] for r in lines] == ["sig-a", "sig-b"]


# ── T3: a read failure leaves no artifact ─────────────────────────────────────


def test_malformed_database_raises_and_leaves_nothing(tmp_path: Path) -> None:
    bad = tmp_path / "research.db"
    bad.write_bytes(b"this is not a sqlite database")
    export_root = tmp_path / "exports"
    with pytest.raises(ExportError):
        _export(bad, export_root, "csv")
    assert list(export_root.iterdir()) == []


def test_missing_database_is_an_error_not_an_empty_export(tmp_path: Path) -> None:
    export_root = tmp_path / "exports"
    with pytest.raises(ExportError):
        _export(tmp_path / "nope.db", export_root, "csv")
    assert list(export_root.iterdir()) == []


# ── T4: every table in the schema has a path out ──────────────────────────────


def test_every_table_in_the_schema_has_an_export_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "research.db"
    agg = _make_aggregator(db, tmp_path / "research_cfg", monkeypatch)
    agg._write_batch([_signal("sig-001", date(2026, 3, 1))])

    conn = sqlite3.connect(db)
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        conn.close()

    declared = {spec.name for spec in TABLE_SPECS}
    # A table added to _SCHEMA_SQL without a TableSpec fails HERE.
    assert names == declared

    result = _export(
        db, tmp_path / "exports", "csv", tmp_path / "research_cfg" / "provenance_key.pem"
    )
    for spec in TABLE_SPECS:
        if spec.kind == "verification":
            assert (result.directory / "verification.json").exists()
        else:
            assert (result.directory / f"{spec.name}.csv").exists()


# ── T5: a missing optional dependency degrades the format ─────────────────────


def test_missing_pyarrow_degrades_format_not_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "research.db"
    agg = _make_aggregator(db, tmp_path / "research_cfg", monkeypatch)
    agg._write_batch([_signal("sig-001", date(2026, 4, 1))])

    # Simulate the missing dependency whether or not pyarrow is installed.
    monkeypatch.setattr(research_exporter, "_module_available", lambda _module: False)

    result = _export(
        db, tmp_path / "exports", "parquet", tmp_path / "research_cfg" / "provenance_key.pem"
    )
    assert result.degraded is True
    assert result.requested_format == "parquet"
    assert result.format == "csv"

    csv_path = result.directory / "research_signals.csv"
    assert csv_path.exists()
    assert len(csv_path.read_text(encoding="utf-8").splitlines()) == 2

    index = json.loads((result.directory / "index.json").read_text(encoding="utf-8"))
    assert index["requested_format"] == "parquet"
    assert index["format"] == "csv"
    assert index["degraded"] is True


# ── T5b: a degraded run never adopts a non-degraded bundle's index ────────────


def test_degraded_export_does_not_inherit_a_clean_bundles_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A degraded run and a clean run write byte-identical DATA files, so a
    content-only address put them in one directory and the second run's
    index.json was discarded — leaving a bundle that claimed degraded=false
    while the CLI reported a degradation. The digest covers the request, so
    the two bundles are separate and each index tells the truth about itself.
    """
    db = tmp_path / "research.db"
    agg = _make_aggregator(db, tmp_path / "research_cfg", monkeypatch)
    agg._write_batch([_signal("sig-001", date(2026, 6, 1))])
    export_root = tmp_path / "exports"

    clean = _export(db, export_root, "csv", tmp_path / "research_cfg" / "provenance_key.pem")
    monkeypatch.setattr(research_exporter, "_module_available", lambda _module: False)
    degraded = _export(db, export_root, "parquet", tmp_path / "research_cfg" / "provenance_key.pem")

    assert degraded.directory != clean.directory, (
        "a degraded run landed in the clean run's bundle; its index.json was "
        "thrown away and the surviving one misdescribes how it was produced"
    )
    for result in (clean, degraded):
        index = json.loads((result.directory / "index.json").read_text(encoding="utf-8"))
        assert index["degraded"] is result.degraded
        assert index["requested_format"] == result.requested_format
        assert index["bundle_digest"] == result.bundle_digest

    # The data files really are identical — which is why the address had to
    # carry more than the bytes.
    assert (clean.directory / "research_signals.csv").read_bytes() == (
        degraded.directory / "research_signals.csv"
    ).read_bytes()


# ── T6: empty and populated corpora are distinct and complete ─────────────────


def test_empty_and_populated_corpora_are_distinct_and_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_db = tmp_path / "empty" / "research.db"
    _make_aggregator(empty_db, tmp_path / "empty_cfg", monkeypatch)
    empty_result = _export(
        empty_db, tmp_path / "exports_empty", "csv", tmp_path / "empty_cfg" / "provenance_key.pem"
    )

    pop_db = tmp_path / "populated" / "research.db"
    agg = _make_aggregator(pop_db, tmp_path / "populated_cfg", monkeypatch)
    agg._write_batch([_signal("sig-001", date(2026, 5, 1))])
    pop_result = _export(
        pop_db, tmp_path / "exports_populated", "csv", tmp_path / "populated_cfg" / "provenance_key.pem"
    )

    # Neither resembles a failure: both completed, and both carry every file.
    row_tables = [s for s in TABLE_SPECS if s.kind == "rows"]
    for res in (empty_result, pop_result):
        assert (res.directory / "index.json").exists()
        for spec in row_tables:
            assert (res.directory / f"{spec.name}.csv").exists()

    # The empty corpus is explicit about being empty: header-only CSV, rows: 0.
    header = (
        (empty_result.directory / "research_signals.csv")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(header) == 1
    assert "signal_id" in header[0]
    empty_index = json.loads(
        (empty_result.directory / "index.json").read_text(encoding="utf-8")
    )
    assert all(t["rows"] == 0 for t in empty_index["tables"])
    assert empty_index["verification"]["status"] == "unavailable"

    pop_index = json.loads(
        (pop_result.directory / "index.json").read_text(encoding="utf-8")
    )
    assert any(t["rows"] > 0 for t in pop_index["tables"])
    assert pop_index["verification"]["status"] == "ok"

    # And the two are plainly different artifacts.
    assert empty_result.bundle_digest != pop_result.bundle_digest
    assert empty_result.directory != pop_result.directory


# ── item 10: byte-exact writes, the bundle signature, and the run identity ───


def test_no_bundle_file_is_written_in_text_mode__ratchet() -> None:
    """RATCHET (P4): a text-mode write of a bundle file translates "\\n" to
    the OS line ending and forks the bundle digest by platform (the measured
    Windows/Linux divergence). Scan the exporter AST: no .write_text( calls
    at all — bundle files go out as bytes. A new text-mode write fails here,
    not in a user's differing digest."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(research_exporter))
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "write_text"
    ]
    assert not offenders, (
        f"text-mode writes at lines {offenders}; bundle files must be "
        "written with write_bytes"
    )


def test_bundle_files_have_platform_independent_bytes(tmp_path, monkeypatch) -> None:
    """TEETH (P4, restated after V4): no byte in the bundle depends on the
    OS. The csv module terminates rows with \\r\\n on EVERY platform — that
    is byte-stable, not a defect — so CSVs must be uniformly CRLF, and
    everything else must contain no \\r at all. The earlier 'no \\r
    anywhere' pin asserted the wrong property and failed on Linux."""
    db = tmp_path / "research.db"
    agg = _make_aggregator(db, tmp_path / "research_cfg", monkeypatch)
    agg._write_batch([_signal("sig-001", date(2026, 7, 1))])
    result = _export(
        db, tmp_path / "exports", "csv", tmp_path / "research_cfg" / "provenance_key.pem"
    )
    for path in result.directory.iterdir():
        data = path.read_bytes()
        if path.suffix == ".csv":
            assert data.endswith(b"\r\n"), path.name
            assert b"\n" not in data.replace(b"\r\n", b""), (
                f"{path.name}: a bare LF means the OS leaked into the bytes"
            )
        else:
            assert b"\r" not in data, path.name


def test_bundle_digest_does_not_depend_on_os_linesep(tmp_path, monkeypatch) -> None:
    """GUARD (P4): simulating a Windows line-ending convention must not move
    the digest or the directory. With byte-exact writes os.linesep is never
    consulted; the ratchet above is what makes that hold under regression."""
    import os

    db = tmp_path / "research.db"
    agg = _make_aggregator(db, tmp_path / "research_cfg", monkeypatch)
    agg._write_batch([_signal("sig-001", date(2026, 7, 2))])
    key = tmp_path / "research_cfg" / "provenance_key.pem"
    export_root = tmp_path / "exports"
    first = _export(db, export_root, "csv", key)
    snapshot = {p.name: p.read_bytes() for p in sorted(first.directory.iterdir())}
    monkeypatch.setattr(os, "linesep", "\r\n")
    second = _export(db, export_root, "csv", key)
    assert second.directory == first.directory
    assert second.bundle_digest == first.bundle_digest
    assert {
        p.name: p.read_bytes() for p in sorted(second.directory.iterdir())
    } == snapshot


def test_every_bundle_is_signed_and_the_run_identity_is_honest(
    tmp_path, monkeypatch
) -> None:
    """TEETH (P2/P3, deliverables 2 and 4): every export — even one with no
    signed rows — carries bundle_signature.json, verifiable with only the
    bundle, and a run identity that never fabricates a commit.

    RED before item 10: no bundle_signature.json existed, and index.json
    held no run_identity."""
    db = tmp_path / "research.db"
    agg = _make_aggregator(db, tmp_path / "research_cfg", monkeypatch)
    agg._write_batch([_signal("sig-001", date(2026, 7, 3))])
    result = _export(
        db, tmp_path / "exports", "csv", tmp_path / "research_cfg" / "provenance_key.pem"
    )
    bundle = result.directory

    sig = json.loads((bundle / "bundle_signature.json").read_bytes())
    index_bytes = (bundle / "index.json").read_bytes()
    expected_payload = {
        "bundle_digest": result.bundle_digest,
        "index_sha256": hashlib.sha256(index_bytes).hexdigest(),
    }
    assert sig["signed_payload"] == expected_payload
    payload_hash = hashlib.sha256(
        json.dumps(sig["signed_payload"], sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert payload_hash == sig["payload_hash"]
    Ed25519PublicKey.from_public_bytes(
        bytes.fromhex(sig["public_key_hex"])
    ).verify(bytes.fromhex(sig["signature"]), payload_hash.encode("utf-8"))
    assert sig["public_key_fingerprint"] == hashlib.sha256(
        bytes.fromhex(sig["public_key_hex"])
    ).hexdigest()
    # The honest F4 claim travels inside the artifact.
    assert "does not prove" in sig["what_this_does_not_prove"]
    assert json.loads(index_bytes)["signature"]["status"] == "signed"

    index = json.loads(index_bytes)
    run_identity = index["run_identity"]
    assert run_identity["aa_version"]
    assert len(run_identity["codebase_sha256"]) == 64
    int(run_identity["codebase_sha256"], 16)
    assert run_identity["python"]
    assert run_identity["os"]
    assert "commit" not in run_identity, (
        "a user's install cannot observe a commit; recording one would "
        "fabricate certainty (F3)"
    )


def test_an_empty_database_exports_an_honestly_unsigned_bundle(tmp_path, monkeypatch) -> None:
    """TEETH (V8): with no provenance key, the export signs NOTHING, mints
    NO key, and the index declares the bundle unsigned. RED before V8:
    _write_bundle_signature load-or-generated a private key as a side
    effect of exporting — hidden persistence, and a key that matched
    nothing in the bundle."""
    db = tmp_path / "research.db"
    _make_aggregator(db, tmp_path / "research_cfg", monkeypatch)
    key = tmp_path / "research_cfg" / "provenance_key.pem"
    result = _export(db, tmp_path / "exports", "csv", key)
    assert not key.exists(), "an export must never create a private key"
    assert not (result.directory / "bundle_signature.json").exists()
    index = json.loads((result.directory / "index.json").read_bytes())
    assert index["signature"]["status"] == "unsigned"
    assert result.verification_status == "unavailable"

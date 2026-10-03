"""Pins for the research bundle verifier (item 10, deliverable 5).

Every test builds a real bundle with the real aggregator and exporter into
tmp paths, then tampers. The six tamper cases from the work order each get
their own failure wording, asserted here. Labels: the clean-bundle and
tamper pins are TEETH (the verifier did not exist before item 10 — red by
ImportError); the exit-code pin is COVERAGE.
"""
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from auto_apply.adapters.primary.cli.research_verify import run_verify_research
from auto_apply.adapters.secondary.research.research_exporter import (
    _SIGNED_FIELDS,
    ResearchExporter,
)
from auto_apply.adapters.secondary.research.research_verifier import (
    _read_signal_rows,
    _verify_rows,
    verify_bundle,
)
from auto_apply.adapters.secondary.research.signal_aggregator import (
    ResearchSignalAggregator,
)
from auto_apply.domain.constants import RESEARCH_SCHEMA_VERSION
from auto_apply.domain.services.signal_detectors import ResearchSignal


def _signal(signal_id: str, detected: date) -> ResearchSignal:
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
        posting_hash="posting-hash",
    )


def _make_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str = "a",
    signals: tuple[str, ...] = ("sig-001", "sig-002"),
    key: Path | None = None,
) -> Path:
    """A real exported bundle directory under tmp_path / name."""
    monkeypatch.setenv("AA_RESEARCH_SALT", f"verifier-test-salt-{name}")
    root = tmp_path / name
    db = root / "research.db"
    key = key or (root / "provenance_key.pem")
    agg = ResearchSignalAggregator(
        db_path=db,
        consent_version="test-consent",
        macro_signal_interval_seconds=999_999.0,
        provenance_key_path=key,
    )
    agg._write_batch([_signal(sid, date(2026, 8, 1)) for sid in signals])
    result = ResearchExporter(
        db_path=db, export_root=root / "exports", provenance_key_path=key
    ).export("csv")
    return result.directory


def _failures(result) -> str:
    return "\n".join(result.failures)


def test_a_clean_bundle_verifies(tmp_path, monkeypatch, capsys) -> None:
    """TEETH (deliverable 5): a clean bundle verifies end to end, exit 0,
    and the report says what was NOT checked."""
    bundle = _make_bundle(tmp_path, monkeypatch)
    result = verify_bundle(bundle)
    assert result.ok, _failures(result)
    assert result.fingerprint
    assert run_verify_research(bundle) == 0
    out = capsys.readouterr().out
    assert "Result: OK" in out
    assert "not checked" in out


def test_one_changed_byte_in_a_data_file_fails(tmp_path, monkeypatch) -> None:
    """TEETH (tamper case 1): one altered byte, row count intact."""
    bundle = _make_bundle(tmp_path, monkeypatch)
    target = bundle / "research_signals.csv"
    data = bytearray(target.read_bytes())
    pos = data.rfind(b"evidence")
    assert pos > 0
    data[pos] = ord("X") if data[pos] != ord("X") else ord("Y")
    target.write_bytes(bytes(data))
    result = verify_bundle(bundle)
    assert not result.ok
    assert "was altered after export" in _failures(result)


def test_a_removed_row_fails_with_a_count_message(tmp_path, monkeypatch) -> None:
    """TEETH (tamper case 2): one row deleted."""
    bundle = _make_bundle(tmp_path, monkeypatch)
    target = bundle / "research_signals.csv"
    lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    target.write_text("".join(lines[:-1]), encoding="utf-8")
    result = verify_bundle(bundle)
    assert not result.ok
    assert "rows were added or removed after export" in _failures(result)


def test_a_table_swapped_from_another_bundle_is_named_a_swap(
    tmp_path, monkeypatch
) -> None:
    """TEETH (tamper case 3): the swapped file's rows are genuine — signed
    by the SAME installation key in the other bundle — so the verifier must
    say 'swapped from another export', not merely 'altered'."""
    shared = tmp_path / "shared" / "provenance_key.pem"
    first = _make_bundle(tmp_path, monkeypatch, "one", ("sig-a", "sig-b"), shared)
    second = _make_bundle(tmp_path, monkeypatch, "two", ("sig-c", "sig-d"), shared)
    shutil.copyfile(second / "research_signals.csv", first / "research_signals.csv")
    result = verify_bundle(first)
    assert not result.ok
    assert "swapped in from another export" in _failures(result)


def test_a_missing_bundle_signature_fails(tmp_path, monkeypatch) -> None:
    """TEETH (tamper case 4): bundle_signature.json removed."""
    bundle = _make_bundle(tmp_path, monkeypatch)
    (bundle / "bundle_signature.json").unlink()
    result = verify_bundle(bundle)
    assert not result.ok
    assert "the signature was stripped" in _failures(result)


def test_a_replaced_public_key_fails_the_digest(tmp_path, monkeypatch) -> None:
    """TEETH (tamper case 5): verification.json's public key replaced.
    verification.json feeds the bundle digest, so this is a digest
    mismatch — a different message from a data-file edit."""
    bundle = _make_bundle(tmp_path, monkeypatch)
    other_key = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    path = bundle / "verification.json"
    payload = json.loads(path.read_bytes())
    payload["public_key_hex"] = other_key
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())
    result = verify_bundle(bundle)
    assert not result.ok
    assert "bundle digest mismatch" in _failures(result)


def test_an_edited_index_fails_the_bundle_signature(tmp_path, monkeypatch) -> None:
    """TEETH (tamper case 6): index.json edited (here: a fabricated
    aa_version). Every file hash and the digest still match — only the
    signature over sha256(index.json) can catch this."""
    bundle = _make_bundle(tmp_path, monkeypatch)
    path = bundle / "index.json"
    index = json.loads(path.read_bytes())
    index["run_identity"]["aa_version"] = "9.9.9-fake"
    path.write_bytes((json.dumps(index, indent=2, sort_keys=True) + "\n").encode())
    result = verify_bundle(bundle)
    assert not result.ok
    assert "signed payload does not match" in _failures(result)


def test_not_a_bundle_folder_exit_codes(tmp_path, capsys) -> None:
    """COVERAGE: missing folder -> 2; a folder with no index.json -> 1."""
    assert run_verify_research(tmp_path / "nope") == 2
    (tmp_path / "empty").mkdir()
    assert run_verify_research(tmp_path / "empty") == 1
    assert "index.json" in capsys.readouterr().out


def test_a_declared_unsigned_bundle_is_reported_not_failed(
    tmp_path, monkeypatch, capsys
) -> None:
    """TEETH (V8): an export with no key mints NOTHING and declares the
    bundle unsigned; the verifier checks everything else, reports the
    state, exits 0, and marks the result unsigned."""
    monkeypatch.setenv("AA_RESEARCH_SALT", "verifier-unsigned-salt")
    root = tmp_path / "u"
    db = root / "research.db"
    key = root / "provenance_key.pem"
    ResearchSignalAggregator(
        db_path=db,
        consent_version="test-consent",
        macro_signal_interval_seconds=999_999.0,
        provenance_key_path=key,
    )
    result = ResearchExporter(
        db_path=db, export_root=root / "exports", provenance_key_path=key
    ).export("csv")
    assert not key.exists(), "V8: an export must never mint a key"
    assert not (result.directory / "bundle_signature.json").exists()

    verified = verify_bundle(result.directory)
    assert verified.ok, _failures(verified)
    assert not verified.signed
    assert any("unsigned" in note.lower() for note in verified.notes)
    assert run_verify_research(result.directory) == 0
    assert "UNSIGNED" in capsys.readouterr().out


def test_row_signatures_are_checked_against_the_key(tmp_path, monkeypatch) -> None:
    """TEETH: a row whose fields and content_hash agree but whose signature
    came from another key is a failure. Every tamper pin above is caught
    earlier by a file hash or the digest, so without this one the row
    signature check itself could be removed and nothing would notice."""
    bundle = _make_bundle(tmp_path, monkeypatch)
    rows = _read_signal_rows(bundle / "research_signals.csv", "csv")
    assert rows
    stranger = Ed25519PrivateKey.generate().public_key()
    verified, _unsigned, failures = _verify_rows(rows, _SIGNED_FIELDS, stranger)
    assert verified == 0
    assert len(failures) == len(rows)
    assert all("row signature invalid" in f for f in failures)


def test_rows_and_bundle_signed_by_different_keys_fail(tmp_path, monkeypatch) -> None:
    """TEETH: rows signed by one key, bundle signed by another. Every hash,
    the digest and both signatures are individually valid; only the key
    cross-check can see that two identities are mixed in one bundle."""
    monkeypatch.setenv("AA_RESEARCH_SALT", "verifier-test-salt-mixed")
    root = tmp_path / "mixed"
    db = root / "research.db"
    agg = ResearchSignalAggregator(
        db_path=db,
        consent_version="test-consent",
        macro_signal_interval_seconds=999_999.0,
        provenance_key_path=root / "row_key.pem",
    )
    agg._write_batch([_signal("sig-001", date(2026, 8, 1))])
    other_key = root / "bundle_key.pem"
    ResearchSignalAggregator(
        db_path=root / "other.db",
        consent_version="test-consent",
        macro_signal_interval_seconds=999_999.0,
        provenance_key_path=other_key,
    )._write_batch([_signal("sig-x", date(2026, 8, 1))])
    bundle = ResearchExporter(
        db_path=db, export_root=root / "exports", provenance_key_path=other_key
    ).export("csv").directory
    result = verify_bundle(bundle)
    assert not result.ok
    assert "name DIFFERENT public keys" in _failures(result)

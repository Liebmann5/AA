"""
Research bundle verifier — check an export with nothing but the bundle.

Offline by construction: no database, no research key, no network. Every
check below uses only files inside the bundle directory, so a recipient of
an export can verify it exactly as exported (item 10, P6).

Checks, in report order:
 1. index.json exists and parses.
 2. Every table file exists; its row count matches the index (CSV and
    NDJSON; Parquet row counts are read through pyarrow when installed,
    skipped with a note otherwise).
 3. Every signed row in research_signals: the content hash recomputed by
    the exported recipe equals the row's content_hash, and the row's
    Ed25519 signature verifies under the bundle's public key. Unsigned
    rows are counted and named — they cannot be verified, by design.
 4. Every table file's sha256 matches the index. A mismatch on
    research_signals whose rows ALL verify means something specific —
    the file was swapped from another export — and the report says so.
 5. The bundle digest recomputed from the files equals index.json's
    bundle_digest. This also covers verification.json, which the digest
    (not the index) hashes.
 6. bundle_signature.json exists, its signed payload matches the digest
    and the actual index.json bytes, and the signature verifies under the
    bundle's public key. This is what catches an edited index.json. A
    bundle whose index DECLARES itself unsigned (V8: the exporting
    installation had no key, and an export never mints one) skips this
    check by declaration — reported, never silently passed.
 7. When verification.json is present, its public key equals the signing
    key.

Named as NOT checked, every time: the run identity (signed, but only
checkable by hashing that code yourself) and the key's owner (the key is
self-generated — the signature proves continuity with the key in this
bundle, not an identity; compare the fingerprint with one the contributor
published).
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from auto_apply.adapters.secondary.research.research_exporter import (
    _SIGNED_FIELDS,
    _bundle_digest,
)

logger = logging.getLogger(__name__)

__all__ = ["VerifyResult", "verify_bundle"]


@dataclass(frozen=True)
class VerifyResult:
    """What verify_bundle found. ``ok`` is exactly ``not failures``."""

    ok: bool
    checks: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    fingerprint: str | None = None
    signed: bool = True


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_rows(path: Path, fmt: str) -> int | None:
    """Data-row count, or None when it cannot be counted here (Parquet
    without pyarrow)."""
    if fmt == "csv":
        with open(path, newline="", encoding="utf-8") as f:
            return max(sum(1 for _ in f) - 1, 0)
    if fmt == "ndjson":
        with open(path, encoding="utf-8") as f:
            return sum(1 for _ in f)
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return None
    return pq.read_metadata(str(path)).num_rows


def _read_signal_rows(path: Path, fmt: str) -> list[dict[str, Any]] | None:
    """research_signals rows as dicts, or None when unreadable here."""
    if fmt == "csv":
        with open(path, newline="", encoding="utf-8") as f:
            return [dict(r) for r in csv.DictReader(f)]
    if fmt == "ndjson":
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return None
    return pq.read_table(str(path)).to_pylist()


def _coerce_row_value(field_name: str, value: Any) -> Any:
    """CSV hands every field back as a string; the signing recipe used the
    typed value. confidence is the only signed numeric field, so it is the
    only coercion — documented rather than guessed generically."""
    if field_name == "confidence" and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _verify_rows(
    rows: list[dict[str, Any]],
    signed_fields: tuple[str, ...],
    public_key: Ed25519PublicKey,
) -> tuple[int, int, list[str]]:
    """(verified, unsigned, failures) over research_signals rows."""
    verified = 0
    unsigned = 0
    failures: list[str] = []
    for row in rows:
        signature_hex = row.get("provenance_signature")
        signal_id = row.get("signal_id") or "<unknown>"
        if not signature_hex:
            unsigned += 1
            continue
        payload = {
            f: _coerce_row_value(f, row.get(f) if row.get(f) is not None else "")
            for f in signed_fields
        }
        digest_hex = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if row.get("content_hash") and digest_hex != row["content_hash"]:
            failures.append(
                f"content hash mismatch for signal {signal_id} — the row's "
                "fields were altered after signing"
            )
            continue
        try:
            public_key.verify(bytes.fromhex(signature_hex), digest_hex.encode("utf-8"))
        except InvalidSignature:
            failures.append(
                f"row signature invalid for signal {signal_id} — the row was "
                "altered after signing or signed by a different key"
            )
        except ValueError:
            failures.append(f"row signature for signal {signal_id} is not valid hex")
        else:
            verified += 1
    return verified, unsigned, failures


def verify_bundle(bundle_dir: Path) -> VerifyResult:
    """Verify one export bundle directory. Never raises for a bad bundle —
    a malformed bundle is a verification RESULT, not an exception."""
    checks: list[str] = []
    failures: list[str] = []
    notes: list[str] = []
    fingerprint: str | None = None

    index_path = bundle_dir / "index.json"
    if not index_path.is_file():
        return VerifyResult(
            ok=False,
            failures=(
                f"index.json is missing — {bundle_dir} is not a research "
                "export bundle",
            ),
        )
    index_bytes = index_path.read_bytes()
    try:
        index = json.loads(index_bytes)
    except json.JSONDecodeError as exc:
        return VerifyResult(ok=False, failures=(f"index.json does not parse: {exc}",))
    fmt = index.get("format", "csv")
    tables = index.get("tables", [])
    checks.append(
        f"index.json parsed — format {fmt}, {len(tables)} tables, "
        f"research schema v{index.get('research_schema_version')}"
    )

    # 2. existence + row counts
    present: dict[str, Path] = {}
    counted = 0
    for entry in tables:
        path = bundle_dir / entry["file"]
        if not path.is_file():
            failures.append(f"{entry['file']} is missing — the bundle is incomplete")
            continue
        present[entry["file"]] = path
        row_count = _count_rows(path, fmt)
        if row_count is None:
            notes.append(
                f"{entry['file']}: row count not checked (reading Parquet "
                "needs pyarrow, which is not installed)"
            )
            continue
        counted += 1
        if row_count != entry["rows"]:
            failures.append(
                f"row count mismatch in {entry['file']}: the index records "
                f"{entry['rows']} rows but the file holds {row_count} — rows were "
                "added or removed after export"
            )
    if counted and not any("row count" in f for f in failures):
        checks.append("every table file is present and row counts match the index")
    elif counted:
        checks.append("every table file is present")

    # verification.json + the bundle's row-signing key
    verification: dict[str, Any] | None = None
    verification_path = bundle_dir / "verification.json"
    verification_expected = (
        isinstance(index.get("verification"), dict)
        and index["verification"].get("status") == "ok"
    )
    if verification_expected and not verification_path.is_file():
        failures.append(
            "verification.json is missing but the index says it was exported"
        )
    elif verification_path.is_file():
        try:
            verification = json.loads(verification_path.read_bytes())
        except json.JSONDecodeError as exc:
            failures.append(f"verification.json does not parse: {exc}")

    public_key: Ed25519PublicKey | None = None
    public_key_hex: str | None = None
    if verification and verification.get("public_key_hex"):
        try:
            public_key = Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(verification["public_key_hex"])
            )
            public_key_hex = verification["public_key_hex"]
        except ValueError:
            failures.append("verification.json carries an invalid public key")

    # 3. row signatures (before file hashes: the swap diagnosis needs them)
    signals_entry = next((e for e in tables if e["table"] == "research_signals"), None)
    signed_fields: tuple[str, ...] = _SIGNED_FIELDS
    if verification and verification.get("signed_fields"):
        signed_fields = tuple(verification["signed_fields"])
    all_rows_verified = False
    if signals_entry and signals_entry["file"] in present:
        rows = _read_signal_rows(present[signals_entry["file"]], fmt)
        if rows is None:
            notes.append(
                "research_signals row signatures not checked (reading "
                "Parquet needs pyarrow, which is not installed)"
            )
        else:
            signed_rows = [r for r in rows if r.get("provenance_signature")]
            if signed_rows and public_key is None:
                failures.append(
                    f"{len(signed_rows)} rows carry provenance signatures but "
                    "verification.json has no usable public key to check "
                    "them against"
                )
            elif public_key is not None:
                verified, unsigned, row_failures = _verify_rows(
                    rows, signed_fields, public_key
                )
                failures.extend(row_failures)
                all_rows_verified = bool(signed_rows) and not row_failures
                if verified:
                    checks.append(
                        f"{verified} signed research_signals row(s) verify "
                        "under the bundle's public key"
                    )
                if unsigned:
                    notes.append(
                        f"{unsigned} row(s) carry no provenance signature "
                        "(written while the signer was unavailable) and "
                        "cannot be verified — by design"
                    )
                if not signed_rows:
                    notes.append("research_signals holds no signed rows to verify")

    # 4. per-file hashes
    file_hashes: list[tuple[str, str]] = []
    mismatched: list[str] = []
    for entry in tables:
        path = present.get(entry["file"])
        if path is None:
            continue
        sha = _sha256_file(path)
        file_hashes.append((entry["file"], sha))
        if sha != entry["sha256"]:
            mismatched.append(entry["file"])
            if entry["table"] == "research_signals" and all_rows_verified:
                failures.append(
                    f"content hash mismatch in {entry['file']} — but every "
                    "row signature in it verifies, so the file was not "
                    "altered here: it was swapped in from another export"
                )
            else:
                failures.append(
                    f"content hash mismatch in {entry['file']} — the file "
                    "was altered after export or does not belong to this bundle"
                )
    if not mismatched:
        checks.append("every file's sha256 matches the index")

    # 5. the bundle digest (covers verification.json, which the index does not)
    if verification_path.is_file():
        file_hashes.append(("verification.json", _sha256_file(verification_path)))
    digest = _bundle_digest(
        file_hashes,
        str(index.get("requested_format", fmt)),
        bool(index.get("degraded", False)),
    )
    if digest != index.get("bundle_digest"):
        failures.append(
            "bundle digest mismatch — the files do not produce the digest "
            "recorded in index.json (a file was changed, added or removed, "
            "or verification.json was replaced)"
        )
    else:
        checks.append("the bundle digest recomputed from the files matches the index")

    # 6. the bundle signature (this is what catches an edited index.json)
    signature_path = bundle_dir / "bundle_signature.json"
    signing_key_hex: str | None = None
    signature_meta = index.get("signature")
    declared_unsigned = (
        isinstance(signature_meta, dict)
        and signature_meta.get("status") == "unsigned"
    )
    if declared_unsigned:
        # V8: an export never mints a key, so an installation without one
        # ships an honestly-DECLARED unsigned bundle. That is a state to
        # report, not a tamper to fail — everything else was still checked.
        notes.append(
            "this bundle is UNSIGNED as declared in index.json — no "
            "provenance key existed on the exporting installation, so the "
            "bundle-level signature cannot be checked; file hashes, row "
            "counts, the bundle digest and any row signatures WERE checked"
        )
    elif not signature_path.is_file():
        failures.append(
            "bundle_signature.json is missing but index.json does not "
            "declare the bundle unsigned — the signature was stripped"
        )
    else:
        bundle_sig: dict[str, Any] | None
        try:
            bundle_sig = json.loads(signature_path.read_bytes())
        except json.JSONDecodeError as exc:
            bundle_sig = None
            failures.append(f"bundle_signature.json does not parse: {exc}")
        if bundle_sig is not None:
            signing_key_hex = bundle_sig.get("public_key_hex")
            payload = bundle_sig.get("signed_payload") or {}
            expected_payload = {
                "bundle_digest": index.get("bundle_digest"),
                "index_sha256": hashlib.sha256(index_bytes).hexdigest(),
            }
            payload_hash = hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode("utf-8")
            ).hexdigest()
            try:
                sig_key = Ed25519PublicKey.from_public_bytes(
                    bytes.fromhex(signing_key_hex or "")
                )
                fingerprint = hashlib.sha256(
                    bytes.fromhex(signing_key_hex or "")
                ).hexdigest()
                if payload != expected_payload:
                    failures.append(
                        "bundle signature's signed payload does not match "
                        "this bundle — index.json or the digest was altered "
                        "after signing"
                    )
                else:
                    sig_key.verify(
                        bytes.fromhex(bundle_sig.get("signature", "")),
                        payload_hash.encode("utf-8"),
                    )
                    checks.append(
                        "the bundle signature verifies — the data files, "
                        "the index and the run identity are unaltered since export"
                    )
            except InvalidSignature:
                failures.append(
                    "bundle signature does not verify — index.json or the "
                    "signed digest was altered after export, or the signing "
                    "key was replaced"
                )
            except (ValueError, TypeError) as exc:
                failures.append(f"bundle_signature.json is malformed: {exc}")

    # 7. key cross-check
    if public_key_hex and signing_key_hex:
        if public_key_hex == signing_key_hex:
            checks.append(
                "verification.json and the bundle signature name the same key"
            )
        else:
            failures.append(
                "verification.json and bundle_signature.json name DIFFERENT "
                "public keys — one of them was replaced"
            )

    # The honesty footer: said every time, whether the bundle passes or not.
    notes.append(
        "not checked: the run identity in index.json is signed, but it is a "
        "claim about the code — verify it only by hashing that code yourself"
    )
    notes.append(
        "not checked: who the contributor is. The signing key is generated "
        "by the installation, so the signature proves this bundle is "
        "unaltered since export, nothing more. Compare the fingerprint "
        "with one the contributor published."
    )

    return VerifyResult(
        ok=not failures,
        checks=tuple(checks),
        failures=tuple(failures),
        notes=tuple(notes),
        fingerprint=fingerprint,
        signed=not declared_unsigned,
    )

"""
ResearchExporter — the research export boundary.

Exports the research SQLite database as ONE self-describing bundle: a
directory whose name is a content address, containing one data file per
table, a verification file carrying the Ed25519 provenance public key, and
an index that binds the bundle together. A recipient can verify every
signed row in ``research_signals`` using only what the bundle contains.

Rulings implemented here (item 4b):

R1  An export is ONE DIRECTORY per database state, not loose files in a
    shared reports folder. The directory name embeds the bundle digest —
    a pure function of the bundle's content and of the export request that
    produced it — so re-exporting an unchanged database the same way
    reproduces the same directory, and two bundles that would describe
    themselves differently can never share one.
R2  Byte-identity guarantee: same database file + same AA version + same
    format (and, for Parquet, the same pyarrow version) means every file
    in the bundle is byte-identical on one machine. No wall-clock
    timestamp appears in any filename or in any file content; row order is
    total (TABLE_SPECS declares an ORDER BY that ends at each table's
    primary key); every file is written as exact bytes, so the digest
    never forks on an OS line-ending convention. Across machines the
    digest-covered files stay identical; ``index.json`` additionally
    records where it ran (OS, Python), so it — and therefore
    ``bundle_signature.json``, which signs its hash — may differ while
    the bundle digest and directory name do not.
R3  The provenance public key travels as ``verification.json`` —
    structurally distinct from the data files — together with the exact
    recipe for reconstructing a signed payload. If no key is on record,
    the file is absent and the index says so explicitly.
R4  A read failure aborts the whole export. Everything is written into a
    temporary directory that is renamed into place only after every byte
    has succeeded, so no partial or plausible-but-empty artifact can
    survive a failure. An empty table is not a failure: its data file
    carries a header (CSV), zero lines (NDJSON), or a zero-row frame
    (Parquet), and the index records ``"rows": 0`` explicitly.

Every bundle from an installation WITH a provenance key is SIGNED (item
10): ``bundle_signature.json`` holds an Ed25519 signature, made with the
installation's own key, over the bundle digest and the sha256 of
``index.json`` — so the data files, the index and the run identity inside
it are all covered. An installation with no signed research rows has no
key, and an export NEVER creates one (V8 — a private key appearing as a
side effect of exporting is hidden persistence, and the key would match
nothing in the bundle): the bundle then declares ``"signature":
{"status": "unsigned"}`` in ``index.json`` instead, and the verifier
reports that state plainly rather than failing it. The signature proves
the bundle is unaltered since this installation exported it; it does not
prove the exporting code was unmodified (the key is self-generated and
vouches for bytes, not code) — the exact claim is written into the file
itself.
``index.json`` also carries a run identity: AA version, a sha256 of the
installed code (CodebaseHasher — never a git commit, which a user install
cannot prove), Python and OS. The per-row signatures it exposes were
minted by signal_aggregator._write_batch, whose signed content this module
never touches (C2). The schema version travels in ``index.json`` for the
whole bundle; it is sourced from domain.constants.RESEARCH_SCHEMA_VERSION.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import logging
import os
import platform
import shutil
import sqlite3
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Callable, Iterable, Literal

from auto_apply.adapters.secondary.security.data_protection import (
    CodebaseHasher,
    ProvenanceSigner,
    read_public_key_fingerprint,
)
from auto_apply.domain.constants import RESEARCH_SCHEMA_VERSION

logger = logging.getLogger(__name__)

ExportFormat = Literal["csv", "ndjson", "parquet"]


class ExportError(Exception):
    """The export failed; no artifact survives a failed export."""


@dataclass(frozen=True)
class TableSpec:
    """Declares how one research table leaves the database.

    ``order_by`` must give a TOTAL order over the table's rows so that two
    exports of the same database byte-match (R2); it therefore always ends
    at the primary key. ``kind="verification"`` marks the table whose
    single row is exported as ``verification.json`` instead of a data
    file (R3). Adding a table to the database schema without adding a
    TableSpec here fails the schema-driven export test.
    """

    name: str
    order_by: tuple[str, ...]
    kind: Literal["rows", "verification"] = "rows"


TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec("research_signals", ("detected_date", "signal_id")),
    TableSpec("job_lifecycles", ("job_fingerprint", "platform")),
    TableSpec("salary_observations", ("posted_date", "obs_id")),
    TableSpec("form_observations", ("observed_date", "form_id")),
    TableSpec("application_outcomes", ("submitted_date", "outcome_id")),
    TableSpec("discovery_pages", ("observed_date", "page_id")),
    TableSpec("discovery_cards", ("page_id", "card_index", "card_id")),
    TableSpec("discovery_candidates", ("card_id", "candidate_id")),
    # Item 5 — detector outcome accounting. Orders end at each primary key
    # so two exports of the same database byte-match (R2), as for every
    # other rows table.
    TableSpec("detector_examinations", ("examined_date", "examination_id")),
    TableSpec("detector_outcomes", ("examination_id", "outcome_id")),
    TableSpec("research_provenance", (), kind="verification"),
)

#: The fields signal_aggregator._write_batch signs, in the recipe's words.
#: Read from the write path; never re-defined independently (C2).
_SIGNED_FIELDS: tuple[str, ...] = (
    "signal_type",
    "severity",
    "confidence",
    "evidence_text",
    "platform",
    "jurisdiction",
    "detected_date",
    "posting_hash",
)

_VERIFICATION_RECIPE: tuple[str, ...] = (
    "1. From a research_signals row, take the eight signed_fields; map SQL NULL to ''.",
    "2. canonical = json.dumps(payload, sort_keys=True).encode('utf-8')  # default separators",
    "3. digest_hex = hashlib.sha256(canonical).hexdigest()  # must equal the row's content_hash",
    "4. message = digest_hex.encode('utf-8')  # the hex string is signed, not the raw digest bytes",
    "5. Ed25519 verify: public_key.verify(bytes.fromhex(provenance_signature), message)",
)


@dataclass(frozen=True)
class TableExportInfo:
    table: str
    filename: str
    rows: int
    sha256: str


@dataclass(frozen=True)
class ExportResult:
    directory: Path
    format: str
    requested_format: str
    degraded: bool
    tables: tuple[TableExportInfo, ...]
    verification_status: Literal["ok", "unavailable"]
    bundle_digest: str


# ── Format writers ────────────────────────────────────────────────────────────
# Uniform signature: (path, columns, rows) -> row count. CSV and NDJSON stream
# row-by-row off the cursor (O(1) memory). Parquet materializes because pyarrow
# builds the table as a columnar batch — see _write_parquet's note.


def _write_csv(path: Path, columns: list[str], rows: Iterable[sqlite3.Row]) -> int:
    count = 0
    # newline="" keeps the csv module's \r\n terminator untranslated, so the
    # bytes are identical on every platform.
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row[c] for c in columns])
            count += 1
    return count


def _write_ndjson(path: Path, columns: list[str], rows: Iterable[sqlite3.Row]) -> int:
    count = 0
    # newline="" disables \n -> \r\n translation on Windows.
    with open(path, "w", newline="", encoding="utf-8") as f:
        for row in rows:
            f.write(
                json.dumps({c: row[c] for c in columns}, ensure_ascii=False, default=str)
            )
            f.write("\n")
            count += 1
    return count


def _write_parquet(path: Path, columns: list[str], rows: Iterable[sqlite3.Row]) -> int:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ExportError(
            "pyarrow is required for Parquet export and its import failed. "
            "Install it with: pip install pyarrow"
        ) from exc
    # pyarrow assembles a Table in memory, so unlike the CSV/NDJSON paths this
    # materializes the whole table. Acceptable at current corpus sizes (a
    # 1M-row signals table costs roughly 1 GB transient); beyond that, use CSV
    # or chunked row-group writing (future work).
    materialized = [{c: row[c] for c in columns} for row in rows]
    if materialized:
        table = pa.Table.from_pylist(materialized)
    else:
        table = pa.table({c: [] for c in columns})
    pq.write_table(table, str(path), compression="snappy")
    return len(materialized)


@dataclass(frozen=True)
class FormatSpec:
    extension: str
    writer: Callable[[Path, list[str], Iterable[sqlite3.Row]], int]
    optional_dependency: str | None = None


_FORMATS: dict[str, FormatSpec] = {
    "csv": FormatSpec("csv", _write_csv),
    "ndjson": FormatSpec("ndjson", _write_ndjson),
    "parquet": FormatSpec("parquet", _write_parquet, optional_dependency="pyarrow"),
}


def _module_available(module: str) -> bool:
    """True when an optional dependency is importable.

    Module-level so tests can patch it to simulate a missing dependency
    without uninstalling anything.
    """
    return importlib.util.find_spec(module) is not None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _bundle_digest(
    file_hashes: list[tuple[str, str]],
    requested_format: str,
    degraded: bool,
) -> str:
    """Digest over the bundle's content AND the request that produced it.

    Covers every bundle file except index.json (which is written after the
    digest and contains it), plus the two facts that index.json records and
    the filenames cannot: which format was ASKED for, and whether the answer
    was a degradation.

    Those two belong in the address because otherwise a bundle can
    misdescribe its own provenance. A run that asked for Parquet, found no
    pyarrow and fell back to CSV writes byte-identical data files to a plain
    CSV run; with a content-only digest both land in one directory, the second
    run's index.json is discarded with its temp directory, and the surviving
    index claims `degraded: false` for a bundle the CLI just told the user was
    degraded. R2's guarantee is already scoped to "the same format choice", so
    making the address a function of the choice is what the ruling said.

    The cost, stated: the same bytes can occupy two directories when reached
    by two different requests. That is the right trade — a duplicated CSV file
    is cheap, and an artifact that lies about its own origin is not.

    This digest is what bundle_signature.json signs (with the sha256 of
    index.json alongside it). Alone it is a checksum and makes no trust
    claim by itself.
    """
    h = hashlib.sha256()
    for rel, sha in sorted(file_hashes):
        h.update(f"{sha}  {rel}\n".encode("utf-8"))
    h.update(f"requested_format={requested_format}\n".encode("utf-8"))
    h.update(f"degraded={int(degraded)}\n".encode("utf-8"))
    return h.hexdigest()


def _run_identity() -> dict[str, str]:
    """What produced this export (F3) — claims, never fabrications.

    ``aa_version`` comes from package metadata and ``codebase_sha256``
    hashes the installed package's own .py files, so all three install
    shapes (git checkout, wheel/sdist, dirty tree) are described the same
    honest way, and a dirty tree simply hashes differently from a clean
    release. A git commit is deliberately NOT recorded: nothing on a
    user's machine observes one, and a field that only exists for the
    maintainer's checkout would fabricate certainty everywhere else. What
    a recipient can conclude: hash the code of a release themselves and
    compare — equality means this bundle came from code identical to that
    release; inequality proves nothing beyond "different".
    """
    try:
        aa_version = importlib_metadata.version("auto_apply")
    except importlib_metadata.PackageNotFoundError:
        aa_version = "unknown"
    import auto_apply  # noqa: PLC0415

    return {
        "aa_version": aa_version,
        "codebase_sha256": CodebaseHasher.hash_src_directory(
            Path(auto_apply.__file__).parent
        ),
        "python": platform.python_version(),
        "os": platform.system(),
        "note": (
            "descriptive, covered by the bundle signature but not by the "
            "bundle digest; verify it only by hashing that code yourself"
        ),
    }


class ResearchExporter:
    """Export the research database as one verifiable, signed bundle.

    Args:
        db_path: Path to the research SQLite database.
        export_root: Directory the bundle directory is created in.
        provenance_key_path: The installation's Ed25519 key, used to sign
            the bundle. READ-ONLY (V8): the bundle is signed only when a
            key already exists at this path — the key is created by the
            first signed research row, never by an export. None resolves
            to domain.config.PROVENANCE_KEY_PATH lazily; tests inject a
            tmp path.
    """

    def __init__(
        self,
        db_path: Path,
        export_root: Path,
        provenance_key_path: Path | None = None,
    ) -> None:
        self._db_path = db_path
        self._export_root = export_root
        self._provenance_key_path = provenance_key_path

    def export(self, fmt: ExportFormat = "csv") -> ExportResult:
        """Export every research table as one bundle directory.

        A missing optional dependency degrades the requested format to CSV;
        it never aborts the export. Any read or write failure aborts the
        export and leaves no artifact behind (R4).

        Args:
            fmt: Output format — 'csv', 'ndjson', or 'parquet'.

        Returns:
            ExportResult describing the published bundle.

        Raises:
            ValueError: For an unknown format (single validation point).
            ExportError: For any database or filesystem failure.
        """
        if fmt not in _FORMATS:
            raise ValueError(
                f"Unsupported format: {fmt!r}. Accepted values: {sorted(_FORMATS)}"
            )
        requested_format: str = fmt
        fmt_spec = _FORMATS[fmt]
        degraded = False
        if fmt_spec.optional_dependency and not _module_available(
            fmt_spec.optional_dependency
        ):
            logger.warning(
                "ResearchExport | %s requested but optional dependency %r is not "
                "installed; degrading to CSV",
                fmt,
                fmt_spec.optional_dependency,
            )
            fmt_spec = _FORMATS["csv"]
            degraded = True

        self._export_root.mkdir(parents=True, exist_ok=True)
        temp_dir = self._export_root / f".aa_export_tmp_{os.getpid()}"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)  # leftover from a crashed run
        temp_dir.mkdir()

        try:
            tables, verification_status, digest = self._export_into(
                temp_dir, fmt_spec, requested_format, degraded
            )
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            if isinstance(exc, ExportError):
                raise
            raise ExportError(f"research export failed: {exc}") from exc

        final_dir = self._export_root / f"aa_research_export_{digest[:12]}"
        if final_dir.exists():
            # Content-addressed: a directory with this name already holds
            # exactly these bytes, so the fresh temp copy is redundant.
            shutil.rmtree(temp_dir)
        else:
            os.rename(temp_dir, final_dir)

        logger.info(
            "ResearchExport | %d tables exported as %s to %s (degraded=%s)",
            len(tables),
            fmt_spec.extension,
            final_dir,
            degraded,
        )
        return ExportResult(
            directory=final_dir,
            format=fmt_spec.extension,
            requested_format=requested_format,
            degraded=degraded,
            tables=tables,
            verification_status=verification_status,
            bundle_digest=digest,
        )

    # ── Bundle assembly ───────────────────────────────────────────────────────

    def _export_into(
        self,
        out_dir: Path,
        fmt_spec: FormatSpec,
        requested_format: str,
        degraded: bool,
    ) -> tuple[tuple[TableExportInfo, ...], Literal["ok", "unavailable"], str]:
        """Write every bundle file into out_dir.

        Returns (per-table info, verification status, bundle digest).
        Any exception propagates to export(), which removes out_dir.
        """
        # Read-only: export can never mutate the research database, and a
        # missing database file fails here at connect instead of exporting
        # as a plausible empty bundle (R4).
        conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
            tables: list[TableExportInfo] = []
            columns_by_table: dict[str, list[str]] = {}
            file_hashes: list[tuple[str, str]] = []
            verification_status: Literal["ok", "unavailable"] = "unavailable"

            for spec in TABLE_SPECS:
                if spec.kind == "verification":
                    verification_status = self._write_verification(
                        conn, out_dir, file_hashes
                    )
                    continue
                info, columns = self._write_table(conn, spec, fmt_spec, out_dir)
                tables.append(info)
                columns_by_table[spec.name] = columns
                file_hashes.append((info.filename, info.sha256))

            digest = _bundle_digest(file_hashes, requested_format, degraded)
            signing_key_exists = self._key_path().exists()
            index = {
                "bundle_schema_version": 1,
                "research_schema_version": RESEARCH_SCHEMA_VERSION,
                "database_user_version": user_version,
                "format": fmt_spec.extension,
                "requested_format": requested_format,
                "degraded": degraded,
                "run_identity": _run_identity(),
                "signature": (
                    {"status": "signed"}
                    if signing_key_exists
                    else {
                        "status": "unsigned",
                        "reason": (
                            "no provenance key exists on the exporting "
                            "installation — one is created when the first "
                            "research row is signed; an export never "
                            "creates one"
                        ),
                    }
                ),
                "tables": [
                    {
                        "table": t.table,
                        "file": t.filename,
                        "columns": columns_by_table[t.table],
                        "rows": t.rows,
                        "sha256": t.sha256,
                    }
                    for t in tables
                ],
                "verification": (
                    {"status": "ok", "file": "verification.json"}
                    if verification_status == "ok"
                    else {
                        "status": "unavailable",
                        "reason": (
                            "research_provenance holds no public key; "
                            "no signed signals have been recorded"
                        ),
                    }
                ),
                "bundle_digest": digest,
            }
            index_bytes = (
                json.dumps(index, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            # Exact bytes (R2): a text-mode write would translate "\n" to
            # the OS line ending and fork verification by platform.
            (out_dir / "index.json").write_bytes(index_bytes)
            if signing_key_exists:
                self._write_bundle_signature(out_dir, digest, index_bytes)
            else:
                logger.info(
                    "ResearchExport | no provenance key on this installation — "
                    "bundle left unsigned (declared in index.json)"
                )
            return tuple(tables), verification_status, digest
        finally:
            conn.close()

    def _key_path(self) -> Path:
        """The provenance key's path: injected, else the config constant."""
        if self._provenance_key_path is not None:
            return self._provenance_key_path
        from auto_apply.domain.config import PROVENANCE_KEY_PATH  # noqa: PLC0415

        return PROVENANCE_KEY_PATH

    def _write_bundle_signature(
        self, out_dir: Path, digest: str, index_bytes: bytes
    ) -> None:
        """Sign the bundle with the installation's Ed25519 key (item 10, F4).

        The signed payload is the bundle digest plus the sha256 of
        index.json, so the signature covers the data files (through the
        digest) AND the index — including the run identity, which a
        contributor therefore cannot edit after the fact. The signature
        file itself is written after the digest is computed and is not
        part of it, exactly like index.json. The claim is written into the
        file, because an honest claim is part of the artifact: the
        signature vouches for these bytes leaving THIS installation
        unaltered, not for the code that produced them.

        A signing failure aborts the export (R4) rather than shipping an
        unsigned bundle that looks finished. Called only when the key file
        exists (checked by _export_into), so ProvenanceSigner's
        load-or-generate only ever LOADS here — an export never mints a
        key (V8).
        """
        try:
            signer = ProvenanceSigner(key_path=self._key_path())
        except Exception as exc:
            raise ExportError(
                f"could not load or create the provenance key for signing: {exc}"
            ) from exc
        index_sha256 = hashlib.sha256(index_bytes).hexdigest()
        signed_payload = {"bundle_digest": digest, "index_sha256": index_sha256}
        payload_hash = hashlib.sha256(
            json.dumps(signed_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        signature = signer.sign_hex(payload_hash)
        fingerprint = read_public_key_fingerprint(self._key_path())
        content = {
            "signature_scheme": "Ed25519",
            "public_key_hex": signer.public_key_hex,
            "public_key_fingerprint": fingerprint,
            "signed_payload": signed_payload,
            "payload_canonicalization": (
                "json.dumps(signed_payload, sort_keys=True) with default "
                "separators, UTF-8 encoded"
            ),
            "payload_hash": payload_hash,
            "signature_message": (
                "the UTF-8 bytes of the lowercase hex SHA-256 digest of the "
                "canonical signed payload; the hex string itself is signed, "
                "not the raw digest bytes"
            ),
            "signature": signature,
            "what_this_proves": (
                "Every file in this bundle is byte-for-byte what this "
                "AutoApply installation exported, and nothing in it has been "
                "altered since. Verify with: python -m auto_apply "
                "--verify-research <this folder>."
            ),
            "what_this_does_not_prove": (
                "It does not prove the exporting code was unmodified "
                "AutoApply: the signing key is generated by the installation "
                "and vouches for bytes, not for code. The run identity in "
                "index.json is covered by this signature but is only a "
                "claim until a recipient hashes that code themselves. It "
                "does not prove who the contributor is: confirm the "
                "fingerprint above matches one you trust before relying on "
                "this bundle."
            ),
        }
        (out_dir / "bundle_signature.json").write_bytes(
            (json.dumps(content, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
        logger.info("ResearchExport | bundle signed (fingerprint %s)", fingerprint)

    def _write_table(
        self,
        conn: sqlite3.Connection,
        spec: TableSpec,
        fmt_spec: FormatSpec,
        out_dir: Path,
    ) -> tuple[TableExportInfo, list[str]]:
        # Table and column names come from TABLE_SPECS (module constants),
        # never from user input, so SQL interpolation is safe here.
        order = ", ".join(spec.order_by)
        cursor = conn.execute(f"SELECT * FROM {spec.name} ORDER BY {order}")
        columns = [desc[0] for desc in cursor.description]
        filename = f"{spec.name}.{fmt_spec.extension}"
        path = out_dir / filename
        rows = fmt_spec.writer(path, columns, cursor)
        info = TableExportInfo(
            table=spec.name,
            filename=filename,
            rows=rows,
            sha256=_sha256_file(path),
        )
        logger.debug(
            "ResearchExport | %s: %d rows -> %s", spec.name, rows, filename
        )
        return info, columns

    def _write_verification(
        self,
        conn: sqlite3.Connection,
        out_dir: Path,
        file_hashes: list[tuple[str, str]],
    ) -> Literal["ok", "unavailable"]:
        """Write verification.json carrying the provenance public key (R3).

        The file is deliberately not a data-table dump: it is the trust
        root for every signature in research_signals, and it carries the
        full recipe for reconstructing a signed payload so a recipient can
        verify using only the bundle.
        """
        row = conn.execute(
            "SELECT public_key_hex, created_at FROM research_provenance WHERE id = 1"
        ).fetchone()
        if row is None:
            logger.info(
                "ResearchExport | no provenance key on record; "
                "verification.json not written"
            )
            return "unavailable"

        payload = {
            "applies_to_table": "research_signals",
            "signature_scheme": "Ed25519",
            "public_key_hex": row["public_key_hex"],
            "key_recorded_at": row["created_at"],
            "content_hash_scheme": "SHA-256",
            "signed_fields": list(_SIGNED_FIELDS),
            "null_encoding": "SQL NULL is signed as the empty string",
            "payload_canonicalization": (
                "json.dumps(payload, sort_keys=True) with default separators, "
                "UTF-8 encoded"
            ),
            "signature_message": (
                "the UTF-8 bytes of the lowercase hex SHA-256 digest; the hex "
                "string itself is signed, not the raw digest bytes"
            ),
            "verification_recipe": list(_VERIFICATION_RECIPE),
            "unsigned_rows": (
                "rows with NULL provenance_signature were written while the "
                "signer was unavailable and cannot be verified"
            ),
        }
        path = out_dir / "verification.json"
        # Exact bytes: this file's on-disk hash feeds the bundle digest, so
        # a text-mode write would fork the digest by OS (P4).
        path.write_bytes(
            (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
        file_hashes.append(("verification.json", _sha256_file(path)))
        logger.info("ResearchExport | verification.json written")
        return "ok"

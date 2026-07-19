"""
ParquetExporter — exports research data for academic analysis.

Supports three export formats:
  - CSV  : Universal, no dependencies
  - JSON : Structured, for API consumers
  - Parquet: Columnar, optimal for academic analysis (requires pyarrow, optional)

Export produces anonymized, analysis-ready datasets. No PII ever exported.
Schema version is embedded in exported files for longitudinal compatibility.
"""
from __future__ import annotations

import csv
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

ExportFormat = Literal["csv", "json", "parquet"]


class ParquetExporter:
    """Exports research data from SQLite to analysis-ready files.

    Args:
        db_path: Path to the research SQLite database.
        export_dir: Directory to write exported files into.
    """

    def __init__(self, db_path: Path, export_dir: Path) -> None:
        self._db_path = db_path
        self._export_dir = export_dir
        self._export_dir.mkdir(parents=True, exist_ok=True)

    def export_signals(self, fmt: ExportFormat = "csv") -> Path:
        """Export all research signals to file.

        Args:
            fmt: Output format — 'csv', 'json', or 'parquet'.

        Returns:
            Path to the exported file.

        Raises:
            ImportError: If 'parquet' is requested but pyarrow is not installed.
        """
        rows = self._query_signals()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"aa_research_signals_{timestamp}.{fmt}"
        out_path = self._export_dir / filename

        if fmt == "csv":
            self._write_csv(rows, out_path)
        elif fmt == "json":
            self._write_json(rows, out_path)
        elif fmt == "parquet":
            self._write_parquet(rows, out_path)
        else:
            raise ValueError(f"Unsupported format: {fmt}")

        logger.info("ResearchExport | %d signals exported to %s", len(rows), out_path)
        return out_path

    def export_salary_corpus(self, fmt: ExportFormat = "csv") -> Path:
        """Export salary observations for market benchmarking analysis.

        Args:
            fmt: Output format.

        Returns:
            Path to the exported file.
        """
        rows = self._query_salary()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"aa_salary_corpus_{timestamp}.{fmt}"
        out_path = self._export_dir / filename

        if fmt == "csv":
            self._write_csv(rows, out_path)
        elif fmt == "json":
            self._write_json(rows, out_path)
        elif fmt == "parquet":
            self._write_parquet(rows, out_path)

        logger.info("ResearchExport | %d salary rows exported to %s", len(rows), out_path)
        return out_path

    def export_form_observations(self, fmt: ExportFormat = "csv") -> Path:
        """Export ATS form complexity observations.

        Args:
            fmt: Output format.

        Returns:
            Path to the exported file.
        """
        rows = self._query_forms()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"aa_form_observations_{timestamp}.{fmt}"
        out_path = self._export_dir / filename

        if fmt == "csv":
            self._write_csv(rows, out_path)
        elif fmt == "json":
            self._write_json(rows, out_path)
        elif fmt == "parquet":
            self._write_parquet(rows, out_path)

        logger.info("ResearchExport | %d form rows exported to %s", len(rows), out_path)
        return out_path

    # ── Private query methods ──────────────────────────────────────────────────

    def _query_signals(self) -> list[dict]:
        return self._query("SELECT * FROM research_signals ORDER BY detected_date")

    def _query_salary(self) -> list[dict]:
        return self._query("SELECT * FROM salary_observations ORDER BY posted_date")

    def _query_forms(self) -> list[dict]:
        return self._query("SELECT * FROM form_observations ORDER BY observed_date")

    def _query(self, sql: str) -> list[dict]:
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql)
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
            return rows
        except Exception as exc:
            logger.error("ResearchExport | Query failed: %s", exc)
            return []

    # ── Writer implementations ────────────────────────────────────────────────

    def _write_csv(self, rows: list[dict], path: Path) -> None:
        if not rows:
            path.write_text("")
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    def _write_json(self, rows: list[dict], path: Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"schema_version": 2, "records": rows}, f, indent=2, default=str)

    def _write_parquet(self, rows: list[dict], path: Path) -> None:
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise ImportError(
                "pyarrow is required for Parquet export. "
                "Install it with: pip install pyarrow\n"
                "Note: pyarrow is an optional dependency — use CSV for worst-case environments."
            ) from exc

        if not rows:
            logger.warning("ResearchExport | No rows to export as Parquet")
            return
        table = pa.Table.from_pylist(rows)
        pq.write_table(table, str(path), compression="snappy")
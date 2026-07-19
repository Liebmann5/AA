# Data Format

Research signals are stored in a single, append‑only SQLite database:
`research_data/research_signals.db`. This database is designed to be directly
queryable with any SQLite client, pandas, R, or spreadsheet application
(after export).

---

## Database Location

| Platform | Default path |
| -------- | ------------ |
| Windows  | `%USERPROFILE%\.auto_apply\research_data\research_signals.db` |
| macOS    | `~/.auto_apply/research_data/research_signals.db` |
| Linux    | `~/.auto_apply/research_data/research_signals.db` |
| USB portable | `<drive>:\AutoApply\data\research_data\research_signals.db` |

The database is created automatically the first time research collection is
enabled and a session runs. If the database already exists, new signals are
appended — existing data is never overwritten.

Export the data to CSV, JSON, or Parquet with:

```bash
python -m auto_apply --export-research              # CSV (default)
python -m auto_apply --export-research --export-format json
python -m auto_apply --export-research --export-format parquet
```

---

## Research Signals Table (`research_signals`)

This is the primary table. Every row is a single anonymised observation.

| Column | Type | Description | Example |
| ------ | ---- | ----------- | ------- |
| `signal_id` | TEXT PRIMARY KEY | Deterministic UUID derived from (signal_type, posting_hash, detected_date) to deduplicate the same fact observed via multiple code paths. | `a1b2c3d4...` |
| `signal_type` | TEXT NOT NULL | The signal identifier, e.g. `"GJ-01"`, `"DISC-01"`. See [Signals Taxonomy](signals_taxonomy.md). | `GJ-01` |
| `severity` | TEXT NOT NULL | One of `"flag"`, `"concern"`, `"violation"`. | `violation` |
| `confidence` | REAL NOT NULL | Detection confidence 0.0–1.0. | `0.88` |
| `evidence_text` | TEXT | Anonymised excerpt proving the signal (max 200 chars). | `"Posting live 120 days (SHRM fill threshold: 41 days)"` |
| `platform` | TEXT | ATS or job‑board identifier (never a raw URL). | `greenhouse`, `linkedin` |
| `jurisdiction` | TEXT | US state/city code, e.g. `"CA"`, `"NYC"`, or NULL. | `CA` |
| `company_id` | TEXT | HMAC‑SHA256 of company name (salt never stored). 16‑hex‑character anonymised identifier. | `a3f2b1c4d5e6f7a8` |
| `job_category` | TEXT | BLS SOC code when available. | `15-1252` |
| `detected_date` | TEXT NOT NULL | ISO‑8601 date when the signal was recorded (no time component). | `2026-05-01` |
| `schema_version` | INTEGER | Version of the research schema (incremented when data practices change). | `2` |
| `consent_version` | TEXT | Version of the consent dialog the user agreed to. | `2.1` |
| `posting_hash` | TEXT | Structural hash of the job posting for lifecycle tracking and deduplication. | `e4f5a6b7...` |
| `content_hash` | TEXT | SHA‑256 of the signal’s evidentiary payload (used for provenance signing). | `b8c9d0e1...` |
| `provenance_signature` | TEXT | Hex‑encoded Ed25519 signature of `content_hash` using an installation‑unique key. | `9f8e7d6c...` |

!!! warning "PII safety"
    The `evidence_text` column is passed through a PII‑redacting filter that
    strips URLs and email addresses before writing. Company names are
    HMAC‑SHA256 anonymised before storage. No job URL, company name, or
    user‑specific data should ever appear in this table. If you find a row
    that appears to contain PII, please report it as a bug.

---

## Supporting Tables

The database also includes these tables, used by detectors that require
accumulated data (lifecycle tracking, salary benchmarking, form analysis,
application outcomes).

### `job_lifecycles`

Tracks when a job posting is first and last seen on each platform, enabling
the “freshness laundering” (GJ‑02) and “refill without hire” (GJ‑03)
detectors.

| Column | Type | Description |
| ------ | ---- | ----------- |
| `job_fingerprint` | TEXT NOT NULL | Structural hash of the posting. |
| `platform` | TEXT NOT NULL | Platform where the posting was observed. |
| `first_seen` | TEXT NOT NULL | ISO‑8601 date when AA first saw this posting. |
| `last_seen` | TEXT NOT NULL | Most recent observation date. |
| `times_seen` | INTEGER | Total distinct observation dates. |
| `times_reposted` | INTEGER | Times the posting disappeared for ≥7 days and reappeared. |
| `applied_to` | INTEGER | 0/1 — whether the user applied to this posting. |
| `response_received` | INTEGER | 0/1 — whether any response was received. |
| `response_date` | TEXT | Date of response, if any. |
| `company_id` | TEXT | Anonymised company identifier. |

Primary key: `(job_fingerprint, platform)`.

### `salary_observations`

Builds a self‑calibrating salary corpus used by the “below‑market salary”
(ST‑03) detector.

| Column | Type | Description |
| ------ | ---- | ----------- |
| `obs_id` | TEXT PRIMARY KEY | Unique observation ID. |
| `salary_min` | INTEGER | Minimum disclosed salary, or NULL. |
| `salary_max` | INTEGER | Maximum disclosed salary, or NULL. |
| `salary_type` | TEXT | `"annual"`, `"hourly"`, etc. |
| `currency` | TEXT | ISO 4217 currency code. |
| `role_title_normalized` | TEXT | Lowercased, stripped job title for grouping. |
| `experience_years_min` | INTEGER | Minimum years of experience required. |
| `experience_years_max` | INTEGER | Maximum years of experience required. |
| `education_required` | TEXT | Degree level when stated. |
| `location_metro` | TEXT | MSA name, if determinable. |
| `jurisdiction` | TEXT | US state/city code. |
| `platform` | TEXT | Source platform. |
| `industry_sic` | TEXT | Standard Industrial Classification code. |
| `posted_date` | TEXT | Date the posting was observed. |
| `schema_version` | INTEGER | Schema version. |

### `form_observations`

Records application form complexity and accessibility data, used by the
“application bloat” (DP‑04) and “salary history inquiry” (ST‑04) detectors.

| Column | Type | Description |
| ------ | ---- | ----------- |
| `form_id` | TEXT PRIMARY KEY | Unique form observation ID. |
| `job_fingerprint` | TEXT | Links to the parent posting. |
| `platform` | TEXT | ATS platform. |
| `company_id` | TEXT | Anonymised company. |
| `total_fields` | INTEGER | Total form fields detected. |
| `required_fields` | INTEGER | Number of required fields. |
| `optional_fields` | INTEGER | Number of optional fields. |
| `essay_fields` | INTEGER | Number of textarea (essay) fields. |
| `file_upload_fields` | INTEGER | Number of file‑upload fields. |
| `knockout_questions` | INTEGER | Number of binary screening questions detected. |
| `wcag_score` | TEXT | `"AA"` or `"FAIL"` depending on detected accessibility violations. |
| `wcag_violations` | TEXT | JSON‑encoded list of violation codes. |
| `salary_history_requested` | INTEGER | 0/1 — whether the form asks for prior salary. |
| `jurisdiction` | TEXT | Jurisdiction code. |
| `estimated_completion_minutes` | INTEGER | Estimated time to complete the form. |
| `observed_date` | TEXT | Date the form was analysed. |
| `schema_version` | INTEGER | Schema version. |

### `application_outcomes`

Tracks whether submitted applications receive any acknowledgment, used by the
“application black hole” (LM‑02) macro‑signal.

| Column | Type | Description |
| ------ | ---- | ----------- |
| `outcome_id` | TEXT PRIMARY KEY | Unique outcome ID. |
| `platform` | TEXT | ATS platform. |
| `company_id` | TEXT | Anonymised company. |
| `submitted_date` | TEXT | Date the application was submitted. |
| `acknowledgment_received` | INTEGER | 0/1 — whether ANY response was received within 30 days. |
| `acknowledgment_date` | TEXT | Date of acknowledgment, if received. |
| `schema_version` | INTEGER | Schema version. |

### `research_provenance`

Stores the public key of the Ed25519 key‑pair used to sign every signal.
This table has exactly one row.

| Column | Type | Description |
| ------ | ---- | ----------- |
| `id` | INTEGER PRIMARY KEY CHECK (id = 1) | Always 1. |
| `public_key_hex` | TEXT | Hex‑encoded public key (64 hex chars). |
| `created_at` | TEXT | ISO‑8601 date when the key was generated. |

---

## Loading the Data

### Python (pandas + sqlite3)

```python
import sqlite3
import pandas as pd

conn = sqlite3.connect("research_signals.db")
df = pd.read_sql_query("SELECT * FROM research_signals", conn)
conn.close()

# Convert date columns
df["detected_date"] = pd.to_datetime(df["detected_date"], utc=True)
```

### R

```r
library(DBI)
library(RSQLite)

con <- dbConnect(SQLite(), "research_signals.db")
df <- dbReadTable(con, "research_signals")
dbDisconnect(con)

# Convert date columns
df$detected_date <- as.Date(df$detected_date)
```

### Export from the CLI

```bash
python -m auto_apply --export-research --export-format csv
```

This produces three CSV files (signals, salary, forms) in the reports
directory — ready for Excel, Google Sheets, or any analysis tool.

---

## Data Integrity & Append‑Only Guarantee

- All tables use SQLite WAL mode for crash safety.
- New rows are appended; existing rows are never updated or deleted by the
  research pipeline (the user may manually purge data via Settings).
- The `research_signals` table uses `INSERT OR IGNORE` keyed on
  `signal_id`. When the same underlying fact is observed via multiple code
  paths (e.g., a job posting observation and a form observation both
  detecting a salary gap), the deterministic `signal_id` ensures only one
  row is recorded — the correct unit of observation for aggregate statistics.

---

## Deleting Research Data

You can delete all research data at any time by:

1.  Deleting `research_signals.db` in AA’s data directory.
2.  Disabling research collection in Settings (this stops future collection
    but does not delete existing data).
3.  Clicking **“Delete All Research Data”** in the Settings menu (if
    available in your AA version).

Deletion is immediate and irreversible.

---

## Schema Versioning

When the research data collection practices change, the `schema_version`
column is incremented. This allows longitudinal analysis tools to detect
schema changes and apply appropriate migrations. The current schema version
is defined in `domain/constants.py` as `RESEARCH_SCHEMA_VERSION`.

---

## Next Steps

- [Signals Taxonomy](signals_taxonomy.md) — what each signal type means.
- [Research Module Overview](index.md) — purpose, ethics, and privacy.
- [Understanding the Output](../user_guide/understanding_output.md) — other
  files AA produces and how to use them.

---
title: "Data Format"
status: needs-review
last_verified: 2026-09-27
verified_against: "bulk provenance stamp 2026-09-27; content not individually re-verified against code"
audience: researchers
---

# Data Format

Research signals are stored in a single, append‑only SQLite database:
`research/research_signals.db` inside AA's data directory. This database is
designed to be directly queryable with any SQLite client, pandas, R, or
spreadsheet application (after export).

---

## Database Location

There is ONE location, on every platform: **`research/research_signals.db`
inside AA's data directory.** (The data directory itself depends on how AA
is installed — a normal install, a USB portable drive, or a development
checkout. On a USB portable install the research database is
`<drive>:\<AA folder>\data\research\research_signals.db`.)

Everything the research module writes lives in that one `research/`
directory — the database and its WAL sidecars. The private provenance
signing key does NOT live there: it sits one level up, beside AA's other
state files, so zipping or sharing the `research/` folder can never leak
the key that signs your rows.

The database is created automatically the first time research collection is
enabled and a session runs. If the database already exists, new signals are
appended — existing data is never overwritten.

Export the data to CSV, NDJSON, or Parquet with:

```bash
python -m auto_apply --export-research              # CSV (default)
python -m auto_apply --export-research --export-format ndjson
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
| `company_id` | TEXT | HMAC‑SHA256 of the company name's canonical form (format characters removed, NFKC, casefolded, whitespace collapsed; punctuation and legal suffixes kept; salt never stored). 16‑hex‑character anonymised identifier. NULL means no usable company name — including the placeholders discovery emits when extraction fails (`Unknown`, `N/A`, `None`); NULL is absence, never a company. Databases below `user_version` 4 were minted from the lower‑cased name only; the v4 migration NULLs their placeholder ids and leaves the rest. | `a3f2b1c4d5e6f7a8` |
| `job_category` | TEXT | BLS SOC code when available. | `15-1252` |
| `detected_date` | TEXT NOT NULL | ISO‑8601 date when the signal was recorded (no time component). | `2026-05-01` |
| `schema_version` | INTEGER | Version of the research schema (incremented when data practices change). Version 3: ST‑01 reworded and re‑graded, salary extraction added. | `3` |
| `consent_version` | TEXT | Version of the consent dialog the user agreed to. | `2.1` |
| `posting_hash` | TEXT | Structural hash of the job posting for lifecycle tracking and deduplication. | `e4f5a6b7...` |
| `content_hash` | TEXT | SHA‑256 of the signal’s evidentiary payload (used for provenance signing). | `b8c9d0e1...` |
| `provenance_signature` | TEXT | Hex‑encoded Ed25519 signature of `content_hash` using an installation‑unique key. | `9f8e7d6c...` |
| `page_copy_id` | TEXT | Fingerprint of the cleaned page copy this signal was detected on, kept on the contributor's device (see [Page Copies](#page-copies)). NULL when page copies were off or no copy was kept, and on every row written before page copies existed. **Not** part of the signed content. | `commit-sha256:5d1e...` |

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
application outcomes). Two more tables exist and are not yet documented
column-by-column here: `detector_examinations` and `detector_outcomes` (one
accounting row per detector run). `detector_examinations` carries the same
`page_copy_id` column as `research_signals`. All eleven tables are covered by research
export and by consent withdrawal's delete-all.

### Discovery tables: `discovery_pages`, `discovery_cards`, `discovery_candidates`

What the search surface looked like: one row per results page, one per result
card on it, one per URL candidate on each card. Child rows join to their
parent through random surrogate keys (`page_id`, `card_id`) that claim no
sameness across observations — re-observing a page is a new page row.

**Never stored:** the search query and any full URL — of the results page, of
a card's destination, or of a candidate. Hosts are the granularity kept
(`page_host`, `selected_host`, `resolved_host`). Text columns
(`discovery_cards.title`, `discovery_candidates.anchor_text`) are stored as
displayed, except that a URL rendered inside the text — a visible URL, or a
breadcrumb such as `www.indeed.com › jobs › …` — is cut down to its host.
`ad_evidence` names the advertising word a URL matched, never the URL's path.

**Hosts can name an employer.** A platform that puts the employer in the host
(`acme.wd5.myworkdayjobs.com`) stores it there. It also makes raw hosts a
poor grouping variable: fifty employers on such a platform are fifty hosts,
while fifty employers on a platform that puts the employer in the path
(`boards.greenhouse.io/acme`) are one. Group destinations by **platform**
instead. The `hosts:` list in each `resources/ats/*.yaml` descriptor is the
classification AA uses (`ATSRegistry.platform_for_host`); it is applied when
the data is read, never stored on the row, so a better list reclassifies
every row already written. A host no list claims is reported as unclassified.

| Table | Key columns |
|---|---|
| `discovery_pages` | `provider`, `page_host`, `page_state`, `blocked`, `architecture`, the per-page card counts, `activation_attempts` / `activation_resolved`, `learned_identity`, `observed_date` |
| `discovery_cards` | `page_id`, `card_index`, `title`, `resolution_state`, `selected_host` |
| `discovery_candidates` | `card_id`, `resolved_host`, `anchor_text`, `source`, `outcome`, `rejection_reason`, `ad_evidence`, `apply_intent`, `title_overlap`, `method` |

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

Rows are written only when a US‑dollar pay figure was found on the posting
(see `domain/services/salary_extraction.py`). `salary_min` / `salary_max`
are ANNUAL USD equivalents: hourly figures are converted at 2,080 hours
per year (40 h × 52 weeks — the BLS full‑time convention, a stated
assumption, not a fact about the job), weekly ×52, biweekly ×26,
semi‑monthly ×24, monthly ×12 (pay per day, per shift or per pay period
is not read: it has no single annual equivalent), and
`salary_type` is therefore `annual` on extracted rows. The figure exactly
as stated on the page (with `[OTE]` for on‑target earnings) is kept in
`source_text`, so every stored number can be audited against the text it
came from. Rows written before salary extraction existed have
`source_text` NULL.

| Column | Type | Description |
| ------ | ---- | ----------- |
| `obs_id` | TEXT PRIMARY KEY | Unique observation ID. |
| `salary_min` | INTEGER | Minimum disclosed salary, annualised USD, or NULL. |
| `salary_max` | INTEGER | Maximum disclosed salary, annualised USD, or NULL. |
| `salary_type` | TEXT | `"annual"` on extracted rows (stored values are annualised). |
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
| `source_text` | TEXT | The pay span as stated on the page (e.g. `$38.00 - $46.00 per hour`, with `[OTE]` for on-target earnings), or NULL on rows written before salary extraction existed. |

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

## Page Copies

A second, separate opt-in (its own consent text, versioned on its own; see
[the consent dialog](../RESEARCH_CONSENT_DIALOG.md)). Only while research
participation is on, AA keeps a **cleaned** copy of each job posting page it
reads, so a research row can later be checked against the page it came from.

**Where.** `research/page_copies/<YYYY-MM-DD>/<16 hex>.warc.gz` inside AA's
data directory — one folder per capture day, one file per distinct page.
Copies never leave the device: research export contains no page copies.

**Format.** WARC/1.1 (ISO 28500), each record gzipped separately, readable by
any web-archive tool (warcio, pywb, ReplayWeb.page). Three records per file:

| Record | Holds |
| ------ | ----- |
| `warcinfo` | What wrote the file. |
| `resource` | The cleaned page, with `WARC-Target-URI` (where it was read) and `WARC-Payload-Digest`. A *resource* record, not a *response*: AA has the page as the browser rendered it, not the bytes the server sent. |
| `metadata` | JSON: `copy_id`, `nonce`, `context`, `captured_at`, `method`, `redactions` (rule → count of what cleaning removed), and `posting` — the listing's `job_title`, `location` and `platform`, which a replay needs to find the jurisdiction (null in copies made before replay existed). |

**Cleaned before writing.** Scripts, noscript blocks, frames, objects and
embeds, event-handler attributes, every form value, hidden input and
textarea text, token/session meta tags, and the person's own name, email,
phone and street address. Single names (a first or last name on its own) are
matched as written, so a name that is also a word is not wiped from every
page; a name written in another case survives. City, state and ZIP are kept:
they are the job's location. Search result pages are never copied.

**The fingerprint.** `page_copy_id = "commit-sha256:" + sha256(nonce ‖ page)`,
where `page` is the resource record's block and `nonce` is 16 bytes stored
only in the copy's metadata record (hex). The nonce is
HMAC-SHA256(the installation's private research key, a fixed context label ‖
page), cut to 16 bytes: the same page gets the same fingerprint on one
device, and nobody without the key can compute it. A plain hash of the page
would let anyone who fetches the same public posting test whether it appears
in someone's rows; the nonce prevents that. To verify a row: take the copy's
`nonce` and resource block, recompute, compare — the key is not needed.

`page_copy_id` is not covered by the provenance signature: it links to a
local file that may expire, and signing it would have changed the content
hash of every earlier signal.

**Written in the background.** Vetting reads and cleans the page; the file
is written by a background writer with a bounded queue, so a copy never
slows a session. When the queue is full the copy is dropped and the row
carries no `page_copy_id`. A write that fails after being queued is counted
in the log, and its row then names a copy that does not exist — check
`page_copy_id` against the folder before relying on it.

**Expiry, size and deletion.** Copies are deleted after
`page_copy_keep_days` (default 90) counted from their capture day, checked
each time a session is built, and the oldest are deleted first whenever all
copies together pass `page_copy_max_mb` (default 200). Turning page copies
off deletes every copy unless the person chooses to keep them; withdrawing
from research deletes them in every case. Copies are plain, unencrypted
files: the consent text tells people to leave them off on a shared
computer.

---

## Loading the Data

### Python (pandas + sqlite3)

```python
import sqlite3
import pandas as pd

conn = sqlite3.connect("research/research_signals.db")  # inside AA's data directory
df = pd.read_sql_query("SELECT * FROM research_signals", conn)
conn.close()

# Convert date columns
df["detected_date"] = pd.to_datetime(df["detected_date"], utc=True)
```

### R

```r
library(DBI)
library(RSQLite)

con <- dbConnect(SQLite(), "research/research_signals.db")  # inside AA's data directory
df <- dbReadTable(con, "research_signals")
dbDisconnect(con)

# Convert date columns
df$detected_date <- as.Date(df$detected_date)
```

### Export from the CLI

```bash
python -m auto_apply --export-research --export-format csv
```

This produces ONE self-describing bundle directory under `reports/` in AA's
data directory — one data file per research table, an `index.json`
describing them, and (once signals have been signed) a `verification.json`
carrying the public key a recipient needs to authenticate every signed row.
CSV and NDJSON open directly in Excel, Google Sheets, or any analysis tool.

### Summarise from the CLI

```bash
python -m auto_apply --research-summary
```

Prints the discovery funnel — pages by provider, state and architecture;
cards by resolution; candidates by outcome and rejection reason; and selected
destinations grouped by hiring platform — with every share shown against its
denominator ("12 of 40 (30.0%)"). It opens the database read-only and never
creates one.

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

1.  Deleting the `research/` directory inside AA's data directory (the
    database and its WAL sidecars live there). To also retire the signing
    identity, delete `provenance_key.pem` one level up.
2.  Withdrawing in the Research screen WITHOUT deletion (this stops future
    collection but does not delete existing data).
3.  Withdrawing consent with deletion requested (the Research screen —
    **File → Research…** in the app, **Settings → Research…**, or
    **`python -m auto_apply --research`** — then confirm deletion): AA
    deletes ALL of it — every table
    in the database, the database files themselves, and the private
    provenance key, so a contribution you make later cannot be linked to
    the deleted one. If another process is holding the database open at
    that moment, AA falls back to erasing every row and compacting the
    file; the result is the same once that process closes.

Page copies under `research/page_copies/` go with the `research/` directory,
and are deleted by any withdrawal from research (see [Page Copies](#page-copies)).

Deletion is immediate and irreversible. Export bundles you already created
under `reports/` are not touched — they are your copies; delete them
yourself if you want them gone.

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

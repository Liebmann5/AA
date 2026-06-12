# Data Format

Research signals are stored in a single, append‑only CSV file:
`research_data/hiring_signals.csv`. This file is designed to be directly
importable into pandas, R, or any spreadsheet application, with no
pre‑processing required.

---

## File Location

| Platform | Default path |
| -------- | ------------ |
| Windows  | `%USERPROFILE%\.auto_apply\research_data\hiring_signals.csv` |
| macOS    | `~/.auto_apply/research_data/hiring_signals.csv` |
| Linux    | `~/.auto_apply/research_data/hiring_signals.csv` |
| USB portable | `<drive>:\AutoApply\data\research_data\hiring_signals.csv` |

The file is created automatically the first time research collection is
enabled and a session runs. If the file already exists, new signals are
appended — existing data is never overwritten.

---

## CSV Schema

The file contains 14 columns. Every cell is a string (including numeric
fields — they are stored as text to avoid floating‑point precision issues
across different CSV parsers).

| Column | Type | Description | Example |
| ------ | ---- | ----------- | ------- |
| `timestamp_utc` | ISO‑8601 string | When the signal was recorded, in UTC. | `2026-05-01T14:32:00` |
| `session_id` | string | Anonymous UUID for the session. Changes every session; cannot be linked to a user across sessions. | `a1b2c3d4` |
| `signal_type` | string | The enum name from `ResearchSignalType` (see [Signals Taxonomy](signals_taxonomy.md)). | `ENTRY_LEVEL_EXPERIENCE_REQUIRED` |
| `category` | string | Broad research category. | `seniority` |
| `platform_type` | string | Normalised ATS or job board identifier, extracted from the URL domain. The URL itself is never stored. | `greenhouse`, `lever`, `indeed`, `unknown` |
| `job_tier_listed` | string | The seniority tier implied by the job title. | `entry`, `mid`, `senior`, `manager`, `unknown` |
| `job_tier_actual` | string | The seniority tier implied by the description content. May differ from `job_tier_listed`. | `senior` |
| `years_required` | string (or empty) | Minimum years of experience explicitly stated in the description. Empty if not specified. | `3` |
| `ats_present` | string | Whether an ATS was detected during the application. | `yes`, `no`, `unknown` |
| `ats_disclosed` | string | Whether the job posting mentioned the use of an ATS. | `yes`, `no`, `unknown` |
| `response_type` | string | The outcome of the application attempt, if known. | `submitted`, `failed`, `rejected`, `unknown` |
| `form_field_type` | string | For form‑anomaly signals, the type of field that caused the conflict. Empty otherwise. | `dropdown`, `checkbox`, `text` |
| `detail_code` | string | Short machine‑readable tag. No free text, no URLs, no email addresses. Sanitised before writing. | `title_description_mismatch` |
| `notes` | string | Optional human‑readable annotation. Sanitised to remove any residual PII. | `Job title: Engineer; desc: Senior` |

!!! warning "PII safety"
    The `detail_code` and `notes` columns are passed through a sanitisation
    function that strips URLs (`https://...` → `[url]`) and email addresses
    (`user@domain.com` → `[email]`). They are then truncated to 80 characters.
    No job URL, company name, or user‑specific data should ever appear in
    these columns. If you find one that does, please report it as a bug.

---

## Example Row

```csv
2026-05-01T14:32:00,sess_a1b2c3d4,ENTRY_LEVEL_EXPERIENCE_REQUIRED,seniority,greenhouse,entry,mid,3,yes,no,failed,,,, 
```

This row says: on 1 May 2026, AA observed a job on Greenhouse that was listed
as “Entry Level” but required 3 years of experience. The ATS was present but
not disclosed in the posting. The application failed.

---

## Loading the Data

### Python (pandas)

```python
import pandas as pd

df = pd.read_csv("hiring_signals.csv")

# Convert timestamp to datetime
df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)

# Convert years_required to numeric (empty → NaN)
df["years_required"] = pd.to_numeric(df["years_required"], errors="coerce")

df.head()
```

### R

```r
library(readr)

df <- read_csv("hiring_signals.csv",
               col_types = cols(
                 timestamp_utc = col_datetime(),
                 session_id = col_character(),
                 signal_type = col_character(),
                 category = col_character(),
                 platform_type = col_character(),
                 job_tier_listed = col_character(),
                 job_tier_actual = col_character(),
                 years_required = col_integer(),
                 ats_present = col_character(),
                 ats_disclosed = col_character(),
                 response_type = col_character(),
                 form_field_type = col_character(),
                 detail_code = col_character(),
                 notes = col_character()
               ))

head(df)
```

### Spreadsheet Applications

Open `hiring_signals.csv` directly in Excel, Google Sheets, or LibreOffice
Calc. The CSV uses UTF‑8 encoding and commas as delimiters. Date columns
may need to be formatted as date/time after import.

---

## Analysis Examples

### 1. How often do "entry‑level" jobs require experience?

```python
entry_signals = df[df.signal_type == "ENTRY_LEVEL_EXPERIENCE_REQUIRED"]
total_applications = df[df.response_type == "submitted"].shape[0]

pct = (entry_signals.shape[0] / total_applications) * 100 if total_applications > 0 else 0
print(f"Entry‑level experience required in {pct:.1f}% of applications")
```

### 2. What is the most common platform where logic conflicts occur?

```python
conflicts = df[df.signal_type == "FORM_LOGIC_CONFLICT"]
platform_counts = conflicts["platform_type"].value_counts()
print(platform_counts.head())
```

### 3. What fraction of applications result in no response (ghosting)?

```python
ghosted = df[df.signal_type == "ATS_NO_RESPONSE"]
total = df[df.response_type != "unknown"].shape[0]
ghost_rate = ghosted.shape[0] / total if total > 0 else 0
print(f"Ghosting rate: {ghost_rate:.1%}")
```

### 4. Are companies more likely to disclose salary ranges on certain platforms?

```python
salary = df[df.signal_type == "SALARY_RANGE_DISCLOSED"]
platform_disclosure = salary["platform_type"].value_counts(normalize=True)
print(platform_disclosure)
```

### 5. Time‑series: Are certain signals becoming more or less common?

```python
df["month"] = df["timestamp_utc"].dt.to_period("M")
monthly = df.groupby(["month", "category"]).size().unstack(fill_value=0)
monthly.plot(kind="line", figsize=(10, 6))
```

---

## Data Integrity & Append‑Only Guarantee

- The CSV header is written exactly once, when the file is first created.
- Each new signal is appended as a single row at the end of the file.
- A background writer thread handles all disk I/O, so the main agent loop is
  never blocked by research data writes.
- If the process crashes mid‑write, the partial row may be incomplete, but
  the previous rows remain intact. The partial row can be identified by
  counting the expected number of columns.
- The file is a plain CSV with no locking — it can be read by another
  application while AA is running. For safety, copy the file before analysing
  it if you need a consistent snapshot.

---

## Deleting Research Data

You can delete all research data at any time by:

1.  Deleting the `research_data/` folder in AA’s data directory.
2.  Disabling research collection in Settings (this stops future collection
    but does not delete existing data).
3.  Clicking “Delete All Research Data” in the Settings menu (if available
    in your AA version).

Deletion is immediate and irreversible.

---

## Next Steps

- [Signals Taxonomy](signals_taxonomy.md) — what each signal type means.
- [Research Module Overview](index.md) — purpose, ethics, and privacy.
- [Understanding the Output](../user_guide/understanding_output.md) — other
  files AA produces and how to use them.
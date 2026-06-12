# Research Module

AutoApply is not just a job‑hunting tool. It is also a **research instrument**
designed to study and document the modern hiring market — from the candidate’s
perspective.

The Research Module is a passive, consent‑gated observer. It records
anonymised, structured signals about the hiring practices AA encounters during
its normal operation. If a million people run AA, we will have the largest
candidate‑side dataset on hiring behaviour ever assembled — and every single
row of that dataset will be free of personally identifiable information.

This section explains what the module collects, why it exists, and how your
privacy is guaranteed by design.

---

## Why This Exists

Most research about hiring uses **employer‑side data** — ATS vendor analytics,
HR surveys, LinkedIn recruiter data. That research answers questions like
“which sourcing channel produces the most applicants?”

AA’s research module answers different questions:

- How often do “entry‑level” postings demand multiple years of experience?
- What fraction of companies disclose salary ranges?
- How frequently do application forms present illogical conflicts?
- Which ATS platforms are most common in which industries?
- How long does the average application take to complete?

These are questions with genuine public‑interest value. The data is designed
to be **publishable** — uniform across all contributors, structured for
standard statistical analysis, and completely anonymous.

---

## The Five Design Principles

Every aspect of the research module is governed by five non‑negotiable
principles. These are encoded in the module’s architecture and cannot be
bypassed.

### 1. Consent First, Always

Research collection is **opt‑in only**. It is disabled by default. No data is
ever collected without an explicit, recorded consent from the user. You enable
it by setting `enable_research_collection: true` in your profile. You can
disable it at any time, and existing data is not deleted unless you
explicitly request deletion.

An administrator may also disable research collection via
`aa_policy.json` (`disable_research_collection: true`). In that case, the
opt‑in toggle in the user interface is locked and the user cannot enable it.

### 2. Zero Personal Data

The research collector **never** records:

- Job URLs (which could identify a user’s browsing pattern)
- Company names (which could identify geography or industry preference)
- User names, emails, resume details, or any profile data
- IP addresses or network information
- Timestamps at a granularity that could correlate to a specific user

A signal says *“a title/description seniority mismatch was observed”* — not
*“Alice applied to Google and the job title said Junior but required Senior
experience.”*

### 3. Passive Observation Only

The collector is a pure **EventBus subscriber**. It listens to events that
the rest of the system already publishes — `APPLICATION_SUBMITTED`,
`JOB_VETTED_FAIL`, `CAPTCHA_DETECTED`, etc. — and extracts anonymised
signals from the payloads. It never calls into domain engines, never
navigates the browser, and never adds latency to the main loop. All disk
writes happen on a background daemon thread via a queue.

If the collector crashes, the agent continues without interruption. Research
is a passenger, not a driver.

### 4. Research‑Grade Uniformity

Every contributor records the same signal types with the same schema. There
is no per‑user variation in the data format. This satisfies the randomisation
requirement for valid statistical analysis: the dataset is identically
structured across all contributors, regardless of their profile
configuration or hardware tier.

### 5. Non‑Blocking by Design

The EventBus delivers signals synchronously on the publishing thread. The
collector only calls `queue.put_nowait()` — never writes to disk on the
hot path. All file I/O happens on the background writer thread. If the queue
fills up, signals are dropped rather than blocking the agent. Research
collection cannot slow down or crash a session.

---

## What Is Collected

The module records **21 standardised signal types** across seven categories:

| Category | What it tracks |
| -------- | -------------- |
| **Seniority** | Title/description mismatches, undisclosed levels, “entry‑level” jobs requiring experience, manager‑heavy postings. |
| **ATS Process** | Rapid rejections, ghosting (no response), undisclosed ATS usage, opt‑out offered. |
| **Hidden Gating** | Requirements revealed only in forms, dropdown gates, numeric gates. |
| **Form Design** | Logic conflicts, Yin‑Yang binary traps. |
| **Compensation** | Deceptive unpaid postings. |
| **Friction** | No direct contact info, auth walls mid‑application, excessive CAPTCHAs. |
| **Early Career** | Internships restricted to current students, unpaid internships. |
| **Positive** | Inclusive language, salary range disclosed, transparent process described. |

The **Positive** category is deliberate. The goal is not to compile a list of
company failures — it is to understand the distribution of hiring practices.
Companies doing things right are equally important data points.

The complete signal catalogue with detailed descriptions is in
[Signals Taxonomy](signals_taxonomy.md).

---

## What the Data Looks Like

Signals are written to `research_data/hiring_signals.csv` in AA’s data
directory. The file is a standard CSV with 14 columns:

```
timestamp_utc, session_id, signal_type, category, platform_type,
job_tier_listed, job_tier_actual, years_required, ats_present,
ats_disclosed, response_type, form_field_type, detail_code, notes
```

Every field is categorical (e.g. `platform_type = "greenhouse"`),
boolean/numeric aggregate (e.g. `years_required = 3`), or a short machine‑
readable code. No field contains a URL, company name, job title, or user
name. The `detail_code` and `notes` fields are sanitised by a regex that
strips URLs and email addresses before they are written.

The CSV is designed to be directly importable into pandas, R, or any
standard data analysis tool:

```python
import pandas as pd
df = pd.read_csv("hiring_signals.csv")
df[df.category == "seniority"].groupby("signal_type").size()
```

Full schema details are in [Data Format](data_format.md).

---

## Privacy Guarantees

### What AA guarantees

- Research data **never leaves your device** unless you explicitly export and
  share it.
- The data contains **no personally identifiable information** — not your
  name, email, IP address, or specific job URLs.
- Company names are **never recorded** — only ATS platform types
  (`"greenhouse"`, `"lever"`, etc.) which are extracted from URL domains
  and immediately discarded.
- The **session ID** is a random UUID that changes every session. It cannot
  be linked to your identity across sessions.
- You can **delete all research data** at any time via the Settings menu or
  by deleting the `research_data/` folder.
- An **admin policy** can globally disable research collection, overriding
  any user opt‑in.

### What AA cannot guarantee

- If you **manually export** the CSV and upload it somewhere, AA no longer
  controls that copy. Be mindful of where you share it.
- The **presence** of research data on your device may indicate that you used
  AA, if someone gains access to your filesystem. Encrypt your profile and
  use a master password to protect your AA data directory.

---

## How to Enable or Disable

=== "GUI"

    1. Open **Settings** → **Safety & Throttling**.
    2. Check or uncheck **“Contribute Anonymized Research Data.”**
    3. Click **Save Changes**.

    The setting takes effect on the next session.

=== "CLI"

    Edit your profile JSON directly:
    ```json
    "app_config": {
        "enable_research_collection": true
    }
    ```

=== "Admin Policy"

    An administrator can permanently disable research collection for all
    users on a device by adding to `aa_policy.json`:
    ```json
    {
        "disable_research_collection": true
    }
    ```

    When this is set, the user’s opt‑in toggle is locked and research
    collection cannot be enabled.

---

## Contributing Data to the Public Dataset

The long‑term vision is to aggregate anonymised signals from consenting
users into a **public research dataset**. This dataset will be:

- Hosted on a public repository (e.g. Kaggle, Hugging Face Datasets).
- Licensed under Creative Commons (CC‑BY‑SA or similar).
- Accompanied by a data dictionary and methodology document.
- Updated on a regular cadence (e.g. quarterly).

If you would like to contribute your data to the public dataset, you can
export your `hiring_signals.csv` and submit it via the project’s contribution
channel (to be announced). Contributions are voluntary, anonymous, and
irreversible — once data is published, it cannot be retracted. Only share
what you are comfortable making public.

---

## For Researchers

If you are an academic researcher interested in using AA’s data for your own
studies, please review:

- [Signals Taxonomy](signals_taxonomy.md) — the complete list of recorded
  observations and what they mean.
- [Data Format](data_format.md) — the CSV schema, data types, and analysis
  examples.
- [Architecture Deep Dive](../architecture/index.md) — how the research
  module integrates with the rest of AA.

For collaboration inquiries, open an issue on
[GitHub](https://github.com/Liebmann5/AA/issues) with the “research” label.

---

## Ethics Statement

AutoApply is built on the belief that the hiring process is broken and that
transparency is the first step toward fixing it. The research module is our
attempt to provide that transparency — not by shaming individual companies,
but by documenting the systemic patterns that affect millions of job seekers.

We commit to:

- **Never monetising research data.** It will always be free and open.
- **Never collecting data without consent.** Opt‑in is the only path.
- **Never storing personally identifiable information** in research records.
- **Never using research data to train proprietary models** or to build
  commercial products.
- **Always providing a clear, simple way to delete all research data.**

If you believe these commitments have been violated, please report it
immediately via [GitHub Issues](https://github.com/Liebmann5/AA/issues).

---

## Next Steps

- [Signals Taxonomy](signals_taxonomy.md) — every signal type explained in
  detail.
- [Data Format](data_format.md) — CSV schema, data dictionary, and analysis
  examples.
- [Profiles & Privacy](../user_guide/profiles_and_privacy.md) — how to
  protect your AA data with encryption and external storage.
---
title: "Research Module"
status: needs-review
last_verified: 2026-09-27
verified_against: "bulk provenance stamp 2026-09-27; content not individually re-verified against code"
audience: researchers
---

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
it by granting consent through the Settings → Research dialog. You can disable
it at any time, and existing data is not deleted unless you explicitly
request deletion.

An administrator may also disable research collection via
`aa_policy.json` (`disable_research_collection: true`). In that case, the
opt‑in toggle in the user interface is locked and the user cannot enable it.

### 2. Zero Personal Data

The research module **never** records:

- Job URLs (which could identify a user’s browsing pattern)
- Your search queries and full web addresses (URLs). A web address shown
  inside a link text is cut down to its host before it is stored.

One honest qualification: in **signal** rows, employer names exist only as an
irreversible anonymous code. But job titles, link texts and destination hosts
on result pages are recorded exactly as displayed (see “What Is Collected”),
and those may include employer names — `acme.myworkdayjobs.com` names its
employer. A results page that repeats your search words in a title or link
text (a listing called “20 Python jobs in Sacramento”) is recorded as shown
too. If that is more than you want recorded, do not opt in.
- User names, emails, resume details, or any profile data
- IP addresses or network information
- Timestamps at a granularity that could correlate to a specific user

A signal says *“a title/description seniority mismatch was observed”* — not
*“Alice applied to Google and the job title said Junior but required Senior
experience.”*

### 3. Passive Observation Only

The research pipeline is a pure **queue‑plus‑daemon‑thread** system.
Workflows push observations into the `ResearchSignalAggregator` via the
`ResearchObserverPort`; detection and persistence happen on a background
thread. The main agent loop is never blocked by research I/O.

If the aggregator crashes, the agent continues without interruption. Research
is a passenger, not a driver.

### 4. Research‑Grade Uniformity

Every contributor records the same signal types with the same schema. There
is no per‑user variation in the data format. This satisfies the randomisation
requirement for valid statistical analysis: the dataset is identically
structured across all contributors, regardless of their profile
configuration or hardware tier.

### 5. Non‑Blocking by Design

Workflows call `observe_job_posting()`, `observe_form()`, and
`observe_application_outcome()` only after wrapping calls in `try/except`.
All I/O happens on the background writer thread. If the queue fills up,
signals are dropped rather than blocking the agent. Research collection
cannot slow down or crash a session.

---

## How It Works (Technical)

When the user has consented and the composition root wires a live
`ResearchSignalAggregator` (instead of `NullResearchObserver`), the
pipeline operates as follows:

1. **Workflows observe** — Discovery, Vetting, and Applications workflows
   call `observe_job_posting()`, `observe_form()`, and
   `observe_application_outcome()` on the injected `ResearchObserverPort`.

2. **Aggregator enqueues** — The aggregator builds a `DetectionContext` from
   the observation, runs the **29 signal detectors** (pure Python, no I/O),
   and pushes resulting `ResearchSignal` objects onto an internal queue.

3. **Daemon thread writes** — A background daemon thread drains the queue
   and writes all signals to a **SQLite database** in a single transaction
   per batch.

4. **Provenance signing** — Every signal’s content is hashed (SHA‑256) and
   signed with an installation‑unique Ed25519 key. The public key is stored
   in the database so third‑party verifiers can authenticate the data.

The SQLite database also includes these supporting tables:

- `job_lifecycles` — tracks posting freshness and cross‑platform reposting
- `salary_observations` — builds a salary corpus for benchmarking
- `form_observations` — records ATS form complexity and accessibility violations
- `application_outcomes` — tracks whether applications receive any response (black‑hole detection)
- `discovery_pages` / `discovery_cards` / `discovery_candidates` — what the
  discovery surface looked like, page by page
- `detector_examinations` / `detector_outcomes` — one accounting row per
  detector run (the denominator behind every rate)
- `research_provenance` — the public half of this installation's signing key

All tables live in one file: `research/research_signals.db` inside AA's
data directory.

---

## What Is Collected

The module records **29 standardised signal types** across eight categories:

| Category | What it tracks |
| -------- | -------------- |
| **Ghost Jobs (GJ)** | Posting age anomalies, freshness laundering, refill‑without‑hire, Apply‑with‑no‑ATS, earnings‑season clustering |
| **Discrimination (DISC)** | Gendered language, age proxies, disability screening, socioeconomic proxy, geographic pay discrimination, intersectional discrimination |
| **Qualification Stacking (QS)** | Experience impossibility, entry‑level contradictions, degree inflation, salary‑skills mismatch, impossible skills combinations |
| **Salary Transparency (ST)** | Legal salary non‑disclosure, range washing, below‑market salary, salary history inquiries |
| **Dark Patterns (DP)** | Title‑description mismatch, toxic culture obfuscation, unpaid labor extraction, application bloat, phantom company detection |
| **Regulatory (RC)** | WARN Act violations, non‑compete illegality, unpaid internship FLSA violations |
| **AI Hiring Bias (AH)** | ATS knockout‑question threshold analysis, readability/complexity asymmetry |
| **Labor Market Macro (LM)** | Sector opening‑to‑application ratio, application black‑hole mapping, geographic pay compression by demographics |

The **Positive** category from earlier documentation is now embedded:
`SALARY_RANGE_DISCLOSED`, `INCLUSIVE_LANGUAGE_DETECTED`, and
`TRANSPARENT_PROCESS_DESCRIBED` detectors exist as positive signals.

The complete signal catalogue with detailed descriptions is in
[Signals Taxonomy](signals_taxonomy.md).

---

## What the Data Looks Like

Signals are written to `research/research_signals.db` inside AA's data
directory — the single home of everything the module collects. The database
can be exported to CSV, NDJSON, or Parquet via
`python -m auto_apply --export-research`.

The `research_signals` table has 16 columns covering signal metadata,
evidence text, jurisdiction, platform, company anonymization, provenance
signing, schema versioning, and the fingerprint of the page copy a signal was
detected on.

If you separately turn on **page copies**, AA also keeps a cleaned copy of
each job posting page it reads — on this device only, as a standard WARC
file, deleted after 90 days — so research rows can be checked against the
pages they came from. Your own details, form values and scripts are removed
before anything is written; search pages are never kept. See
[Page Copies](data_format.md#page-copies).

Full schema details are in [Data Format](data_format.md).

---

## Privacy Guarantees

### What AA guarantees

- Research data **never leaves your device** unless you explicitly export and
  share it.
- The data contains **no personally identifiable information** — not your
  name, email, IP address, or specific job URLs.
- In signal rows, company names are stored only as an irreversible anonymous
  code (HMAC with a private per-installation salt). Job titles, link texts
  and destination hosts from result pages are stored as displayed and may
  name employers — the consent dialog says so explicitly, in the list of
  what IS collected.
- The **session ID** is a random UUID that changes every session. It cannot
  be linked to your identity across sessions.
- You can **delete all research data** at any time via the Settings menu or
  by deleting the `research/` directory inside AA's data directory.
- An **admin policy** can globally disable research collection, overriding
  any user opt‑in.

### What AA cannot guarantee

- If you **manually export** the database and upload it somewhere, AA no
  longer controls that copy. Be mindful of where you share it.
- The **presence** of research data on your device may indicate that you used
  AA, if someone gains access to your filesystem. Encrypt your profile and
  use a master password to protect your AA data directory.

---

## How to Enable or Disable

=== "GUI"

    *(The Research screen arrives with the GUI/CLI consent change that
    follows the consent backend; until then there is no GUI control.)*

    1. Open **Settings** → **Research**.
    2. Read the consent dialog and choose **“I Agree — Enable Research
       Participation.”**

    The decision is recorded in AA's consent database (not in your profile)
    and collection starts on your next session. Withdraw from the same
    screen at any time — withdrawal stops collection immediately, and you
    can delete everything collected so far in the same step.

=== "CLI"

    *(The research-consent command arrives with the GUI/CLI consent change
    that follows the consent backend; until then there is no CLI command.)*

    Use the research-consent command, which calls the same consent interface
    as the GUI (`composition_root.build_research_consent()`), shows the same
    dialog text, and records the same versioned decision. Collection starts
    on your next session.

    Editing the profile JSON does **not** enable research:
    `app_config.enable_research_collection` is not read for consent (the
    templates no longer carry it), and the `enable_research_collection`
    config flag only controls whether research is *offered* at all.

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

If you would like to contribute your data to the public dataset, run
`python -m auto_apply --export-research` and submit the **export bundle**
it creates (a directory under `reports/` in AA's data directory) via the
project’s contribution channel (to be announced). The bundle is the
contribution format: it is self-verifying — it carries the public key a
recipient needs to authenticate every signed row — and it contains nothing
private. Share ONLY the bundle, never the raw `research/` directory.
Contributions are voluntary, anonymous, and irreversible — once data is
published, it cannot be retracted. Only share what you are comfortable
making public.

---

## For Researchers

If you are an academic researcher interested in using AA’s data for your own
studies, please review:

- [Signals Taxonomy](signals_taxonomy.md) — the complete list of recorded
  observations and what they mean.
- [Data Format](data_format.md) — the SQLite schema, data types, and analysis
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
- [Data Format](data_format.md) — SQLite schema, data dictionary, and analysis
  examples.
- [Profiles & Privacy](../user_guide/profiles_and_privacy.md) — how to
  protect your AA data with encryption and external storage.

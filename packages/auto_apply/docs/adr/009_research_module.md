# ADR‑009: Consent‑Gated, Zero‑PII Research Module

**Status:** Accepted  
**Date:** 2026‑01‑15  
**Deciders:** Nick Liebmann  
**Technical Story:** AutoApply is uniquely positioned to observe the hiring market from the candidate’s perspective at scale. Most academic research on hiring uses employer‑side data (ATS vendor analytics, HR surveys). AA produces the first large‑scale candidate‑side dataset. However, collecting any data about a user’s job hunt carries ethical and privacy risks. The research module had to be designed so that it is impossible to extract personally identifiable information from its output, even with full access to the raw data files.

---

## Context

AutoApply, in the course of its normal operation, encounters systematic patterns in the hiring market:

- Job postings labelled “Entry Level” that require years of experience.
- ATS platforms that reject applications within minutes.
- Forms that present logical contradictions.
- Companies that disclose salary ranges versus those that do not.

These observations have genuine public‑interest value. Aggregated across many users, they could inform policy discussions, empower job seekers, and hold employers accountable. However, collecting this data requires navigating a fundamental tension: we want rich, structured observations, but we must never record anything that could identify an individual user or their specific job applications.

---

## Decision

We implemented a **consent‑gated, passive, zero‑PII research data collector** — the `ResearchCollector`. It is governed by five non‑negotiable design principles encoded in its implementation.

### 1. Consent First, Always

Research collection is **opt‑in only** and **disabled by default**. The user must explicitly set `enable_research_collection: true` in their profile. An administrator may globally disable collection via `aa_policy.json` (`disable_research_collection: true`), which overrides any user opt‑in. The collector checks consent before every operation; if consent is absent, it is a no‑op.

### 2. Zero Personal Data

The collector **never** records:

- Job URLs (which would reveal browsing patterns)
- Company names (which would reveal industry or geography preferences)
- User names, emails, resume content, or any profile data
- IP addresses or precise timestamps that could correlate to a specific user

Instead, it records only categorical, aggregate signals. A signal says *“a title/description seniority mismatch was observed on platform `greenhouse`”* — not *“Alice applied to Google and the job title said Junior but required Senior experience.”*

The `platform_type` field is extracted from the URL domain (e.g., `greenhouse.io` → `"greenhouse"`) and the full URL is immediately discarded. The `detail_code` and `notes` fields are sanitised by a regex that strips any residual URLs and email addresses.

### 3. Passive Observation Only

The collector is a pure **EventBus subscriber**. It listens to events that the rest of the system already publishes — `APPLICATION_SUBMITTED`, `APPLICATION_FAILED`, `JOB_VETTED_FAIL`, `FORM_FIELD_FAILED`, `CAPTCHA_DETECTED`, etc. — and extracts anonymised signals from their payloads. It never calls into domain engines, never navigates the browser, and never adds latency to the main agent loop. All disk writes happen on a background daemon thread via a queue.

### 4. Research‑Grade Uniformity

All contributors record the same 21 signal types with the same schema. There is no per‑user variation in the data format. This satisfies the randomisation requirement for valid statistical analysis: the dataset is identically structured across all contributors, regardless of their profile configuration or hardware tier.

### 5. Non‑Blocking by Design

EventBus delivers signals synchronously on the publishing thread. The collector only calls `queue.put_nowait()` — never writes to disk on the hot path. All file I/O is performed by a background writer thread. If the queue fills up, signals are dropped rather than blocking the agent. Research collection cannot slow down or crash a session.

### Signal Taxonomy

The module records 21 standardised signal types across eight categories:

| Category | Example Signals |
|----------|-----------------|
| Seniority | `TITLE_DESCRIPTION_MISMATCH`, `ENTRY_LEVEL_EXPERIENCE_REQUIRED` |
| ATS Process | `ATS_REJECTION_RAPID`, `ATS_NO_RESPONSE` |
| Hidden Gating | `HIDDEN_REQUIREMENT_FORM`, `HIDDEN_REQUIREMENT_DROPDOWN_GATE` |
| Form Design | `YIN_YANG_CONFLICT`, `FORM_LOGIC_CONFLICT` |
| Compensation | `UNPAID_DECEPTIVE_POSTING` |
| Friction | `NO_DIRECT_CONTACT`, `CAPTCHA_EXCESSIVE` |
| Early Career | `INTERNSHIP_CURRENT_STUDENT_ONLY`, `INTERNSHIP_UNPAID` |
| Positive | `SALARY_RANGE_DISCLOSED`, `INCLUSIVE_LANGUAGE_DETECTED` |

The **Positive** category is deliberate — the dataset must document good practices as well as bad ones. A balanced taxonomy ensures the research is credible and fair.

### Output Format

Signals are written to `~/.auto_apply/research_data/hiring_signals.csv`. The CSV is append‑only; headers are written once on first run. The file is designed to be directly importable into pandas, R, or any spreadsheet application with zero preprocessing:

```csv
timestamp_utc,session_id,signal_type,category,platform_type,job_tier_listed,...
2026-05-01T14:32:00,sess_a1b2,ENTRY_LEVEL_EXPERIENCE_REQUIRED,seniority,greenhouse,entry,...
```

### Background Writer Architecture

```
EventBus handler (publishing thread)
    │
    └─ queue.put_nowait(signal)      ← non‑blocking; drops on overflow

Background daemon thread (ResearchWriter)
    │
    └─ queue.get(timeout=1.0)
    └─ write one CSV row
    └─ loop until stop_event + queue empty
```

On shutdown, the writer drains the queue before exiting, with a 10‑second timeout. Any remaining signals are counted as dropped and logged.

---

## Options Considered

### Do not collect any data at all
**Rejected.** This would forfeit the unique opportunity to build a candidate‑side hiring dataset at a scale no individual researcher could achieve. The ethical risks are mitigated by the five design principles — consent, zero‑PII, passive, uniform, non‑blocking.

### Collect richer data (company names, job titles) under a stronger anonymisation scheme
**Rejected.** Even hashed company names could be re‑identified by correlating them with public job listings. The safest approach is to never store the data in the first place. The signal taxonomy captures the pattern without the identifying detail.

### Use a remote server to aggregate data automatically
**Rejected.** This would violate the “everything runs locally” architectural principle and introduce network privacy risks. The CSV is stored locally; users must explicitly export and share it. Future aggregation will be opt‑in and use cryptographic signing (see `ProvenanceSigner` in `data_protection.py`) to verify data integrity without revealing user identity.

---

## Consequences

### What becomes easier

- **Academic research:** Any researcher with access to a user’s CSV file can immediately load it into pandas and begin analysis. The uniform schema eliminates data cleaning.
- **User trust:** The module’s design is auditable. A user can inspect the CSV at any time and confirm that it contains no personal data.
- **Admin compliance:** Institutions with strict data policies can disable the module globally via `aa_policy.json`.

### What becomes harder

- **Longitudinal analysis:** Because `session_id` is a random UUID that changes every session, tracking the same user across sessions is impossible by design. This is intentional — it prevents user profiling — but it limits certain kinds of longitudinal research.
- **Maintaining the signal taxonomy:** Adding a new signal type requires updating the `ResearchSignalType` enum, the CSV headers (which must be append‑compatible), the collector’s event handlers, and the documentation. This is deliberate friction to ensure each signal is carefully considered.

---

## References

- [ADR‑001: Hexagonal Architecture](001_hexagonal_architecture.md) — the EventBus and port/adapter pattern that enables passive observation
- [ADR‑005: Human‑in‑the‑Loop](005_human_in_the_loop.md) — the consent model is similar: opt‑in, overrideable by admin policy
- `application/services/research/collector.py` — the `ResearchCollector` implementation
- `domain/events.py` — the `Event` enum and payload conventions
- `adapters/secondary/security/data_protection.py` — `ProvenanceSigner` for future data integrity
- [Research Module Documentation](../research_module/index.md)
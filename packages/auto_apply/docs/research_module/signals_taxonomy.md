# Signals Taxonomy

The Research Module records 29 standardised signal types across eight
categories. Each signal is a single, anonymised observation of a hiring
market pattern. Below is the complete catalogue, including academic
grounding and the Python detector classes that implement them.

All detectors are pure functions (zero I/O) and live in
`domain/services/signal_detectors/`.

---

## Categories & Signals

### Ghost Jobs (GJ)
Signals that detect job postings with no genuine hiring intent.

| Signal | Identifier | Detector Class | Description |
|--------|------------|----------------|-------------|
| Posting Age Anomaly | `GJ-01` | `PostingAgeAnomalyDetector` | Posting has been live longer than typical fill times for the role category (SHRM benchmark). Exempts evergreen retail/warehouse roles. |
| Freshness Laundering | `GJ-02` | `FreshnessLaunderingDetector` | Identical job hash appears on multiple platforms with posting‑date spreads >14 days, indicating reposting to game “new this week” algorithms. |
| Refill Without Hire | `GJ-03` | `RefillWithoutHireDetector` | Role cycles through open/closed/open ≥3 times in 6 months, suggesting pipeline‑building without genuine intent to hire. |
| Apply‑with‑no‑ATS | `GJ-04` | `ApplyWithNoATSDetector` | “Apply” button resolves to a homepage, mailto: link, or page with zero form fields — no functional application path exists. |
| Earnings‑Season Clustering | `GJ-05` | `EarningsSeasonClusteringDetector` | Posting spikes correlate with public‑company earnings windows, suggesting growth signaling rather than hiring. Requires SEC EDGAR data enrichment (P3 roadmap). |

**Academic grounding:** Clarify Capital (Jan 2025) — 1 in 3 employers admit posting with no intent to hire. Greenhouse (2024) — 18‑22% of online listings are fake. SHRM average time‑to‑fill: 41 days.

---

### Discrimination (DISC)
Signals that detect discriminatory language or practices.

| Signal | Identifier | Detector Class | Description |
|--------|------------|----------------|-------------|
| Gendered Language | `DISC-01` | `GenderedLanguageDetector` | Computes Gender Coding Score (GCS) from validated masculine/feminine word lists (Gaucher, Friesen & Kay 2011). Flags when GCS exceeds ±0.25 with ≥3 coded words. |
| Age Discrimination | `DISC-02` | `AgeDiminateProxyDetector` | Detects explicit age proxies (graduation year, experience caps, “digital native”) and softer proxies (“energetic team”). |
| Disability Screening | `DISC-03` | `DisabilityScreeningDetector` | Flags unnecessary physical requirements (lifting, standing, driver’s license) in demonstrably desk‑based roles — potential ADA violation. |
| Socioeconomic Proxy | `DISC-04` | `SocioeconomicProxyDetector` | Detects credit checks, personal vehicle requirements, unpaid trial periods, and high GPA cutoffs — documented EEOC disparate‑impact indicators. |
| Geographic Pay Discrimination | `DISC-05` | `GeographicPayDiscriminationDetector` | Normalises salary by metro‑area cost‑of‑living index and flags individual postings with COL‑adjusted salary below 65% of national median. Aggregate analysis (LM‑03) performs the actual discrimination test. |
| Intersectional Discrimination | `DISC-06` | `IntersectionalDiscriminationDetector` | Fires when ≥2 discrimination signals co‑occur on the same posting, using geometric‑mean compound confidence. Aligns with California AB 218 (2024) and Park & Oh (2025). |

**Academic grounding:** Gaucher, Friesen & Kay (2011) for DISC‑01. ADEA / EEOC guidance for DISC‑02 and DISC‑04. ADA for DISC‑03. BLS Regional CPI methodology for DISC‑05. Park & Oh (2025) for DISC‑06.

---

### Qualification Stacking (QS)
Signals that detect unrealistic or contradictory qualification requirements.

| Signal | Identifier | Detector Class | Description |
|--------|------------|----------------|-------------|
| Experience Impossibility | `QS-01` | `ExperienceYearImpossibilityDetector` | Flags when required years of experience exceed the known age of the technology (e.g., 11 years of React when React was released in 2013). |
| Entry‑Level Contradiction | `QS-02` | `EntryLevelContradictionDetector` | Role titled “Entry Level” / “Junior” but requires ≥4 years of experience — a senior‑level bar with an entry‑level label. |
| Degree Inflation | `QS-03` | *(structural — implemented as part of knockout‑threshold analysis in AH‑01)* | Graduate degree required for roles that did not require one five years prior (Hershbein & Kahn 2018). |
| Salary‑Skills Mismatch | `QS-04` | `SalarySkillsMismatchDetector` | Required skill bundle (e.g., Kubernetes + Terraform + ML) commands market salary far above the offered compensation. |
| Impossible Skills Combination | `QS-05` | `ImpossibleSkillsCombinationDetector` | Requires simultaneously deep expertise in competing technologies (e.g., React + Angular + Vue at expert level). |

**Academic grounding:** Harvard Business School / Burning Glass (2024) — 85% of companies claim skills‑based hiring; actual impact on hires is 0.14%. Hershbein & Kahn (2018) on credential inflation.

---

### Salary Transparency (ST)
Signals that detect compensation opacity and wage violations.

| Signal | Identifier | Detector Class | Description |
|--------|------------|----------------|-------------|
| Legal Salary Non‑Disclosure | `ST-01` | `SalaryTransparencyLegalViolationDetector` | No salary disclosed in a jurisdiction where disclosure is legally required (≥15 US states/cities as of 2026). |
| Salary Range Washing | `ST-02` | `SalaryRangeWashingDetector` | Disclosed range is so wide (max/min > 2x) that it conveys no genuine information, violating “good faith” requirements. |
| Below‑Market Salary | `ST-03` | `BelowMarketSalaryDetector` | Offered salary is below the 25th percentile for equivalent role/skills in AA’s accumulated salary corpus (self‑calibrating). |
| Salary History Inquiry | `ST-04` | `SalaryHistoryInquiryDetector` | Application form asks for prior salary in a jurisdiction that has banned salary‑history questions. Direct form‑field evidence. |

**Academic grounding:** DLA Piper (2026) for jurisdiction tracking. Colorado Equal Pay Act (2021), NYC Local Law 32 (2022), and subsequent state laws for legal requirements.

---

### Dark Patterns (DP)
Signals that detect manipulative or deceptive design in job postings.

| Signal | Identifier | Detector Class | Description |
|--------|------------|----------------|-------------|
| Title‑Description Mismatch | `DP-01` | `TitleDescriptionMismatchDetector` | Job title and description opening share <15% keyword overlap (Jaccard similarity) — bait‑and‑switch. |
| Toxic Culture Obfuscation | `DP-02` | `ToxicCultureObfuscationDetector` | Scores description for obfuscated exploitative conditions (“wear many hats”, “work hard play hard”, “like a family”) using a weighted lexicon. |
| Unpaid Labor Extraction | `DP-03` | `UnpaidLaborExtractionDetector` | Take‑home assessments >2 hours or portfolio requirements misrepresenting unpaid labor as “interview process”. |
| Application Bloat | `DP-04` | `ApplicationBloatDetector` | Form field count exceeds norms for the role’s seniority level, disproportionately filtering candidates who cannot take time off work. |
| Phantom Company Detection | `DP-05` | `PhantomCompanyDetector` | Company has no LinkedIn presence, a domain registered <90 days ago, or no verifiable web presence — possible fraudulent posting. |

---

### Regulatory (RC)
Signals that detect legal non‑compliance.

| Signal | Identifier | Detector Class | Description |
|--------|------------|----------------|-------------|
| WARN Act Violation | `RC-01` | `WarnActPostingDetector` | Company is posting jobs while simultaneously having an active WARN Act mass‑layoff filing (requires DOL data enrichment). |
| Non‑Compete Illegality | `RC-02` | `NonCompeteIllegalityDetector` | Non‑compete clause in a jurisdiction where non‑competes are void by statute (CA, MN, ND, OK, DC). |
| Unpaid Internship FLSA | `RC-03` | `UnpaidInternshipFLSADetector` | Unpaid internship fails the FLSA primary‑beneficiary test (≥2 of 4 factors indicate employer‑beneficiary). |

---

### AI Hiring Bias (AH)
Signals that detect algorithmic screening bias in ATS platforms.

| Signal | Identifier | Detector Class | Description |
|--------|------------|----------------|-------------|
| Knockout Question Threshold | `AH-01` | `KnockoutQuestionPatternDetector` | ATS binary screening questions set above 90th‑percentile market norms (e.g., “Do you have ≥10 years of experience?”). Novel data source — AA records the exact threshold the ATS enforces. |
| Readability Asymmetry | `AH-02` | `ReadabilityAsymmetryDetector` | Entry‑level posting has Flesch‑Kincaid grade level ≥16 (post‑graduate reading difficulty), potentially screening less‑credentialed candidates. |

---

### Labor Market Macro (LM)
Aggregate‑level signals computed periodically from the accumulated corpus.

| Signal | Identifier | Analysis Function | Description |
|--------|------------|-------------------|-------------|
| Sector Opening‑to‑Application Ratio | `LM-01` | `compute_sector_opening_ratios` | Compares AA’s observed posting volume per sector to BLS JOLTS data, identifying sectors with anomalous ghost‑posting rates. |
| Application Black Hole Mapping | `LM-02` | `compute_black_hole_index` | Identifies platforms or companies where <5% of applications receive any acknowledgment. Supports legislative pushes for mandatory acknowledgment (Ontario 2026). |
| Geographic Pay Compression | `LM-03` | `compute_geographic_pay_compression` | Kendall’s Tau correlation between COL‑normalised salary and metro‑area demographic composition. Ecological correlation only — not individual‑level discrimination. |

**Note:** LM‑01, LM‑02, and LM‑03 are macro‑signals that run on aggregated data, not per‑posting. They are implemented in `domain/services/macro_analysis.py`.

---

## How Signals Are Recorded

1. **Workflows observe** — Discovery, Vetting, and Applications workflows call
   `observe_job_posting()`, `observe_form()`, and
   `observe_application_outcome()` on the injected `ResearchObserverPort`.

2. **Aggregator enqueues** — The `ResearchSignalAggregator` builds a
   `DetectionContext`, runs all 29 detectors, and pushes resulting
   `ResearchSignal` objects onto an internal queue.

3. **Daemon thread writes** — A background thread drains the queue and
   writes all signals to a SQLite database (`research_signals.db`).

4. **Provenance signing** — Every signal’s content is hashed and signed
   with an installation‑unique Ed25519 key. The public key is stored in
   the `research_provenance` table for third‑party verification.

Signal IDs are deterministic for per‑posting detectors when `posting_hash`
is present: `signal_id = SHA‑256(signal_type + posting_hash + detected_date)`.
This ensures that the same fact observed via multiple code paths (e.g., a
salary gap detected during both job posting analysis and form analysis)
produces exactly one row in the database — the correct unit of observation
for aggregate statistics.

---

## Extending the Taxonomy

New signal types can be added by:
1. Adding a constant to `domain/constants.py` (e.g., `SIG_NEW_01 = "NEW-01"`).
2. Creating a new detector class in `domain/services/signal_detectors/`
   that implements the `SignalDetector` Protocol.
3. Adding the detector instance to the `ALL_DETECTORS` list in
   `domain/services/signal_detectors/__init__.py`.
4. Adding an entry to this document.

The `DetectionContext` carries all available data; new detectors only need
to inspect the fields they require. Unknown or missing fields are simply
ignored (graceful degradation).

---

## Next Steps

- [Data Format](data_format.md) — the SQLite schema and analysis examples.
- [Research Module Overview](index.md) — purpose, ethics, and privacy.
- [Understanding the Output](../user_guide/understanding_output.md) — where
  the research data file lives and how to use it.

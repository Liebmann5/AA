# AutoApply Ethics Statement

## deon Checklist

This document follows the [deon](https://github.com/drivendataorg/deon) ethics
checklist for data science and software projects involving data collection.

### A. Data Collection

- [x] **Informed consent**: Users must explicitly opt in to research data collection.
  Default is `research.enabled: false`. Consent is versioned and stored with each record.
- [x] **Right to withdraw**: Users can delete their research contribution at any time
  via Settings → Research → Delete My Data. Deletion takes effect within 24 hours.
- [x] **Data minimization**: Only the minimum data needed for each research signal is
  collected. Full job descriptions are never stored; only anonymized excerpts ≤200 chars.
- [x] **Anonymization**: Company names are HMAC-SHA256 anonymized. No personally
  identifiable information (PII) is ever stored in research tables.
- [x] **Third-party data**: Research data may include signals from third-party job
  boards. This data reflects employer behavior (job descriptions, form fields) rather
  than user behavior.

### B. Data Storage

- [x] **Encryption at rest**: Research databases use SQLite WAL mode with system-level
  file encryption. Future versions will implement AES-256 encryption at the file level.
- [x] **Access controls**: Research data is stored locally on the user's device.
  No data is transmitted to external servers without explicit user action (export).
- [x] **Data retention**: Research signals are retained for 90 days by default,
  configurable via `research.retention_days` in `runtime_defaults.yaml`.
- [x] **Breach response**: In the event of a discovered vulnerability affecting
  research data, users will be notified via the project's issue tracker within 72 hours.

### C. Analysis

- [x] **Proxy discrimination**: Signals for discrimination proxies (DISC-01 through
  DISC-06) are documented with their academic grounding. Confidence scores reflect
  the probability of a genuine signal, not a legal determination.
- [x] **Spurious correlations**: All signals include confidence scores and evidence
  text. Aggregate analysis uses Benjamini-Hochberg FDR correction to control for
  multiple comparisons.
- [x] **Honest reporting**: Signal detectors are designed to minimize false positives.
  The `js_variables` CAPTCHA detector, for example, was explicitly set to empty
  because presence of `window.grecaptcha` is not a genuine CAPTCHA challenge.

### D. Modeling (N/A for this version)

AutoApply v1.0 does not train ML models on research data. If this changes, this
section will be updated with model cards and fairness assessments.

### E. Deployment

- [x] **Worst-case user first**: Every feature degrades gracefully for users on
  library computers with 2GB RAM and no admin rights.
- [x] **Accessibility**: Application forms are assessed for WCAG 2.1 compliance.
  AA itself targets keyboard accessibility in its GUI.
- [x] **Transparency**: This ethics statement is public and versioned. Changes
  to data collection practices require an update to this document and to the
  user consent dialog's version string.

## Research Ethics Statement

AutoApply's research capabilities are designed for labor market science. The research
program aims to provide empirical evidence of systematic hiring dysfunction for the
benefit of workers, policymakers, and researchers. The platform:

1. **Does not impersonate**: AA fills real job applications on behalf of real users
   who have given consent for their applications.
2. **Correspondence audits**: If AA is used for correspondence audit studies
   (fake paired applications for discrimination research), this requires separate
   IRB-equivalent review, must be pre-registered on OSF, and must comply with
   all applicable laws regarding fictitious applications.
3. **Employer accountability**: Research signals attribute dysfunction to specific
   employer behaviors (job descriptions, form fields, policies), never to individual
   employees or candidates.
4. **Open data**: Aggregate research data may be published openly to support
   independent verification and replication.

## Contact

For ethics-related concerns, open an issue on Codeberg with the label `ethics`.

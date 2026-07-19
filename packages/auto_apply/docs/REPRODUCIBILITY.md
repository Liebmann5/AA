# Reproducibility Guide for AutoApply Research

AutoApply is engineered to support **deterministic, reproducible execution** for
academic research, correspondence audits, and hiring-market studies. This guide
documents how to produce identical execution traces, export research data in
standard formats, and verify the integrity of collected signals.

---

## Deterministic Execution

AA can run in a fully deterministic mode where every random choice — browser
timing, mouse jitter, provider ordering, and session warmup — is governed by a
single seed.

```bash
python -m auto_apply --seed 42 --cli
```

With the same seed, same profile, and same runtime configuration, AA produces:

- Identical discovery ordering (which provider runs first, query iteration order)
- Identical jitter and timing sequences (mouse offsets, keystroke delays)
- Identical research signal IDs (deterministic hashing from posting hash + date)

**Requirements for bit-identical traces:**

1. Use the **same seed** (`--seed N`).
2. Use the **same profile** (identical `UserProfile` JSON).
3. Use the **same `runtime_defaults.yaml`** (no config drift between runs).
4. Run on the **same OS and Python version** (timing is affected by OS scheduler).
5. For network-dependent research (salary corpus, lifecycle tracking), use the
   **same research database state** at the start of each run.

The `BehaviorParameters` model (in `domain/models/timing.py`) centralises all
randomness. When `random_seed` is set, `BehaviorParameters.make_rng()` returns
a `random.Random(seed)` instance that is injected into every component that
needs randomness. Components use `self._rng.uniform()` instead of the global
`random` module. No AA component should call `random.uniform()` or
`secrets.SystemRandom()` directly — if you find one that does, it is a bug
and should be reported.

### Verifying Determinism

Run the same session twice and compare the research signal files:

```bash
# First run
python -m auto_apply --seed 42 --cli --portable
python -m auto_apply --export-research --export-format json
mv research_signals_*.json run1.json

# Second run (identical configuration)
python -m auto_apply --seed 42 --cli --portable
python -m auto_apply --export-research --export-format json
mv research_signals_*.json run2.json

# Compare
diff <(jq -S . run1.json) <(jq -S . run2.json)
```

If the two JSON files differ, check that no component is using un-seeded
randomness (common culprits: `random.choice()` in provider selection,
`time.sleep()` without going through the injected `BehaviorSimulator`).

---

## Exporting Research Data

AA stores all research observations in SQLite databases. Export to
analysis-ready formats using the built-in CLI:

```bash
# Export all research signals as CSV (default)
python -m auto_apply --export-research

# Export as JSON
python -m auto_apply --export-research --export-format json

# Export as Parquet (requires pyarrow; install with `uv sync --extra research`)
python -m auto_apply --export-research --export-format parquet
```

Export files are written to the session reports directory (typically
`~/.auto_apply/reports/` or `<USB>/data/reports/` in portable mode).

The exporter writes three files per invocation:

| File prefix | Contents |
|---|---|
| `aa_research_signals_*` | All individual signal events (29 detector types) |
| `aa_salary_corpus_*` | Salary observations for market benchmarking (ST‑03) |
| `aa_form_observations_*` | ATS form complexity observations (DP‑04, ST‑04) |

---

## Research Signal Schema

### `research_signals` — Individual Signal Events

| Column | Type | Description |
|---|---|---|
| `signal_id` | `TEXT PK` | Deterministic ID derived from (signal_type, posting_hash, date) |
| `signal_type` | `TEXT` | Signal code: `GJ-01`, `DISC-01`, `ST-01`, etc. |
| `severity` | `TEXT` | `flag`, `concern`, or `violation` |
| `confidence` | `REAL` | Detection confidence 0.0–1.0 |
| `evidence_text` | `TEXT` | Anonymized evidence excerpt (max 200 chars) |
| `platform` | `TEXT` | ATS or job board identifier |
| `jurisdiction` | `TEXT` | US state/city code (e.g. `CA`, `NYC`) |
| `company_id` | `TEXT` | HMAC-SHA256 of company name (anonymized) |
| `job_category` | `TEXT` | BLS SOC code when available |
| `detected_date` | `TEXT` | ISO date of detection |
| `schema_version` | `INTEGER` | Schema version for longitudinal compatibility |
| `consent_version` | `TEXT` | Version of consent dialog user agreed to |
| `posting_hash` | `TEXT` | Structural hash of the source job posting |
| `content_hash` | `TEXT` | SHA-256 of evidentiary content |
| `provenance_signature` | `TEXT` | Ed25519 signature (see Provenance below) |

### `job_lifecycles` — Posting Lifecycle Tracking (GJ‑02, GJ‑03)

| Column | Type | Description |
|---|---|---|
| `job_fingerprint` | `TEXT PK` | Structural hash of posting (part of composite key) |
| `platform` | `TEXT PK` | Platform where observed (part of composite key) |
| `first_seen` | `TEXT` | Earliest observation date |
| `last_seen` | `TEXT` | Most recent observation date |
| `times_seen` | `INTEGER` | Total distinct observation dates |
| `times_reposted` | `INTEGER` | Times posting disappeared and reappeared (gap > 7 days) |
| `applied_to` | `INTEGER` | Whether user applied to this posting |
| `response_received` | `INTEGER` | Whether any response was received |
| `response_date` | `TEXT` | Date of response, if any |
| `company_id` | `TEXT` | Anonymized company identifier |

### `salary_observations` — Salary Corpus (ST‑03)

| Column | Type | Description |
|---|---|---|
| `obs_id` | `TEXT PK` | Unique observation ID |
| `salary_min` | `INTEGER` | Minimum disclosed salary (USD/year) |
| `salary_max` | `INTEGER` | Maximum disclosed salary (USD/year) |
| `salary_type` | `TEXT` | `annual`, `hourly`, or `monthly` |
| `currency` | `TEXT` | ISO 4217 currency code |
| `role_title_normalized` | `TEXT` | Lowercased, stripped job title |
| `experience_years_min` | `INTEGER` | Minimum years experience required |
| `experience_years_max` | `INTEGER` | Maximum years experience required |
| `education_required` | `TEXT` | Education level if specified |
| `location_metro` | `TEXT` | Metropolitan Statistical Area (MSA) |
| `jurisdiction` | `TEXT` | US state/city code |
| `platform` | `TEXT` | Source platform |
| `industry_sic` | `TEXT` | Standard Industrial Classification code |
| `posted_date` | `TEXT` | Date posting was observed |
| `schema_version` | `INTEGER` | Schema version |

### `form_observations` — ATS Form Complexity (DP‑04, ST‑04)

| Column | Type | Description |
|---|---|---|
| `form_id` | `TEXT PK` | Unique observation ID |
| `job_fingerprint` | `TEXT` | Structural hash of parent posting |
| `platform` | `TEXT` | ATS or job board identifier |
| `company_id` | `TEXT` | Anonymized company identifier |
| `total_fields` | `INTEGER` | Total form fields detected |
| `required_fields` | `INTEGER` | Required field count |
| `optional_fields` | `INTEGER` | Optional field count |
| `essay_fields` | `INTEGER` | Textarea/essay field count |
| `file_upload_fields` | `INTEGER` | File upload field count |
| `knockout_questions` | `INTEGER` | Binary screening question count |
| `wcag_score` | `TEXT` | Accessibility compliance score |
| `wcag_violations` | `TEXT` | JSON array of violation codes |
| `salary_history_requested` | `INTEGER` | Whether prior salary was requested (ST‑04) |
| `jurisdiction` | `TEXT` | US state/city code |
| `estimated_completion_minutes` | `INTEGER` | Estimated time to complete form |
| `observed_date` | `TEXT` | Date form was analyzed |
| `schema_version` | `INTEGER` | Schema version |

### `application_outcomes` — Black‑Hole Tracking (LM‑02)

| Column | Type | Description |
|---|---|---|
| `outcome_id` | `TEXT PK` | Unique outcome ID |
| `platform` | `TEXT` | ATS or job board identifier |
| `company_id` | `TEXT` | Anonymized company identifier |
| `submitted_date` | `TEXT` | Date application was submitted |
| `acknowledgment_received` | `INTEGER` | Whether any response was received within 30 days |
| `acknowledgment_date` | `TEXT` | Date of acknowledgment, if received |
| `schema_version` | `INTEGER` | Schema version |

---

## Cryptographic Provenance

Every research signal written to the database is signed with an **Ed25519**
key unique to the AA installation. The public key is stored in the
`research_provenance` table so third-party verifiers can authenticate signals
without the private key ever leaving the device.

**Verifying provenance externally:**

```python
import json, hashlib
from cryptography.hazmat.primitives.asymmetric import ed25519

# 1. Load the public key from the research database
import sqlite3
conn = sqlite3.connect("research_signals.db")
row = conn.execute("SELECT public_key_hex FROM research_provenance WHERE id = 1").fetchone()
public_key = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(row[0]))

# 2. For each signal, verify the signature
for signal in exported_signals:
    content = json.dumps({
        "signal_type": signal["signal_type"],
        "severity": signal["severity"],
        "confidence": signal["confidence"],
        "evidence_text": signal["evidence_text"] or "",
        "platform": signal["platform"] or "",
        "jurisdiction": signal["jurisdiction"] or "",
        "detected_date": signal["detected_date"],
        "posting_hash": signal["posting_hash"] or "",
    }, sort_keys=True).encode("utf-8")

    content_hash = hashlib.sha256(content).hexdigest()
    signature_bytes = bytes.fromhex(signal["provenance_signature"])

    public_key.verify(signature_bytes, content_hash.encode("utf-8"))
    # No exception → signature valid
```

---

## Correspondence Audit Reproducibility

For correspondence audit studies (paired-profile callback testing), AA provides:

- **AuditCoordinator** — schedules paired applications, computes Fisher's exact
  test and Wilson confidence intervals for callback-rate differences.
- **Pre‑registration export** — `AuditCoordinator.export_protocol_for_preregistration()`
  produces a JSON document suitable for OSF pre‑registration before any
  submissions begin.
- **Withdrawal safeguards** — any interview offer immediately triggers
  withdrawal of both paired applications.

See `AA_ARCHITECTURE_BIBLE.md` Section 18 and `docs/ETHICS.md` for the
ethical requirements governing correspondence audit studies.

---

## Mock ATS Benchmark Suite

To verify that AA's form-filling engine produces consistent, correct results
across ATS platform changes, run the mock ATS benchmark:

```bash
uv run pytest tests/benchmarks/ats_forms/ -v
```

This suite includes:

| Fixture | Platform | Key Features |
|---|---|---|
| `greenhouse_simple.html` | Greenhouse | Single-page, file upload, honeypot field |
| `workday_multi_step.html` | Workday | 3-step wizard, select dropdowns, essay questions |

The benchmark verifies that AA correctly identifies form fields, classifies
field types, and produces interaction plans for each fixture. Results are
deterministic when run with `--seed`.

---

## Property‑Based Testing

Mathematical algorithms (Hungarian assignment, convex hull, structural hashing)
are tested with the **Hypothesis** library to verify invariants across
thousands of random inputs:

```bash
uv run pytest tests/property_based/ -v --hypothesis-seed=0
```

These tests are required for ACM Artifacts Functional badge certification
and provide statistical confidence that the core algorithms are correct.

---

## Memory Profiling

To verify that AA stays within the worst‑case memory budget (2 GB RAM target,
1.8 GB ceiling):

```bash
python -m auto_apply --profile --seed 42 --cli
```

This writes a JSON performance profile to the reports directory, including
`tracemalloc` peak memory, per-component allocation breakdown, and session
duration. Use this to detect memory regressions before they affect
worst‑case users.

---

## Publishing Research Results

When publishing results derived from AA data, please include:

1. **AA version** — the Git SHA or release tag used.
2. **Configuration** — the `runtime_defaults.yaml` values active during
   collection (the YAML file itself is ideal).
3. **Seed** — the `--seed` value if deterministic mode was used.
4. **Signal schema version** — `RESEARCH_SCHEMA_VERSION` from
   `domain/constants.py` (currently `2`).
5. **Consent version** — `CURRENT_CONSENT_VERSION` from
   `domain/constants.py` (currently `"2.1"`).
6. **Citation** — use the `CITATION.cff` file in the repository root.

---

## Related Documentation

- [Architecture Bible](../AA_ARCHITECTURE_BIBLE.md) — complete architectural reference
- [Research Module Overview](research_module/index.md) — purpose, ethics, privacy
- [Signals Taxonomy](research_module/signals_taxonomy.md) — every signal type explained
- [Data Format](research_module/data_format.md) — detailed schema and analysis examples
- [ETHICS.md](ETHICS.md) — deon ethics checklist
- [Installation Guide](getting_started/installation.md) — all install methods

---

*"The purpose of AA was to provide people/candidates with the same automating
computer programs that companies utilize to expedite and simplify the hiring
process — then provide the data to build something better."*

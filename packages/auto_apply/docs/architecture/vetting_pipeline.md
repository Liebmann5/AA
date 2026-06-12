# Vetting Pipeline

Discovery finds jobs. The Vetting Pipeline decides which ones are worth
applying to. It is a **composable, short‑circuiting filter chain** that
evaluates each job against the user’s profile. Only jobs that pass every
filter reach the Application Engine.

The pipeline is designed to be **fast on low‑end hardware** — filters are
ordered from cheapest to most expensive, and evaluation stops on the first
failure. Optional NLP and AI tiers improve accuracy when available, but the
pipeline works correctly with nothing more than standard library string
matching.

---

## The Goal: Two‑Way Fit

The pipeline enforces a **two‑way fit**:

1.  **The job is a fit for the user** — the title, location, salary, and
    workplace type match the user’s preferences.
2.  **The user is a fit for the job** — the user’s skills, experience level,
    and work authorisation meet the job’s requirements.

If either side fails, the job is rejected with a descriptive reason. This
prevents AA from wasting time (and the user’s reputation) on mismatched
applications.

---

## Pipeline Architecture

The pipeline is an ordered list of filter objects, each implementing the
`BaseVettingFilter` interface:

```python
class BaseVettingFilter(ABC):
    def filter(self, job: Job) -> tuple[bool, str]:
        """Returns (passed: bool, reason: str)."""
```

The `VettingEngine` (or `VettingWorkflow`) iterates through the filters in
order. The first filter to return `False` stops the chain — remaining filters
are never called. The rejection reason always identifies the most severe
issue first.

```
Discovered Job
    │
    ▼
[ThrottlingFilter] ── fail ──→ "Cooldown active (23 days)"
    │ pass
    ▼
[SpatialLocationFilter] ── fail ──→ "Too far (47 mi > 25 mi max)"
    │ pass
    ▼
[TitleLogicFilter] ── fail ──→ "Negative keyword: 'Senior'"
    │ pass
    ▼
 ... more filters ...
    │ pass
    ▼
[RoleAlignmentFilter]
    │ pass
    ▼
✅ Approved → Application Engine
```

This short‑circuit design is both a performance optimisation and a correctness
guarantee — the rejection reason tells the user exactly what to adjust in
their profile if they want different results.

---

## Filter Catalogue

Filters are listed in execution order, from cheapest to most expensive.

---

### 1. ThrottlingFilter

**Purpose:** Enforce per‑company rate limits and cooldown periods.

AA records every application in a persistent database. Before vetting a new
job, the `ThrottlingFilter` queries this database:

1.  **Max applications per company:** If the user has already applied to
    `MAX_APPLICATIONS_PER_COMPANY` (default 3) jobs at this company in any
    session, the job is rejected.
2.  **Cooldown period:** If the user has applied to this company before, the
    filter checks how many days have passed. The required cooldown is the
    **maximum** of three values:

    | Source | Example |
    | ------ | ------- |
    | **Company mandate** | The company’s confirmation page said “apply again in 6 months.” AA extracts this automatically and stores it. |
    | **User preference** | The user set `cooldown_days: 90` in their profile. |
    | **System default** | `DEFAULT_COOLDOWN_DAYS` = 180 days. |

    The filter always errs on the side of waiting longer.

3.  **Unknown companies** always pass — AA gives them the benefit of the doubt.

---

### 2. SpatialLocationFilter

**Purpose:** Reject jobs that are too far from the user’s home.

1.  Resolves the user’s home city and the job’s location to geographic
    coordinates using an offline SQLite database (`GeoDatabaseRepository`).
2.  Computes the great‑circle distance using the **Haversine formula**.
3.  If the distance exceeds the user’s `max_commute_miles`, the job is
    rejected.
4.  **Remote jobs** are always accepted if the user has `"remote"` in their
    workplace types.
5.  If coordinates cannot be resolved (e.g. unknown city name), the filter
    falls back to basic string matching and logs a warning — it never blocks
    a job due to missing geodata.

---

### 3. TitleLogicFilter

**Purpose:** Block jobs whose titles contain negative keywords, and score
the remaining titles for relevance.

This is a two‑step logic gate:

1.  **Hard block:** If the user’s experience level is “Entry” or “Junior,”
    any title containing “Senior,” “Lead,” “Principal,” “Staff,” “Manager,”
    “Head of,” or “Director” is immediately rejected.
2.  **Fuzzy match:** The job title is compared against every desired title in
    the user’s profile using `difflib.SequenceMatcher`. If the best similarity
    score is below 0.4, the job is rejected for low relevance.

The threshold is intentionally low (0.4) — the filter’s main job is to catch
obvious mismatches. The finer‑grained semantic matching is handled later by
the `RoleAlignmentFilter`.

---

### 4. CompanyBlacklistFilter

**Purpose:** Reject jobs from companies the user has a non‑compete agreement
with.

The user’s `legal_info.non_compete_agreements` list is compared (case‑
insensitively) against the job’s company name. If there is a match, the job
is rejected with “Company Blacklisted (Non‑Compete).”

---

### 5. LocationLogicFilter

**Purpose:** Reject jobs whose location doesn’t match any of the user’s
preferred locations.

The job’s `location` field is compared against the user’s
`preferred_locations` list using case‑insensitive substring matching. If none
of the user’s preferred locations appear in the job’s location string, the
job is rejected. If the user has no location preference set, all locations
pass.

This filter catches city and state mismatches before the more expensive
spatial distance calculation is needed.

---

### 6. ExperienceFilter

**Purpose:** Reject jobs that require more years of experience than the user
has.

The filter reads `experience_years_min` from the job’s metadata (populated by
SpaCy during the NLP parsing step). It maps the user’s experience level
(`"ENTRY"`, `"MID"`, `"SENIOR"`, etc.) to an approximate years range via a
`LEVEL_TO_YEARS` mapping. If the user’s years are lower than the job’s
minimum, the job is rejected.

If the job description does not specify a minimum experience, or if the user
has not set an experience level, the filter passes.

---

### 7. HardSkillsFilter

**Purpose:** Reject jobs whose required skills don’t overlap enough with the
user’s skills.

The filter reads `required_skills` from the job’s metadata (populated by
SpaCy’s `PhraseMatcher`). It computes the overlap ratio:

```
overlap = (user_skills ∩ required_skills) / required_skills
```

If the ratio is below `vetting.hard_skills_min_overlap` (default 0.5, i.e.
50%), the job is rejected. The user is told exactly which skills are missing.

If the job description lists no required skills, the filter passes — it never
blocks a job due to missing data.

---

### 8. RoleAlignmentFilter

**Purpose:** Use semantic similarity to ensure the job title conceptually
matches the user’s desired titles.

This is the most expensive filter and the only one that requires SpaCy (or
falls back gracefully).

1.  The job title and each of the user’s desired titles are converted to
    numerical vectors using SpaCy’s word vectors (`en_core_web_lg` or
    `en_core_web_md`).
2.  The **cosine similarity** is computed between each pair.
3.  The highest similarity score is compared against
    `vetting.role_alignment_threshold` (default 0.6).

This filter solves the “Principal Engineer vs. School Principal” problem:
titles that share keywords but are conceptually unrelated will have a low
cosine similarity and be rejected.

If SpaCy is not installed, the filter passes all jobs with a log message —
it never blocks a job due to missing optional dependencies.

If the user has no desired titles configured, the filter passes.

---

## NLP Scoring & SpaCy Integration

The vetting pipeline uses SpaCy for two tasks, both performed by
`VettingWorkflow._parse_with_spacy()` before the filter chain runs:

1.  **Entity extraction:** Skills, locations, organisations, and experience
    years are extracted from the job description via SpaCy’s NER and
    `PhraseMatcher`. These are stored in `job.metadata["parsed"]` and
    consumed by `ExperienceFilter`, `HardSkillsFilter`, and
    `SpatialLocationFilter`.
2.  **Title similarity:** Used by `RoleAlignmentFilter` as described above.

All NLP data is cached in the job’s metadata dict, so it is computed once and
reused across all filters.

If SpaCy is not installed, `TextMatcher` falls back to `difflib.SequenceMatcher`
for similarity and returns empty lists for entity extraction. The filters that
depend on NLP data (`ExperienceFilter`, `HardSkillsFilter`) pass automatically
when the data is absent — they never block due to missing NLP.

---

## GPT4All Borderline Reasoning

Some jobs fall into a grey area: the objective filters pass, but the fit
score is neither high enough to be clearly good nor low enough to be clearly
bad. For these borderline cases, AA can invoke a **local LLM** (GPT4All) to
make a final judgement.

### How It Works

1.  After all filters have run, the `VettingWorkflow` computes a
    **weighted fit score** (see below).
2.  If the score falls within the **borderline band** (default 0.45–0.65),
    and if GPT4All is installed, AA sends a prompt to the model:

    ```
    Job title: Software Engineer
    Company: Acme Corp
    Required skills: Python, Docker, AWS
    User background: Experienced software engineer with 7 years...

    Based only on the above, is this job a good mutual fit for this candidate?
    Answer with exactly one word: YES or NO.
    ```

3.  If the model responds **YES**, the fit score is bumped to just above the
    band (e.g. 0.66) and the job passes.
4.  If the model responds **NO**, the score is dropped to just below the band
    (e.g. 0.44) and the job is rejected.
5.  If GPT4All is not installed, or if the model fails to load, the borderline
    band is ignored — the job is processed based on its original fit score
    alone.

This gives premium users an AI‑powered tiebreaker without blocking core users
who don't have the hardware for a local LLM.

---

## Weighted Fit Score

Every filter contributes to an overall **fit score** between 0.0 and 1.0.
The score is a weighted sum of pass/fail values (1.0 for pass, 0.0 for fail):

```
fit_score = Σ (filter_weight × pass_value)
```

The default weights are:

| Filter | Weight |
| ------ | ------ |
| `ThrottlingFilter` | 0.10 |
| `SpatialLocationFilter` | 0.15 |
| `LogicFilters` (title, blacklist, location) | 0.15 |
| `ExperienceFilter` | 0.15 |
| `HardSkillsFilter` | 0.20 |
| `RoleAlignmentFilter` | 0.25 |

These weights can be adjusted in `runtime_defaults.yaml`. The `RoleAlignmentFilter`
has the highest weight because it represents the closest thing to “does this
job actually match what I want to do?”

---

## Post‑Vetting: Cooldown Extraction

After a successful application submission, AA scans the confirmation page
(“Thank you for applying”) for cooldown signals. If the page contains phrases
like “apply again in 6 months” or “we will keep your application on file,” AA
extracts the cooldown period (in days) and stores it in the company’s history
record.

The `ThrottlingFilter` reads this stored value on future sessions, ensuring
AA respects each company’s specific rules — even if the user never reads the
confirmation page themselves.

---

## Configuration

All vetting thresholds are configurable in `resources/config/runtime_defaults.yaml`:

```yaml
vetting:
  hard_skills_min_overlap: 0.5       # minimum skill overlap ratio
  role_alignment_threshold: 0.6      # minimum SpaCy cosine similarity
  borderline_band: [0.45, 0.65]      # GPT4All invoked for scores in this range
  filter_weights:                    # must sum to ~1.0
    ThrottlingFilter: 0.10
    SpatialLocationFilter: 0.15
    LogicFilters: 0.15
    ExperienceFilter: 0.15
    HardSkillsFilter: 0.20
    RoleAlignmentFilter: 0.25
```

---

## Extending the Pipeline

Adding a new filter requires three steps:

1.  **Create the filter class** in `domain/vetting/`. It must implement
    `BaseVettingFilter` and its `filter(job) -> (bool, str)` method.
2.  **Add the filter to the pipeline** in the composition root, at the correct
    position in the ordered list (cheapest filters first).
3.  **Add its weight** to `VettingWorkflow.DEFAULT_WEIGHTS` (optional — only
    needed if you want it to contribute to the fit score).

No other code needs to change. The `VettingEngine` and `VettingWorkflow`
iterate over whatever filter list they receive.

---

## Graceful Degradation

The vetting pipeline is designed to never block a job due to missing
optional dependencies:

| If … | AA will … |
| ---- | --------- |
| No database is available | `ThrottlingFilter` passes all jobs (no cooldown enforcement). |
| No geodatabase is available | `SpatialLocationFilter` falls back to string matching. |
| SpaCy is not installed | `RoleAlignmentFilter` passes all jobs; skill/experience filters pass if data is absent. |
| GPT4All is not installed | Borderline band is ignored; original fit score determines outcome. |
| The filter pipeline is empty (all imports failed) | All jobs pass vetting with a logged warning. |

This ensures that AA’s vetting works on the weakest machine with zero
configuration, while premium users get the full intelligence of NLP and AI.

---

## Next Steps

- [Application Engine](application_engine.md) — what happens after a job
  passes vetting: the form‑filling process.
- [Installation Guide](../getting_started/installation.md) — how to install
  the NLP and AI tiers for smarter vetting.
- [ADR‑005: Human‑in‑the‑Loop](../adr/005_human_in_the_loop.md) — how
  checkpoints let the user review vetting decisions before applying.
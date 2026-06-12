# Application Workflows

Three workflow files, one per engine, each a complete end-to-end description of what
that engine does from entry to exit.

## What are workflows?

The `use_cases/` layer contains the original engine classes (`DiscoveryEngine`,
`VettingEngine`, `ApplicationEngine`). The workflow files in this directory are a
**parallel orchestration layer** that wires the same underlying domain objects and
adapters into a richer, more readable 8–11 step pipeline:

| Workflow | Steps | Entry | Returns |
|---|---|---|---|
| `DiscoveryWorkflow` | 9 | `run(override_criteria?)` | `int` — jobs enqueued |
| `VettingWorkflow`   | 8 | `run(job)`               | `bool` — passed? |
| `ApplicationsWorkflow` | 11 | `run(job)`            | `bool` — submitted? |

A contributor new to the codebase can open any workflow file and understand an engine's
full process without reading other files.

---

## Three intelligence layers (each degrades gracefully)

| Layer | Library | Capability | Fallback |
|---|---|---|---|
| Mathematical | `WebpageAnalyzer` + Hungarian | Form structure, field pairing | Skip WebpageAnalyzer; use empty structure |
| Linguistic | SpaCy via `TextMatcher` | Entity extraction, similarity, NER | stdlib `difflib.SequenceMatcher` |
| Generative | GPT4All via `TextGenerationPort` | Custom question answers, borderline reasoning | SpaCy similarity ranking |

---

## Optional dependency installation

### SpaCy (recommended — improves vetting and form filling)

```bash
pip install "auto-apply[nlp]"
python -m spacy download en_core_web_lg   # best quality, ~700 MB
# Alternatives: en_core_web_md (faster), en_core_web_sm (no word vectors)
```

### GPT4All (optional — enables local AI for open-ended questions)

```bash
pip install "auto-apply[ai]"
# The default model (~4.7 GB) downloads automatically on first use to ~/.cache/gpt4all/
```

### Both at once

```bash
pip install "auto-apply[full]"
python -m spacy download en_core_web_lg
```

---

## Extension recipes

### Add a new discovery source

1. Implement `DiscoveryProviderPort` (from `domain/ports/discovery_port.py`).
2. Register the instance in `infrastructure/composition_root.py` under the `providers` list.
3. No changes to `DiscoveryWorkflow` required.

### Add a new vetting filter

1. Subclass `BaseVettingFilter` (from `domain/vetting/base_filter.py`).
2. Implement `filter(self, job: Job) -> tuple[bool, str]`.
3. Add an instance to `filter_pipeline` in `infrastructure/composition_root.py` (cheapest first).
4. Add the filter's class name and weight to `VettingWorkflow.DEFAULT_WEIGHTS`.
5. Tune the threshold in `resources/config/runtime_defaults.yaml`.

### Add a new ATS handler

1. Create a YAML descriptor in `resources/ats/<platform>.yaml` following the existing format.
2. `ATSRegistry` picks it up automatically at startup — no code changes needed.

---

## Configuration

All thresholds and timeouts are in `resources/config/runtime_defaults.yaml`:

```yaml
vetting:
  hard_skills_min_overlap: 0.5    # 50% skill overlap required
  role_alignment_threshold: 0.6   # SpaCy cosine similarity threshold
  borderline_band: [0.45, 0.65]   # GPT4All invoked for scores in this range

discovery:
  max_concurrent_sources: 4       # ThreadPoolExecutor max_workers
  max_pages_per_query: 5

applications:
  max_pages: 10                   # Form page limit
  dom_stabilization_timeout_s: 8.0
```

---

## Tests

```bash
cd packages/auto_apply
python -m pytest tests/workflows/ -v
```

Test files are in `tests/workflows/`:
- `test_discovery_workflow.py` — 4 tests
- `test_vetting_workflow.py` — 4 tests
- `test_applications_workflow.py` — 4 tests

All tests use MagicMock objects; no real browser, database, or network access.

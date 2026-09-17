# AA — Master Outstanding-Work Reference

**Purpose:** single authoritative inventory of everything in AA that is unfinished, broken, deferred, or undecided.
**Docs caveat:** `docs/adr/*` and the architecture docs are frequently stale. Trust live code, the measurements in this file, and `docs/STATUS.md` over docstrings.
**As of:** **2026-09-09 (late)** · **NINE RED PINS. Release criterion 3 is un-met and the file says
deliberate reds still count.** Nineteen files corrected across two kimicli batches; the CLI is usable
under output redirection for the first time, and `STATIC_ASSISTED` is deleted.

**Measured 2026-09-09 on Nick's machine:** `1,259 passed, 2 skipped, 9 failed` in 115s.
Seven of the nine failures are tests asserting the static-mode behaviour that was just deleted — they
assert something that was never real, and P8 rewrites them. **Two are genuine and were not predicted:**
a live mypy error in the new refusal path, and three modules the reachability pin correctly caught as
orphaned by the deletion. Both are named under *The 2026-09-09 batches* below.

**The 1,264 figure carried since 2026-09-04 was stale by 3 and caused four consecutive wrong
predictions. The green baseline before this batch was 1,268 — predict against that, not 1,264.**

> **Fence convention:** every code block in this file is indented two spaces. A fence at column 0
> truncates the document when it is emitted through kimicli. Keep the indent.

| Measured | Value | Δ since 2026-09-02 |
|---|---|---|
| Test suite | **9 failed / 1,259 passed / 2 skipped** — measured 2026-09-09 (late) | was 0 / 1,268 / 2 |
| Type gate, `src/` | **1** — `composition_root.py:990`, `", ".join(list[str] | None)` in the new refusal | was 0 |
| Undefined names (ruff F821) | Clean | unchanged |
| Hexagonal boundaries | **0**, asserted at equality | unchanged |
| Modules that raise on real import | **0 of 261** · but **3 now unreachable** — `bs4_adapter`, `urllib_http_client`, `http_client_port` | reachability pin red |
| Both architecture pins | Green, `MAX_EXEMPTIONS` ceilings | unchanged |
| **Live discovery** | **3 real LinkedIn postings resolved, verified, enqueued** | **was 0, always** |
| Discovery verification | `[PASS]: 3 jobs \| fields OK \| chrome OK \| dedup OK \| cap OK` | first PASS on real jobs |
| Harvest cost | **0.4–0.7 s** on `fast:deferred` | was 47–123 s via the miner |
| Source | ~53,000 LOC · 261 modules · 45 ports · 109 test modules | +1 module (`locale_normalization`) |
| External users | **Zero** | unchanged |

---

# Definition of Release-Ready

**The exit condition. Without it the list is infinite by construction.**

1. **One real application submitted end to end** on a live ATS form, gate honoured, complete evidence record written. — **OPEN, and now the top of the list.**
2. **Discovery yields real jobs on at least one provider**, verified by `DiscoveryVerifier` on a live run. — **✅ MET 2026-09-02, Bing.**
3. **Zero red pins.** Ruff F821 and the mypy gate green over `src/` **and** `tests/`. — **❌ RE-OPENED 2026-09-09.** Met from 2026-09-04 until the STATIC_ASSISTED deletion landed. Nine failures: seven tests asserting deleted behaviour, one real mypy error, one reachability pin correctly flagging three orphaned modules. **A deliberate red is still a red** — this criterion does not re-close until P8 lands.
4. **One clean run on worst-case hardware** (the ASUS CX1100CN, 4 GB), from the USB stick, logs captured. — OPEN.
5. **Repo hygiene:** one canonical repo URL across `README.md` / `CITATION.cff` / `pyproject.toml`; LICENSE present; CI green on Windows, Linux **and macOS**. — **PARTIAL.** `.github/workflows/ci.yml` committed 2026-09-04 (3 OSes × Python 3.10/3.12, `uv sync`, four gates as named steps, reporting-only until first all-green). Still open: commit `uv.lock`, canonical URL, and the packaging cleanup below.
   *(macOS added 2026-09-04: excluding it is AA choosing which operating systems its users are allowed to have, which contradicts AA's first principle.)*

**Tag `v0.1.0`, not `v1.0.0`.** Then five people. Explicitly out of scope: the Application Traversal Graph (AD-4), the TTK Supervisor (AD-5), Browser-Use / Copilot-Vision / OCR, browser extensions, and Google's jobs vertical if ruled parked. **Adding any of them restarts the clock.**

---

# THE ROOT

> **AA's verification stack checked SHAPE AND TEXT, not BINDING.**

| # | Instance | Status |
|---|---|---|
| 1 | port pin matched *method names* with no import check | **fixed, Batch 1** |
| 2 | reachability pin resolved the *module*, never the imported *name* | **fixed, Batch 1** |
| 3 | `aa_measure.py` claimed `compileall` caught unimportable modules | **fixed, Batch 1** |
| 4 | the mypy gate ran blind under `--explicit-package-bases` | **fixed 2026-08-29; closed by Batch 3** |
| 5 | **~34 pins still assert on raw source substrings** | open, RV-6 |
| 6 | `human_like_adapter.py:150` used a base class it never imported | **fixed 2026-08-30** |
| 7 | Appendix B — capability constructed, nothing calls it | open, **19 instances, 6 closed** |
| 8 | port-contract drift | **fixed, Batch 3** (R-5, R-7) |
| 9 | callers ignored `fill`'s boolean | **fixed 2026-09-04** (P1-e) |
| 10 | résumé upload swallowed its own failure | **fixed 2026-09-04** (P1-f) |
| 11 | three events published to nobody; FSM refused a transition with a warning | **fixed 2026-09-04** (P1-g) |
| 12 | kimicli discarded 5 of 7 blocks and reported "clean" | open, **T-1** |

**Four more instances found and closed 2026-09-04. Every one was found by EXECUTION, not by a gate:**

**9. A failed form fill was recorded as filled.** `fill()` never raised, so the success path always
ran. Closed by P1-e — `_required_fields_filled` now increments only on `True`.

**10. The résumé upload swallowed its own failure.** The raw stored path went to the file handler,
which resolved it against the process working directory, missed, and raised into a bare
`except Exception` that only logged. No event, no `_failed_required_fields` — **the fail-closed gate
submitted applications with no résumé attached.** Closed by P1-f.

**11. Three events published into a bus with no listener,** one of them a terminal hang. Closed by
P1-g. And a fifth variant inside it: the FSM **refused an invalid transition with a warning instead
of an exception**, so `_handle_captcha` transitioned to a state the table forbade and the machine
carried on with its state lying. The Bible documented the edge; the table was the liar.

**12. The tooling itself.** kimicli's parser matches `### FILE:` and nothing else, returns only what
it matched, and never counts what it discarded. A reply emitting 7 blocks staged 2 and printed
`PASS 1 clean`. **Shape checked, binding not — in the tool that applies the fixes for the other
eleven.** Still open: **T-1**.

---

# The Predicate Enumeration *(new, 2026-09-08 — the instrument)*

> **THE ROOT, generalised: a predicate answered independently in more than one place, with nothing
> checking the answers against each other.**

The three notations that produced this framing were the capability profile disagreeing with the
orchestrator about whether DISCOVER needs a browser, the event bus publishing to nobody, and the
state machine requesting transitions its own table forbids. They are the same defect in three
languages. The unit of work is therefore not "bugs" but **duplicated predicates**, and this table is
the census. Ranked by blast radius: rows 1–7 can silently produce a wrong result a user acts on.

**Verification column is honest.** `exec` means proven by running code or reading both sites with
line numbers. `read` means asserted from the source by Kimi and not independently checked.

| # | Predicate | Answering sites | Status | Ver. |
|---|---|---|---|---|
| 1 | Should this failed task be retried? | `orchestrator.py` `_dispatch_task` / `run()` / `_resolve_task_failure` · `database.py` `reschedule_for_retry` | **CLOSED 2026-09-09 (P5).** `_dispatch_task` now owns the failure outcome and `run()` marks a task complete only when dispatch succeeded, so the DB-backed retry and its backoff are live for the first time. The second, `context_data`-based retry path is deleted; the `<=` off-by-one and the new-id-per-retry churn went with it. **Unproven live — no test covers the new path.** | exec |
| 2 | Is a live browser available for discovery? | `registry.py` · `capability_profile.py` · `session_plan.py` · `orchestrator.py:1181` | **CLOSED 2026-09-09 (P6).** Cascade exhaustion refuses startup with `BrowserSetupError` before a session is constructed. `STATIC_ASSISTED` and `static_fetch` are deleted; `has_browser=False` now yields an empty `allowed_task_types` and mode `NO_BROWSER`. `discovery_requires_live_browser()` survives returning `True` unconditionally — an honest bridge until a follow-up collapses its call sites in `orchestrator.py`. | exec |
| 3 | Is the browser usable right now? | `orchestrator.py:1181` (None-check only) · `browser_monitor.py` `is_healthy()` · `resilient_driver.py` `is_alive()` | **OPEN.** Presence is not liveness — this is CB-10's mechanism. | exec |
| 4 | What kind of CAPTCHA is this? | `applications_workflow.py:1419` (writes `challenge_type`) · `orchestrator.py:929` (reads it correctly) · `captcha_adapter.py:52` (read `"type"` — wrong key) | **CLOSED 2026-09-09.** Was `"unknown"` on 100% of calls, making the `audio` branch unreachable. Proven before and after by execution. | exec |
| 5 | What is a failure? | `orchestrator.py` (four writers) · `context.py` · `session_report.py:137` | **HALF CLOSED 2026-09-09 (P5).** `context.py` now carries `applications_blocked`, `applications_errored`, `applications_unsuccessful` and `tasks_exhausted` — one writer each, populations documented — with `applications_failed` derived from the first three so it cannot drift from `SessionReport`. `update_stats` now raises on an unknown category instead of warning and discarding. **Still open:** `session_report.py`, `dashboard.py` and the GUI compute their own populations, and the four new counters have no reader outside `to_dict`. | exec |
| 6 | Is this application finished? | `applications_workflow.py:1436` (terminal outcome recorded) · `:1413` (queues a task presuming it is not) | **OPEN.** Measured gap between the two on a live run: mean 62.8 s, max 110 s. | exec |
| 7 | Has AA applied to this job before? | `applied_jobs` via `record_application_permanently` · `job_history` via `mark_applied` · `batch_scheduler.is_duplicate` · `throttling_filter` | **OPEN.** Two stores, two vocabularies, two write paths, each in its own swallowing try/except. | read |
| 8 | Where does a form field's answer come from? | `semantic_filler.py:21` `_DIRECT_MAPPINGS` · `rule_based_adapter.py:463` `_flatten_profile` | **OPEN.** Two independently maintained profile→answer maps over the same fields. Agree today by coincidence of authorship. | exec |
| 9 | Have we seen this URL? | `composition_root.py:699` · `orchestrator.py:211` · `database.py:569` | **CLOSED 2026-09-09 (P5).** Level 1 is real: `_is_duplicate_task` uses `check_and_mark` (APPLY-scoped, retry-exempt) instead of a read that could never return True. **Unproven live.** | exec |
| 10 | How does a suspended application resume? | `task_payloads.py:63` `parent_task_id` · `applications_workflow.py:1424-1425` `return_state`/`return_url` | **OPEN.** Two unwired resume mechanisms for one job. `parent_task_id` appears exactly once in the codebase — its own declaration. | exec |
| 11 | What type is a WorkUnit payload? | `orchestrator.py:654`, `:927`, `:1890` · `captcha_adapter.py:52` | **OPEN.** Constructed as a pydantic model, arrives as a dict; `get_next_task` rehydrates only `Job`. Four independent `isinstance` guesses. | exec |
| 12 | Is this page a block or challenge? | `applications_workflow.py` (raw substring scan) · `evasion/detection.py:74` `DefaultDetectionStrategy` · `evasion/manager.py:37` | **INSTRUMENTED 2026-09-09 (P4) — NOT YET ANSWERED.** Both verdicts are logged side by side with form/iframe counts, and `page_source` is dumped to `dev_data/detector_samples/` on disagreement, capped at 20 files across all sessions. **A single live run is the deliverable.** Note P4 added a temporary *third* instance — a 1:1 inline mirror of the weighted strategy — because the application layer may not import a secondary adapter (two pins, ceiling 0). It is dated and carries a deletion path. | exec |
| 13 | What locale is this? | profile `app_config.locale` · `i18n.py` · `selenium_provider.py` — all now via **`domain/services/locale_normalization.py`** | **CLOSED 2026-09-09 (P7).** One normaliser to ISO 639-1 + ISO 3166-1 alpha-2, placed in the domain layer because a secondary adapter importing an application service is a boundary violation at ceiling 0. `C`/`POSIX` and Windows language names map correctly; unrecognised values fall back without fabricating a file lookup and log what the OS actually said. `getdefaultlocale` is gone, so the Python 3.15 removal no longer bites. `configure()` is idempotent, which kills the three-configures-in-13-seconds spam. | exec |
| 14 | Is this environment low-resource? | `registry.py:73-75` thresholds, compared at `:311-313` with strict `<` · `capability_profile.py:73` | **OPEN, but less urgent since 2026-09-09.** RAM `< 2048`, cores `< 2`, disk `< 512`. The ASUS CX1100CN (4 GB, 2 cores) trips none of them, so the low-resource path cannot fire on the machine AA was designed for. With `static_fetch` deleted, a mis-firing threshold can no longer select a dead discovery mode — the question is now only about worker counts and browser choice. Criterion 4's USB run is the evidence that would settle where the thresholds belong. | exec |
| 15 | Must we throttle requests to this domain? | `network/throttler.py` + `network/robots.py` (built) · `base_provider.py:87` `safe_navigate` | **OPEN.** The docstring promises rate limiting and page-safety validation across ~20 lines; the body is `self.browser.get(url)` in a try/except and `return True`. | exec |
| 16 | Is this event heard? | publishers vs `subscribe()` | **OPEN.** 243 orphaned publications across 8 types in one 22-minute run: `TASK_SKIPPED_DUPLICATE` 113, `DISCOVERY_COMPLETE` 24, `JOBS_DISCOVERED` 24, `BROWSER_HEALTHY` 19, `APPLICATION_FAILED` 18, `JOB_VETTED_PASS` 18, `JOB_VETTED_FAIL` 14, `CAPTCHA_DETECTED` 13. | exec |
| 17 | Does this transition exist? | `state_machine.py` `VALID_TRANSITIONS` vs call sites | **OPEN.** `PAUSED → ERROR_RECOVERY` and `RESOLVING_CAPTCHA → AWAITING_HUMAN` have no edge; the second is worked around with an artificial RUNNING hop. Refusals warn instead of erroring, so the machine carries on with its state lying. | read |
| 18 | Is research enabled? | `registry.is_research_enabled()` · `ResearchConsentManager.is_active()` | Judgement, not defect — possibly a deliberate two-key system. Flagged because nothing says so either way. | read |
| 19 | Has the session ended? | `orchestrator.run()` (idles forever on an empty queue) · dashboards · `_teardown` | **OPEN.** No session self-completes, so the SessionReport is only written when the user kills the run. | read |
| 20 | Is the page ready? | `dom_observer.wait_for_dom_stable` · `resilient_driver._wait_for_ready_state` · `behavior.simulate_idle_time` | Near-cosmetic; three definitions for three moments. Listed for completeness. | read |
| 21 | What does `save_profile` return? | `profile_repository_port.py:44` (`-> object`, deliberately loose) · `profile_repository.py:171` (`-> Path`) · `profile_wizard.py` (needs a `Path`) | **OPEN, narrowed at the boundary 2026-09-09.** Found *by* the fix for row 10's sibling. Tightening the port breaks no caller in the tree (`settings_editor.py`, `app.py` onboarding, `import_profile`, `startup.py` — all single positional arg). | exec |

**How to use this table:** the graph is the instrument, criterion 1 is the ordering. Fix the rows on
the path to one submitted application first. Do not treat it as a backlog to burn down.

---

# The 2026-09-09 batches — nineteen files, and the nine reds they left

Two kimicli batches. **Batch A** (three sessions, manifests `d0ef6dc0`, `8d15876b`, `a3cf6995`,
`8c05cf1a`) made the CLI usable: nine files plus a pin, taking the suite from 1,264 to a verified
1,268 green. **Batch B** (one session, manifest `b7ebbb8d`, $6.71 over five calls) applied ten files
against predicates 1, 5, 9, 12, 13 and CB-8, and left the suite at 1,259/2/9.

**Batch B files:** `applications_workflow.py` (2458→2729) · `orchestrator.py` (1897→1964) ·
`context.py` (468→558) · `composition_root.py` (996→1063) · `registry.py` (749→766) ·
`browser_cascade.py` (304→310) · `capability_profile.py` (79→102) · `i18n.py` (444→514) ·
`selenium_provider.py` (660→673) · **new** `domain/services/locale_normalization.py` (198).

## The nine failures, with dispositions — this is P8's work order

**Seven assert behaviour that was never real.** Static discovery had no provider; these tests pinned
a mode name, not a capability.

  1. `tests/integration/test_static_mode.py::TestStaticCapabilityProfile::test_discover_allowed_in_static_mode` — delete or invert.
  2. `  same file ::test_vet_allowed_in_static_mode` — delete or invert.
  3. `  same file ::test_mode_name_is_static_assisted` — rewrite to `NO_BROWSER`.
  4. `  same file ::TestWorkUnitRejectionStaticMode::test_database_manager_allows_discover_in_static_mode` — invert: DISCOVER must now be **rejected** with an empty `allowed_task_types`.
  5. `tests/infrastructure/test_interaction_tool_wiring.py::test_static_mode_builds_without_a_tool_and_without_raising` — rewrite to assert `BrowserSetupError`.
  6. `tests/adapters/test_dom_readiness.py::test_static_mode_still_builds_with_no_driver_and_no_observer` — same disposition.
  7. `tests/infrastructure/test_reproducibility.py::TestCompositionRootNamespacing::test_build_orchestrator_make_rng_called_with_at_least_four_namespaces` — different in kind: its fake `acquire_driver` returns `None`, so the refusal fires inside a harness rather than a product path. Make the fake return a driver, or assert the RNG namespaces before the refusal.

**Two are genuine and were NOT predicted. Both are P8's first job.**

  8. `tests/infrastructure/test_mypy_gate.py::test_mypy_src_passes` — a real type error in shipped code:

         composition_root.py:990: error: Argument 1 to "join" of "str" has
         incompatible type "list[str] | None"; expected "Iterable[str]"

     `_refuse_no_browser` guards with `getattr(policy, "allowed_browsers", None)`, which mypy cannot
     narrow, then passes the attribute to `", ".join(...)`. A local variable and an explicit `is not
     None` check fixes it. **This is a live defect in the refusal path, not a test problem.**

  9. `tests/architecture/test_module_reachability.py::test_every_src_module_is_reachable_from_an_entry_point` —
     three modules orphaned by the deletion and correctly caught:
     `adapters/secondary/perception/bs4_adapter.py`, `adapters/secondary/network/urllib_http_client.py`,
     `domain/ports/http_client_port.py`. **The pin did its job.** P6 named the retirement and did not
     perform it — it is a manual `retire.py` step to `docs/old_retired_files/` with a ledger entry,
     per R-18. Nothing is deleted.

## What the batch left unproven

The retry reconciliation, the counter split and dedup level 1 all have **zero test coverage** — they
are correct by reading and by one another's construction, not by execution. P4's instrumentation has
never run against a live page. **Nothing in this batch has been proven on a real site.**

## Two prompt-writing lessons, both cheap to repeat

**Kimi types against the implementation signature when the caller holds the port.** It annotated a
callable `-> Path` from `ProfileRepository` while `startup.py` passes it through
`ProfileRepositoryPort`, which declares `-> object`. Check port declarations before accepting any
`Callable[...]` annotation.

**A prompt instruction can collide with a pin, and the pin should win.** P4 was told to import
`DefaultDetectionStrategy` into `applications_workflow.py`. That is an application→adapters import,
which two pins forbid at ceiling 0. Kimi refused, mirrored the logic inline instead, and flagged the
cost — a temporary third instance of the very predicate it was measuring. **The prompt was wrong and
the model was right.** Check the boundary table when a prompt names an import.

---

# Critical Blockers

## CB-1 — Google yields nothing — root-caused, measured, bounded
Three architectures measured in one live run:

  ```
  Bing   18 cards, identity at +10 ['id','data-jobid','data-k','data-url']        -> 3 jobs resolved
  Google 30 cards, identity at +3  ['id','data-async-fc','data-fc-up','data-preview-id'] -> 0
  Indeed  4 cards, marker_frac=0.00, no identity, no titles                        -> 0
  ```

Google's activation reveals 12 anchors — eight `Apply on X` wrappers whose payloads are **encrypted
protobuf**, plus two company searches. They cannot be decoded locally and cannot be title-aligned,
because there is nothing readable inside to align with. **The opaque-uniform stop detects this after
ONE activation attempt** and skips the other 29 cards.

**R-16 remains unruled** and the evidence has hardened: (A) the second hop is now *known* to yield
only opaque wrappers, so it buys nothing without following each one over the network; (B) ordinary
Google web search has real anchors and would work through today's code unchanged; (C) drop Google.
**Only A preserves R-1, and A is now the weakest of the three on evidence.**

## ~~CB-8 — The static path: three answers to one question~~ — **CLOSED 2026-09-09 (P6)**
Ruled 2026-09-08: **delete the pretence.** A mode name with no implementation behind it is capability
built and never connected — THE ROOT, flavour one. Cascade exhaustion now refuses startup with an
actionable terminal message and `BrowserSetupError`; `STATIC_ASSISTED`, `static_fetch` and the
`"static"` cascade candidate are gone. **R-12 and R-13 are answered by the deletion.** Still open:
`domain/models/browser_candidates.py:35` still appends the `"static"` candidate (filtered at the
cascade instead, because P6 did not own that file), and `orchestrator._requires_browser` /
`_ensure_browser_active` are untouched by design. Historical detail retained below.

- `registry.py:706` sets `has_browser` from the cascade's real result and drives `STATIC_ASSISTED`.
- `registry.py:413-422` sets `discovery_strategy = static_fetch` **only** inside `if is_low_resource:`.
- `registry.py:463` and `session_plan.py:189` read only `discovery_strategy`.
- **Second half:** `base_provider.py:69` returns `requires_live_browser = True` for every provider, so static mode registers `providers=0` even once the raise is fixed.
- **R-12 unruled. This is the primary persona's path**, and it is now the largest untested surface in the project.

## CB-2 — Google rate-limiting — **not reproduced in four consecutive runs**
`/sorry/` has not appeared since 2026-08-30 despite unchanged scroll behaviour. **The teleport is
therefore weak as an explanation** (see AD-10, R-19). Detection works and fails closed.

## ~~CB-4~~ spaCy guard · ~~CB-5~~ suite collects · ~~CB-6~~ gate sighted · ~~CB-7~~ interruption handler — **CLOSED**
CB-7 is closed as a wiring defect and **still unproven live** — no overlay has been dismissed on a
real site. Release criterion 1 is its proof.

---

# Pending Tasks (by Priority)

## ~~P1-e / P1-f / P1-g~~ — **ALL CLOSED 2026-09-04**

**P1-e — a failed form fill recorded as filled.** Closed at `applications_workflow.py:860`, `:997`,
`:1099`. Each `else` publishes `FORM_FIELD_FAILED`; `_required_fields_filled` increments only on
`True`.

**P1-f — the documents contract.** Four defects, all confirmed by execution, all closed:
the upload site now resolves through `get_resolved_resume_path()` / the new
`get_resolved_cover_letter_path()`; one shared `is_document_path` predicate decides prose-vs-file;
the `cover_letter` validator no longer path-normalises prose (it was collapsing `//`, breaking every
URL, at construction *and* on every assignment); an unresolvable document is now evidence, not a
swallowed warning. Plus a **cross-OS** defect found by the pins on Windows: relative document values
are now stored in **POSIX form** always, with a raw-first separator fallback so profiles already
written on Windows still resolve. A profile written on Windows could not find its own résumé on
Linux or macOS — the USB scenario AA exists for.

**P1-g — three events published into a bus with no listener.** CAPTCHA escalation now routes through
the working HITL channel (`HUMAN_APPROVAL_REQUESTED`, both dashboards, a real release path);
`PROVIDER_TIMED_OUT` re-queues; `REDIRECT_TO_LIST_DETECTED` enqueues a Discovery WorkUnit. The
`RUNNING → RESOLVING_CAPTCHA` and `RESOLVING_CAPTCHA → STOPPING` FSM edges were added — the table
disagreed with both the code and `AA_ARCHITECTURE_BIBLE.md:384`, and refused the transition with a
warning rather than an exception.

**STILL OPEN from P1-f:** `rule_based_adapter.py`'s cover-letter branch (`_solve_file_upload`,
~line 415) reads `cover_letter` raw on the FormSolver plan path. It gets POSIX storage for free but
never goes through the resolver, so a legacy Windows-form value misses the fallback there.

---

# The 2026-09-04 live runs — what they proved and what they found

**PROVED (three runs, GUI, `--debug`):**
- The CAPTCHA round trip works **end to end with a human in it**:
  `HITL gate open … subscribers=2` → `HITL resumed | choice='skip'` →
  `AWAITING_HUMAN → RUNNING (triggered_by=hitl:granted)` → `Task complete | duration=80.4s`.
  Twenty-four hours earlier this was a terminal hang that published into silence.
- The subscription race is fixed. Run 1 showed `subscribers=1` and the Dashboard subscribing
  *after* the publish; run 3 shows `subscribers=2` at gate-open.
- The gate also **times out** (300s) and releases rather than hanging.
- Ghost tasks are gone: run 3's CAPTCHAs are real `cf-turnstile` challenges on live ZipRecruiter
  URLs, not a 9-hour-old `expired_jd_redirect` task restored from a checkpoint.
- Discovery returns real jobs: `discovery verification [PASS]: 8 jobs` — eight London backend roles
  from LinkedIn and Glassdoor via Bing.

**FOUND — new, measured, not yet fixed:**

## CB-9 — `resolved=0` on every provider, every run *(new, 2026-09-04)*
`analyze_serp` reports cards found and cards resolved. Across all three engines it resolved **none**:
  - Bing `cards=18 resolved=0` — yet the strategy still produced 8 jobs, so Bing's yield comes from
    a different path entirely and the resolver contributes nothing.
  - Google `cards=30 resolved=0` → `Total unique jobs: 0`. **Google is a 100% loss.** Its jobs
    surface (`udm=8`) puts the listing in a side panel with no followable URL on the card — which is
    exactly what was observed on screen.
  - Indeed `cards=4 resolved=0 level=detected`.
The math resolver is running on every page and resolving nothing anywhere. Whether that is a bug or
a subsystem that was never actually load-bearing is the question to settle — it bears directly on
**CB-1** and on AA's central claim of zero-shot comprehension.

## CB-10 — the driver dies and 23 navigations fail loudly, then quietly *(new, 2026-09-04)*
After the second HITL skip: `Navigation failed: Message: invalid session id` × 23, and the run
finished with `discovery verification [PASS]: 0 jobs`. A dead driver produced a **PASS** verdict on
zero jobs. Verification that passes when the browser is gone is not verification.

## P2 — Activation budget is spent re-discovering known jobs *(new)*
One session, three rounds: 8 attempts → 3 jobs → **enqueued 3**; 8 → 6 → **enqueued 3**; 8 → 6 →
**enqueued 0**. Dedup is correct; the *clicks* are wasted. Resolutions are not cached across rounds.
Cheapest fix: key them by the learned identity value and skip cards already resolved this session.

## P2 — Bing's per-page ceiling is the activation budget
18 cards, budget 8 → **at most 8 jobs per page, ever**. A designed bound, not a defect, but it caps
yield. → RV-8

## P2 — Indeed serves a 4-card, title-less page and the block gate does not fire
`analyze=0.00s cards=4 marker_frac=0.00`, no CAPTCHA verdict, no abort. Either a genuinely thin page
or a block shape `PageClassifier` does not recognise. **The D5 gate is in place and did not classify
it as blocked** — worth checking, because a block counted as an empty harvest poisons the
degradation baseline.

## P2 — Harvest time grows with page size (explained, not a leak)
Marginal cost ~**60 ms per additional candidate**, flat: the page grows ~1,400 px per scroll,
candidates ~570, and the miner is O(candidates) at roughly ten WebDriver round trips each. **Largely
moot on the fast route** (0.4–0.7 s); it returns only if a provider falls back to the miner.

## P2 — `ApplicationEvidence` accepts unknown fields (R-7 original, ruled: both layers) → RV-1

## ~~P2 — Logging honesty~~ — **CLOSED, both halves**
- `logging_setup.py:128-132` mutes the selenium wire logger at WARNING, with the 96–98% measurement
  in the comment. The USB blocker is gone.
- `log_filter.py` uses `(?<!\w)`/`(?!\w)` lookarounds instead of `\b` (protects the 32-char task
  IDs) plus `\x00`-sentinel two-phase substitution (kills the re-match).

## P2 — `posting_hash` / `form_shape_hash` (R-8, ruled)
Identity (normalised URL) and shape are different questions. Recorded fragility: `sorted(classes)` over rotating obfuscated class names is not stable across days.

## P3 — Fast-route hard bound (FR-205) · Screenshot and logging path defects
Unchanged.

## P3 — DISCOVER dispatches at priority 5
A **live wiring bug on the GUI queueing path**, not a stale row — two sessions produced two different new task ids, both at priority 5, where `TaskPriority.DISCOVER` is 100.

## ~~P3 — i18n locale resolution~~ — **CLOSED 2026-09-09 (P7), after six sightings**
`locales/english.json`, `locales/c.json` and `locales/none.json` — a language *name*, a POSIX
placeholder and a literal `none`, all used where an ISO code belongs, warning on every run since
2026-08-11. Now one normaliser in `domain/services/locale_normalization.py`, consumed by both
`i18n.py` and `selenium_provider.py`. See predicate 13.

---

# Architectural Debt

## AD-11 — Discovery resolution: what was built *(new, 2026-09-03)*
The URL problem is solved generally. Seven stages, none of which knows any vendor:

1. **detect** — structural card grouping (unchanged, S8f).
2. **climb** — the detector returns the *smallest* repeated unit; the addressable unit is usually above it. Walk up while one-node-per-card holds; stop at collapse. **Measured: Bing +10, Google +3, Rippling and DuckDuckGo +0.**
3. **identity** — sibling-diff attribute learning: same name + same value is chrome; same name + distinct values is identity. Tracking-shaped, positional and non-page-unique names excluded.
4. **static** — resolve from in-card anchors first; **no click needed** on anchor boards.
5. **relocate** — re-find the live element by learned identity; abort if not unique.
6. **activate** — click, diff anchors, record navigation; bounded at 8/page with an opaque-uniform early stop.
7. **classify** — reject by scheme, dead-end text and **whole-URL advertising evidence**; unwrap wrappers through a stdlib codec ladder; rank by title alignment; **fail closed**.

**Proven on four architectures, two of which AA had never seen:** Bing (identifier + decodable
wrapper → resolves), Rippling ATS (anchor board → resolves with no click), Google (identifier +
opaque wrapper → fails closed), DuckDuckGo (first-party ad → **rejected**, which is the point).

## AD-10 — The scroll primitive teleports
`window.scrollTo(0, document.body.scrollHeight)` every 2 s. Fully agnostic; **no card coupling**.
Instrumented since Batch 2: `height 1911 -> 3283 -> 4707`, viewport bottom equal to the previous
height each time. **Four runs, no `/sorry/`**, which weakens the CB-2 link. The humanised scrollers
(`PageActionService.scroll_page`, `behavior.human_like_page_scan`) remain orphaned;
`heuristic_adapter.py` is recovered and retired, so the route back exists. → **R-19**

## AD-9 — ~~The fast route is wired into one provider~~ — **CLOSED**
All three providers pass `fast_extractor`; every provider logs `via fast:deferred`.

## AD-1 — Scroll & pagination: memo ruled, unimplemented — the fix for AD-10
Option C in full: one `ScrollPort`, cadence as declarative data, plus the missing
`scroll_container(element, dy)`. Humanised default, `instant` opt-in (R-4), cadence "a fast human" (R-3).

## AD-2 / AD-3 / AD-6 / AD-4 / AD-5 / AD-8 — unchanged
ADR-013 supersedes ADR-003; `ApplicationState` and `TaskLifecycleState` still orphaned.
`domain/exceptions.py` double definitions (R-9). Dead config surface (R-11 → RV-4).

---

# Review Register

| # | Item | Reservation |
|---|---|---|
| RV-1 | `ApplicationEvidence` two layers | Runtime + author-time, not either/or |
| RV-2 | Mouse/click consolidation | Deferred out of AD-1 |
| RV-4 | Dead config surface | Exemption list + pin rather than removal |
| RV-5 | The two exemption dicts | 50 modules + 22 ports, each with a reason and a tag. `MAX_EXEMPTIONS` is a ceiling, so the count can only fall. |
| RV-6 | The substring pins | **~34 remain.** Convert opportunistically using `_binding.py`; do not schedule it. |
| RV-7 | The retirement directory | Nothing is deleted. **Check the ledger before building anything new.** Risk to watch: a directory that only grows becomes a second codebase nobody reads. |
| **RV-8** | *(new)* **The activation budget as a constant** | 8 clicks/page is a bound with a real reason — an opaque architecture must not consume unbounded rate-limit budget — but it silently caps yield at 8 jobs/page. Make it config with the reason attached, not a literal. |
| **RV-9** | *(new)* **Apply-intent is one English word** | The classifier's apply-intent signal is `"apply"`. A non-English panel scores 0 on it and degrades to overlap/external/pending. Acceptable now; localisation debt with a known shape. |

---

# T-1 — kimicli silently discards blocks it does not recognise *(open)*
Measured: a reply emitting **7 blocks across 4 files** (5 `### PATCH:`, 2 `### FILE:`) staged **2**
and printed `PASS 1 clean: 2 file(s) OK`. The dropped hunks were sound — all five anchors matched the
tree exactly once. Applying the staged subset alone aborts pytest **collection**. `FILE_BLOCK`
(`kimicli.py:386`) matches `### FILE:` only; `parse_file_blocks` (`:395`) returns just what it
matched; the string "PATCH" appears nowhere in 1,648 lines. **The block accounting matters more than
PATCH support** — any unrecognised shape vanishes the same way. Prompt written:
`prompt_patch_support.txt`. Note `kimicli.py` is in `PROTECTED`, so the fix is hand-applied.

**Second measurement, 2026-09-09 — a truncated emission is silent too.** A resume turn that runs out
of output budget mid-file leaves the opening ```` ```python ```` with no closing fence, so
`FILE_BLOCK` matches nothing for it and the earlier files stage without a word about the missing one.
A prompt demanding two files staged one. The tell is an **odd fence count** in the reply. The lost
file was `context.py`, and applying the staged half alone would have been worse than the defect it
fixed — the emitted `orchestrator.py` wrote six stat categories the un-emitted `context.py` was to
define, so every failure count in the product would have silently become zero. **Standing check:
after every call, compare the staged-file count against the count the prompt demanded, and treat any
shortfall as truncation until proven otherwise.** Recovery is a same-session resume naming only the
missing file and forbidding re-emission of the staged ones — measured 98% cached, $0.47.

---

# PKG-1 — Packaging, entry points and environment *(new, 2026-09-04 — NEXT)*

The dependency graph does not currently tell the truth, and three separate things depend on it: the
disposable-execution research, CI, and every new contributor.

- **`run.bat:166` runs `python -m pip install -e "<dir>[dev]"`.** There is no `dev` extra in
  `packages/auto_apply/pyproject.toml` — the extras there are `nlp`, `semantic` and friends. `black`,
  `mypy`, `ruff`, `hypothesis` and `pytest-mock` live in the **workspace-root** `[dependency-groups]
  dev` (PEP 735), which **pip cannot read**. So AA's own launcher installs nothing, and `run.bat test`
  then aborts on `import hypothesis`. Same broken instruction survives in `CONTRIBUTING.md` §1.1.
- **`run.bat` + `run.sh` are ~400 lines duplicating what one tool already does** from `pyproject.toml`
  — resolve, install, create the environment, lock versions, run the entry point, on all three OSes.
  That is a DRY violation, a single-source-of-truth violation, and platform-specific code standing in
  for a platform-agnostic tool.
- **`numpy` is imported by ZERO files in `src/`** (one test file uses it) and is declared in neither
  pyproject — it arrives transitively. Yet its stubs are the sole reason the root `pyproject.toml`
  sets **`python_version = "3.12"`** for mypy while `requires-python` stays `">=3.10"`. **The type
  gate now checks AA against 3.12 semantics while AA claims to support 3.10**, so 3.11/3.12-only
  syntax would pass the gate and break on a 3.10 machine. Ruff is the only thing still holding the
  floor. Get numpy out of the runtime graph, put `python_version` back to 3.10.
- **No `uv.lock` is committed**, so CI resolves fresh every run. The beautifulsoup4 stub upgrade
  (4.14.3 → 4.15.0, two new errors on an identical tree) is what that costs.
- **No default dependency layout declared** — optional extras, dev group and runtime deps are not
  cleanly separated.

Target: `pyproject.toml` as the single source of truth for what AA is, needs, builds as and is
entered by; one tool driving it on all three OSes; the shell scripts retired to
`docs/old_retired_files/` with a ledger entry. **Do this before the disposable-execution research**,
which audits this same graph.

---

# Next Steps

1. **P8 — get back to green. Nothing else starts until criterion 3 is met again.** Two real fixes
   (the `composition_root.py:990` mypy error, the three orphaned modules retired via `retire.py`)
   and seven test rewrites, all with dispositions written out under *The 2026-09-09 batches*.
   **Fresh kimicli session** — the P4–P7 conversation is at ~975k tokens and a sixth turn would be
   capped. Regenerate `AA-kimi.txt` first: nineteen files changed and one module is new.
2. **Run P4's instrumentation once, live.** One short session answers predicate 12: whether 13 of
   18 blocked applications were real gates or a substring scan inventing them. **Everything about
   gate-crossing waits on this**, and the scaffolding is already in the tree with a deletion path.
3. **The CAPTCHA suspend/resume contract (predicate 10).** Ruled option A — synchronous, in place,
   implemented as a resolver behind the existing `ResolutionInterface` port. Needs P4's measurement
   first, and collides with `orchestrator.py`, so it is its own session.
4. **One real application** (criterion 1). Nothing in the 2026-09-09 batches has been proven on a
   real site; the retry reconciliation, the counter split and dedup level 1 have zero coverage.
5. **CB-9 — `resolved=0` everywhere**, 180/180 samples in the 2026-09-08 run.
6. **Predicate 3** — presence is not liveness; `_ensure_browser_active` is a None-check while a
   health monitor sits unconsulted. This is CB-10's mechanism.
7. **Predicate 15** — `safe_navigate`'s docstring promises rate limiting and page-safety checks its
   body does not perform. The throttler and robots policy are built and unconsulted.
8. **`uv.lock` committed + CI flipped to blocking.**
9. **T-1 — kimicli block accounting**, now with two measured failure modes: unrecognised block
   shapes, and silent truncation. Cheap, hand-applied, protects every change after it.
10. **The USB run** (criterion 4) — measurement first. It is also the evidence that would settle
    predicate 14's thresholds.
11. **Honest README + `DISCLAIMER.md`** — must carry the measured ChromeOS boundary: AA requires a
    local shell and a Python interpreter; crosh provides neither and Crostini is disabled by policy
    on most managed school and library devices. **AA cannot run on a locked-down managed Chromebook.**
    A measured limit of the platform, not a bug in AA — and a research finding about who automation
    tooling structurally excludes.

**Applied 2026-09-08/09, do not re-run:** `P1_enumeration_and_challenge_type.md` ·
`P2_environment.md` + `P2fix_portable_firefox.md` + `P2fix2_stdout_encoding.md` ·
`P3_cli_ux.md` + `P3fix_vault_downgrade.md` + `P3fix2_save_callable_typing.md` ·
`P4_detector_instrumentation.md` · `P5_orchestrator_retries_counters_dedup.md` +
`P5cont_context_py.md` · `P6_delete_static_assisted.md` · `P7_locale_predicate.md`.

**Standing check, learned the hard way:** after every kimicli call, compare the staged-file count
against the count the prompt demanded. A shortfall means truncation, and truncation is silent.

**Applied 2026-09-04, do not re-run:** `prompt_documents.txt` (P1-f) · `prompt_events.txt` (P1-g)
· `prompt_ci.txt` (CI). Written and not yet run: `prompt_patch_support.txt` (T-1),
`prompt_docs_revamp.txt`, `prompt_execution_architecture.txt`.

**Standing method:** trace before writing · reuse before creating · **check `old_retired_files/`
before building** · teeth-proven pins · anti-orphan proof · honest pin labels · one all-or-nothing
change per stage · verify by execution · own mistakes plainly.

---

# Appendix A — Completed (do not redo)

**Config / Startup / Discovery / Tools arc (S1–S7) / Performance (S8b–S8f):** typed `EffectiveConfig`; session-cap gate; proxy fail-closed; ADR-011 pipeline priority; the three-verb interaction protocol; ADR-012 fail-closed submission gate; ruff F821 gate; occlusion guard; `DOMNode.__hash__` fix (~1,200×); the card detector.
**2026-08-29/30:** CB-5 · CB-6 · 41 of 69 type findings · S8f proven live · CB-4 proven live · `--debug` reaches the console.
**Batch 1 (2026-09-01/02) — "make the gates tell the truth":** `_binding.py` · port pin fixed (24 → 22, measured) · reachability `BROKEN INTERNAL NAME` + regression fixture · `MAX_EXEMPTIONS` ceilings (**R-17**) · 50 + 22 exemptions with reasons and tags (**P1-c, P1-d**) · brittle interruption pin converted to AST · `aa_measure.py` comment corrected.
**Batch 2 (2026-09-02) — "make discovery observable and human":** fast route into all three providers (**AD-9**) · per-scroll observability · per-phase harvest timing · degradation guard wired to Indeed.
**The URL arc (2026-09-02) — discovery resolution:** `url_evidence.py` · `card_static_resolution.py` · `card_activation.py` · `DiscoveryObservation` + `observe_discovery` · the climb · sibling-diff identity · whole-URL ad rejection · the wrapper codec ladder · fail-closed classification · bounded activation with an opaque-uniform stop. **60 synthetic-shape pins. Proven live.**
**Batch 3 (2026-09-02/03) — "triage the 28":** R1 narrowing · R2 portable paths + round-trip pin · R3 argparse validation · R4 Literal-safe selections · R5 port narrowed to the implemented contract · R6 salary guard + teeth pin · R7 port declares `fill -> bool` · R8 all eight singles.
**2026-09-04 — verified by execution:** Batch 3 applied (type gate 0) · **P1-e** closed at all three `fill` sites · **P1-f** documents contract closed (4 defects + the cross-OS separator defect) · **P1-g** three events wired, CAPTCHA HITL round trip proven live · **P2 logging honesty** closed both halves · `.github/workflows/ci.yml` committed · **suite 1,264 passed / 0 failed**.
**Tooling and policy:** kimicli hardened (`PROTECTED`, `ACCOUNT_TPM`, `Session.cache_key`, `METHOD_RULES` + `APPLIER_CONTRACT` in the cached prefix) · retirement policy + `retire.py` + ledger · all four deleted modules recovered from git and retired.

---

# Appendix B — "Built and never connected"

**Canonical. Count: 21, of which 6 are closed.**

| # | Instance | Status |
|---|---|---|
| 1–4, 8 | `PageActionService` · `execute_plan`/`FormSolver` · `EffectiveConfig` accessor · `analyze_serp` · `record_outcome` | **fixed** |
| 5, 6 | PRA loop / `ApplicationState` · `TaskLifecycleState` | open (AD-2) |
| 7 | `honeypot_detection` + `entropy` + `occlusion` — dead **as one chain** | open — **keep and wire** |
| 9 | `JobCardInfo.confidence` — the recorded doubt nobody reads. **Still written by `resolve_card_group`; still unread.** | open, low priority |
| 10 | `PaginationHandler`'s 4-strategy cascade — `max_pages_per_query=1` makes `range(1,1)` empty | open (AD-1) |
| 11 | The humanised scrollers — orphaned via `HeuristicFinder`, **now recovered and retired, so the route back exists** | open (**AD-10**) |
| 12–15 | `fingerprint_js` · `telemetry` · `heuristic_adapter` · `location_extractor` | **retired 2026-09-02**, recoverable. `telemetry.py` is a working Bayesian confidence tracker `PageActionService` was meant to consult |
| 16 | `selector_loader` + `toolbar_locator` | open, exempted `WIRE-LATER` |
| 17 | `FeedbackRepositoryPort` — adapter built and constructed, no consumer | open, exempted `WIRE-LATER` |
| 18 | ~~`fast_extractor` passed by one provider of three~~ | **CLOSED, Batch 2** |
| **19** | *(new)* **`DiscoveryObservation`** — the record is built and emitted; `ResearchSignalAggregator.observe_discovery` logs and counts but **writes no rows**. The consumer batch is unwritten. | open, **by design and disclosed** |

| **20** | *(new, 2026-09-09)* **`bs4_adapter` · `urllib_http_client` · `http_client_port`** — orphaned by the STATIC_ASSISTED deletion; the reachability pin caught all three. Retirement to `docs/old_retired_files/` is a manual `retire.py` step, not yet done. | open, **red pin** |
| **21** | *(new, 2026-09-09)* **The four new failure counters** — `applications_blocked`, `applications_errored`, `applications_unsuccessful`, `tasks_exhausted` are written with one writer each and read by nothing outside `to_dict`. Deliberate: `session_report.py`, `dashboard.py` and the GUI are a follow-up's scope. | open, **by design and disclosed** |

**Outside AA:** `kimicli.py` defined `APPLIER_CONTRACT` and no code path read it — **fixed
2026-09-02**. The defect class is a property of how work is done, not of this codebase.

---

# Appendix C — Environment facts (hard-won, keep)

- Two Python environments. **Canonical, from `packages/auto_apply`:** `..\..\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`. Never bare `python`.
- **kimicli.py, retire.py and probe_v4.py live in the repo ROOT.**
- **A bare `webdriver.Chrome()` is served `/sorry/index` instantly; AA's `BrowserCascade` reaches the real SERP.** Any probe must go through the cascade.
- **Google's job cards carry zero anchors** and open a side panel by jsaction; activation reveals `goto?url=` wrappers whose payloads are **encrypted protobuf** — not base64, not decodable offline.
- **Bing's `ck/a?u=` payload is base64 with a two-character prefix** and decodes offline to the real posting. Rippling's ATS cards carry ordinary relative anchors.
- **DuckDuckGo serves first-party ads on its own host** (`y.js?ad_domain=…&ad_provider=…&ad_type=…`). A host-only ad rejector misses them; the signal is in the query keys.
- **`compileall` does not catch a module that cannot import.** Only a real subprocess import does.
- **kimicli cannot create a file whose basename exists elsewhere**; cannot delete or move files.
- **kimicli's `FILE_BLOCK` regex truncates fenced markdown** at the first column-0 fence. Indent every fence in this file two spaces; never pass `--allow-shrink` to force one through.
- **The shrink guard has caught two real losses:** a truncated `AA_MASTER_TODO.md`, and a blind test-file rewrite that would have deleted 18 passing pins. Trust it.
- **Kimi K3 has no fixed output ceiling** — `--max-completion` is honoured; one call returned the full 90,000. An earlier 16,384 was the model stopping, not a cap. Long answers arrive in pieces; `--resume last --prompt "<continue>"` picks up at 86–97% cached.
- **kimicli's local token estimate runs 18–29% high.** Budget from the exact figure the preflight prints.
- **A full batch costs ~$1.60 in plus output.** The URL arc cost $8.28 over three calls; Batch 3, $3.44 over two.
- **Never retire personal data.** `dev_data/`, screenshots, logs, `.env`, résumés, live-run fixtures. The retirement directory is committed and shipped to everyone who clones AA.
- **kimicli has no `--prompt-file`.** `--prompt` takes prompt text **or a path** to a `.txt`/`.md` file.
- **`DEFAULT_MAX_COMPLETION = 131_072`.** A smaller `--max-completion` *lowers* the ceiling. Omit it.
- **kimicli parses `### FILE:` and nothing else.** Other shapes are discarded with no counter — T-1.
- **The cached prefix carries three blocks:** `METHOD_RULES`, `APPLIER_CONTRACT`, `CODE_CONTRACT`. The last tells the model to propose a smaller change rather than reproduce a large file — a prompt must **explicitly override that line** when the defect lives in a 2,000-line file.
- **`AA_MASTER_TODO.md` is injected as `<authoritative_todo>`** and supersedes docstrings — a stale line here outranks any prompt. It is also part of the cached prefix, so **editing it invalidates the cache**: measured, the first call after a TODO edit ran 0% cached ($3.32), the next 100% ($1.40). Batch prompts against one warmed prefix.
- **Omitting `--request-code` does not reliably hold code back** — a "rule the fork first" turn staged all 7 files anyway, and the follow-up re-emitted them byte-identical for $1.08. Send single `--request-code` calls and spend the second call on what execution finds.
- **`kimicli.py` and `callapi.py` are `PROTECTED`** — the applier refuses to write the tool itself.
- **Résumé paths are stored relative and resolved at runtime** — an absolute `Path` carries a drive letter and breaks when the stick mounts as a different letter. `get_resolved_resume_path()` is the accessor; use it.

---

## kimicli cost model — measured 2026-09-08/09

**Fresh calls never hit the context cache.** Two non-resumed calls against an identical prefix
(same dump, same TODO, same rules) nine minutes apart both reported **0% cached** at ~$2.70 each.
Every cache hit on record is a `--resume` turn. The prompt text sits inside the cached region, so a
differing prompt breaks the prefix by construction.

**A resume only hits if it is fired within minutes.** Three resumes sent shortly after the previous
turn ran 97% / 95% / 98% cached at $0.54–0.59. A fourth on the same session, sent after a gap spent
applying files and running the suite, ran **0% cached, $2.61**. The TTL, not the resume mechanism,
is the binding constraint.

**Therefore:** write every prompt in a chain before firing any of them, fire them back-to-back in
one sitting, and save applies and test runs for afterwards. Editing this file invalidates the prefix,
so batch TODO edits to a moment when the cache is already cold. **Measured on the P4–P7 chain: one
fresh call plus four resumes at 93% / 96% / 97% / 98% cached cost $6.71 total, against roughly $14
if each had been fresh.**

**The window fills, and the cap arrives silently.** On a long resume chain the preflight starts
capping output as the conversation grows — "capping output at 113,895" by turn 4, 73,678 by turn 5,
against a ~1.05M window. A four-to-five-turn chain on a ~975k-token conversation is at the ceiling.
**That cap is what truncated `context.py` mid-file.** Start a fresh session rather than adding a
sixth turn, and regenerate the dump first so the new session sees current code.

Also measured: preflight's local token estimate runs 22–27% high · default `reasoning effort = max`
bills as output (~10–40k tokens, $0.15–0.60 per call) · **PowerShell has no backslash escape, so any
`\"` inside a `"..."` argument silently terminates the string and the rest is parsed as PowerShell.**
Pass anything with embedded quotes as a script file, never as `python -c`.

---

## Rulings — status

| # | Section | Status | Decision |
|---|---|---|---|
| R-1 | CB-1 | **RULED** | Strengthen the *general* capability; do not special-case Google. **Honoured throughout the URL arc.** |
| R-2 … R-11 | various | **RULED** | Flush per round · AD-1 Option C · humanised default · P3 reclassification · spaCy guard · both layers · identity vs shape · exceptions renamed · repo URL · keep-all-with-exemptions |
| R-15 | P1-b | **SUPERSEDED** | Was "delete all four"; **all four recovered and retired 2026-09-02.** Nothing is deleted. |
| **R-12 / R-13** | CB-8 | **RULED 2026-09-08 · BUILT 2026-09-09 (P6)** | **Delete the pretence.** Static discovery was never implemented — no provider exists that runs without a driver. A missing browser becomes an explained refusal at startup, not a degraded session that idles. Option A (build static discovery) does not earn the word "mode" until a spike measures whether plain-HTTP discovery yields anything at all. The single source of truth is the cascade's real result, consumed at the composition root. |
| R-17 | Pins | **RULED · BUILT** | `MAX_EXEMPTIONS`, a ceiling. A lower count is success. |
| R-18 | Retirement | **RULED · BUILT** | Nothing is deleted. `docs/old_retired_files/` + ledger. **Check it before building.** |
| **R-5** | P1-a | **RULED · BUILT (Batch 3)** | **Narrow `ILogicSolver` to the implemented contract** — `solve(aom_nodes) -> dict[str, str]`. A port is a promise to consumers; the only honest promise is the implemented one. A future generic ASP consumer gets a *separate* port, never a widened union. `asp_adapter.py` needed no change: the error was in the port. |
| **R-14 / R-7** | P1-a | **RULED · BUILT (Batch 3)** | **`InteractionPort.fill -> bool`.** Filling a form field is not clicking a button: one unfillable optional field must not abort a 20-field application. Rejected: raise-like-click (wrong failure mode for the person relying on AA), result object (over-engineering for zero callers). `human_like_adapter.py` needed no change. **Callers must now honour the boolean — see P1-e.** |

**Open rulings:**

| # | Question |
|---|---|
| **R-16** | **The Google fork** (CB-1): (A) second hop — now measured to yield only opaque wrappers · (B) ordinary web search, which has real anchors and would work through today's code · (C) drop Google. Only A preserves R-1, and A is now the weakest on evidence. |
| **R-19** | **The scroll cadence** (AD-10): keep the teleport, adopt AD-1's `ScrollCadence`, or take an interim viewport-height step? **Four runs with no `/sorry/` weaken the CB-2 justification**, so this is now a stealth-posture question rather than a rate-limit fix. |
| **R-20** | *(new)* **Client-rendered / virtualized boards.** A learned identity attribute can point at a recycled row — a wrong-URL failure with no visible symptom. What detects such a page, and what is the smallest staleness guard? Scoped, not built. |

---

## A standing instruction to whoever builds these

Each item is scoped to finish in one stage, with one change file and one predicted test count.

**Do not treat any proposed solution here as the answer.** Measurement has an unbroken record of
overturning reasoning in this project. **This revision alone records five reversals:**

- a proposed port-pin fix was measured and made the report **worse** (24 → 33 flags);
- the "card boundary is one level too deep" option was dismissed by two models and turned out to be
  right — identity sits **ten** levels above the detected node on Bing;
- `Path | None` was recommended for résumé paths and would have broken USB portability, which the
  model's own docstrings already explained;
- a probe's looser title scorer slipped into production and re-opened the tab-bar hole the S8e fix
  closed;
- the anchor-ancestor hypothesis that motivated the whole investigation was refuted by one devtools
  search.

**Every one of those was caught by running something. Not one was caught by reading.**

**The lesson this document exists to record:** the 2026-08-01 version was right on its date and wrong
in almost every count four weeks later. The 2026-08-29 version was wrong in five counts within
twenty-four hours. **It rots at the speed of the work.** Update it in the change that makes it false.

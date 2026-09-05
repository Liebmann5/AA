# AA — Master Outstanding-Work Reference

**Purpose:** single authoritative inventory of everything in AA that is unfinished, broken, deferred, or undecided.
**Docs caveat:** `docs/adr/*` and the architecture docs are frequently stale. Trust live code, the measurements in this file, and `docs/STATUS.md` over docstrings.
**As of:** **2026-09-04 (evening)** · **Zero red pins. The CAPTCHA human-in-the-loop round trip works end to end.**

**Measured 2026-09-04 on Nick's machine:** `1,264 passed, 2 skipped, 0 failed` in 114s.
Verified by execution this revision: Batch 3 applied · **P1-e, P1-f, P1-g, P2-logging all CLOSED** ·
CI workflow committed · four new document-path defects found and fixed · kimicli measured to discard
`### PATCH:` blocks silently.

> **Fence convention:** every code block in this file is indented two spaces. A fence at column 0
> truncates the document when it is emitted through kimicli. Keep the indent.

| Measured | Value | Δ since 2026-09-02 |
|---|---|---|
| Test suite | **0 failed / 1,264 passed / 2 skipped** — measured 2026-09-04 | was 1 / 1189 / 1190 |
| Type gate, `src/` | **0** — Batch 3 applied | was 28 |
| Undefined names (ruff F821) | Clean | unchanged |
| Hexagonal boundaries | **0**, asserted at equality | unchanged |
| Modules that raise on real import | **0 of 260** | unchanged |
| Both architecture pins | Green, `MAX_EXEMPTIONS` ceilings | unchanged |
| **Live discovery** | **3 real LinkedIn postings resolved, verified, enqueued** | **was 0, always** |
| Discovery verification | `[PASS]: 3 jobs \| fields OK \| chrome OK \| dedup OK \| cap OK` | first PASS on real jobs |
| Harvest cost | **0.4–0.7 s** on `fast:deferred` | was 47–123 s via the miner |
| Source | ~53,000 LOC · 260 modules · 45 ports · 109 test modules | +3 modules |
| External users | **Zero** | unchanged |

---

# Definition of Release-Ready

**The exit condition. Without it the list is infinite by construction.**

1. **One real application submitted end to end** on a live ATS form, gate honoured, complete evidence record written. — **OPEN, and now the top of the list.**
2. **Discovery yields real jobs on at least one provider**, verified by `DiscoveryVerifier` on a live run. — **✅ MET 2026-09-02, Bing.**
3. **Zero red pins.** Ruff F821 and the mypy gate green over `src/` **and** `tests/`. — **✅ MET 2026-09-04.** No red pins remain, deliberate or otherwise.
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

## CB-8 — The static path: three answers to one question
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

## P3 — i18n locale resolution — **fifth sighting**
`locales/english.json` and `locales/none.json`, three warnings every run since 2026-08-11. A language
*name* and the literal `none` used where a code belongs. Three lines of noise in the first log a new
user reads.

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

1. **PKG-1 — packaging and entry points.** Everything below depends on the dependency graph being
   honest, and it is the last thing standing between a stranger and a working checkout.
2. **CB-9 — `resolved=0` everywhere.** Settle whether the resolver is broken or was never
   load-bearing. This is CB-1's real question and it touches AA's central claim.
3. **One real application** (criterion 1). Both known reasons the run would produce a wrong record
   are now closed. **Note:** the log shows Bing yielding 8 real jobs, so there is something to apply
   to.
4. **CB-10 — a dead driver produced a PASS verdict on zero jobs.** Verification must fail loudly
   when the browser is gone.
5. **`uv.lock` committed + CI flipped to blocking** on its first all-green run across three OSes.
6. **T-1 — kimicli block accounting.** Cheap, hand-applied, protects every change after it.
7. **The docs/ revamp** (`prompt_docs_revamp.txt`) — needs a docs-inclusive dump first; the current
   one carries 2 of ~55 files.
8. **The disposable-execution architecture research** (`prompt_execution_architecture.txt`), after
   PKG-1. Bears on criterion 4 and on the macOS window.
9. **CB-8 / R-12 + R-13**, then **CB-1 / R-16**.
10. **The USB run** (criterion 4) — measurement first.
11. **Honest README + `DISCLAIMER.md`**, tag **v0.1.0**, five people, `v0.1.1`, **stop and rest.**

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

**Canonical. Count: 19, of which 6 are closed.**

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

## Rulings — status

| # | Section | Status | Decision |
|---|---|---|---|
| R-1 | CB-1 | **RULED** | Strengthen the *general* capability; do not special-case Google. **Honoured throughout the URL arc.** |
| R-2 … R-11 | various | **RULED** | Flush per round · AD-1 Option C · humanised default · P3 reclassification · spaCy guard · both layers · identity vs shape · exceptions renamed · repo URL · keep-all-with-exemptions |
| R-15 | P1-b | **SUPERSEDED** | Was "delete all four"; **all four recovered and retired 2026-09-02.** Nothing is deleted. |
| R-17 | Pins | **RULED · BUILT** | `MAX_EXEMPTIONS`, a ceiling. A lower count is success. |
| R-18 | Retirement | **RULED · BUILT** | Nothing is deleted. `docs/old_retired_files/` + ledger. **Check it before building.** |
| **R-5** | P1-a | **RULED · BUILT (Batch 3)** | **Narrow `ILogicSolver` to the implemented contract** — `solve(aom_nodes) -> dict[str, str]`. A port is a promise to consumers; the only honest promise is the implemented one. A future generic ASP consumer gets a *separate* port, never a widened union. `asp_adapter.py` needed no change: the error was in the port. |
| **R-14 / R-7** | P1-a | **RULED · BUILT (Batch 3)** | **`InteractionPort.fill -> bool`.** Filling a form field is not clicking a button: one unfillable optional field must not abort a 20-field application. Rejected: raise-like-click (wrong failure mode for the person relying on AA), result object (over-engineering for zero callers). `human_like_adapter.py` needed no change. **Callers must now honour the boolean — see P1-e.** |

**Open rulings:**

| # | Question |
|---|---|
| **R-12** | **The static path** (CB-8): real discovery / direct-URL only / nothing useful. Do not default to the first. |
| **R-13** | **One truth about the browser** (CB-8): what becomes the single source, and who owns it. |
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

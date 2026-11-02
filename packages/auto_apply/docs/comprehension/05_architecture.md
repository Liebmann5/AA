---
title: "Page Comprehension Toolkit: Architecture"
status: needs-review
last_verified: 2026-11-02
verified_against: "1bf7935"
audience: contributors
---

# Architecture

## 1. Shape in one paragraph

A **pure-Python, standard-library library** (working name `pagecomp`, CT-Q-002)
whose centre is a sans-IO pipeline over one immutable value:

    Access (port) -> Observe -> PageObservation -> Doc (columnar) -> tools -> Findings -> Trace

Tools never touch a browser, a clock, a file or a global. The browser is reached
only through the **Access port**, which declares what it can do. Engines (AA's
Discovery, Vetting, Applications) are *consumers* that turn findings into
decisions. This is the Bible 26 sans-IO rule applied to the whole subsystem, and
it is what makes every tool testable on fixtures, replayable, and replaceable.

## 2. Tools and contracts

Every tool is a function `run(inputs, params, ctx) -> Result`, where `ctx` carries
the seed, a work-unit meter (`ctx.tick(n)`, the duty-cycling hook) and a trace
sink. A `Result` is `Findings + Evidence + Confidence`, or `Abstain(reason)`, or
`Timeout(partial)`. **No tool raises on malformed input**; it returns `Abstain`.
Hang paths are listed per tool in [06](06_mathematics.md).

| ID | Tool | Input → output | Cost | Status |
| --- | --- | --- | --- | --- |
| CT-T-001 | **Access** (`AccessPort` + adapters) | request → raw page facts, by declared capability | I/O | `[PARTIAL]` |
| CT-T-002 | **Observe** | `ObservationRequest` → `PageObservation` (levels L0-L4, region, budget) | O(page) | `[PARTIAL]` |
| CT-T-003 | **Text** | bytes/str → decoded, normalised key, script, direction, mojibake flag | O(chars) | `[PARTIAL]` |
| CT-T-004 | **Doc** | observation → columnar `Doc` + path/box indexes | O(n) | `[PLANNED]` |
| CT-T-005 | **Visibility** | Doc → visible/occluded/hidden/honeypot per node | O(n log n) | `[PARTIAL]` |
| CT-T-006 | **Verdict** | (url, title, Doc/html) → page kind, defence, auth, consent, closed/applied/success | O(n) | `[LIVE]` (`assess_page`) |
| CT-T-007 | **Regions** | Doc → region tree (landmarks, XY-cut, density), page-family scores | O(n log n) | `[PLANNED]` |
| CT-T-008 | **Records** | Doc, regions → ranked record runs and record roots | O(n·K) | `[PARTIAL]` |
| CT-T-009 | **Fields** | record or JD region → title, link(s), company, location, date, sections | O(r) | `[PARTIAL]` |
| CT-T-010 | **Forms** | Doc → forms, steps, sections, controls | O(n log n) | `[PARTIAL]` |
| CT-T-011 | **Pairing** | labels × controls → pairs with margin | O(m³), m ≤ 120 | `[WIRED]` |
| CT-T-012 | **Typing** | control + label → canonical field type | O(1) | `[WIRED]` |
| CT-T-013 | **Required** | controls + signals → REQUIRED/OPTIONAL/UNKNOWN; error mapping | O(c) | `[PARTIAL]` |
| CT-T-014 | **Widgets** | subtree → APG pattern + operation plan | O(s) | `[PARTIAL]` |
| CT-T-015 | **OptionLists** | combobox/listbox state machine for async and paged lists | bounded steps | `[PLANNED]` |
| CT-T-016 | **Transitions** | before/after observations → settle, diff, navigation kind, window set | O(n) | `[PLANNED]` |
| CT-T-017 | **Structured** | JSON-LD, microdata, embedded app state → typed postings | O(bytes) | `[PARTIAL]` |
| CT-T-018 | **Trace** | tool runs → append-only events at levels L0-L3 | O(1) per run | `[PARTIAL]` |
| CT-T-019 | **Tune** | traces + gold labels → proposed `ParameterSet` | offline | `[PLANNED]` |
| CT-T-020 | **Memory** | domain/template key → verified hints | O(1) | `[PLANNED]` |
| CT-T-021 | **Profile** | machine facts + user choice → strategy per tool | O(1) | `[PARTIAL]` (router) |
| CT-T-022 | **Replay** | stored observation + parameters → results | = tools | `[PARTIAL]` |
| CT-T-023 | **Ledger** | YAML → coverage, UNKNOWN capture | O(rows) | `[PLANNED]` |
| CT-T-024 | **Workbench** | traces + ledger → review and explore UI | UI | `[PLANNED]` |
| CT-T-026 | **SubmitPredictor** | form + state → BLOCKED / WILL_SUBMIT / UNKNOWN (advisory) | O(c) | `[PLANNED]` |

*Seam rule.* Tools depend on `Doc`/`Observation` and on each other only through
`Result` values. A tool may be swapped by registering another implementation under
the same ID with a declared version; the registry records which one ran.

## 3. Data structures

| ID | Structure | Essence | Status |
| --- | --- | --- | --- |
| CT-DS-001 | `PageObservation` | Frozen: url, title, `doc_payload` (kind: dom-walk / snapshot / html), viewport, scroll, font+env fingerprint, window set, **truncations** (depth, node cap, frame skips), manifest hash, access adapter+capabilities used, timings | `[PLANNED]` |
| CT-DS-002 | `Doc` | Struct-of-arrays: `parent`, `first_child`, `next_sibling`, `tag_id`, `attr_ofs`, `text_id`, `x,y,w,h`, `flags` (visible, hidden, shadow, frame), as stdlib `array` objects; strings interned once. Target ≤ 100 B/node (object tree measured ~360 B/node) | `[PLANNED]` |
| CT-DS-003 | `PathIndex` / `Sketch` | Interned tag-paths; per-subtree 16-slot MinHash of path multiset | `[PLANNED]` |
| CT-DS-004 | `BoxGrid` | Uniform grid hash of boxes for point and ray queries | `[PLANNED]` |
| CT-DS-005 | `Finding` | `kind, node_ids, value, evidence[], confidence, margin, tool_id, version` | `[PLANNED]` |
| CT-DS-006 | `Trace` / `ToolRun` | `run_id, tool, tool_version, params_version, input_hash, output_hash, level, duration, work_units, strategy, abstain/timeout` | `[PLANNED]` |
| CT-DS-007 | `ParameterSet` | Versioned, hashed map of tool parameters with bounds; provenance of every change | `[PLANNED]` |
| CT-DS-008 | `MemoryEntry` | `host+template key, hint, evidence count, created, expires, uses, failures` | `[PLANNED]` |
| CT-DS-009 | `LedgerRow` | the YAML row of [02](02_ledger.md) | `[PLANNED]` |
| CT-DS-010 | `CapabilitySet` | Frozen set of capability names (section 5) | `[PLANNED]` |
| CT-DS-011 | `ResourceProfile` | Named bundle: read mode, node cap, duty cycle, copies, concurrency | `[PLANNED]` |
| CT-DS-012 | `PauseContext` | Observation id, epoch, findings, intended actions, confidence, human-edit log | `[PLANNED]` |

*Why struct-of-arrays and not objects.* `DOMNode` is a frozen slotted object with
an eager md5 at construction (`math_dom.py:171-177`); the local probe measured
~360 B/node retained. Arrays remove per-node object headers, make parent/sibling
walks index arithmetic, and make the whole tree cheap to hash (digest of the
arrays). Rejected: keeping objects and adding `__slots__` (already done; the floor
is the object header). Counter-argument: objects read better. Answer: a thin
`NodeView` over the arrays gives readable access at the edges; hot loops use
indexes. Loss recorded: readability below performance would normally lose to
readability (rank 4 vs 5), so the view layer is mandatory, and arrays are adopted
only because the **worst-case user** (rank 1) is memory- and CPU-bound.

## 4. Workflow: access → obtain → break down → engine step

    1. ACCESS    adapter reports capabilities; Profile picks read mode.
    2. OBTAIN    Observe(request) -> PageObservation (hash, truncations, env).
    3. BREAK DOWN Doc -> Verdict -> Regions -> family scores   (always)
                  then only the tools the family needs:
    4. ENGINE
       Discovery    Records -> Fields -> (Structured) -> candidates, ranked runs
       Vetting      Verdict(closed/expired) -> Structured -> Fields(JD) -> description
       Applications Forms -> Pairing -> Typing -> Required -> Widgets
                    -> (engine fills) -> Transitions -> Required(errors) -> SubmitPredictor
    5. TRACE     every step appends ToolRun events; checkpoint = one epoch.

*Epoch rule* (CT-INV-003). Any action that can change the page (click, type,
navigate, window event, human pause) increments the epoch. Findings carry the
epoch of their observation; a consumer acting on a finding from an older epoch
receives `Stale`. This is how "never act on stale understanding" is made
mechanical rather than a habit.

## 5. The Access port and capability model

`AccessPort` exposes only primitives; a **capability** is a fact an adapter
declares, and tools declare which they need or prefer.

| Capability | Meaning | Selenium classic | Selenium BiDi | Playwright | Direct protocol (CDP) | Replay |
| --- | --- | --- | --- | --- | --- | --- |
| `SNAPSHOT_HTML` | serialized DOM text | yes | yes | yes | yes | yes |
| `SNAPSHOT_LAYOUT` | boxes, paint order, computed style in one call | Chromium via `execute_cdp_cmd`; else script walk | no (script walk) | Chromium via a CDP session; else script walk | yes (`DOMSnapshot`) | stored |
| `AX_TREE` | accessibility tree | Chromium via CDP | partial | yes (version-dependent) | yes | stored |
| `SHADOW_PIERCING` | open+closed shadow content | script only (open) | script | locators pierce open | yes | stored |
| `IFRAME_TRAVERSAL` | cross-origin frame content | switch-to | contexts | frames | targets | stored |
| `ISOLATED_WORLD` | scripts invisible to page hooks | no | yes (`sandbox`) | utility world | yes (isolated worlds) | n/a |
| `TRUSTED_INPUT` | `isTrusted` input events | yes | yes | yes | yes | no |
| `WINDOW_EVENTS` | new window/pop-up/dialog events | polling | events | events | events | no |
| `NETWORK_EVENTS` | requests, idle detection | no | yes | yes | yes | no |
| `FILE_CHOOSER` / `DOWNLOAD_EVENTS` | upload/download hooks | partial | partial | yes | yes | no |
| `REGION_QUERY` | read only a subtree in place | script | script | locators | `DOM.*` | n/a |

`[GOAL]` The matrix is the author's reading of the vendors' documented surfaces;
each cell is a **verification item** (ledger CT-PH-0xx "access mechanism" rows)
because versions change. Where a capability is missing the declared fallback is
used and the trace names it: for example `SNAPSHOT_LAYOUT` missing → one batched
script walk (today's behaviour), `ISOLATED_WORLD` missing → page-world script,
labelled in the trace and counted against the footprint budget (07). Any
model-based adapter (CT-FR-001 "future agents") must produce the same
`PageObservation` and is optional (Bible 1: no required keys). A static HTML file
is an `Access` too (replay); there is no retired "static mode" here
([ADR-013](../adr/013_static_path_retirement.md)): replay is not a way to browse.

## 6. Adaptive strategy selection and the tuning loop

*Selection* is a pure table from `(capabilities ∩ profile)` to a strategy per
tool, e.g. Records: `sketch-windowed` (default), `exact-hash` (tiny pages),
`numpy-accelerated` (optional). A **cost model** `T ≈ a + b·n` per strategy is
calibrated once per machine by a short benchmark (the repo's `aa_measure.py`
pattern), recorded in the trace, and used for the choice; the same calibration
record gives the same choice (determinism). Machine *condition* (thermal, load)
enters only through the profile's duty cycle, never through a mid-run switch.
`[GOAL]` The seam for a learned selector exists (the selector is a registered
tool); none ships.

*Tuning* (CT-ALG-019) changes **parameters**, not code. A `ParameterSet vN` is
loaded at session start and is immutable for the run; the trace records its hash.
Proposals come from offline comparison on stored observations (counterfactual
replay), reach the user as a visible, reversible diff, and apply to the **next**
run. The user can pin any parameter. Safety thresholds (submit gate, honeypot cost
ratio, consent) are not tunable.

## 7. Resource profiles and duty cycling

| Profile | Read mode | Node cap | Duty cycle | Copies | Applications mode |
| --- | --- | --- | --- | --- | --- |
| `library` (2 GB, no admin, USB) | in-place region query when the cost model says so; else snapshot | 15,000 | burst 150 ms / rest 100 ms | off | question by question |
| `standard` | snapshot, layout in one call where available | 60,000 | none | optional | page at a time |
| `workstation` | snapshot + optional accelerators | 200,000 | none | optional | page at a time, parallel records |

`[PARTIAL]` A router already picks an analysis tier per page
(`page_analysis_router.py`). In-place query pays `q` round trips against one
bulk transfer; with round-trip time `r`, bulk time `B(n)` and `q` region queries,
in-place wins when `q·r < B(n) - B(n_region)`. The default stays **snapshot**
until slice 0 measures `r` and `B(n)` on the worst-case laptop (CT-Q-025).
*Duty cycling* is cooperative: tools call `ctx.tick(units)` every ≤ 256 units; the
meter yields (sleeps `rest`) when the burst budget is spent. Cost: one call per
256 units, below 0.1%. Hard guarantee: no tool holds the CPU longer than one burst
plus one tick interval.

## 8. Feedback loop and domain memory

| Piece (today) | Role in the new design | Decision |
| --- | --- | --- |
| Harvest baselines, read live by the degradation detector | an *expectation monitor* (yield, bytes, time per provider) | **Keep, change**: read once at run start into the run's immutable snapshot; write at run end. Today's live read makes a run unreplayable |
| Learned identity attributes (per page, kept nowhere) | in-run `PageHints` | **Keep as in-run only**; persisted form is domain memory. Add the R-20 staleness guard (CT-ALG-018) |
| Page feedback (EMA tier success, ≥ 5 samples, Applications path only) | seed of the feedback loop | **Keep, generalise**: all engines, `n_min` from the tuning rule, deterministic flag honoured; 5 samples is a heuristic, not an inference |
| `SelectorLoader` (bundled engine YAML; user overrides absent) | last-resort selector hints | **Keep** as the lowest memory tier; verified like any hint |
| Per-domain memory | missing | **New** (CT-T-020) |

*Roles.* The **feedback loop** improves the mathematics: it changes numbers in a
`ParameterSet`, offline, under a test. **Domain memory** accelerates and rescues:
a hint (`which strategy and parameters worked on this template`) with an expiry,
a size cap, and a verification on every use (the hint's prediction must satisfy
the same invariants a fresh run would, e.g. record count within tolerance and a
title-link bijection). A failed verification demotes the entry and the general
method runs. Memory is **never authoritative** (CT-INV-012) and every hit or miss
is in the trace. The tool must be strong without either.

## 9. Channels beyond the browser: the seam

Ruling: API and feed channels are a **sibling abstraction, the Source Channel**,
not part of this toolkit (CT-Q-011, CT-Q-021). Reason: a feed needs no
comprehension (the vendor already gave structure) and has different
legal/ethical and pacing rules; coupling would drag `HostPacer`, consent and
catalog policy into a pure library. The **seam**: `PageObservation.payload_kind`
may be `json`/`xml`/`feed`, so a channel can reuse `Structured`, `Trace`,
`Replay` and the ledger; and `Fields`' output type is the same candidate shape.
A paid fast service conflicts with "nothing that costs money" and is listed as an
owner ruling (CT-Q-016), not designed.

## 10. Hexagonal fit, the kernel, packaging

- **Hexagonal.** The library has no import of `auto_apply`. AA provides adapters
  (`secondary/browser`) implementing `AccessPort`, and a thin application service
  mapping findings to `Job`, `UIModel` and `FormStructure`. Domain/application
  never import adapters (Bible 1.3 rule 1). `[PLANNED]`
- **Existing ports.** `PageUnderstandingPort` (Bible 9.3) and
  `MathematicalPerceptionPort` stay as compatibility shims over the new tools;
  Bible 9.3 describes a detector that is not the live one (defect 10) and is
  corrected in slice 6.
- **Kernel.** The Typed Task Runtime Kernel exists only as docstrings in
  `work_unit.py:3`, `task_lifecycle.py:1`, `task_payloads.py:3` and a
  commented-out import at `composition_root.py:82`. The toolkit's unit of work is
  `run(tool_id, observation_ref, params_version) -> result_ref`, which maps onto a
  typed work unit and its lifecycle without change. Slices do not wait for the
  kernel (CT-Q-024). Epoch and `ExecutionMap` heartbeats (Bible 13.2) come from
  `ctx.tick`.
- **Packaging.** Slice order: (1) an import-boundary pin keeps the new package
  free of `auto_apply`; (2) separate `pyproject`; (3) a separate repository.
  `[PLANNED]` Public API is `observe`, `analyze`, `run_tool`, `Trace`, `Ledger`.

## 11. Specific cross-cutting rulings

- **Text and encodings** (CT-T-003, part of the toolkit; the seam is `TextPort`
  for AA's wider NLP). Reason: layout algorithms depend on direction and
  normalised keys, so the minimal text tool must ship inside. Details in
  [06](06_mathematics.md) section 10 and ledger CT-PH-07x.
- **"Required" and submit prediction** are **both**: the toolkit recognises
  (CT-T-013, CT-T-026, advisory); Applications decides and holds the gate
  (ADR-012). The seam is `SubmitPrediction`, a value with no side effects.
- **Containers/VMs.** `ResourceProfile` adds an `EnvFacts` block (display type,
  fonts fingerprint, `/dev/shm` size, cgroup limits, timezone, locale, GPU
  absence). Geometry thresholds are relative (to root font size and viewport),
  and the font fingerprint enters the observation so a replay explains layout
  differences. Chrome in containers needs adequate shared memory and sandbox
  flags; the adapter reports, the toolkit adapts (07 section 6).

## 12. The Workbench

Left: the live page in AA's own browser. Right: all tools (used highlighted,
unused dimmed) and the three engine workflows with the path taken highlighted.
**Review** opens a trace; **Explore** runs selected tools or a workflow live on the
page through an `AccessPort` wrapped in a **read-only guard** (the wrapper removes
`TRUSTED_INPUT` and any action capability, so the Workbench structurally cannot
submit). It reads `02_ledger.yaml` and the trace, the same trace ADR-022's page
record uses, so there is one record, not two. Failure classification is CT-ALG-026.
`[PLANNED]` It is a primary adapter and so depends on the toolkit, never the
reverse.

## 13. Cost of modularity (derived; to be measured, slice 0)

| Cost | Per pass | Basis | Bound |
| --- | --- | --- | --- |
| Call boundaries | about 25 tool calls × 0.1 µs | CPython call overhead | < 0.01 ms |
| Data copying | none between tools: indexes into one `Doc` | design rule | 0 |
| Observation → Doc | once | 12,000 nodes about 70 ms built as objects (measured); arrays should be faster | < 70 ms |
| Trace record (L1) | 25 events × about 3 µs + 2 KB | dict + hash | < 0.1 ms, 2 KB |
| Strategy selection | table lookup | 25 × 5 µs | 0.1 ms |
| Total overhead | | against a pass of about 100 ms | **< 1%** |

What would make AA slower over time, and its guard: unbounded traces (retention by
level and age), growing memory store (size cap, expiry), tuning that drifts to a
costlier strategy (the tune test includes a non-inferiority bound on time), a ledger
that grows linearly in lookup (indexed by ID), plugin discovery at start (cached by
manifest hash), and trace schema migrations (versioned, lazy). A performance gate
compares each build's per-tool time against the previous release on a fixed corpus
(CT-NFR-018).

## 14. Hard caps and the edge-case contract (pass 2)

Every tool contract in section 2 gains three obligations
([12](12_edge_cases_and_adversity.md)): it states its behaviour on the edge-case
catalogue (returns, raises, never hangs), it enforces its caps at its own
boundary, and it implements the unknown-unknown hook (fail closed, record a
`[?]` candidate, hand to the human, contain the failure to its unit of work).
The caps are parameters in `ParameterSet` (CT-DS-007), chosen per resource profile
(section 7); the defaults below are for the worst-case profile.

| Cap | Default | Applies to | Why (evidence) |
| --- | --- | --- | --- |
| Node cap `N` | 30,000 | T-002, T-004 | A: 30,000 list rows cost 16.1 s and 11.1 MB in today's script |
| Byte cap `B` | 8 MB per observation, 2 MB visible text for the verdict | T-002, T-006 | A: verdict 2.8 s on a 5.6 MB page (C14) |
| Depth cap `D_cap` | 64, iterative traversal | T-002, T-004, T-005 | O: depths 34-41 on real pages; A: Python recursion fails at 3,000 |
| Frame depth | 3 | T-002 | O: frames nested 3 deep (L17) |
| Sibling cap `S` | 2,000 per parent | T-008, ALG-005 | O: 803 rows on one board (L18) |
| Residual pairing `m` | 120 per section, 8 nearest candidates per control | T-011 | A: cubic growth, 1.6 s at 302 |
| Script deadline | 10 s per call | T-001, T-002 | R: one command blocked 87 s (LR-5) |
| Settle `T_max` | 10 s | T-016 | O: pages that never render (L50, F05) |
| Scroll rounds `P_max` | 10 | T-016 | O: endless growth (C14) |
| New windows per action | 4 | T-016 | design |
| Option-list settle waits | 12 | T-015 | 06, section 7 |

**Where the caps live.** In the tool library, never in the engines: a cap
in an engine is the scattered-knowledge defect ADR-004 removed. The trace
records every cap that fired (`truncations` on `PageObservation`, CT-DS-001),
so a truncated result can always be told apart from a small page.

**Environment facts recorded with every observation (pass 2).** Specimens
taken in a data centre differ from the owner's runs in IP reputation, fonts,
GPU and proxy rules (O: C09, the proxy accepts HTTPS only). The
`PageObservation` therefore carries an environment fingerprint (OS, browser and
version, headless or not, font set hash, device scale factor, viewport) and
an environment tag (`cloud`, `owner`, or another named host). Evidence from one
environment never ticks a ledger box for another.

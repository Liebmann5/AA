---
title: "Page Comprehension Toolkit: Architecture"
status: needs-review
last_verified: 2026-11-02
verified_against: "7701de8 + S1 reply files (pass 3)"
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
| CT-T-027 | **Controls** | Doc, regions, piece vocabulary → `ControlBinding` per filter, sort, toolbar or pagination control (s15) | O(n) | `[PLANNED]` |
| CT-T-028 | **Views** | observation, catalog → `ViewMap` of alternate views, equivalence, choice (s16) | O(n) + plain GETs | `[PLANNED]` |
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
| CT-DS-013 | `ViewMap` / `ViewTemplate` | record key → views (kind, locator, access, cost, fields, verified); per-host templates (s16) | `[PLANNED]` |
| CT-DS-014 | `ControlBinding` | control key, widget kind, search piece, options, current value, apply mode, region (s15) | `[PLANNED]` |
| CT-DS-015 | `ActionRequest` / `ActionOutcome` / `EffectCheck` | the contract between understanding and acting (s17); `ActionOutcome` is today's `ActionResult` | `[PLANNED]` |
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
| Text cap per node | 256 characters of full-subtree text or accessible name, flagged `text_truncated` | T-002 | S1: longest heading or link name on the S1 fixtures under 200 characters |
| Text budget per observation | 2,000,000 characters of full text and names, then direct text only, flagged | T-002 | the 2 MB visible-text cap above |
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

## 15. Toolbars and filter controls (pass 3; CT-T-027, CT-FR-035)

The family covers the WAI-ARIA toolbar pattern, filter bars and chips, facet
sidebars with counts, sort controls, date-posted, remote, salary and
"Easy Apply" filters, pagination and page-size controls, and toolbars inside
forms (a rich-text editor above a cover-letter box). Ledger rows CT-PH-215 to
CT-PH-231. ADR-021 already names filter controls as a channel for a search
piece; this section is how the toolkit serves that channel.

**What already exists, reused.** `ToolbarElementLocator` (YAML selectors with
a Math-DOM fallback) finds Google's toolbar items for
`SearchEngineStrategy.apply_toolbar_filters`; `VerifiedPageAdvancer` advances
pages through a verified ladder (URL template, `rel=next`, structural,
numbered, load-more, scroll) and verifies by result-list identity; the query
builder writes known URL parameters from the catalog (ADR-019). None of these
is rebuilt. The toolkit adds recognition where no selector exists, the
mapping from a control to a search piece, verification of a filter's effect,
and learning the URL parameter a control writes.

**CT-T-027 Controls.** `(Doc, regions, piece vocabulary) -> [ControlBinding]`.
Pure, `O(n)`, no I/O. For each candidate control (native `select`, checkbox
and radio groups, `role=switch|menu|listbox|slider|toolbar`, buttons with
`aria-expanded`/`aria-haspopup`, chips with a remove action) it returns a
`ControlBinding` (CT-DS-014):

| Field | Meaning |
| --- | --- |
| `control_key` | stable key of the control in the `Doc` (path + accessible name), valid for one epoch |
| `widget_kind` | APG pattern: `select`, `checkbox_group`, `radio_group`, `switch`, `menu_button`, `listbox`, `slider`, `range`, `chip`, `link_set`, `toolbar` |
| `piece` | search piece it maps to: `date_posted`, `remote`, `salary`, `sort`, `easy_apply`, `location`, `page_size`, `facet:<name>`, or `unknown` |
| `options` | option names and values as shown (bounded, 200 per control) |
| `current` | the value the page shows as selected now (default filters, CT-PH-225) |
| `apply_mode` | `instant`, `apply_button`, `drawer` (behind a "Filters" button) |
| `region` | `toolbar`, `facet_sidebar`, `chip_bar`, `pagination`, `form` |
| `confidence`, `evidence` | as every finding (CT-DS-005) |

Mapping a control to a piece uses the accessible name and option names
against a small, locale-keyed vocabulary (the piece names of ADR-019's
catalog), and structure (a `role=switch` labelled "Remote" is `remote`). An
unmatched control is `piece=unknown` and is never operated: it is recorded so
the catalog can grow (unknown-unknown rule, [12](12_edge_cases_and_adversity.md) s2).

**Operating a control.** The toolkit never operates anything. It hands an
`ActionRequest` (section 17) to the existing interaction layer, which picks
the method (pointer, keyboard, native) and the pacing. Every widget kind of the
table maps to an existing `PageActionService` operation except `slider` and
`range`, for which the smallest extension is a keyboard operation (arrow and
Page keys on the focused thumb) on the existing keyboard rung of the click
ladder; no script value injection.

**Verifying the effect (ADR-021).** After the action, the existing settle
runs, the page is re-observed (`epoch++`), and ALG-027
([06](06_mathematics.md) s13) compares before and after: the result set
(record identities), the total-count text, and the URL. The outcome is
`APPLIED`, `NO_EFFECT` (a filter that silently does nothing, CT-PH-226),
`RESET` (state lost on pagination, CT-PH-227), `CONTRADICTED` (counts that
lie, CT-PH-228) or `UNKNOWN`. Only `APPLIED` lets the engine count the piece
as applied; the others are recorded and the channel is benched for the
session (ADR-021 decision 4).

**Learning the URL parameter.** When `APPLIED` and the URL changed, the
query-string difference that is new or changed (one key, or one value of a
key) is a candidate parameter for `(host, piece, option)`. It becomes a
catalog proposal only after a second, independent verification: applying the
learned URL directly must reproduce the same result set (ALG-027 step 4).
Learned parameters live in the catalog ADR-019 already defines, as entries
with provenance `learned`, never in domain memory (they are facts about a
surface, not hints about a layout). Later runs then apply the piece through
the URL: one navigation, no clicks, lower footprint ([07](07_footprint_and_defences.md) s10).

## 16. Alternate views of the same record (pass 3; CT-T-028, CT-FR-036)

The same posting, list or form is often reachable through more than one
view: the guest view and the signed-in view (LinkedIn, Notion); a Google Form
embedded in a page and at its own URL; a Notion database view and its parent
page; a Greenhouse board redirected to the company's site; DirectEmployers'
mirror hosts; JSON-LD `JobPosting` inside the page; RSS and Atom feeds;
sitemaps; vendor posting APIs; print, AMP and mobile views. Ledger rows
CT-PH-256 to CT-PH-266, with CT-PH-020, 140, 158, 162 and 192. The owner's
ruling (pass 3): guest views are useful and supported, not a problem to work
around.

**Recognise.** CT-T-028 Views reads, from one observation, every advertised
alternative: `link rel=alternate` (feeds, mobile, hreflang), `link
rel=canonical` on another host, `link rel=amphtml`, print stylesheets and
print links, embedded frames whose source is a known form or board host,
`JobPosting` structured data, and `Sitemap:` lines in `robots.txt` (already
fetched for policy, CT-Q-026). Vendor posting APIs are not discovered from
pages; they come from the catalog, keyed by the vendor the verdict recognised.

**The view mapping (CT-DS-013 `ViewMap`).**

| Field | Meaning |
| --- | --- |
| `record_key` | the record's identity: canonical URL, else vendor posting id, else `(host, normalised title, location)` |
| `views` | list of `View(kind, locator, access, cost, fields, observed_at, verified)` |
| `kind` | `page_guest`, `page_signed_in`, `embedded`, `own_url`, `db_view`, `parent_page`, `jsonld`, `feed`, `sitemap`, `api`, `print`, `amp`, `mobile`, `mirror` |
| `access` | `public`, `needs_sign_in`, `needs_key`, `refused` (robots, 401, 403) |
| `cost` | expected bytes, requests and footprint class (07 s3) |
| `fields` | which of title, company, location, pay, dates, description, apply target the view carries |
| `verified` | result of ALG-028 against another view of the same record, with the fields that disagree |

Per host, a `ViewTemplate` generalises a mapping once it has held on
`n_min` records (default 3): for example "`/p/<id>` page ↔ database row with
the same id", or "board slug ↔ API `boards/<slug>/jobs`".

**Where learned mappings live.** In a sibling of domain memory, the view
catalog: the same bounded, verified, expiring store as CT-T-020 (section 8),
keyed by `(registrable domain, view template)`, because a view mapping is a
verified hint about a surface that can rot. It is never authoritative: a view
is used only after ALG-028 verifies it again on the record at hand, at the
sampling rate of ALG-028. The seam is the Source Channel seam of section 9:
feeds, sitemaps and APIs are non-HTML channels behind the same `Finding`
contract, so an engine asks "give me this record's fields" and the toolkit
answers from the cheapest view that verified.

**Choose.** ALG-029 ([06](06_mathematics.md) s15) picks, per record, the view
that carries the needed fields at the lowest cost and footprint, subject to
access (`public` only, unless the user's own browser session is the view)
and to verification. A view that needs sign-in is never chosen; an apply
control behind sign-in is the existing sign-in-wall handling (`LOGIN_REQUIRED`,
hand-off), not a new case.

**Edge cases** ([12](12_edge_cases_and_adversity.md) s9): views that disagree
(the disagreement is reported field by field, never averaged), views that lag
(a feed or sitemap that still lists a closed posting; a feed that returns
410), views that need sign-in, a mirror that serves 404 with content, a
canonical link pointing at a page that redirects back.

## 17. The contract between understanding and acting (pass 3)

The toolkit says **what**: the target, the kind of widget, the intent, the
expected effect and the confidence. The existing interaction layer decides
**how**: the method (pointer, keyboard, native, script as last rung), the
pacing, the footprint. Nothing in the toolkit imports a browser type or calls
a browser method; nothing in the interaction layer interprets a page.

**Types that cross the boundary (CT-DS-015).**

| Type | Direction | Fields | Maps onto today's code |
| --- | --- | --- | --- |
| `ActionRequest` | toolkit → engine → interaction layer | `epoch`, `control_key`, `widget_kind`, `intent` (`click`, `open`, `choose(option)`, `set_text`, `set_checked`, `set_value`, `scroll_into_view`, `expand`, `advance_page`), `value`, `expected_effect` (`navigation`, `dom-change`, `results-change`, `value-change`, `none`), `confidence`, `irreversible` | `PlannedAction` (target id, action type, value, reasoning, confidence, `is_critical`) for Applications; direct `PageActionService` calls for Discovery |
| element resolution | engine | `control_key` → `ElementInterface` via the locator the finding names (the path, or an identity attribute as card activation does) | `PageActionService.find`/`find_all`; `CardActivator` relocation |
| `ActionOutcome` | interaction layer → toolkit | `success`, `reason`, `rung`, `effect`, plus the new `epoch` | `ActionResult(success, reason, element, rung, effect)` unchanged; the epoch is the engine's counter |
| `EffectCheck` | toolkit | before and after observations → `APPLIED`, `NO_EFFECT`, `RESET`, `CONTRADICTED`, `UNKNOWN` | new (ALG-027); replaces nothing |

**Errors.** A stale `epoch` makes the engine refuse the request (`Stale`,
section 4, CT-INV-003). An element that cannot be resolved returns
`ActionResult(False, "not found")` today; the engine records it as the
finding's failure and re-observes. `irreversible=True` routes through the
existing submission gate and the approval checkpoint
(`Checkpoint.BEFORE_FORM_SUBMIT`); the toolkit's `SubmitPredictor` is advisory
input to that gate, never a replacement. A challenge recognised after an
action goes to the in-place pause (`ApplicationsWorkflow._pause_for_challenge`,
ruling A of 2026-09-09) exactly as today.

**Ports.** The interaction layer keeps its ports: `PageActionPrimitives`,
`PageNavigationPort` and `DomReadinessPort` (domain), `InteractionPort` and
`InteractionPlan`/`PlannedAction` (Applications). The boundary pin
`tests/architecture/test_page_action_boundary.py` stays in force; the
toolkit adds one architecture pin of its own: no module under the toolkit
imports `application.services.page_action` or a browser adapter.

**Overlaps and rulings.** Default is reuse (ENGINEERING_PHILOSOPHY: single
source of truth, DRY).

| Blueprint piece | Existing code | Ruling | Reason |
| --- | --- | --- | --- |
| Operating any control (click, type, select, check, scroll, hover) | `PageActionService` and its components | **reuse** | meets the contract: typed result, rung and effect, pacing, probe |
| Widget operation plans (CT-T-014) | handlers `text`, `select`, `checkable`, `date`, `file` behind `UnifiedInteractor` | **reuse**; **change** for sliders and ranges (keyboard operation on the existing rung) | the handlers dispatch on tag and type; the plan names the handler |
| Settle after an action (CT-T-016 settle) | `PageActionService.settle`, `DOMObserver.wait_for_dom_stable`, `DomReadinessPort` | **reuse**; **change**: return the settle outcome (`stable`, `timeout`) instead of a bare bool where needed | one settle, one cap |
| Page advance (Discovery) | `VerifiedPageAdvancer` | **reuse** | already verifies by result-list identity, the ALG-027 idea for pages |
| Toolbar element finding | `ToolbarElementLocator` | **keep both**, YAML first | YAML selectors are the lowest-memory tier and are measured per selector; CT-T-027 is the fallback for surfaces without YAML. Cost: one extra observation only when YAML misses |
| Form state classification | `DOMObserver.get_current_state` (`FormState`) | **keep both** until S4, then **change** to consume CT-T-010 findings | the observer is live in Applications; replacing it needs S4's forms tool and its pins |
| Page verdict after an action | `page_assessment` via ADR-022 checkpoint in `page_action/` | **reuse** | one verdict |
| Card activation clicks | `CardActivator` | **reuse**; **change** (value pinning R-20, verdict after each click LR-4) | as in section 2 of [10](10_gap_analysis_and_build_plan.md) |
| Headless direct-API interaction | `adapters/secondary/interaction/api_direct_adapter.py` (empty file, marked PLANNED in the reachability pin) | **keep** as a placeholder; no ruling to retire | an empty planned module costs nothing and is pinned as planned; retiring it is the owner's call (Bible 7.4) |

**Which existing tool operates each ledger row.** Recorded per row in the
ledger (`acts:` in the *Tool* column; key `acts` in the YAML). Status follows
evidence only: the code and its tests count toward `[~]`; `[x]` still needs
a live run on three sources.

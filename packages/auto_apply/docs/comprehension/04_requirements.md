---
title: "Page Comprehension Toolkit: Requirements"
status: needs-review
last_verified: 2026-11-02
verified_against: "7701de8 + S1 reply files (pass 3)"
audience: contributors
---

# Requirements

Every requirement has a verification method (a falsifier) and a status at
commit `1bf7935`. "Slice" refers to [10](10_gap_analysis_and_build_plan.md).
Verification kinds: **U** unit pin on fixtures · **P** property-based test ·
**R** replay over a stored observation · **L** live run on the frozen set
([09](09_verification.md)) · **A** analysis (a proof in [06](06_mathematics.md)) ·
**M** measurement on a named machine.

IDs 001-099 are defined on this page. IDs 101 and above (engine needs `CT-FR-1xx`, research criteria `CT-NFR-1xx`) are defined in the ledger ([02](02_ledger.md)); the ledger is their source.

## Functional requirements

| ID | Requirement | Verification | Status |
| --- | --- | --- | --- |
| CT-FR-001 | Access any page through one port with declared capabilities (Selenium classic and BiDi, Playwright, direct protocol, replay, future agents); missing capability degrades a strategy, never the contract | U (contract suite run per adapter), L | `[PARTIAL]` browser adapters exist; no capability model |
| CT-FR-002 | Obtain a `PageObservation` at a requested level and region, inside a time and byte budget, recording what was truncated | U, M | `[PARTIAL]` whole-page script walk, depth cap 50 silent |
| CT-FR-003 | Break the page into a columnar `Doc`, traversing open and closed shadow roots and iframes where the access method allows, and flag every truncation | U, L | `[PARTIAL]` no shadow traversal; cap silent |
| CT-FR-004 | Classify page family and verdict (result list, job description, form, login, challenge, consent, closed, applied, success, error, unknown) with signals and confidence, abstaining under a margin | U, R, L | `[PARTIAL]` `assess_page` kinds `[LIVE]`; no list/feed/consent kinds |
| CT-FR-005 | Segment records on result lists as **ranked candidate runs**, tolerant of promoted/selected variants, not one exact-hash group | P, U, L | `[PARTIAL]` one group, exact hash incl. classes (defects 1, 8) |
| CT-FR-006 | Per record: title, destination link(s), company, location, date, with evidence and a resolution state; title read from full subtree text; `<a>` and custom-element cards supported | U, L | `[PARTIAL]` direct-text title (defect 4); guard excludes `<a>` (defect 7) |
| CT-FR-007 | List movement: pagination, load-more, infinite scroll, virtualized rows, with a staleness guard on node handles (R-20) | U, L | `[ ]` |
| CT-FR-008 | Job description: sections, title, company, location, salary, apply entry, closed/expired state, structured data (JSON-LD JobPosting, microdata, embedded state) | U, L | `[PARTIAL]` JSON-LD check inside the verdict only |
| CT-FR-009 | Segment forms into steps, sections and fields, including formless single-page-app forms and repeating "add another" sections | U, L | `[PARTIAL]` container detection by input density |
| CT-FR-010 | Pair labels with controls by a constraint ladder, then assignment for the residual; report margin and evidence | P, U | `[PARTIAL]` Hungarian `[WIRED]` |
| CT-FR-011 | Infer field type, with HTML autofill tokens first; enumerate options for select, radio group, checkbox group | U | `[PARTIAL]` scoring classifier `[WIRED]` |
| CT-FR-012 | Mark each field REQUIRED, OPTIONAL or UNKNOWN before any submit, from all signals (CT-ALG-010) | U, L | `[ ]` pass 2: today's code reports every field as required (A, stage 5 on three live forms; [10](10_gap_analysis_and_build_plan.md) defect 23) |
| CT-FR-013 | Predict whether a submit attempt will be blocked by native validation, will go through, or is unknown (CT-ALG-011); unknown is treated as "will go through" | P, U | `[ ]` |
| CT-FR-014 | After a failed submit, map every error (inline, summary, toast, focus, highlight, changed page) back to its field and advise a correction | U, L | `[ ]` |
| CT-FR-015 | Recognise ARIA Authoring Practices widgets and HTML controls and give an operation plan for each (combobox, listbox, dialog, date pickers, file drop zones, rich text, phone with country code, tag inputs) | U, L | `[PARTIAL]` per-type handlers `[WIRED]` |
| CT-FR-016 | Select from long asynchronous or paged option lists (school lists) by a bounded protocol (CT-ALG-015) | U, L | `[ ]` |
| CT-FR-017 | Visibility, occlusion and honeypot judgement with an explicit cost asymmetry; computed style and paint order when the access method provides them | P, U | `[PARTIAL]` inline-style only `[WIRED]` |
| CT-FR-018 | Recognise defences (challenges, bot walls, rate limits, login walls, consent walls, honeypots, obfuscation) and record them as research data; handling stays in ADR-012/020 policy | U, L | `[PARTIAL]` challenge and login wall `[LIVE]` |
| CT-FR-019 | Transitions: settle detection, document diff, navigation kinds, new windows and pop-ups, iframes, dialogs, downloads, PDF viewers | U, L | `[PARTIAL]` tab switch `[WIRED]`; ADR-022 `[PLANNED]` |
| CT-FR-020 | At every human pause expose understanding, intended action and confidence; on resume re-observe and never act on stale understanding (CT-ALG-024) | U, L | `[ ]` |
| CT-FR-021 | Text, encodings and languages handled with graceful degradation and a user-visible notice (CT-T-003) | P, U | `[PARTIAL]` locale normalisation `[WIRED]` |
| CT-FR-022 | Record a trace of every tool run at levels L0-L3 (CT-DS-006) | U, R | `[PARTIAL]` counts only (defect 9) |
| CT-FR-023 | Replay: run any tool over a stored observation with its recorded parameters and obtain the identical result | R | `[PARTIAL]` replay of detectors `[LIVE]`; not of comprehension |
| CT-FR-024 | Tuning: propose and apply parameter sets only under the significance rule (CT-ALG-019), versioned, reversible, never mid-run | P, U | `[ ]` |
| CT-FR-025 | Domain memory: bounded, expiring, verified-on-use accelerator, never authoritative (CT-ALG-020) | U | `[ ]` |
| CT-FR-026 | Resource profiles and duty cycling select strategies; in-place query on tight-memory profiles; question-by-question mode on weak machines | M, U | `[PARTIAL]` analysis tier router `[WIRED]` |
| CT-FR-027 | Load the ledger, compute coverage, and capture an `UNKNOWN` phenomenon with evidence for the human | U | `[ ]` |
| CT-FR-028 | Workbench: review a trace, or explore tools live on the page; classify a failure | U, manual | `[ ]` |
| CT-FR-029 | Observations may wrap non-HTML payloads (JSON, XML, feeds) so a Source Channel can reuse findings, replay and trace | U | `[ ]` |
| CT-FR-030 | Offer the existing `PageUnderstandingPort` and `MathematicalPerceptionPort` as thin compatibility shims during migration | U | `[WIRED]` (current), `[PLANNED]` (shim) |
| CT-FR-031 | Recognise feed-style pages (LinkedIn feed) and extract hiring-announcement posts as text-only candidates with their contact route | U, L | `[ ]` |
| CT-FR-032 | Detect login, sign-up, verification-code and "sign in with …" gates, and hand off without entering third-party credentials | U, L | `[PARTIAL]` login wall verdict `[LIVE]` |
| CT-FR-033 | Unknown-unknown capture: an unrecognised state fails closed, is recorded as a `[?]` row candidate with evidence, is handed to the human, and is contained to its unit of work so other safe work continues ([12](12_edge_cases_and_adversity.md) section 2) | U (property test on random DOMs: no silent default), L | `[ ]` (pass 2) |
| CT-FR-034 | Edge-case contract: every tool declares and pins its behaviour on the catalogue of [12](12_edge_cases_and_adversity.md) (returns, raises, never hangs), its caps, and its trace record | U, P | `[ ]` (pass 2) |
| CT-FR-035 | Filter and toolbar controls: recognised, mapped to search pieces, operated through the existing interaction layer, verified (ADR-021), learned as URL parameters ([05](05_architecture.md) s15) | U, L | `[ ]` (pass 3) |
| CT-FR-036 | Alternate views of one record: recognised, mapping learned, equivalence verified, cheapest sufficient view chosen ([05](05_architecture.md) s16) | U, L | `[ ]` (pass 3) |
| CT-FR-037 | Ledger coverage: every item of the frozen reference lists maps to a row or a reasoned not-applicable entry ([09](09_verification.md) s8) | U | `[ ]` (pass 3; the check is specified, not built) |

## Non-functional requirements

| ID | Requirement | Verification | Status |
| --- | --- | --- | --- |
| CT-NFR-001 | **Zero required runtime dependencies.** Standard library only; accelerators optional and declared | import-boundary pin | `[PARTIAL]` domain is stdlib; adapters are not |
| CT-NFR-002 | Pure Python, 3.10 floor (docs gate); no C extensions required | CI matrix | `[WIRED]` |
| CT-NFR-003 | **Determinism**: same observation + configuration + parameter version + seed → byte-identical findings; no clock, I/O or global state inside a tool | R, P | `[PARTIAL]` |
| CT-NFR-004 | Time: P95 analysis CPU ≤ 1.0 s for ≤ 12,000 nodes on the reference slow machine; each tool within its declared bound | M | `[GOAL]` |
| CT-NFR-005 | Memory: Python-side ≤ 100 B/node (columnar) and ≤ 25 MB for 100,000 nodes; in-place profile bounded by region | M | `[GOAL]` measured today: ~360 B/node object tree |
| CT-NFR-006 | **Observable footprint**: default profile uses the lowest-footprint read; every page-world script is registered with a justification; zero by default where protocol reads exist | analysis, L experiment | `[GOAL]` |
| CT-NFR-007 | Accuracy targets per family and source ([01](01_charter.md)) with intervals | L | `[GOAL]` |
| CT-NFR-008 | Calibrated abstention: wrong-and-confident ≤ 1%; confidence reported with an ECE in the evaluation | L | `[GOAL]` |
| CT-NFR-009 | Every tool declares worst-case complexity; none is worse than O(n log n) on node count, or O(n²) only on a bounded n with a hard cap | A | `[GOAL]` |
| CT-NFR-010 | **No hangs**: every wait, loop and recursion has a declared cap and returns a typed timeout | U, fault injection | `[ ]` pass 2: label pairing is cubic in text nodes with no cap; the extraction script has no deadline or size cap (A, [12](12_edge_cases_and_adversity.md) section 5) |
| CT-NFR-011 | Library API semantic versioning; findings schema versioned; deprecation window of one minor | review | `[ ]` |
| CT-NFR-012 | Portability: Windows, macOS, Linux; Chrome, Edge, Firefox; WebKit via Playwright where available | L matrix | `[PARTIAL]` |
| CT-NFR-013 | Container and VM adaptation: headless, no GPU, font differences, shm and memory limits, timezone and locale | M, U | `[ ]` |
| CT-NFR-014 | Privacy: traces carry no PII by default; values and URLs with the user's search words are hashed or excluded below L3 | sentinel pin | `[PARTIAL]` |
| CT-NFR-015 | Research-grade provenance: tool versions, parameter version, schema version, environment fingerprint in every trace | U | `[PARTIAL]` |
| CT-NFR-016 | The Workbench is operable by keyboard and screen reader | manual + pin | `[ ]` |
| CT-NFR-017 | Modularity cost ≤ 2% of a pass (calls, copies, trace, selection) | M | `[GOAL]` derived < 1% ([05](05_architecture.md)) |
| CT-NFR-018 | Nothing makes AA slower over time: every store has a cap and a retention rule; a performance gate fails the build on regression | M, CI | `[ ]` |
| CT-NFR-019 | Tuning safety: parameter sets versioned, recorded, reversible, visible, never changed mid-run; safety thresholds never tuned | U, P | `[ ]` |
| CT-NFR-020 | Testability: every tool runs on fixtures with no browser (sans-IO, Bible 26) | U | `[PARTIAL]` |
| CT-NFR-021 | Language-agnostic structure: no tool requires a lexicon to produce structure; lexicons only add evidence | U on non-Latin fixtures | `[PARTIAL]` |
| CT-NFR-022 | Ledger, requirements and tests stay in sync (coverage pin) | CI | `[ ]` |
| CT-NFR-023 | Fail closed: anything that cannot be determined is UNKNOWN and treated as the unsafe case for irreversible steps | U | `[WIRED]` (ADR-012) |
| CT-NFR-024 | Lifetime budget: tool registry lookups, trace and memory writes are O(1) amortised and bounded in size | M | `[ ]` |
| CT-NFR-025 | Tail budgets: p95, p99 and maximum per tool on the worst-case machine and on adversarial input ([12](12_edge_cases_and_adversity.md) section 6), the maximum enforced as a hard cap | M (slice 0 on the specimen shapes) | `[ ]` (pass 2) |
| CT-NFR-026 | Bounded acquisition: node, byte, depth, frame and time caps on every observation, each recorded as a truncation flag | U, M | `[ ]` (pass 2; A: no cap today) |
| CT-NFR-027 | Operating filters and fetching alternate views within the footprint budget: one verified operation per piece, then the learned URL; views by plain GET after `robots.txt` ([07](07_footprint_and_defences.md) s10) | M | `[ ]` (pass 3) |

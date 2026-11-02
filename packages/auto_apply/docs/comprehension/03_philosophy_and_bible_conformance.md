---
title: "Page Comprehension Toolkit: Philosophy and Bible Conformance"
status: needs-review
last_verified: 2026-11-02
verified_against: "1bf7935"
audience: contributors
---

# Conformance to the Philosophy and the Bible

Method: each principle or invariant is mapped to the requirement (CT-FR/NFR),
design decision (05/06/07/08) and ledger row that satisfies it, and any gap is
named. "Gap" means *not satisfied at `1bf7935`* or *not yet provable*. The
Philosophy outranks everything; where this suite proposes a change to existing
documentation it follows the Philosophy's own **Documentation Interpretation Policy**
and says so (section 3).

## 1. Philosophy, principle by principle (CT-INV-201 to 219)

| ID | Principle | How the blueprint satisfies it | Gap |
| --- | --- | --- | --- |
| 201 | Core mission: worst-case users first | decision order puts the worst-case user first; `library` profile (05 s7); NFR-004/005 budgets on the reference slow machine; in-place query and duty cycling | budgets unmeasured on the worst-case laptop (S0) |
| 202 | Tool-first: predictable, fails safely, explains, respects intent, protects data, works constrained, improves | pure tools (INV-001); abstain over guess (INV-004); evidence on every finding (INV-005); `Trace`; privacy levels; tuning with rollback | none by design; proof pending live runs |
| 203 | Prefer low memory, offline, deterministic, graceful degradation, user-owned data, local execution, portable, explicit policy | stdlib only; replay needs no network; capability fallbacks; local traces; no hidden behaviour (every parameter and strategy is in the trace) | memory figures measured only on a desktop |
| 204 | Autonomy with guardrails: never-before-seen pages, general strategies, structured perception, policy-driven, HITL, evidence, separation | Records/Forms are general (no site names); `UNKNOWN` plus human hand-off; `PauseContext`; epoch rule; engines keep decisions | generalisation unproven until the DRAW set |
| 205 | Architectural commitments: SoC, single source of truth, DRY, SRP, boundaries, contracts, replaceable | one tool per concern; ledger is the single list of phenomena; ALG-002 reused for form repeats; ports/`Result` contracts; registry swap | duplicate vocabularies exist today (two structural hashes) |
| 206 | Progressive enhancement: advanced never mandatory; optional stays optional; faster paths preserve correctness; feature detection; reversible upgrades; fallback maintained | capability model (05 s5); accelerators must be result-equivalent or declare tolerance; fallback strategy per tool tested in CI | equivalence tests not written |
| 207 | AA as research-grade software: deterministic, reproducible, versioned, tested, transparent, explainable, documented, safe, private, maintainable | INV-001/006; `ParameterSet` versions; property tests of lemmas; trace; this suite; `ctx` meter | none by design |
| 208 | Outputs as research-grade data: auditable, reproducible, explainable, structured, comparable, privacy-preserving, exportable, validatable | trace schema (08) separates observation, inference, decision, action, result; levels; fingerprints; gold-label validation (09) | trace not built; today counts only |
| 209 | Safety, security, respect: store only necessary, local, visible, few network calls, no hidden persistence, no privilege assumptions, shared devices, safe failure, user control | L0/L1 default, L2/L3 consent; bounded stores; read-only Workbench guard; fail-closed gate stays | shared-device scoping of queue (LR-9) is outside this toolkit |
| 210 | Structural excellence: modular, composable, encapsulated, layered, decoupled, scalable, extensible | tools/contracts (05 s2); hexagonal fit; registry; cost of modularity quantified | none |
| 211 | Performance: efficient, optimized, lean, responsive, concurrent, asynchronous | O(n·D·K) records; columnar `Doc`; duty cycling; concurrency only where a browser lease allows (rule 3) | optimisation follows measurement (S0), not assumption |
| 212 | Maintainability: readable, self-documenting, testable, robust, consistent, predictable | `NodeView`; sans-IO fixtures; typed `Result`; one trace; IDs | arrays reduce readability, mitigated |
| 213 | Adaptability: reusable, configurable, portable, parametric, generic | standalone library; `ParameterSet`; profiles; ports | library not yet extracted (S6) |
| 214 | Quality: stable, secure, verified, auditable, compliant | no-hang rule (NFR-010); lemma tests plus live runs; trace; accessibility of the Workbench; legal flags as CT-Q | compliance questions are owner rulings |
| 215 | Repository health: documented, maintained, community-friendly, CI, versioned | docs gate, ledger sync pin, semantic versioning (NFR-011), changelog | versioning of the library not started |
| 216 | Decision standard: closer to a reliable, secure, efficient, maintainable, extensible, research-grade, user-respecting tool | decision order recorded at each decision; losses named (05 s3) | none |
| 217 | Guidance for AI-assisted contributors (10 points) | this suite is the acceptance criteria; layer and boundary named per tool; deterministic default; documentation updated in the same slice | none |
| 218 | Documentation interpretation: prefer a demonstrably superior solution; say when documents must change | section 3 lists the proposed documentation changes | pending owner approval |
| 219 | Final principle: ambitious without careless, flexible without chaotic, autonomous without unsafe | abstention, caps, gate, tunable-only-perception | none |

## 2. Bible invariants (CT-INV-101 to 120)

| ID | Invariant | How satisfied | Gap |
| --- | --- | --- | --- |
| 101 | 1.1 Worst-case contract: 2 GB, no admin, no keys, maybe no internet beyond the browser, USB, Windows first | stdlib only; no install of system packages; `library` profile; L2 optional for USB | CT-NFR-013 untested |
| 102 | 1.2 Separation of concerns | one reason to change per tool | none |
| 103 | 1.2 Single source of truth | parameters in `ParameterSet` read from `runtime_defaults.yaml` defaults; phenomena in the ledger | parameter source of truth to be wired (rule 2) |
| 104 | 1.2 DRY | one structural vocabulary; `assess_page` reused; labelling and replay reused | two hash vocabularies today |
| 105 | 1.2 Hexagonal | library has no `auto_apply` import; adapters implement `AccessPort` | S6 |
| 106 | 1.2 Dependency inversion | consumers depend on `Result`/ports, not adapters | none |
| 107 | 1.2 Worst-case first | decision order | none |
| 108 | 1.2 Zero required keys | model adapters optional; none shipped | none |
| 109 | 1.2 Agnostic implementations | capability model; no browser, OS, site named in a tool | per-site hints only in memory tier |
| 110 | Rule 1: no domain/application import of infrastructure or adapters | library boundary pin | S6 |
| 111 | Rule 2: no default overriding `runtime_defaults.yaml` | initial parameters loaded from the YAML where they exist; new keys added with comments (Bible 22.3) | new keys to be added |
| 112 | Rule 3: browser never shared across threads without a lease | `AccessPort` calls happen under the existing lease; tools are pure and may run on any thread | none |
| 113 | Rule 4: engines never call each other | engines consume findings via the orchestrator and event bus; the toolkit has no engine knowledge | none |
| 114 | Rule 5: math is a strategy, not a source | the toolkit returns findings; no provider logic inside | none |
| 115 | Rule 6: absolute imports only | enforced in the new package like the rest | none |
| 116 | 27 Session Supervisor components (lease, plan, behaviour parameters, execution map, watchdog) | `ctx.tick` heartbeats feed `ExecutionMap`; `ParameterSet` joins `SessionPlan`; seed from `random_seed` | supervisor items are `[PLANNED]` in the Bible |
| 117 | 26 Sans-IO | the whole design | none |
| 118 | 16 Evasion and security: detection is confidence-weighted; `js_variables` empty; CAPTCHA policies | CT-T-006 reuses it; 07 structural-signature rule | vendor coverage `[?]` |
| 119 | 30.4 Disk pre-checks (USB safety) | trace and L2 writes check free space; caps | to be wired |
| 120 | 31 Agnostic trinity: platform, framework, provider | OS/browser/provider appear only as capabilities | none |

## 3. Proposed documentation changes (Documentation Interpretation Policy)

| Document | Proposed change | Reason |
| --- | --- | --- |
| Bible 9.3 | replace the sketch of `find_repeated_patterns` with a pointer to this suite | the live path is `_detect_job_listings`, a different detector (defect 10) |
| Bible 7.3 | list `AccessPort` adapters by capability; `CDPDOMAdapter` becomes a capability, not a stealth claim | footprint analysis (07) |
| Bible 22.1 | feedback loop paragraph points to CT-ALG-019/020 and drops "weekly aggregation of strategy success" as the mechanism | the n ≥ 5 EMA is a heuristic, not an inference |
| Bible 25.3 | add the replay property to the reproducibility checks | 08 section 3 |
| ADR-022 | note that the step record is a `step` event of the shared trace | one trace |
| STATUS.md | add this subsystem row only after S1/S2 measurements | status rules |

Only the Bible 9 pointer is applied in the same change as this suite; the rest are
recorded here for the owner to approve.

## 4. Edge cases as conformance (pass 2)

The Philosophy names **Robust** ("handles edge cases, bad inputs, partial
failures, and environmental instability gracefully"), **Predictable** and
**Stable**, and it says reliability "is proven through repeated behavior, clear
evidence, safe failure modes, and tests that cover realistic failure
conditions". Pass 2 reads these as conformance requirements:

| Principle | How the suite now meets it | Evidence of the gap at `1bf7935` |
| --- | --- | --- |
| Robust | a catalogue of 45 edge cases with per-tool handling ([12](12_edge_cases_and_adversity.md)) | cubic pairing, silent truncation, shadow blindness (A) |
| Stable, never enters unrecoverable flows | caps at every tool boundary; Lemma 4 ([06](06_mathematics.md) s12) | CT-NFR-010 is `[ ]` on evidence |
| Autonomy with guardrails ("ask for help when needed") | the unknown-unknown rule: fail closed, record, hand off, contain | today's verdict returns `UNKNOWN` without a path to a human |
| Research-grade data ("what external barrier affected execution") | environment tags; block kinds; robots per host (07 s9) | plain blocks read as `UNKNOWN` (10 s5) |
| Worst-case-user first | tail budgets on the worst-case machine, not averages ([12](12_edge_cases_and_adversity.md) s6) | p95/max not yet measured on the owner's laptop |
| Accessibility and fairness ("exclusionary design") | RTL and non-English pages are first-class catalogue entries | RTL labels make today's rule skip real fields (EC-32) |


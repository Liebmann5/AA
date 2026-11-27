---
title: "Page Comprehension Toolkit: Production Readiness"
status: needs-review
last_verified: 2026-11-03
verified_against: "bcb6c2c + S4 form reply files (pass 4)"
audience: contributors
---

# Production readiness

This page reviews the whole blueprint as the team that must build, ship and
maintain it would. A build is production-ready only when every item of the
checklist holds. Each item states where it is satisfied, what pass 3 changed,
and what remains. Readiness of AA itself is claimed only in
[STATUS.md](../STATUS.md); this page is about the blueprint.

## 1. Checklist

| # | Item | State | Where satisfied | What remains |
| --- | --- | --- | --- | --- |
| 1 | Every ledger row has a responsible tool | **holds** (421 of 421) | ledger *Tool* column; [02_ledger_plan.yaml](02_ledger_plan.yaml) resolves each to toolkit tools | none |
| 2 | Every ledger row has a verification method | **holds** (421 of 421; CT-PH-213 fixed in pass 3) | ledger *Verification* column | none |
| 3 | Every row has a bound on time and memory | **specified, not measured** | per tool and algorithm: [06](06_mathematics.md) s11-12 (worst case, caps), [05](05_architecture.md) s14 (caps), [12](12_edge_cases_and_adversity.md) s6 (tail budgets); rows inherit through their tools in [02_ledger_plan.yaml](02_ledger_plan.yaml) | budgets assume the reference machine is 8× slower than the probe machine; S0 measures the owner's worst-case laptop (order 1) |
| 4 | Every row has a defined failure behaviour (returns, raises, never hangs) | **specified** | tool contract: no tool raises, returns `Abstain` or `Timeout` ([05](05_architecture.md) s2); per tool [12](12_edge_cases_and_adversity.md) s4; Lemma 4 ([06](06_mathematics.md) s12) | Lemma 4 depends on caps not yet enforced in code (G2 does not hold at `7701de8`): S0 |
| 5 | Every row names the slice that delivers it | **holds** (pass 3) | [02_ledger_plan.yaml](02_ledger_plan.yaml): 356 rows to a slice, 62 cross-cutting (release checks), 2 outside the toolkit, 1 owner ruling | none |
| 6 | Every algorithm: statement, proof or sketch, termination, worst-case complexity, budget | **holds for ALG-001 to 029**, budgets derived | [06](06_mathematics.md) s1-16; s12 table | worst-case budgets measured in S0 |
| 7 | Every interface typed and specified, with errors | **specified as records**; Python protocols not yet written | tools: [05](05_architecture.md) s2; data structures CT-DS-001 to 015: s3; understanding to acting: s17 (`ActionRequest`, `ActionOutcome` = `ActionResult`, `EffectCheck`, `Stale`) | each tool's `typing.Protocol` lands with its slice (S2 records, S3 access) |
| 8 | Every tunable parameter: default, valid range, evidence, owner | **holds** (pass 3, section 2) | section 2 below | ranges confirmed by the tuning rule once the trace corpus exists (S7) |
| 9 | Migration slice by slice, with keep/reuse/change/retire verdicts and a way back | **holds** | verdicts: [10](10_gap_analysis_and_build_plan.md) s2 (perception and, pass 3, interaction layer); slices s3; way back: s3 and section 3 below | none |
| 10 | Test plan: unit pins and live runs per slice | **holds** | section 4 below; acceptance per slice in [10](10_gap_analysis_and_build_plan.md) s3 | none |
| 11 | Observability: what the trace shows and how a user or the owner reads it | **holds for discovery** (S1 built) | [08](08_evidence_and_research.md) s10; section 5 below | the JSON Lines trace file (S0) and the Workbench view (S8) |
| 12 | Security, privacy and footprint for every new piece | **holds** | section 6 below; [07](07_footprint_and_defences.md) s10 | owner rulings CT-Q-035 to 038 |
| 13 | The documents agree with each other and with the code | **holds after pass 3 fixes** | section 7 below lists the checks run and the contradictions fixed | re-run the checks of section 7 in every slice |
| 14 | Coverage: every standard pattern, role and control is known to the ledger (added by this review) | **holds** | [02_ledger_coverage.yaml](02_ledger_coverage.yaml); check [09](09_verification.md) s8; prototype run: 0 gaps, frozen lists equal to the fetched standards | build the check as a unit test (S6) |
| 15 | No hang on the discovery path (added by this review, from evidence) | **holds since S1**; **not on the forms path** | S1: listings-only `analyze_serp` | label pairing is still cubic for forms (defect 11: 165 s on one page with 3 inputs); S3 caps it (order 2) |

## 2. Parameter register

Defaults are for the worst-case profile. *Owner* is who may change the value:
**tuning** means the tuning rule (CT-ALG-019) within the range, with its
evidence recorded; **owner** means a ruling.

| Parameter | Default | Valid range | Evidence | Owner |
| --- | --- | --- | --- | --- |
| Run similarity `τ` | 0.75 | 0.6 to 0.9 | Lemma 2: a promoted variant of a 30-label card scores ≥ 0.9; nav vs cards far below ([06](06_mathematics.md) s1) | tuning |
| Run cohesion `τ_c` | 0.65 | 0.5 to 0.8 | single-linkage drift example (s1) | tuning |
| Window `K`, depth `D` | 3, 6 | 1-5, 3-10 | `O(n·D·K)` budget (s11) | tuning |
| Climb levels `h` | 12 | 6 to 16 | identity at +10 on Bing (CB-1) | owner |
| Record-root share | 0.8 | 0.6 to 1.0 | S1 fixtures: 100% of records at the chosen level on Bing, Jobvite, Ashby, LinkedIn | tuning |
| Related-link overlap | 0.5 | 0.3 to 0.8 | S1: LinkedIn posting slug carries the title (1.0); company links 0 | tuning |
| Link-title distinctness | 0.8 | 0.6 to 1.0 | S1: Jobvite titles all distinct; repeated "Apply" columns fail | tuning |
| Title-relation link term | 0.5 | 0.3 to 1.0 | S1: same-host Jobvite links scored 0 without it | tuning |
| Candidate threshold, selection margin | 0.5, 0.5 | 0.3-0.8 | `url_evidence` (existing, pinned) | tuning |
| Anchors per record | 64 | 16 to 256 | s12 ALG-004 cap | owner |
| Text cap per node | 256 chars | 128 to 1,024 | S1 fixtures: longest heading or link name under 200 chars | owner |
| Text budget per observation | 2,000,000 chars | 0.5M to 8M | 05 s14 visible-text cap | owner |
| Node `N`, byte `B`, depth `D_cap`, siblings `S` | 30,000; 8 MB; 64; 2,000 | profile-dependent | 05 s14 measurements | owner (per profile) |
| Residual pairing `m` | 120 | 60 to 300 | cubic growth, 1.6 s at 302 (A) | owner |
| Script deadline, settle `T_max`, scroll rounds `P_max` | 10 s, 10 s, 10 | 5-30 s, 5-30 s, 3-30 | LR-5, L50, C14 | owner |
| New windows per action, option-list waits | 4, 12 | 2-8, 6-24 | design | owner |
| Card activations per page | 8 | 0 to 20 | existing constant (`DEFAULT_MAX_CARD_ACTIVATIONS`) | owner |
| Filter confirmations to learn a parameter | 2 | 2 to 3 | ALG-027 proof sketch | tuning |
| View-template minimum `n_min`, re-verification sample | 3, max(3, 5%) | 2-10, 1-20% | ALG-028 | tuning |
| View agreement: description Jaccard, date tolerance | 0.8, 1 day | 0.6-0.95, 0-3 days | ALG-028 | tuning |
| Domain memory: entries, expiry, quarantine after failures | 2,000, 30 days, 2 | 500-10,000, 7-90, 1-3 | s10 | owner |

## 3. The way back, per slice

Every slice lands as reply files applied by `kimicli.py`, which keeps an undo
manifest (`kimicli.py --undo <manifest>` restores byte for byte), and as one
commit that can be reverted. In addition:

| Slice | What can go wrong on the owner's machine | Way back |
| --- | --- | --- |
| S0 | a cap fires on a real page and truncates useful content | caps are parameters; raise per profile (section 2), the truncation flag says which fired |
| S1 | a page that resolved before resolves worse | revert the reply files; the S1 record shows which rule changed the outcome (title source, record level, reason). No page regressed on 56 specimens (cloud) |
| S2 | ranked runs pick a worse group than today | configuration key `perception.records` = `legacy` (default until the S2 acceptance run passes) or `runs` |
| S3 | access port breaks an adapter | the old `MathDOMAdapter` path stays behind the port shim until S6 |
| S4 | forms tools mislabel fields | the existing service stays behind `FormUnderstandingPort`; the submission gate is unchanged |
| S5 to S9b | new capabilities only | each is opt-in by engine call site; turning it off restores today's flow |

## 4. Test plan per slice

| Slice | Unit pins (CI, no network) | Live runs (owner's machine, three sources) |
| --- | --- | --- |
| S0 | a fault-injection pin per cap; iterative-walk pins at depth 3,000 | stage timings on the worst-case laptop |
| S1 (built) | 36 tests: 10 teeth pins red at `7701de8`; fixture pins on Bing, Jobvite, LinkedIn, Ashby; Google fixture pin waiting | Google `site:` search, Bing, a Jobvite board: ≥ 1 resolved record each, with the page record in the log |
| S2 | Lemma 1-3 property tests; fixtures CT-PH-001..008 | recall on ANCHOR with intervals; no regression on Bing |
| S3 | capability model, truncation flags, shadow and frame pins | CT-PH-080..082 on three sources |
| S4 | CONTROL forms; false-optional rate | observe-only on three live forms |
| S5 | HITL edge-case table, one pin per row | pause and resume on three sources |
| S6 | import-boundary pin; coverage check (09 s8) | none |
| S7 | tuning-rule and rollback pins | none (offline over traces) |
| S8 | failure classification over recorded failures | none |
| S9a | one pin per widget kind and per ALG-027 outcome over recorded before/after observations | a filter applied, verified and its parameter learned on three sources |
| S9b | replay pins over stored view pairs | a cheaper verified view chosen on three sources |

## 5. Observability: reading a discovery record

The session log file holds, per discovery pass, one line from logger
`auto_apply.trace`: `page record <source> {json}`. Read it in this order:

1. `observation.truncations`: empty means nothing was cut; `text_cap`,
   `text_budget` or `depth_cap` mean part of the page was not read.
2. `detection.group_sizes`: the first number is the group read; a large
   second group can be the real results (a sign for S2).
3. `record_level`: `detected`, `+1`, …; empty means no level held a title and
   a link, so cards were read at the identity level (anchorless cards).
4. `counts`: `kept:title_and_link` is the yield; every other `fate:reason`
   says why the rest were lost (`dropped:no_title`, `deferred:multi_route`,
   `deferred:no_eligible_link`, `deferred:no_link`).
5. To see a dropped card's links, search the same log for
   `discovery url:` lines with the card's `url_ref`.

The finalize pass adds `opened:*` decisions, one per click, and each card's
fate after clicking. A run where every card is `deferred:no_link` on a results
page is the signature of anchorless cards (the jobs widget case of LR-1).

## 6. Security, privacy and footprint of the new pieces

| Piece | Holds because |
| --- | --- |
| Page record (S1) | no page text by construction (pinned); `url_ref` local only, never exported (CT-Q-038) |
| LR-6 log lines | DEBUG, session log file only, never the console; the session record already holds the kept URLs |
| Fixture folder for owner pages | git-ignored, so a saved results page with account details is never committed; the pin strips scripts and event handlers before loading |
| Extraction script changes | read-only DOM reads; one computed-style read per zero-size element; no network |
| Filter operation (S9a) | through the existing interaction layer and its pacing; one operation per piece, then the URL (07 s10) |
| Alternate views (S9b) | plain GETs after `robots.txt`; never a key, never a sign-in; hosts that refuse are never read |

## 7. Consistency checks run in pass 3

| Check | Result |
| --- | --- |
| Ledger YAML and Markdown agree row for row and status for status (4 parts) | 421 rows, 0 mismatches |
| Coverage check prototype (09 s8) | 0 gaps, 0 unknown row IDs; frozen APG (30), ARIA (94) and input-type (22) lists equal the fetched standards |
| Readiness script (rows without tool, verification or slice) | 0, 0 (after fixing CT-PH-213), 0 |
| AA docs gate (`tests/infrastructure/test_docs_gate.py`) | passes on the result |
| Contradictions fixed | 06 s2 still called the 8-card case unexplained (now: H1 and H2 confirmed, a fourth cause found); 10 s1 listed defects 4, 9 and 23 as open (now closed or fixed, with commit); 04 lacked the pass-3 requirements (added); 05 s14 had no text cap although S1 introduced one (added); CT-Q-030 recorded as ruled |

Scripts: `work/docs3/` in the evidence set (`build_docs3.py`, `build_plan.py`,
`readiness_check.py`, `check_coverage.py`, `scan_patterns.py`).

## 8. What pass 3 changed in this review, and why

1. **Slices for every row** ([02_ledger_plan.yaml](02_ledger_plan.yaml)): 92
   rows named their tool in words, so no slice could be derived for them.
2. **Parameter register** (section 2): parameters were scattered over six
   pages, some with no range or owner.
3. **Way back per slice** and the `perception.records` switch for S2 (section 3,
   [10](10_gap_analysis_and_build_plan.md) s3): the plan had no rollback.
4. **Slices S9a and S9b** for the two new families, with acceptance.
5. **Coverage as a check** ([09](09_verification.md) s8) with a prototype run.
6. **A measured hazard promoted**: label pairing on the discovery path (165 s),
   removed from discovery in S1; on the forms path it stays the top risk.
7. **Consistency fixes** listed in section 7.

## 9. What remains, in order

Pass 4 (slice S4 in part): the form reader (`form_fields.py`) is bounded by the
residual cap (`m <= 120`, 8 candidates per control) and records every cap that fired
in `FormRecord`; parameters `residual_cap`, `candidates_per_control`, `em`,
`max_label_distance`, `section_gap` are tuning parameters in `FormReadingParams`;
`trap_threshold` (0.09, `C_trap = 10 C_skip`) is a safety parameter (owner). Way back:
the reply files' undo manifests restore the previous reader.

| # | Item | Needs | Order reason |
| --- | --- | --- | --- |
| 1 | Measure every budget and cap on the owner's worst-case laptop; enforce caps at the tool boundary (G2) | a measurement on the owner's machine; slice S0 | every budget here is derived, not measured |
| 2 | First owner run of the S4 form reader on three ATSs (Greenhouse, Ashby, Lever or Eightfold), observe-only, with the form record logged | the owner; `reply_files_forms` | the cap on label pairing (defect 11) and the trap rule are in place (pass 4) but proven only on owner captures replayed in `cloud`; the first real application waits on this |
| 3 | The owner's Google results page as a fixture, and one live Google run with the S1 record | the owner; the skipping fixture pin names the path and the browser steps | settles the LR-1 jobs-widget hypothesis |
| 4 | Owner rulings CT-Q-026 (robots), CT-Q-035 to CT-Q-038 | owner rulings | they gate which views and sources may be used |
| 5 | Records tool with ranked runs (S2), replacing the S1 stopgaps | slice S2 | 28 specimen pages with records still resolve none |
| 6 | The JSON Lines trace writer and the coverage check as unit tests | slices S0 and S6 | observability and coverage stay mechanical |
| 7 | Evidence for the 23 new rows with fewer than three observed sources (toolbar role, page-size select, tree and treegrid, grid, splitter, spinbutton, date-time variants, struck text, AMP, mobile views, database views) | captures from the owner's machine or more cloud captures | rows exist; their recognisers need fixtures |
| 8 | Filters and toolbars (S9a), then alternate views (S9b) | slices S9a, S9b after S2 | depend on records and the contract |
| 9 | Typed protocols for each tool | each tool's slice | written with the code |

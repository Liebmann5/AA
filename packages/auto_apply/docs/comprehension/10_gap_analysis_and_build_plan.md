---
title: "Page Comprehension Toolkit: Gap Analysis and Build Plan"
status: needs-review
last_verified: 2026-11-02
verified_against: "7701de8 + S1 reply files (pass 3)"
audience: contributors
---

# Gap analysis and build plan

Retirement follows the repository rule: nothing is deleted; replaced files go to
`docs/old_retired_files/` through `retire.py` once they have no consumer
([ADR-016](../adr/016_retirement_over_deletion.md)).

## 1. The measured defects, re-verified

| # | Defect | Evidence at `1bf7935` | Verified | Closed by |
| --- | --- | --- | --- | --- |
| 1 | Grouping hash includes CSS classes, contradicting the code's own rule | `math_dom.py:171-177` vs `structural_hashing.py:39`; probe: equal structure + one extra class → different hash | reproduced locally | CT-ALG-001/002 (S2) |
| 2 | Marker fraction counts any non-tracking `data-*` on any descendant; rarely separates groups | `structural_hashing.py:34-49` | read | CT-ALG-003 identity-by-distinctness (S2) |
| 3 | Climb picks the lowest level with an identity attribute, not the level holding heading and link | `card_static_resolution.py:152-172` | read | record-root rule, Lemma 3 (S2) |
| 4 | Extraction keeps only direct text; `<h3><span>T</span></h3>` has an empty heading | `math_dom_adapter.py:87-95`; probe: `'Engineer 1'` vs `''` | reproduced locally | full-subtree text rule: **closed in S1** (reply files `reply_files_s1`) |
| 5 | No computed style | adapter script has none; `occlusion.py` reads inline style only | read | `SNAPSHOT_LAYOUT` / style batch (S3) |
| 6 | No shadow-DOM traversal; depth cap 50 silent | `math_dom_adapter.py:62,72` | read | truncation flags, shadow capability (S3) |
| 7 | Card guard excludes `<a>` and custom elements; area floor a constant | `structural_hashing.py:21-22,74` | read | CT-ALG-003 (S2) |
| 8 | One group only | `dom_segmentation.py:760-818` (`max` of groups) | read | ranked runs (S2) |
| 9 | Decisions recorded as counts only | `dom_segmentation.py` logging; LR-6 | read | trace: **closed in S1** (per-page record, LR-6 log lines) |
| 10 | Bible 9.3 describes a detector that is not the live one | Bible 9.3 vs `_detect_job_listings` | read | Bible edit, S6 |
| 11 | Label pairing runs a square Hungarian over every visible text node in the container: cubic, no cap | `dom_segmentation.py` `_pair_labels_to_inputs`, `_collect_label_candidates`; A: 1.6 s at 2 inputs + 300 text nodes | probe (pass 2) | ladder + residual cap `m ≤ 120` (S3) |
| 12 | Honeypot rule skips real fields: label on the right (RTL) or > 50 px above; substring trap names (`address2`, `attestation`, `latest_employer`, …) | `dom_segmentation.py` `_is_honeypot`, `_has_associated_label`; `honeypot_detection.py` `SUSPICIOUS_NAME_PATTERNS`; A | probe (pass 2) | CT-ALG-014 decision rule, token matching, computed direction (S3) |
| 13 | A CSS-hidden required input has no geometry, so it is excluded from interactables and never reported; `HoneypotDetector` treats missing geometry as "not a honeypot" | adapter script `rect.width > 0 \|\| rect.height > 0`; `_is_visible`; `_check_geometry`; A | probe (pass 2) | requiredness from the DOM regardless of geometry (S3) |
| 14 | Extraction script: no node, byte or time cap; depth-50 truncation silent; shadow roots not walked; one frame level, all frames skipped on a count mismatch | `math_dom_adapter.py` `_EXTRACTION_SCRIPT`, `_stitch_iframes`; A: 30k rows 16.1 s, 11.1 MB; 0 anchors from a shadow root | probe (pass 2) | caps and flags (S0), shadow and frame capability (S3) |
| 15 | `label_input_pairing.build_parent_map` keys by value: identical cards collapse, and every lookup re-hashes a subtree | `label_input_pairing.py:206-222`; used by `mathematical_web_analyzer.py:173`; A: 50 cards → 3 keys | probe (pass 2) | index identity (S2) |
| 16 | Vetting's descriptor pairing runs Hungarian over every span/div/heading with text in the main area: cubic on a long posting | `mathematical_web_analyzer.py:160-181` | read (pass 2) | JD sections by structure (S5) |
| 17 | `iter_nodes`, `_build_dom_node` and the structural hash recurse in Python; safe today only because the script stops at depth 50 | `math_dom.py` `iter_nodes`, `_compute_structural_hash`; A: `RecursionError` at depth 3,000 | probe (pass 2) | iterative traversal (S2) |
| 18 | The verdict has no kind for plain block pages and rate limits; misreads a block after a login redirect as a login wall | `challenge_assessment.py`, `page_assessment.py`; A: 10 of 16 challenge/block pages not recognised as blocks | replay (pass 2) | block kind (S1) |
| 19 | The verdict calls list pages with a search box application forms, an invisible reCAPTCHA on a formless form a gate, an empty page with JSON-LD a job description, and a sign-in page a confirmation | `page_assessment.py` precedence; `apply_target.page_has_fillable_form`; A | replay (pass 2) | family model as evidence, not first match (S1, S4) |
| 20 | Closed and missing postings are not recognised in the wording and statuses met live | `page_phrases.py` tables; A: 0 of 4 | replay (pass 2) | phrases per locale plus structure (S5) |
| 21 | `MathFormUnderstandingService` keeps per-call state on the instance (`_parent_map`, `_text_nodes_cache`, `_root_for_label_search`) although documented as stateless and thread-safe | `dom_segmentation.py` `analyze` | read (pass 2) | pure function over the `Doc` (S2) |
| 22 | `MathPageUnderstandingAdapter` re-extracts the whole DOM in each of `analyze_serp`, `analyze_form` and `analyze_job_listing`; `analyze_form` reports confidence 0.9 whenever any field exists | `math_dom_adapter.py` | read (pass 2) | one observation per epoch; calibrated confidence (S2) |
| 23 | Every control is reported required: `_is_required` tests `get_attribute("required") is not None`, but `get_attribute` returns `""` when the attribute is absent | `dom_segmentation.py` `_is_required`, `math_dom.py` `get_attribute`; A (stage 5): 34/34, 40/40, 14/14 on three live forms | live run (pass 2, cloud) | presence test on the attribute tuple: **fixed in `7701de8`** (unit-pinned; no live proof yet) |

| 24 | Discovery's `analyze_serp` ran the whole form analysis (label pairing, defect 11) to obtain the listings | S1 specimen run (cloud): 165 s on C13, 356 s on C05, 5.4 s on a live SmartRecruiters board | measured (S1) | listings-only detection: **closed in S1** |
| 25 | Two links in one card to the same destination (title link and URL line) counted as two routes: `multi_route`, card dropped | S1 trace: Bing fixture 10/10 | trace (S1) | merge by canonical URL: **closed in S1** |
| 26 | A direct same-host posting link with an opaque slug scores 0 and is never eligible (H2) | S1 trace: Jobvite 106/106 `deferred` | trace (S1) | title-relation link term: **closed in S1** |
| 27 | Dead-end text matched as a substring: with full link names, "Help Desk Technician" or "Reporting Analyst" would be rejected | `url_evidence.evaluate_candidates`; S1 pin | read (S1) | phrase covering half of a short name: **closed in S1** |
| 28 | The climb reads cards at the lowest level with an identity attribute, below the record (H1, defect 3); heading-only titles drop link-titled rows | S1 trace: Ashby, LinkedIn, Bing; Jobvite | trace (S1) | record-root rule and link-tier title: **stopgap in S1**, replaced by S2 |

*S1 finding on LR-1* (cloud, from the trace on reachable fixtures; Google itself unreachable): the "6 dropped for no title" case is defect 4 or a link-titled row (defects 4, 28); the "8 with a heading, no link eligible" case matches defects 25, 26 and 28 on Bing and the boards, and, for Google, the one resolved click going to ZipRecruiter under a `site:jobs.jobvite.com` query points at the jobs widget (anchorless `role=button` cards) being the selected group. The S1 record now names the group sizes, title sources and per-card reasons, so the owner's next Google run settles it ([evidence: `s1_live_check.md`]).

*Live observations not explained by the code reading* (LR-1, as written in pass 2): "6 selected, all dropped
for no title" is consistent with defect 4; "8 selected, each with a heading, no link
eligible" is **not** explained by any defect above (H1-H3 in 06 section 2). The first
slice captures a fixture and a trace before changing a threshold.

**Code read in full in pass 2** (pass 1 read several of these by docstring):
`domain/models/math_dom.py`, `adapters/secondary/perception/math_dom_adapter.py`
(script, iframe stitching, `MathPageUnderstandingAdapter`),
`domain/services/dom_segmentation.py`, `structural_hashing.py`,
`label_input_pairing.py`, `honeypot_detection.py`, `page_assessment.py`,
`challenge_assessment.py`, and the job-description path of
`application/services/mathematical_web_analyzer.py`. The owner's design
conversation was also read in full. Its proposed code is the origin of several
defects above. Its Hungarian solver padded with infinity never terminates on a
non-square matrix (reproduced offline in the evidence set); today's `1e9`
padding avoids that.

## 2. Existing code against the blueprint (file by file)

| File | Verdict | Plan |
| --- | --- | --- |
| `domain/models/math_dom.py` | **Change** | keep `Geometry`; `DOMNode` becomes a `NodeView`; hash without classes (S2 shim); retire eager md5 |
| `domain/models/math_webpage.py` | Keep, extend | findings map to these types via the shim |
| `domain/ports/page_understanding_port.py` | **Keep as shim** | implemented over the new tools (S6) |
| `domain/ports/math_perception_port.py`, `math_reasoning_port.py` | Keep as shim | thin |
| `domain/services/dom_segmentation.py` (830 lines) | **Change / split** | records → CT-T-008; forms → CT-T-010; job-listing detection retired when unreferenced |
| `domain/services/structural_hashing.py` | **Change** | keep `is_card_like` (generalised), drop the second hash vocabulary |
| `domain/services/card_static_resolution.py` | **Change** | `extract_card_title` full text; identity climb replaced; learned attributes stay in-run (R-20 guard) |
| `domain/services/url_evidence.py` | **Reuse** | link eligibility input to CT-ALG-004 |
| `domain/services/label_input_pairing.py` | **Change** | add ladder (L1-L6) before assignment; explicit `c0`; direction-aware |
| `domain/services/convex_hull.py` | Keep (optional) | region helper, not on the critical path |
| `domain/services/page_assessment.py`, `challenge_assessment.py` | **Reuse** | = CT-T-006; extend kinds (feed, consent) |
| `domain/services/honeypot_detection.py`, `entropy.py` | **Change** | decision rule with cost ratio; entropy weight small |
| `domain/services/occlusion.py` | **Change** | computed style / paint order input |
| `domain/services/field_type_inference.py` | **Change** | autofill tokens first; token matching |
| `adapters/secondary/perception/math_dom_adapter.py` | **Change** | `AccessPort` adapter; full-subtree text; truncation flags; optional layout snapshot |
| `adapters/secondary/perception/math_perception_adapter.py` | **Change** | consumes `Doc` |
| `adapters/secondary/perception/aom_adapter.py` | Keep | `AX_TREE` capability source |
| `adapters/secondary/perception/dom_adapter.py` | Keep | until superseded; no new use |
| `application/services/webpage_analyzer.py`, `mathematical_web_analyzer.py` | **Change** | thin engine-facing services over tools |
| `application/services/page_analysis_router.py`, `domain/models/analysis_tier.py` | **Change** | = CT-T-021 strategy selection |
| `application/services/page_feedback_service.py` and repository | **Change** | generalise; n_min from the tuning rule; read at run start |
| harvest baseline repository, `degradation_detector.py` | **Change** | snapshot at start (replayable) |
| `application/services/page_action/` | Keep, extend | footprint-aware method choice; ADR-022 checkpoint lives here; file by file below (pass 3) |
| `adapters/secondary/discovery/components/card_activation.py` | **Change** | value pinning (R-20); verdict after each click (LR-4) |
| `adapters/secondary/discovery/strategies/selector_loader.py` | Keep | lowest memory tier |
| `adapters/secondary/browser/*`, `infrastructure/browser_cascade.py`, `resilient_driver.py` | Keep, extend | declare capabilities; deadline on every command (LR-5, S0) |
| `application/services/page_copier.py`, `domain/models/page_copy.py`, `replay_service.py`, `domain/services/replay.py` | **Reuse** | L2 and replay |
| `domain/models/annotation.py`, `application/services/labelling.py` | **Reuse** | gold labels |
| `application/workflows/*` | Change (consumers) | consume findings; keep the gate; no re-derivation |
| `resources/ats/*.yaml`, `resources/engines/*.yaml` | Keep | memory/selector tier; sampling frame |
| `tests/benchmarks/ats_forms/` | Reuse | CONTROL set |
| Static fetch path | stays retired ([ADR-013](../adr/013_static_path_retirement.md), `old_retired_files`) | replay is not browsing |

### The interaction layer, file by file (pass 3)

Read in full for the contract of [05](05_architecture.md) s17. Verdict per file; *how* stays here, *what* comes from the toolkit.

| File | What it does | Tests | Verdict | Plan |
| --- | --- | --- | --- | --- |
| `page_action/service.py` | facade: navigate (bounded retries, warm-up), find and wait, delegates the rest | boundary pin, many unit pins | **Reuse** | executes `ActionRequest`s; no toolkit logic enters it |
| `page_action/result.py` | `ActionResult(success, reason, element, rung, effect)` | used everywhere | **Reuse** | is the `ActionOutcome` of the contract; the engine adds the epoch |
| `page_action/state.py` | shared `PageActionContext` (config, RNGs, pacer) | boundary pin | **Reuse** | unchanged |
| `page_action/probe.py` | geometry, reachability, panes, frames, effect after action | real-browser pins (`test_probe_real_browser.py`, skipped without Chrome) | **Reuse** | its effect field feeds `EffectCheck` as a first signal; the toolkit's comparison of observations decides |
| `page_action/clicking.py` | click ladder (pointer, keyboard, native, JS last), hover | unit pins | **Reuse**; **change** (small) | a keyboard operation for slider and range thumbs on the existing keyboard rung (CT-PH-244) |
| `page_action/scrolling.py` | into view (pane-aware), container, feed, reveal | unit and real-browser pins | **Reuse** | split panes and feeds (CT-PH-018, 157, 241) |
| `page_action/text_input.py` | text entry, select and checkbox values | unit pins | **Reuse** | typing, select and check intents |
| `page_action/pacing.py` | settle, macro pause, warm-up, idle | unit pins | **Reuse**; **change** (small) | settle returns its outcome where the toolkit needs `stable` vs `timeout` |
| `interaction/human_like_adapter.py` | `UnifiedInteractor` dispatch to handlers; `InteractionExecutor` runs `InteractionPlan`s | `test_handler_protocol.py`, `test_fill_evidence.py` | **Reuse** | executes plans whose actions come from toolkit findings |
| `interaction/handlers/text.py` | text, contenteditable | protocol pin (contenteditable unpinned) | **Reuse**; pin contenteditable in S4 | CT-PH-036, 224 |
| `interaction/handlers/select.py` | native select and comboboxes, semantic option match | none-attribute guard pins | **Reuse** | CT-PH-034, 039; the async option-list protocol (CT-T-015) plans the steps, the handler acts |
| `interaction/handlers/checkable.py` | radio and checkbox with state verification | none found by name | **Reuse**; add a pin in S4 | CT-PH-035, 245 |
| `interaction/handlers/date.py` | three strategies (JS value + events, send keys, type and Tab) | none found by name | **Reuse**; **change** in S4: script value injection moves to the last rung (footprint, 07 s4) | CT-PH-037, 253 |
| `interaction/handlers/file.py` | sets the file input directly | guard pins | **Reuse** | CT-PH-038 |
| `interaction/handlers/base.py` | handler contract | protocol pin | **Reuse** | unchanged |
| `interaction/dom_observer.py` | `FormState` classification, DOM stability wait | `test_page_state_agreement.py` | **Keep both** until S4, then **change** to consume CT-T-010 findings | two classifiers of one state are a single-source-of-truth risk; S4 resolves it |
| `interaction/api_direct_adapter.py` | empty, marked PLANNED in the reachability pin | reachability pin | **Keep** (placeholder) | retiring is the owner's call (Bible 7.4) |
| `discovery/strategies/toolbar_locator.py` | YAML selectors with Math-DOM fallback for engine toolbars | `test_discovery_providers.py` | **Keep both** with CT-T-027 (YAML first) | the lowest-memory tier stays; CT-T-027 covers surfaces without YAML |
| `navigation/page_advancer.py` | verified page advance ladder | `test_page_advancer.py`, real-browser pins | **Reuse** | the model for ALG-027's verification |
| `applications_workflow.py` HITL: approval gate, `Checkpoint` enum, `_pause_for_challenge` (ruling A) | submission gate, in-place CAPTCHA pause | workflow pins | **Reuse** | `irreversible` requests and challenges route here unchanged |

## 3. Build slices (small, ordered)

Each slice names acceptance criteria tied to ledger rows and is shippable alone. No slice
waits for the kernel (CT-Q-024).

**S0. Measure and bound (no behaviour change).**
Instrument stages (acquire, transfer, parse, group) and run `aa_measure.py`-style timing
on the worst-case laptop; deadline on every browser command (ADR-022 minimum slice items
1 and 5); freeze `LIVE-SET v1.0` candidates ([09](09_verification.md)); run CT-EXP-001.
Pass 2 adds: enforce the caps of [05](05_architecture.md) s14 at the tool boundary (node, byte,
depth, frame, script deadline, settle, scroll, residual pairing), each with a truncation flag;
replace the Python recursions with iterative walks; run the verdict replay of s5 in CI over
the frozen specimen fixtures (CT-Q-027).
*Accepts:* CT-NFR-004/005 get measured values; CT-NFR-010 and CT-NFR-026 `[~]` with a
fault-injection pin per cap; footprint table cells measured; every catalogue entry of
[12](12_edge_cases_and_adversity.md) that names a cap has a pin.

**S1. First slice: read result lists on real pages from three sources.** *(the slice that
unblocks LR-1)* **Delivered in pass 3** as reply files `reply_files_s1` (36 tests; live cloud 417/417 on six boards; see 09 s9). The Google fixture waits for the owner; Lever was not captured (its `robots.txt` names the capturing agent).
1. Trace (CT-T-018, L0-L1) and URL-level discovery logging (LR-6): every card found,
   kept, dropped, opened, with reason.
2. Full-subtree text and accessible-name rule in the extraction (defect 4).
3. Capture cleaned fixtures of one Google, one Bing and one Jobvite-restricted results page
   (the three LR-1 sources) and the fixtures of two further sources (LinkedIn public list,
   a Lever board).
4. Explain the "heading present, no link eligible" case from the trace; fix its cause.
*Accepts (rows):* CT-PH-001, 003, 012 move to `[~]` with a fixture pin each and a live
run recording ≥ 1 resolved record on each; CT-FR-006 and CT-FR-022 `[~]` improved; defect
4 pin red→green.

**S2. Records tool (CT-T-008).** Skeleton multisets, windowed sibling runs, ranking,
record-root rule, ranked output (defects 1, 2, 3, 7, 8). *Accepts:* property tests for
Lemmas 1-3; CT-PH-001..008 fixtures; recall measured on ANCHOR with intervals; no
regression on Bing (the working source).

**S3. Access port and `Doc`.** Capability model, `PageObservation`, columnar `Doc`,
truncation flags, shadow/iframe traversal, optional layout snapshot (defects 5, 6).
*Accepts:* CT-FR-001/002/003; CT-NFR-005 measured; CT-PH-080..082.

**S4. Forms tools.** Segmentation, pairing ladder, typing, requiredness (native
`valueMissing` first), error mapping; `SubmitPredictor` advisory; widgets and the option-list
protocol. *Accepts:* CT-FR-009..016; CT-PH-030..059 on CONTROL then observe-only on
live; false-OPTIONAL rate reported.

**S5. Transitions, windows, resume.** Settle, DocDiff, window set, OAuth pop-up
classification, `PauseContext` and resume protocol. *Accepts:* CT-FR-019/020; CT-PH-062,
080..089; the HITL edge-case table has a test per row.

**S6. Library boundary, shims, Bible correction.** Import-boundary pin; `PageUnderstandingPort`
shim; Bible 9.3 corrected; retirements via `retire.py`. *Accepts:* CT-FR-030, CT-NFR-001.

**S7. Domain memory and tuning.** After the trace corpus exists. *Accepts:* CT-FR-024/025;
the tuning rule's tests; rollback test.

**S8. Workbench.** Review first (reads traces and ledger), Explore after. *Accepts:*
CT-FR-027/028; failure classification on recorded failures.

**S9. Capabilities.** Feed/Source Channel seam use, additional access adapters, AI-era
rows.

**S9a. Filters and toolbars (pass 3; after S2).** CT-T-027 Controls, ALG-027 effect
verification and parameter learning, the keyboard operation for sliders. *Accepts:*
CT-FR-035 and CT-PH-215..231 `[~]` with fixture pins (a control per widget kind,
recorded before and after observations for each ALG-027 outcome); on the owner's
machine, three sources where a filter is applied, verified and its parameter learned
and confirmed; footprint measured (CT-NFR-027).

**S9b. Alternate views (pass 3).** CT-T-028 Views, `ViewMap`, ALG-028 and ALG-029, the
view catalog beside domain memory. *Accepts:* CT-FR-036 and CT-PH-256..266 `[~]` with
replay pins over stored view pairs (page and feed, page and API, embedded and own
URL); a live run on three sources choosing a cheaper verified view.

*Way back.* Every slice lands as reply files applied by `kimicli.py`, which writes an
undo manifest; a slice that fails on the owner's machine is reverted with
`kimicli.py --undo <manifest>` (or a revert of its commit). From S2 on, the new
record reading sits behind one configuration key (`perception.records`, values
`legacy` and `runs`, default `legacy` until the S2 acceptance run passes), so the
owner can switch back without a code change ([13](13_production_readiness.md) s3).

Ordering rationale: S0 first because every budget in this suite is derived, not measured;
S1 because the owner's run found zero records and a trace makes every later slice
diagnosable; S2 before S3 because the record tool works on today's adapter output.

## 4. Release checks that keep the suite true

- A pin that the ledger YAML and Markdown agree, that every `CT-FR/NFR` in `04` has a
  ledger row, and that a row is `[x]` only if its `ev` names a trace and a set version.
- An import-boundary pin for the library; a performance gate comparing per-tool time with
  the previous release on a fixed corpus.
- Bible §9 carries a one-line link to this suite; `STATUS.md` carries the headline rate
  once S1 and S2 are measured (never before).

## 5. Baseline: today's code on the pass-2 specimens (environment `cloud`)

AA's page verdict (`assess_page` at `1bf7935`) was replayed offline over the
saved specimens (119; the four Notion re-probes, N58 to N62, have no summary and were not replayed). It is a pure function of URL, title and rendered HTML, so the
replay is exact for the verdict. Behaviour on the owner's machine can differ,
because the pages themselves differ there. This baseline feeds the gap
analysis; it changes no `[x]`.

| Family | Specimens | Today's verdict kinds |
| --- | --- | --- |
| list | 55 | UNKNOWN 44, APPLICATION_FORM 9, JOB_DESCRIPTION 1, ERROR_404 1 |
| posting | 30 | UNKNOWN 15, JOB_DESCRIPTION 14, APPLICATION_FORM 1 |
| form | 15 | UNKNOWN 4, APPLICATION_FORM 4, CAPTCHA_BLOCK 3, JOB_DESCRIPTION 2, LOGIN_REQUIRED 1, SUCCESS_PAGE 1 |
| gate | 19 | UNKNOWN 11, CAPTCHA_BLOCK 6, LOGIN_REQUIRED 2 |

What it shows:

- **Blocks.** Challenges with vendor markup are recognised (Google `/sorry/`,
  Cloudflare, DataDome: 6 pages). Plain blocks and rate limits are not:
  DuckDuckGo, Brave, Mojeek, Indeed, Workable ×3, Drushim and Baitoru return
  `UNKNOWN`, and LinkedIn's block is read as `LOGIN_REQUIRED` (defect 18).
- **Closed postings.** 0 of 4 are judged `CLOSED`. The one board-level 404 is
  found by its title (defect 20).
- **Lists.** 44 of 55 lists are `UNKNOWN`. That is honest, because "list" is
  not a verdict kind; but 9 are judged `APPLICATION_FORM` because of a search box
  or an embedded sign-in widget, and RemoteOK is judged `JOB_DESCRIPTION`
  because of JSON-LD (defect 19).
- **Postings.** 14 of 30 are `JOB_DESCRIPTION`, all through JSON-LD. Postings
  without JSON-LD are `UNKNOWN`, and so is every Notion or shadow-DOM posting.
- **Forms.** Greenhouse and the embedded Google Form are `APPLICATION_FORM`.
  The three Ashby forms are `CAPTCHA_BLOCK` (gated), so AA would refuse them.
  The Jobvite consent step is `UNKNOWN`, the Workday apply shells are
  `JOB_DESCRIPTION`, and the Microsoft sign-in page is `SUCCESS_PAGE`.
- **Cost.** Median 28 ms, p95 224 ms, maximum 2.8 s per page here: about
  0.2 s, 1.8 s and 22 s on the assumed 8× slower machine (EC-39).

The extraction script and `MathFormUnderstandingService` were measured on
adversarial synthetic pages, offline ([12](12_edge_cases_and_adversity.md) s5). A live run of
the full perception path on live pages is part of S0, from the owner's machine.
The pass-2 data-centre environment could not reach the search engines it
matters most for.

### Live perception path (stage 5, environment `cloud`)

AA's extraction script ran in Chromium on ten live pages: lists, postings and
forms, each from three or more sources. `MathDOMAdapter._build_dom_node`,
`MathFormUnderstandingService.analyze` and `resolve_card_group` then ran on the
payloads, all at `1bf7935`, unchanged. Frames were not stitched; the main frame
only. Inputs and outputs are in the evidence set
(`analysis/stage5_live_perception.json`).

| Page (source) | Present | Today's result | Time (script / analyze) |
| --- | --- | --- | --- |
| Jobvite list (nutanix) | 50 rows | 38 cards, 0 titles, 0 links resolved (all deferred) | 277 ms / 6 ms |
| Ashby list (linear) | 31 rows | 31 cards, 31 titles, 0 links resolved | 78 ms / 4 ms |
| Taleo list (D.R. Horton) | 25 rows | 25 cards, 0 titles, 25 links resolved | 241 ms / **1.87 s** |
| HN submissions | 30 rows | 30 cards, 0 titles, 0 links resolved | 136 ms / 20 ms |
| Jobvite posting | 1 posting | company read as "Products" (navigation), 23,429 chars of text including chrome, apply link found | 49 ms / 10 ms |
| Ashby posting | 1 posting | company "Unknown", no apply link | 33 ms / 5 ms |
| Dice posting | 1 posting | company read as the job title, 169,036 chars including chrome | 161 ms / 287 ms |
| Greenhouse form | 21 fields | 34 "fields" (buttons included), all labelled, **all required**, 13 honeypots | 251 ms / 281 ms |
| Ashby form | 36 fields | 40 "fields", **all required**, 7 honeypots | 74 ms / 548 ms |
| Google Form (embedded) | 9 fields | 14 "fields", **all required**, 2 honeypots | 80 ms / 63 ms |

**Reading.** Records are found: 124 of 136 rows were detected as cards. But
**none** came back with both a title and a resolved link, so Discovery would
read 0 usable jobs from these four sources. This is the LR-1 symptom (owner,
Google), reproduced on four more sources in another environment. Forms are
found, but requiredness is always "yes" (defect 23), and 5% to 38% of real
controls are flagged as traps. The slowest analysis step (1.87 s on Taleo) is
label pairing over a search form inside a text-heavy page (defect 11). Peak
Python memory stayed under 1 MB per page. These are cloud baselines for the gap
analysis and change no `[x]`.

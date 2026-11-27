---
title: "Page Comprehension Toolkit: Edge Cases and Adversity"
status: needs-review
last_verified: 2026-11-02
verified_against: "7701de8 + S1 reply files (pass 3)"
audience: contributors
---

# Edge cases and adversity

AA works on the open web, where randomness is the normal case. An edge case
is therefore **as essential as the tool running normally**: a tool that is
right on typical pages and hangs, guesses or goes silent on an odd one is not
finished. This page is the cross-cutting catalogue. For every edge case it
gives the ledger rows, the tools involved, the evidence, and the handling:
what the tool returns, raises or (never) hangs on; how it is bounded; how the
case is detected; what the trace records; and what the user is told.

Evidence tags follow [00](00_index.md): **O** observed live in the pass-2
session (specimen IDs; environment `cloud`), **R** recorded in AA's own
evidence (environment `owner`), **K** recalled, **A** an offline probe of AA's
code at `1bf7935` (no network). The specimens and probes are in the evidence
set ([08](08_evidence_and_research.md), section 9). A specimen shows what a
page looked like to a data-centre client. It is never proof of how AA behaves
on the owner's machine.

## 1. How to use this page

- **Building a tool:** find its section in [section 4](#4-per-tool-handling). Each
  catalogue entry named there needs a unit pin (on a specimen or a synthetic
  page) before the tool counts as `[WIRED]`.
- **Meeting a page AA did not handle:** look it up in [section 3](#3-catalogue). If no
  entry matches, the unknown-unknown rule in [section 2](#2-the-unknown-unknown-rule) applies,
  and the page becomes a new `[?]` row.
- **Reviewing a budget:** the worst cases and tail budgets are in
  [section 6](#6-worst-case-against-typical) and in [06, section 12](06_mathematics.md#12-worst-case-adversarial-inputs-and-tails).

## 2. The unknown-unknown rule

**Statement (CT-INV-013, CT-FR-033).** When a tool, or an engine step that
consumes a tool's findings, meets a state that no ledger row describes, it:

1. **Fails closed.** It returns `Abstain(UNRECOGNISED, evidence)`, never a
   guess. An engine that receives it takes its safe path: Discovery drops the
   page with a reason, Vetting does not pass the job, Applications does not
   type, click or submit on that page.
2. **Records it as a `[?]` row candidate with evidence.** The trace gets one
   `UNKNOWN_PHENOMENON` event carrying the observation hash, the URL host, the
   verdict signals, the tool and its inputs' fingerprints, and the page copy if
   the recording level allows it (CT-Q-017). The Workbench (CT-T-024) lists
   these events; a human turns each into a ledger row, a parameter, or a
   non-goal ([00](00_index.md), "How to add to the ledger").
3. **Hands it to the human.** In attended mode, it raises a checkpoint that
   shows what was seen, in plain words. In unattended mode, it skips and
   records (CT-Q-023), and the end-of-session report lists the case.
4. **Keeps the run's other work going where that is safe.** The unknown is
   contained to its unit of work: one record, one posting or one form. Other
   records on the page, other jobs in the queue and other hosts continue. It
   stops the session only when the unknown is in a shared resource: the
   browser is unresponsive, the profile is unreadable, or every host answers
   with the same unknown state.

**What counts as "no row describes it".** A state is recognised when a tool
returns a finding with confidence above its threshold and the finding's kind is
one the ledger names. Anything else is unknown, including these: a verdict
`UNKNOWN`; abstentions from two or more tools on one observation; a transition
the engine did not plan; a window it did not open; a page whose family scores
have no winner (06, section 3); a timeout whose last observation differs from
every known kind.

**Where it is specified.** Every tool's contract carries it (section 4, last
column), and so does every engine checkpoint:

| Place | Unknown state | Safe path |
| --- | --- | --- |
| CT-T-006 Verdict | no kind above threshold | `UNKNOWN` verdict with signals; never `clear` by default |
| CT-T-007 Regions | no family wins by margin | `UNKNOWN` family; engines treat as not-their-page |
| CT-T-008 / 009 Records, Fields | no run, or runs with no title/link | `Abstain(no-repeat / no-title / no-link)` with candidates |
| CT-T-010 to 015 Forms | control of unknown kind, widget with no pattern | `UNKNOWN` field; not filled; human asked |
| CT-T-016 Transitions | navigation, window or dialog the action did not predict | epoch++, re-observe, `WINDOWS_CHANGED` / `NAVIGATED`; the planned action is dropped |
| CT-T-017 Structured | JSON-LD that disagrees with the visible page | both kept; visible page wins for decisions; disagreement is a finding |
| CT-T-026 SubmitPredictor | anything not certified | `UNKNOWN`, which Applications treats as `WILL_SUBMIT` (ADR-012) |
| Discovery step | page that is not a list, posting or known gate | drop with reason `unrecognised`; continue the queue |
| Vetting step | posting state unknown (open? closed?) | do not pass; record; continue |
| Applications step | anything unknown before an irreversible action | no action; checkpoint; the job is re-queued only by a human |

**Proof obligations.** (a) No tool's return type admits a silent default for an
unrecognised input: each result is a finding with evidence or an abstention
with a reason (pinned by a property test that feeds random DOMs). (b) The
engine's handling of `Abstain` and `UNKNOWN` is total (every branch is named).
(c) Containment: a unit of work cannot raise past its engine step. A tool
exception is caught at the step boundary, becomes `Abstain(TOOL_ERROR)` with the
traceback in the trace, and the step continues with the next unit. This is the
one place a broad `except` is allowed, and it **records**, unlike the swallow
ADR-012 removed.

## 3. Catalogue

Columns: **EC** ID · **case** · **rows** (CT- prefix dropped) · **tools** ·
**evidence** · **handling**, given as *returns / bound / detected by → trace
→ user*. "Today" means the code at `1bf7935`, where a probe measured it.

### 3.1 Degenerate inputs

| EC | Case | Rows | Tools | Evidence | Handling |
| --- | --- | --- | --- | --- | --- |
| EC-01 | Empty page: nothing renders after the settle cap | PH-181, PH-094 | T-002, T-006, T-016 | O: L50 (0 chars after 15 s, JSON-LD present), L14, P24, F05 | returns `Verdict(EMPTY)` after `T_max`; no record tools run / bound: settle cap `T_max` (default 10 s) / detected by text mass 0 and no controls → trace `EMPTY, settle=timeout` → user "page did not load" with the URL. Today: the verdict says `JOB_DESCRIPTION 0.8` for L50 (A) |
| EC-02 | One record only | PH-182 | T-008 | A (run needs ≥ 2 members) | returns no run; the family model can still say "list" from headings and total text; then a single-record fallback (largest linked block in `main`) is offered at lower confidence / bound O(n) / trace `run=none, fallback=single` / user: nothing unless the engine needs it |
| EC-03 | Ten thousand or more siblings | PH-183, PH-113 | T-002, T-004, T-008 | O: L18 (803 rows), C14 (6,554 anchors after 6 scrolls); A: 10k rows extract 6.0 s, 3.7 MB; 30k rows 16.1 s, 11.1 MB | returns the first `N_cap` nodes with `truncated=node_cap` / bound: node cap (default 30,000), byte cap (default 8 MB), per-parent sibling cap (default 2,000) / trace truncation flags / user "large page, read the first part" |
| EC-04 | Depth beyond any cap | PH-184 | T-002 | O: depth 41 (L27), 35-36 (Notion); A: a depth-60 link is dropped silently today | returns the tree to depth `D_cap` with a `depth_truncated` flag and the count of cut subtrees / bound `D_cap` (default 64; iterative walk, no recursion) / trace flag / user only if a needed record was cut |
| EC-05 | No text: only images, canvas or icon fonts | PH-214, PH-079 | T-003, T-009 | O: L62 images became "Go online to view this image" | returns `Abstain(no-text)` for the record; `alt`/`aria-label` are read as text first / bound O(r) / trace `no-text` / user if the page family needs text |
| EC-06 | Duplicate IDs | PH-185 | T-011 | O: L22 (8), L39 (8), L43 (10), L45 (4) | `label[for]` and `aria-labelledby` that resolve to more than one element drop to the next rung of the pairing ladder / bound O(c) / trace `ambiguous-id` / user nothing |
| EC-07 | Card with no link | PH-005, PH-170 | T-009 | O: P15, L53, L55, P08 (Apply buttons with no href); R: Google jobs vertical | `NO_DESTINATION` or `DEFERRED` state; never a guessed URL / trace state / user sees "link not on the card" |
| EC-08 | Link with no href, script-only (`role=link`, `data-href`, `onclick`) | PH-186 | T-009 | O: L28 (38 anchors without href); A: AA's extractor keeps the node but gets no destination | candidate route from `data-href`, `formaction` or the URL pattern, marked `MULTI_ROUTE` or `DEFERRED`; resolution only by an observed click under ADR-022 / trace route kind |
| EC-09 | Identical cards | PH-187 | T-004, T-008 | A: a node-keyed parent map collapses 50 identical cards to 3 keys | nodes are keyed by index in the columnar `Doc`, never by value / property test: k identical siblings give k records |
| EC-10 | Records interleaved with headings or ads | PH-015, PH-002 | T-008 | O: L09 (departments), C04 (ad slots), L06 | runs per section, `allow_gap=1`; ranked runs, not one group / bound O(n·D·K) |

### 3.2 Hostile or unstable inputs

| EC | Case | Rows | Tools | Evidence | Handling |
| --- | --- | --- | --- | --- | --- |
| EC-11 | Obfuscated or rotating class names | PH-079, PH-188 | T-008 | O: hashed-class share over 30% on 12 specimens (scan); R: Google | classes never enter similarity (06, Lemma 2 tolerance) / pin: rename every class, same runs |
| EC-12 | DOM changes while it is read | PH-189 | T-002, T-016 | O: P19 vs C13 (same thread, 95,032 then 95,037 chars) | each observation is one atomic snapshot call; a second read is a new epoch; findings from an old epoch are `Stale` / bound one snapshot per step / trace epoch |
| EC-13 | Timing race: content arrives after load | PH-117, PH-181 | T-016 | O: L50, F05; Workday and Notion render late | settle by volatility hash (ALG-016) with `T_max`; `Timeout(last hash)` is a result, not an error |
| EC-14 | Never-ending scroll | PH-018, PH-161 | T-016 | O: C14 grew for 6 rounds with no end | stop at `P_max` rounds (default 10, Bible 30.1), at no growth for 2 rounds, or at the node cap; trace `stop=cap` / user "list is longer than read" |
| EC-15 | Recycled (virtualised) rows | PH-019 | ALG-018 | O: none found on C14, C15, C16 (cloud) | value pinning before any activation; mismatch aborts that activation / O(1) per activation |
| EC-16 | Decoy and honeypot controls | PH-077 | T-005, ALG-014 | O: hidden `website` (L15), `imgurl` (L02), `career_discipline` (L29) inputs; A: today's detector also flags real fields (EC-31, EC-32) | invisible → never filled; visible and unlabelled → `UNKNOWN`, not filled; trap-token names are weak evidence only |
| EC-17 | Challenge appears mid-task | PH-073, PH-197, PH-196 | T-006, T-016 | O: L54 (login redirect then block), F07 and F10 (hCaptcha beside login), P08 (invisible reCAPTCHA) | every transition re-runs the verdict (ADR-022); `gated` stops the unit and benches the host (ADR-020); `embedded` continues and is recorded |
| EC-18 | Status contradicts content | PH-190 | T-006 | O: L34-L36 (404 + 2,170 jobs), L48 (200 + "no longer available"); A: today all `UNKNOWN` | status and content are both evidence; the content kind wins, and the contradiction is a signal in the trace |
| EC-19 | Missing posting redirects silently | PH-191 | T-006, T-016 | O: L47 | the transition tool compares the requested and final page family; posting requested, list served → `MISSING_REDIRECT` |
| EC-20 | Cross-host redirect | PH-192, PH-089 | T-016 | O: L15, L16, L17, L22, L41 | final host recorded; the off-platform rule (ADR-020, 022) applies to the final host |
| EC-21 | Rate limit or block on first contact | PH-194, PH-195, PH-075 | T-006 | O: L24-L26 (429), L03, L05, L42, C02, C10 (block pages); A: today `UNKNOWN` for all | blocks recognised from status plus a near-empty page with no forms, no records and a block lexicon in any language; the host is benched, never retried in-session |
| EC-22 | Non-English challenge text | PH-073, PH-109 | T-006 | O: C08 (Ukrainian) | challenge markup decides, not text; the lexicon only adds evidence |
| EC-23 | Same posting on several hosts | PH-158, FR-110 | Discovery dedup | O: P18 and P25 | key on posting ID plus normalised title and company; keep every host in provenance |
| EC-24 | Control withheld from this client | PH-180, PH-205 | T-006, T-009 | O: L59, L62 (controls the owner saw are absent) | the absence is evidence, not a fact about the page; `[?]` for the owner's machine |

### 3.3 Environment edges

| EC | Case | Rows | Tools | Evidence | Handling |
| --- | --- | --- | --- | --- | --- |
| EC-25 | Slow or overheating machine | PH-211, PH-133 | all, ALG-022 | K; derived 8× factor (06, section 11) | budgets in work units, not seconds; the meter sleeps between bursts; outputs never depend on wall time |
| EC-26 | Low memory (2 GB shared) | PH-133, NFR-005 | T-002, T-004 | A: 11.1 MB of JSON for 90k nodes, held twice during `dumps/loads` today | byte cap on the script result; streamed parse; columnar `Doc` |
| EC-27 | Missing browser capability | PH-123 to PH-130 | T-001 | design (05, section 5) | declared fallback, named in the trace; a tool that needs it abstains with `CAPABILITY_MISSING` |
| EC-28 | No GPU, different fonts, container | PH-210, PH-138 | T-002, T-005 | O: every cloud capture (server fonts, no GPU) | geometry thresholds in em and relative units; the font fingerprint is recorded with the observation |
| EC-29 | Window resized or zoomed mid-run | PH-209 | T-016 | A: geometry is fixed at capture | resize and zoom events increment the epoch; geometric findings are re-read before any click |
| EC-30 | Proxy or network refuses a scheme or host | PH-210 | T-001 | O: C09 (the cloud proxy accepts HTTPS only) | `ACCESS_REFUSED` with the layer that refused (proxy, DNS, TLS, site); never retried as a site block |

### 3.4 Edge cases of today's code found by the probes

| EC | Case | Rows | Evidence (A, cloud, 4-core Xeon 2.8 GHz, Python 3.14) | Required behaviour |
| --- | --- | --- | --- | --- |
| EC-31 | Real field names containing trap tokens | PH-200 | `address2`, `attestation`, `latest_employer`, `extracurricular`, `email_verification_code` and `contest_entry` are all flagged as honeypots by substring | token match on name parts, never substring; trap names are weak evidence and never decide alone |
| EC-32 | Label on the right (RTL) or more than 50 px above | PH-201, PH-105 | `_is_honeypot` is True in both layouts, so the field is skipped | orientation from computed `direction`; honeypot decided by visibility first |
| EC-33 | Hundreds of text nodes in a form container | PH-202 | 2 inputs with 25/50/100/200/300 text nodes: 0.001/0.008/0.055/0.52/1.6 s, cubic | pairing ladder first; residual Hungarian on at most `m ≤ 120` per section, over unclaimed text near controls only |
| EC-34 | Content in open shadow roots | PH-156, PH-164 | AA's extractor: page shows "Shadow Engineer"; 0 anchors and 0 inputs extracted | `SHADOW_PIERCING` capability; script fallback walks `shadowRoot` |
| EC-35 | Nested same-origin frames | PH-080 | 3 frames in the page, 0 anchors at the top level; stitching handles one level and skips all frames on a count mismatch | frame tree by frame identity, not position; depth cap; flag per skipped frame |
| EC-36 | Required control hidden by CSS | PH-203 | a `display:none` required input has no geometry, is excluded from interactables and is never reported | requiredness read from the DOM regardless of geometry; hidden-but-required becomes a finding (often a custom widget's backing input) |
| EC-37 | Title text only in a child element | PH-001 (defect 4) | `<h3><span>Title</span></h3>` gives `h3.text == ''` | full-subtree text rule (06, section 2) |
| EC-38 | Python recursion on deep trees | PH-184 | `iter_nodes` raises `RecursionError` at depth 3,000 (fine at 900; the script cap of 50 hides it today) | iterative traversal everywhere |
| EC-39 | Verdict on very large pages | NFR-004 | today's verdict: median 28 ms, p95 224 ms, max 2.8 s (C14, 5.6 MB) over 119 specimens | verdict reads a bounded text prefix; parse cost capped by the byte cap |
| EC-40 | Invisible reCAPTCHA on a form without a `<form>` | PH-070, PH-032 | Ashby forms F02, F03, F04 are judged `CAPTCHA_BLOCK` (gated) | an invisible badge is `embedded`; "gated" needs a visible widget or a challenge URL |
| EC-41 | Search box makes a list look like a form | PH-199 | Bing results, a Jobvite home and Dice results are judged `APPLICATION_FORM 0.85` | family model weighs record runs against forms (06, section 3) |
| EC-42 | Sign-in page read as a confirmation | PH-098 | F12 (Microsoft sign-in choices) is judged `SUCCESS_PAGE` | login evidence outranks confirmation phrases; a URL `apply?` is not a confirmation |
| EC-43 | Closed postings in other words or languages | PH-023, FR-116 | 0 of 4 closed or missing postings judged `CLOSED` (L46, L47, L48, L52) | phrase tables per locale plus structure (no apply control, status 404/410, redirect to list) |
| EC-44 | Requiredness of a control with no `required` attribute | PH-051, FR-012 | stage 5 (live): every control on three real forms reported required, because a missing attribute reads as `""`, not `None` | presence test on the attribute; tri-state fusion (06, section 5) |
| EC-45 | Records found without title or link | FR-006, PH-012 | stage 5 (live): 124 of 136 rows detected as cards, 0 with both title and resolved link | full-subtree text rule; link scoring with candidates (06, section 2); `Abstain` with candidates, never a silent drop |

## 4. Per-tool handling

For each tool: the catalogue entries it must pin, what it does on them, its
hard bound, and its unknown-unknown hook. "Bound" means the cap that turns a
possible hang into a typed result. Work units (`wu`) are defined in 06,
section 10.

| Tool | Must pin | On those inputs it | Hard bound (time / memory / steps) | Unknown-unknown hook |
| --- | --- | --- | --- | --- |
| T-001 Access | EC-27, EC-30 | returns capability set; refuses with the layer named | per-command deadline (ADR-022); no retry on a refusal | `ACCESS_REFUSED(layer)` → trace → user |
| T-002 Observe | EC-01, EC-03, EC-04, EC-12, EC-26, EC-34, EC-35 | one atomic snapshot with truncation flags (node, byte, depth, frame, shadow) | node cap 30k, byte cap 8 MB, depth 64, frame depth 3, script deadline 10 s | an observation with any flag set is still returned; flags are findings |
| T-003 Text | EC-05, PH-206, PH-207, PH-208 | decodes, flags mojibake, zero-width, bidi and confusables; never rewrites values | O(chars), capped by the byte cap | unknown encoding → `Abstain(decode)` with bytes kept |
| T-004 Doc | EC-03, EC-09, EC-38 | builds the columnar form iteratively; index identity | O(n), ≤ 100 B/node target | malformed payload → `Abstain(build)` |
| T-005 Visibility | EC-16, EC-28, EC-32, EC-36 | visible / occluded / hidden / honeypot-probability per node | O(n log n) with a box grid | contradictory style data → `UNKNOWN` visibility (not filled) |
| T-006 Verdict | EC-01, EC-17 to EC-22, EC-24, EC-39 to EC-43 | page kind with signals; `UNKNOWN` is a kind | O(min(bytes, cap)) | `UNKNOWN` + signals → section 2 |
| T-007 Regions | EC-10, EC-41 | region tree and family probabilities | XY-cut depth 12; O(b log b) per level | no winner by margin → `UNKNOWN` family |
| T-008 Records | EC-02, EC-03, EC-09, EC-10, EC-11 | ranked runs with features | O(n·D·K), `D=6`, `K≤8`, sibling cap 2,000 | `Abstain(no-repeat)` |
| T-009 Fields | EC-05, EC-07, EC-08, EC-37 | title, link states, metadata with evidence | O(r) per record | `Abstain(no-title/no-link)` with candidates |
| T-010 Forms | EC-36, EC-40 | forms, steps, sections; formless forms by control density | O(n) | control of unknown kind → `UNKNOWN` field |
| T-011 Pairing | EC-06, EC-32, EC-33 | ladder then residual assignment | `m ≤ 120` per section, O(m³) ≤ 1.7·10⁶ steps | no label → `UNLABELED` finding |
| T-012 Typing | EC-31 | autofill token → type → token lexicon | O(1) per control | `UNKNOWN` type → engine asks |
| T-013 Required | EC-36, PH-050 to PH-054 | REQUIRED / OPTIONAL / UNKNOWN by fusion | O(c) | `UNKNOWN` is filled if data exists, else asked |
| T-014 Widgets | PH-039 to PH-042 | APG pattern and operation plan, or none | O(s) per subtree | no pattern → `UNKNOWN_WIDGET`, not operated |
| T-015 OptionLists | PH-039, PH-040 | `FOUND` / `NOT_FOUND` / `NOT_FOUND_BUDGET` | ≤ 12 settle waits, each ≤ `W` | empty or erroring list → `NOT_FOUND(evidence)` |
| T-016 Transitions | EC-12 to EC-14, EC-17, EC-19, EC-20, EC-29 | settle, diff, navigation kind, window set; epoch++ | settle `T_max`; scroll rounds `P_max`; diff O(n) | unplanned window, dialog or navigation → re-observe, plan dropped |
| T-017 Structured | EC-01, PH-162, PH-163 | typed postings with the source of each field; disagreement finding | O(bytes), JSON parse capped at 2 MB per block | unparseable block → kept as text, flagged |
| T-018 Trace | all | append-only events; truncates payloads at the level's cap | O(1) per event; disk pre-check (Bible 30.4) | disk full → stop recording, tell user, keep running |
| T-019 Tune | n/a (offline) | no change without evidence | offline; cooldown | insufficient evidence → no change |
| T-020 Memory | EC-11 | a hint only after verification | 2,000 entries, LRU | failed verification twice → quarantine |
| T-021 Profile | EC-25, EC-26, EC-27 | strategy per tool from machine facts | O(1) | unknown machine → most conservative profile |
| T-022 Replay | all | same bytes on the same inputs | = tools | input hash mismatch → refuse to compare |
| T-023 Ledger | section 2 | loads rows; adds `[?]` candidates | O(rows) | an unparseable row fails the docs gate |
| T-024 Workbench | section 2 | lists unknowns, review queue | UI | n/a |
| T-026 SubmitPredictor | EC-40, EC-36 | `BLOCKED` only when certified; else `UNKNOWN` | O(c) | `UNKNOWN` = `WILL_SUBMIT` for the gate |

## 5. Today's code under adversity (measured, offline)

All numbers are from two probes in the evidence set, `analysis/aa_worst_case_probe.py`
(Python, AA's domain services on synthetic `DOMNode` trees) and
`analysis/js_extractor_probe.js` (AA's extraction script, run in Chromium on
synthetic local pages with no network). Machine: a 4-core Intel Xeon at 2.8 GHz
in a cloud container, Python 3.14.6, Chromium 153. They show the shape of
the worst cases, not the owner's numbers.

| Probe | Input | Result | Consequence |
| --- | --- | --- | --- |
| Label pairing | 2 inputs + n text nodes in one container | n=100: 0.055 s; 200: 0.52 s; 300: 1.6 s; cubic | at n=1,000 about 60 s here and about 8 minutes on an 8× slower machine: a hang in practice, with no cap |
| Honeypot rule | RTL label; label 70 px above; six real names | all flagged | real fields skipped silently on RTL pages and on common layouts |
| Node-keyed parent map (`label_input_pairing.build_parent_map`) | 50 identical cards | 3 keys | wrong parents for identical records; the id-keyed map in `dom_segmentation` is correct |
| `DOMNode` hash | 1,601-node subtree | 5.2 µs per hash, uncached | every dict lookup re-hashes a subtree |
| `analyze` on 10,000 sibling cards | flat list | 0.17 s, 10.5 MB peak, 10,000 cards | flat lists are cheap; deep or text-heavy containers are not |
| `iter_nodes` | chain of 3,000 | `RecursionError` | today hidden by the script's depth cap of 50 |
| Extraction script | shadow root with a link and an input | 0 anchors, 0 inputs | shadow-built pages read as empty |
| Extraction script | link at depth 60 | dropped, no flag | silent truncation |
| Extraction script | `display:none` required input; input at `left:-9999px` | geometry `null`; geometry present at x=-9999 | the first is invisible to every later tool; the second is caught by the offscreen rule |
| Extraction script | 10,000 / 30,000 list rows | 6.0 s, 3.7 MB / 16.1 s, 11.1 MB (30,002 / 90,002 nodes) | the script call has no deadline and no byte cap |
| Verdict (`assess_page`) | 119 cloud specimens | median 28 ms, p95 224 ms, max 2.8 s | the verdict alone can cost seconds on a large page |

## 6. Worst case against typical

Typical cost is what the first pass stated. The worst case is the input an
adversary or an odd page would give. The budget is what the tool may spend on
the **reference worst-case machine** (assumed 8× slower than the measuring
machine, 06, section 11), stated as tails.

| Tool / algorithm | Typical | Adversarial input | Worst case without caps | With caps | Budget p95 / p99 / max (worst-case machine) |
| --- | --- | --- | --- | --- | --- |
| Observe (T-002) | O(n) script walk | 90k nodes, deep shadow, nested frames | unbounded time and memory | n ≤ 30k, 8 MB, depth 64, frames 3 | 2 s / 4 s / 10 s (deadline) |
| Doc build (T-004) | O(n) | 30k nodes | O(n) objects at about 360 B/node | columnar ≤ 100 B/node | 0.4 s / 0.8 s / 1.5 s |
| Verdict (T-006) | O(bytes) | 5.6 MB page | 2.8 s measured, about 22 s at 8× | byte cap 2 MB of visible text | 0.3 s / 0.6 s / 1 s |
| Records (ALG-002) | O(n·D·K) | wide parent with 10k children | O(n·D·K) still; MinHash prefilter | sibling cap 2,000 per parent | 0.2 s / 0.4 s / 0.8 s |
| Record root (ALG-003) | O(h·r) | deep chains | O(h·r) | `h ≤ 12` | negligible |
| XY-cut (ALG-005) | O(b log b) per level | each cut peels one box | O(b²) | depth 12, b ≤ 2,000 | 0.1 s / 0.2 s / 0.5 s |
| Pairing (ALG-008) | ladder resolves 80%+ | 300 unclaimed text nodes | O((|L|+|K|)³) | `m ≤ 120` per section | 0.15 s / 0.3 s / 0.6 s per section |
| Required fusion (ALG-010) | O(c) | 500 controls | O(c) | control cap 500 per form | negligible |
| Option list (ALG-015) | O(log L) queries | list never settles | unbounded waits | 12 settle waits × `W` | 4 s / 8 s / 12·W |
| Settle (ALG-016) | 2-3 polls | animated page | unbounded polls | `T_max` | equal to `T_max` |
| DocDiff (ALG-017) | O(n) | regenerated IDs everywhere | O(n) (over-reports) | n ≤ 30k | 0.2 s / 0.4 s / 0.8 s |
| Scroll growth | P rounds | infinite scroll (C14) | unbounded | `P_max = 10`, node cap | 10 rounds |

The p95/p99 numbers are **targets to be measured** in slice 0
([10](10_gap_analysis_and_build_plan.md)). The maximum is a **hard cap**: a
tool that reaches it returns `Timeout(partial)` or a truncated result with a
flag, never more work. Each cap is a parameter in `ParameterSet` (CT-DS-007);
caps that protect safety cannot be tuned upward automatically (CT-NFR-019).

## 7. Where each edge case lives in the ledger

Every catalogue entry maps to at least one ledger row. Rows added in pass 2 for
entries that had no row: CT-PH-150 to CT-PH-214, CT-FR-033, CT-FR-034,
CT-FR-109, CT-FR-110, CT-FR-116 to CT-FR-119, CT-FR-135 to CT-FR-137,
CT-NFR-025, CT-NFR-026, CT-INV-013, CT-INV-014. The category **Phenomena: edge
cases and adversity** is in [ledger part 2](02_ledger_part2.md). Coverage per row,
with the gaps and what was tried, is in the evidence set (`coverage.md`).

## 8. Edge cases added in pass 3

### 8.1 Toolbars and filter controls

| EC | Case | Rows | Tools | Evidence | Handling |
| --- | --- | --- | --- | --- | --- |
| EC-46 | Filter accepts a choice and the results do not change | PH-226 | T-027, ALG-027 | R: LR-2 (owner, Bing site:); O: L02 | `NO_EFFECT` after two queries benches the channel; the piece is applied through the next channel or reported as not applied |
| EC-47 | Filter resets on pagination or back navigation | PH-227 | T-027, ALG-027 | K | `RESET` revises earlier pages' outcome; the learned URL parameter, when there is one, is carried on every page instead |
| EC-48 | Facet counts that disagree with the results | PH-228, FR-109 | ALG-027 | O: counts on 6 sources | `count_mismatch` recorded; the completeness check uses the results, never the facet count |
| EC-49 | Filter reachable only after scrolling or behind a "Filters" drawer | PH-229 | T-027, T-016 | O: 5 sources | the binding records `apply_mode=drawer`; the drawer is opened through the interaction layer, then re-observed |
| EC-50 | Rich-text editor toolbar above an answer box | PH-224 | T-014 | O: F03 | the toolbar is never operated; plain text is typed into the editable region |
| EC-51 | Filter applied by default (IP location, "Recommended" sort) | PH-225 | T-027 | O: chips on first load | the default is read and recorded as `current` before any piece is applied; never assumed absent |
| EC-52 | Slider or two-thumb range with no text input | PH-221, PH-244 | T-014 | O: 3 sources | keyboard operation on the focused thumb only; no script value injection; `UNKNOWN` if the value cannot be read back |

### 8.2 Alternate views

| EC | Case | Rows | Tools | Evidence | Handling |
| --- | --- | --- | --- | --- | --- |
| EC-53 | Two views of one record disagree | PH-264, PH-162 | ALG-028 | O: L49, L50 | `compatible` with the fields that differ; the record keeps both values and the source of each |
| EC-54 | A view lags or vanishes (feed 410, sitemap 404, closed posting still listed) | PH-265 | ALG-028, T-006 | O: X01, USAJOBS sitemap, L34-L36 | the view is re-verified before use and dropped from the `ViewMap` on failure |
| EC-55 | Struck or inserted text (`del`, `ins`, `s`) inside a record | PH-251 | T-003, T-009 | K | struck text is excluded from field values and kept as evidence; to build with T-003 |
| EC-56 | A view needs sign-in or a key | PH-266 | T-006, T-028 | O: X02, L55, L56 | never chosen; an apply control behind sign-in is the existing sign-in-wall handling |
| EC-57 | Canonical link points at another host that redirects back | PH-256, PH-192 | T-028 | O: 8 sources declare a canonical on another host | followed once; a loop is recorded and the current view kept |

### 8.3 Cases slice S1 touched, now pinned

| EC | Pin |
| --- | --- |
| EC-02 (one record) | the link-named title needs two or more records (`anchor_titles`) |
| Identical cards | `test_identical_cards_are_separate_records`, `test_identical_cards_get_one_fate_each` |
| Empty list | `test_empty_list_returns_no_records`, `test_empty_list_records_a_pass_with_no_decisions` |
| Link without `href` | `test_link_without_href_is_never_a_resolved_link` |
| Title nested deeper than one element | `test_heading_title_nested_in_span_teeth`, `..._two_levels_..._teeth`, the Chrome pin |
| Text cap | `test_text_cap_truncates_and_flags` (Chrome), `test_python_subtree_text_is_capped_and_flagged` |
| Dead-end words inside a real title ("Help Desk") | `test_dead_end_words_inside_job_titles_are_not_dead_ends_teeth` |

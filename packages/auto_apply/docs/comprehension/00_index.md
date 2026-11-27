---
title: "Page Comprehension Toolkit: Index"
status: needs-review
last_verified: 2026-11-02
verified_against: "7701de8 + S1 reply files (pass 3)"
audience: contributors
---

# Page Comprehension Toolkit: Index

This suite is the blueprint and the master capability ledger for the one
capability every AA engine rests on: **understanding any webpage it meets,
quickly, accurately and cheaply, on any device and browser, including the odd,
broken and hostile pages that are the normal work of a tool on the open web.**
It is written before the code, so that the code can be built and judged
against it.

It is a design, not a report of what exists. Every claim carries a status
marker (the vocabulary of [STATUS.md](../STATUS.md)): `[LIVE]` on a real path
and exercised live, `[WIRED]` connected and unit-tested, `[PARTIAL]` works
under stated conditions, `[ORPHAN]` built with no consumer, `[PLANNED]` decided
and not built, `[GOAL]` intended with no committed design. Nothing in this suite
is `[LIVE]` unless it was already live at commit `1bf7935`.

## What the authoring sessions could and could not do

- **Pass 1** read the code path, the Bible, the Philosophy, the ADRs and the
  to-do registers, and re-ran the grouping and title defects locally. It had no
  web access.
- **Pass 2 (this version)** opened every link of the owner's list once, and
  collected **123 live specimens from 45 sources**: 56 result lists,
  32 postings, 16 application forms (structure only) and 19 challenge, block
  or wall pages. This was done from a **data centre**, with one headless
  Chromium, one tab, polite pacing and `robots.txt` honoured. It ran AA's own
  page verdict over every specimen, and AA's extraction script and domain
  services on adversarial synthetic pages, both offline. It read in full: the
  owner's design conversation, the Engineering Philosophy, the Bible, ADR-005,
  008, 012, 013, 016, 017, 020, 021 and 022, and the perception code listed in
  [10](10_gap_analysis_and_build_plan.md), section 2.
- **Neither pass** proved anything about AA's behaviour on the owner's machine.
  A data-centre client gets different answers (4 of 5 search engines refused
  it). Specimens are evidence for the design and future unit-test inputs, never
  proof. No ledger row is `[x]`, because `[x]` means *the built tool proven live
  by AA's own runs on three sources*.
- No source or test code is written here.

## Reading order

| # | Page | Read it for |
| --- | --- | --- |
| 01 | [Charter](01_charter.md) | thesis, scope, non-goals, success measures, the honest limits of proof, owner rulings (CT-Q) |
| 02 | [Ledger](02_ledger.md) · [part 2](02_ledger_part2.md) · [part 3](02_ledger_part3.md) · YAML [1](02_ledger.yaml) [2](02_ledger_part2.yaml) [3](02_ledger_part3.yaml) | the checklist: every phenomenon, edge case, requirement, principle, invariant, engine need |
| 03 | [Philosophy and Bible conformance](03_philosophy_and_bible_conformance.md) | principle by principle: how the design satisfies it, and the gaps |
| 04 | [Requirements](04_requirements.md) | CT-FR and CT-NFR, each with a verification and a status |
| 05 | [Architecture](05_architecture.md) | tools, contracts, data structures, access port, profiles, memory, tuning, the Workbench, caps |
| 06 | [Mathematics](06_mathematics.md) | every algorithm: statements, proofs, typical **and worst-case** complexity, failure modes, rejected alternatives |
| 07 | [Footprint and defences](07_footprint_and_defences.md) | detection footprint per method, the defences observed live, `robots.txt` |
| 08 | [Evidence and research](08_evidence_and_research.md) | the trace schema, recording levels, consent, replay, **the pass-2 evidence set** |
| 09 | [Verification](09_verification.md) | the live evaluation set, metrics, sample sizes, how specimens, unit pins and live runs divide the proof |
| 10 | [Gap analysis and build plan](10_gap_analysis_and_build_plan.md) | code against blueprint, defects, the **baseline of today's code on the specimens**, ordered build slices |
| 11 | [Risks and open questions](11_risks_and_open_questions.md) | what could still go wrong, and what nobody knows yet |
| 12 | [Edge cases and adversity](12_edge_cases_and_adversity.md) | the cross-cutting catalogue: each edge case, its rows, tools, evidence and handling; the unknown-unknown rule |

An engineer building from this suite starts at 10 (the first slice), consults 04
for what must hold, 06 for the algorithm, 12 for the inputs that must not break
it, 05 for where it lives, and 02 for the box it ticks.

## Conventions

- **IDs.** `CT-FR-nnn` functional requirement · `CT-NFR-nnn` non-functional ·
  `CT-PH-nnn` phenomenon · `CT-ALG-nnn` algorithm · `CT-DS-nnn` data structure ·
  `CT-T-nnn` tool · `CT-INV-nnn` invariant (001-099 the toolkit's own, 101-199
  the Bible's, 201-299 the Philosophy's) · `CT-Q-nnn` owner ruling · `EC-nn` an
  entry of the edge-case catalogue ([12](12_edge_cases_and_adversity.md)). An ID is never
  reused; a withdrawn item keeps its ID and is marked withdrawn. Pass-2 rows take
  new IDs (phenomena from CT-PH-150); no pass-1 ID changed.
- **Source tags.** **O** observed live in pass 2, citing specimen IDs (`L01`-`L62`
  the owner's link list, `P`/`F`/`C` found by navigation or independently, `N` the
  Notion re-probes) · **R** recorded in AA's own evidence · **K** recalled,
  unverified · **A** an offline analysis or probe of AA's code (no network).
- **Environment tag** on every observation: `cloud` (pass 2, a data centre) or
  `owner` (AA's runs on the owner's machine). Evidence from one environment never
  ticks a box for the other.
- **Decision order when qualities conflict** (lexicographic, the loss recorded at
  the decision site): worst-case user, then research-grade, then architectural
  longevity ("extensible at named points" counts), then readability, then
  performance, then scale ("generic" counts).
- **Capability vs commitment.** A *commitment* ships. A *capability* is something
  the architecture must not foreclose and must name a seam for. Each is tagged.
- **Depth.** Depth means derivation, not length. Each design choice states the
  options considered and why the rejected ones lost. Each tool states what it
  returns, raises and **how it could hang, with the cap that prevents it**, plus
  the counter-argument. Edge cases are part of the contract, not an appendix.
- **Three-sources rule.** A phenomenon row needs three independent sources (site
  families, not tenants of one vendor) before its tool can be `[x]`.

## How to add to the ledger

The ledger is open by design. An unrecognised phenomenon is **recorded, not
guessed at** (the unknown-unknown rule, [12](12_edge_cases_and_adversity.md) section 2).

1. Append one row to the YAML part that holds its category (one line per row;
   keys `id, cat, item, src, st, tool, ver, ev`). The root `02_ledger.yaml` lists
   the categories and the parts. Take the next free ID.
2. Unknown thing? Set `st: "[?]"`, `tool: none`, and put the evidence (trace ID,
   page-copy fingerprint, specimen ID, or a plain description) in `ev`. The human
   decides whether it becomes a tool, a parameter, or a non-goal.
3. Add `src` entries only for sources you verified, tagged O, R or K, with the
   environment for O. A phenomenon row needs three independent sources before it
   can leave `[?]`/`[ ]` for `[x]`.
4. Regenerate the Markdown page of that part from its YAML. The two must agree row
   for row and status for status; the Workbench reads only the YAML.
5. Comment, don't edit history: a disagreement with a row is a new row of kind
   `note` pointing at the original ID, never a silent edit.

Nothing in the ledger is ever deleted. A row whose subject is retired is marked
`withdrawn` with the reason, mirroring the repository rule that nothing is
deleted ([ADR-016](../adr/016_retirement_over_deletion.md)).

## Changes in pass 2

What changed from pass 1, and why. Each item cites its evidence.

1. **Live evidence replaces recall.** Every appendix link was opened once.
   Specimens were stratified by ledger row and chosen with a recorded seed
   (20261102). Wherever a specimen exists, `K` sources in the ledger became `O`
   sources with specimen IDs: 126 `K` entries before, see the ledger now. In
   06, every recalled example became an observed one, except error displays,
   which need a submit.
2. **Edge cases are first-class.** New page [12](12_edge_cases_and_adversity.md) holds 45
   catalogue entries: degenerate, hostile, environment, and defects of today's code
   found by probes. It also holds the per-tool handling, the unknown-unknown rule
   and the tail budgets. New ledger category *edge cases and adversity*. New
   section 12 of [06](06_mathematics.md), worst case for all 26 algorithms with
   Lemma 4 (termination under caps). New section 14 of [05](05_architecture.md),
   hard caps.
3. **Corrections from the live evidence** (cloud environment):
   - DuckDuckGo HTML, Brave and Mojeek block a data-centre client just as Google
     does. Bing answered, and ignored `site:jobs.jobvite.com` (confirms LR-2 from a
     second environment).
   - `job-boards.greenhouse.io/<company>` for large tenants redirects to the
     company's own site (Stripe, Databricks, Figma), so "Greenhouse board layout"
     is often not Greenhouse markup at all.
   - Three DirectEmployers hosts answer **HTTP 404 with full job lists**.
   - Ashby renders all rows of an 803-role board at once. No virtualised list was
     found on any reachable board, so R-20 stays a risk confined to signed-in
     surfaces.
   - Non-UTF-8 job pages were not found on 34 probed hosts in seven languages.
     Encoding risk now sits in block pages and saved copies, not in live postings.
4. **Corrections to pass 1 from reading in full.**
   - The owner's design conversation contains a pure-Python Hungarian solver that
     **never terminates** on any non-square matrix padded with infinity. Today's
     code pads with `1e9`, which avoids this; reproduced offline.
   - The conversation's `DOMNode` could not be hashed. Today's tuple form can,
     but `label_input_pairing.build_parent_map` still keys by value and
     collapses identical cards.
   - Label pairing in today's `dom_segmentation.py` runs Hungarian over every
     visible text node in the form container. That is cubic, with no cap.
   - The honeypot rule skips real fields in RTL layouts and real fields named
     `address2` or `attestation`.
   - The extraction script misses shadow content, truncates at depth 50
     silently, and has no deadline or size cap.
5. **Baseline of today's code** ([10](10_gap_analysis_and_build_plan.md), section 5). Today's page
   verdict, replayed over 119 specimens, recognises 6 of 16 challenge and block pages
   and none of the 4 closed or missing postings. It calls three list pages application forms, and
   gates all three Ashby application forms as CAPTCHA blocks.
   AA's live perception path, run from the cloud on ten pages, found 124 of 136
   list rows as cards, but none with both a title and a link. It reported every
   control of three real forms as required (a one-line defect, 23).
6. **Status changes, on evidence only.** CT-NFR-010 (no hangs) `[~]` → `[ ]`;
   CT-PH-051 (required attribute) and CT-FR-012 (requiredness) `[~]` → `[ ]`;
   CT-PH-061 (account required to apply) `[?]` → `[ ]`; CT-PH-063 (email
   verification) `[?]` → `[ ]`. Each row's `ev` says why. No row became `[x]`.
7. **Thin categories expanded from specimens.** Result lists 9 → 21 rows, job
   descriptions 5 → 17, accounts and authentication 5 → 12, Vetting needs 5 → 12.
8. **The ledger is split into three files** (root plus two parts, YAML and
   Markdown each). The single file had grown past what one reviewable change can
   carry. One ID space, one schema, the root lists the parts.
9. **New owner rulings** CT-Q-026 to CT-Q-034, including every host whose
   `robots.txt` disallowed a path that was opened ([01](01_charter.md)).

## Changes in pass 3

1. **Slice S1 built** (reply files outside this suite, applied to AA): full-subtree
   text and accessible names in the extraction script (defect 4), the per-page
   record of every card's fate (trace L0/L1, LR-6), the record-root rule and
   link-tier titles (stopgaps S2 replaces), one route per destination, a
   title-relation link term, chrome landmarks excluded from records, and
   listings-only discovery (no label pairing on results pages). Live (cloud):
   417 of 417 records on six boards; 2,201 of 2,959 on the 55 list specimens
   (137 at the branch head). See [10](10_gap_analysis_and_build_plan.md) s1 and
   [09](09_verification.md) s9.
2. **A completeness audit that stays in force.** Seven frozen reference lists
   (APG patterns, WAI-ARIA 1.2 roles, HTML input types and form elements,
   engine steps, recognition signatures, alternate views) are mapped to the
   ledger in [02_ledger_coverage.yaml](02_ledger_coverage.yaml). Before: 120 of
   228 items mapped, 24 not applicable, **84 gaps** (toolbars among them, as
   the owner found). After: 204 mapped, 24 not applicable, 0 gaps. The check
   that keeps it so is specified in [09](09_verification.md) s8.
3. **Ledger part 4** ([02_ledger_part4.md](02_ledger_part4.md)): 52 phenomenon
   rows in three new categories (toolbars and filter controls; interaction
   patterns and HTML controls; alternate views) plus CT-FR-035 to CT-FR-037
   and CT-NFR-027. 29 of the 52 have three or more observed sources (pattern
   scan of 129 pages and pass-3 live views); the rest name their gap.
4. **Toolbars and filter controls** ([05](05_architecture.md) s15,
   [06](06_mathematics.md) s13, [07](07_footprint_and_defences.md) s10,
   [12](12_edge_cases_and_adversity.md) s8.1): recognise, map to a search piece,
   operate through the existing interaction layer, verify the effect
   (ADR-021), learn the URL parameter.
5. **Alternate views** ([05](05_architecture.md) s16, [06](06_mathematics.md)
   s14-15, [12](12_edge_cases_and_adversity.md) s8.2): recognition, the
   `ViewMap`, equivalence, selection by cost and footprint; learned mappings
   live in a verified view catalog beside domain memory, behind the Source
   Channel seam.
6. **The contract between understanding and acting** ([05](05_architecture.md)
   s17) and the interaction layer file by file ([10](10_gap_analysis_and_build_plan.md)
   s2): the toolkit says what, the existing layer decides how; reuse by
   default, with every overlap ruled. Each ledger row that operates something
   names the existing tool (`acts:`).
7. **Statuses from evidence.** CT-PH-051 `[~]` (defect 23 fixed in `7701de8`);
   CT-PH-006, 012, 013, 014, 153, CT-FR-108 and CT-PH-005 `[~]`; no row is `[x]`.
   Owner ruling CT-Q-030 recorded; new questions CT-Q-035 to CT-Q-038.
8. **Production readiness** ([13](13_production_readiness.md)): the review of
   this suite as the team that builds, ships and maintains it, with what was
   changed and what still stands between the blueprint and a production build.

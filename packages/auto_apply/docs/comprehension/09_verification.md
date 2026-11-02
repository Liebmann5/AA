---
title: "Page Comprehension Toolkit: Verification"
status: needs-review
last_verified: 2026-11-02
verified_against: "1bf7935"
audience: contributors
---

# Verification

*Unit tests guard code; live runs prove behaviour.* The owner's rule is adopted
and sharpened: a ledger row can be `[x]` only through a **recorded live run on three
independent sources**; a unit pin can take a row to `[~]` at most. Everything below is
`[PLANNED]`. **The URLs are candidates.** Pass 1 had no web access. Pass 2 fetched the
owner's list and 58 further pages once each from a data centre (specimens, s2); freezing the
set (slice 0) re-resolves, labels and hashes each entry from the owner's environment.

## 1. How the proof divides

| Layer | Proves | Cannot prove | Where |
| --- | --- | --- | --- |
| Property tests (P) | lemmas of 06: tolerance bound, collapse monotonicity, assignment optimality, `diff(a,a)=∅`, determinism | behaviour on real pages | `tests/` |
| Fixture pins (U) | a captured page (cleaned) yields the expected findings; each past live failure becomes a fixture | generalisation | `tests/` |
| Replay (R) | byte-identical results from a stored observation; counterfactual tuning | what the web does today | traces, 08 |
| Live runs (L) | behaviour on the open web, error rates with intervals | code-level properties | the live set |
| Measurement (M) | time and memory per pass per profile, on named machines | accuracy | `aa_measure.py` pattern |
| Specimens (O) | what a page looked like to one client in one environment on one date; inputs for fixture pins and offline replay of today's code | AA's behaviour; anything about another environment | the pass-2 evidence set, 08 s8 |

Every live failure produces three artefacts: a sans-IO fixture, a ledger note (or an
`UNKNOWN` row), and, if the cause is a defect, a pin that fails before the fix.

## 2. The live evaluation set: `LIVE-SET` versioned, three sets

- **ANCHOR** (regression): fixed, named entries, re-run every release; shows drift.
- **DRAW** (generalisation): a **seeded random sample** from a declared sampling frame;
  the only set that supports a claim about never-seen pages (hand-picked URLs bias the
  estimate upward). Frame: platform hosts from `resources/ats/*.yaml` (35 descriptors at
  `1bf7935`) and tenants found through AA's own measured `site:` plans (ADR-020), plus a
  fixed list of 30 (title, location) queries per engine. Seed and draw are recorded.
- **CONTROL** (project-owned): a local tripwire page (07), mock ATS forms
  (`tests/benchmarks/ats_forms/`, the Bible 25.5 five), and one project-owned Google Form.
  Interaction is allowed here only.

*Rule.* On third-party pages the evaluation is **observe-only**: no submit, ever. Pacing
via `HostPacer`; no bulk crawling; vendor terms reviewed first (CT-Q-012). The public
dataset publishes URL, date, observation hash and copy **fingerprint**; copies stay local
(CT-Q-018).

Each entry stores: id, URL or template, retrieval date, observation hash, L2 copy
fingerprint, access adapter and browser, gold labels (two labellers on a 20% sample using
the existing blind labelling tool), and the ledger rows it exercises.

### Pass-2 specimens as seeds (environment `cloud`, 2026-11-02)

Pass 2 replaced the templates below with real pages wherever a page was
reachable. The specimen IDs are in the evidence set (08 s8) and per ledger row
in its `coverage.md`. Under CT-Q-027 they may be frozen as ANCHOR fixtures that
guard code, tagged `cloud`. The DRAW set must still be drawn fresh, and from the
owner's environment for any claim about AA.

| Family | Specimens (sources) | Notes |
| --- | --- | --- |
| Result lists | L06-L39 (Jobvite, Workday, iCIMS, Ashby, SmartRecruiters, Oracle, Taleo, Eightfold, NEOGOV, DirectEmployers, HN, Arbeitsagentur, StepStone, Tencent), C01-C21 | search engines refused the cloud client except Bing (L02); LinkedIn guest list L43 is out of the set (CT-Q-030) |
| Careers pages | L15-L17 and L22 (company sites reached from vendor URLs), L60, L61 (Notion) | vendor URLs redirect to company sites |
| Postings | P01-P26 (seed 20261102), L46-L52 closed or missing, L53/L55 LinkedIn guest (out of set) | JSON-LD present on some tenants only |
| Forms (structure only) | F01-F14, P08, F09, L57 | Greenhouse, Ashby, Jobvite consent step, Workday/iCIMS/Taleo/Eightfold walls, Oracle email-first |
| Gates | L01, L03-L05, L24-L26, L40, L42, L44, L54, L56, C02, C08, C10, C17, F08, F13 | the block kinds today's verdict misses |

### Candidate ANCHOR entries (templates; tenants chosen at freeze)

| Family | ID | Source (URL form) | Rows exercised |
| --- | --- | --- | --- |
| Result list | LS-RL-01 | Google web search: `https://www.google.com/search?q={q}` | CT-PH-001, 002 |
| Result list | LS-RL-02 | Bing: `https://www.bing.com/search?q={q}` | CT-PH-003 |
| Result list | LS-RL-03 | DuckDuckGo HTML: `https://html.duckduckgo.com/html/?q={q}` | CT-PH-004 |
| Result list | LS-RL-04 | Google jobs vertical: web search with `udm=8` (Bible CB-1) | CT-PH-005 |
| Result list | LS-RL-05 | LinkedIn public jobs: `https://www.linkedin.com/jobs/search/?keywords={q}&location={l}` | CT-PH-006, 007 |
| Result list | LS-RL-06 | Indeed: `https://www.indeed.com/jobs?q={q}&l={l}` | CT-PH-008 |
| Careers page | LS-CP-01 | Lever: `https://jobs.lever.co/{tenant}` | CT-PH-010 |
| Careers page | LS-CP-02 | Greenhouse: `https://boards.greenhouse.io/{tenant}` | CT-PH-011 |
| Careers page | LS-CP-03 | Jobvite: `https://jobs.jobvite.com/{tenant}` | CT-PH-012 |
| Careers page | LS-CP-04 | Ashby: `https://jobs.ashbyhq.com/{tenant}`; SmartRecruiters; Workable | CT-PH-013 |
| Careers page | LS-CP-05 | Workday: `https://{tenant}.wd{n}.myworkdayjobs.com/{site}` | CT-PH-014 |
| Job description | LS-JD-01..04 | one posting each from Lever, Greenhouse, Workday, a company site with JSON-LD | CT-PH-020..024 |
| Form | LS-FM-01..05 | Greenhouse and Lever apply pages (observe-only), Workday multi-step with account, SmartRecruiters, project Google Form | CT-PH-030..046 |
| Auth / pop-up | LS-AU-01..03 | LinkedIn authwall; an ATS "Sign in with Google" pop-up; Workday sign-up | CT-PH-060..064 |
| Feed | LS-FD-01 | LinkedIn feed with the owner's own session, consent-gated (CT-Q-006) | CT-PH-009 |
| Defence demos | LS-DF-01..04 | vendor-published CAPTCHA demo pages (Google reCAPTCHA, hCaptcha, Cloudflare Turnstile); Google "unusual traffic" page when it occurs naturally (not provoked) | CT-PH-070..074 |

Every family has at least three independent sources; the DRAW set widens each.
A family that cannot reach three verified sources stays below `[x]`.

**Pass-2 coverage.** Of 209 page-exercisable ledger rows, 80 have specimens from
three or more independent sources, all in the `cloud` environment. The other 129
are listed as gaps with what was tried. Most need a submit, a sign-in, a
signed-in surface or another operating system: none of these is available
read-only from a data centre.

## 3. Metrics

| Metric | Definition |
| --- | --- |
| Record recall / precision | a returned record matches a gold record when canonical destination URL equal, else normalised (title, company) equal |
| Field accuracy | exact match after key normalisation, per field |
| Pairing precision/recall | label-control pairs vs gold; `UNLABELED` counted separately |
| Required confusion matrix | REQUIRED/OPTIONAL/UNKNOWN vs gold; **false-OPTIONAL is reported on its own** |
| Abstention rate | share of pages/fields with `Abstain` or `UNKNOWN` |
| Wrong-and-confident | wrong with confidence ≥ 0.9 (the dangerous cell) |
| Calibration | expected calibration error (10 bins) and Brier score |
| Time and memory | per pass per profile; P50/P95; tracemalloc peak; on named machines |
| Footprint | page-realm scripts per page, by class (07) |
| Determinism | replay hash equality, 100% required |
| Ledger coverage | rows exercised, rows `[x]`, rows with no live evidence |
| Drift | ANCHOR error rate over time |

## 4. Intervals and sample sizes

Proportions use **exact (Clopper-Pearson)** intervals; planning uses Wilson. Page-level
aggregates use a **cluster bootstrap by site** (pages of a site are correlated; the
design effect is `1 + (m-1)ρ` for `m` pages per site and intra-site correlation `ρ`).
Reported per family **and** per source.

| Claim | Clean trials needed (95% one-sided) | Note |
| --- | --- | --- |
| error ≤ 5% | 59 sites with zero failures | `ln 0.05 / ln 0.95 = 58.4` |
| error ≤ 1% | 299 sites with zero failures | `ln 0.05 / ln 0.99 = 298.1` |
| recall ≥ 0.90, observed 0.96 | about 100 sites (96/100 → Wilson lower 0.902) | per family |
| recall ≥ 0.94, observed 0.97 | about 300 sites (290/300 → Wilson lower 0.940) | per family |
| estimate a rate near 0.9 within ±0.05 | 139 sites | `1.96²·p(1-p)/e²` |
| estimate a rate near 0.95 within ±0.03 | 203 sites | |

Consequence stated plainly: with 3 sources per cell and a handful of pages per source,
**per-source rates are wide**; the claim "handles never-seen pages at target" needs the
DRAW set at the sizes above per family, which is a project commitment (CT-Q-001), not a
free outcome. Tool comparisons (paired, same pages) use the exact sign test of
CT-ALG-019, whose power needs about 15-20 discordant sites.

## 5. Procedure

1. **Freeze (slice 0).** Resolve candidates, draw DRAW with a recorded seed, capture
   observations (L2), label, hash. Tag `LIVE-SET v1.0`. Any later change is `v1.1`; old
   results keep their set version.
2. **Run.** The Workbench (or a script) runs the toolkit on each entry; the trace is the
   result. Replays check determinism.
3. **Score** per metric above, per family and source, intervals included.
4. **Update the ledger** (`st`, `ev` with trace id and set version). A row becomes `[x]`
   only with three verified sources in one recorded run.
5. **Failures:** open the trace in the Workbench; its failure class (CT-ALG-026) routes
   the work: workflow bug, workflow change, missing tool, tool defect, blocked access,
   unknown phenomenon.
6. **Drift check** each release on ANCHOR; a regression beyond the non-inferiority bound
   blocks the release.

## 6. The Workbench in verification

Review: open any trace, see which tools ran, their findings and the failure class.
Explore: select tools or a workflow and run them live on the page the left pane shows,
through the read-only guard (CT-T-024), to reproduce a failure or probe a new page. It
writes `UNKNOWN` ledger rows (with the evidence) on request, never silently.

## 7. Measuring today's code on the specimens (pass 2)

Pass 2 measured AA's current code without changing any status to `[x]`:

1. **Offline replay of the page verdict** (`assess_page`, a pure function of
   URL, title and rendered HTML) over all saved specimens. Results per family are
   in [10](10_gap_analysis_and_build_plan.md) s5. This needs no browser and repeats
   byte for byte.
2. **Adversarial synthetic pages**: AA's extraction script runs in Chromium on
   local pages built to hit one edge case each (shadow root, depth 60, hidden
   required input, nested frames, 10,000 and 30,000 rows). AA's domain services run on
   synthetic trees (pairing growth, honeypot layouts, identical cards, deep
   chains). Results are in [12](12_edge_cases_and_adversity.md) s5.
3. **Live perception runs** (the extraction script plus `MathFormUnderstandingService`
   on live pages). Pass 2 ran them from the cloud on ten pages, three or more sources per
   family ([10](10_gap_analysis_and_build_plan.md) s5, "Live perception path"). That is a
   baseline for the gap analysis only; the proving runs are slice 0 work from the owner's machine.

Each measurement names its machine (pass 2: 4-core Intel Xeon at 2.8 GHz,
Python 3.14.6, Chromium 153 headless). Worst-case budgets are stated on the
reference machine by the 8× assumption until slice 0 measures the owner's
worst-case laptop.

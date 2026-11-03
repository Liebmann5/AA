---
title: "Page Comprehension Toolkit: Charter"
status: needs-review
last_verified: 2026-11-02
verified_against: "7701de8 + S1 reply files (pass 3)"
audience: contributors
---

# Charter

## Thesis

AA needs one capability, **page comprehension**, and today it has one grouping
heuristic wearing the name of a subsystem. The thesis of this blueprint:

> Comprehension is best built as a **small set of pure, replaceable tools that
> read one immutable observation of a page and return findings with evidence and
> confidence**, never a decision. Access is a port with declared capabilities.
> Every tool states its complexity and its failure modes, runs inside a budget,
> and may abstain. The three engines consume findings; they do not re-derive
> them. When the built tool fails, the reason is **an unchecked ledger box or an
> error rate the ledger already states**, never a surprise.

Why this and not a bigger heuristic: the measured failure (Bible LR-1) is not a
missing algorithm. It is that the pipeline *collapses a rich page into one
exact-hash group, throws the evidence away, and cannot say what it did not
understand* (defects 1-10 in [10](10_gap_analysis_and_build_plan.md)). A tool
that returns ranked candidates with evidence, and abstains when unsure, turns a
silent zero into a recorded, diagnosable `UNKNOWN`.

## Scope

In scope: *access, obtain, break down* for the three page families (result
lists, job descriptions, online forms), plus the surfaces they sit behind
(logins, consent walls, pop-up windows, challenge pages, confirmation pages).
Also in scope: the evidence trace, replay, the ledger, tuning, domain memory,
resource profiles and the Workbench, because the tool is not trustworthy
without them.

## Non-goals

| Non-goal | Why |
| --- | --- |
| Deciding *whether to apply* (fit, vetting policy) | Bible 8.1-8.3: engines decide; the toolkit reports |
| Submitting anything | The fail-closed gate stays in Applications (ADR-012). The toolkit only *advises* (CT-T-026) |
| Evading or defeating defences | Recorded honestly as research data, handled by ADR-012/020 policies and Bible 16 |
| Any required model, key or paid service | Bible 1.1; Philosophy "Worst-Case-User-First" |
| Being a general crawler | Interactive browsing only; pacing stays in `HostPacer` (ADR-020) |
| Replacing the browser cascade | Access consumes it ([ADR-013](../adr/013_static_path_retirement.md): a browser is required) |
| Understanding page *meaning* (fit, truthfulness of a posting) | Out of reach of structure; belongs to vetting |

## Success measures

Proposed targets, **to be ruled by the owner (CT-Q-001)**. They are stated so the
ledger can be checked against numbers rather than adjectives. All are measured
on the *random-draw* set of [09](09_verification.md), per family and per source,
with exact confidence intervals.

| Measure | Proposed target | Status |
| --- | --- | --- |
| Result lists: record recall (lower 95% bound) | ≥ 0.90 | `[GOAL]` |
| Result lists: record precision | ≥ 0.95 | `[GOAL]` |
| Title+link correct, given the record is found | ≥ 0.95 | `[GOAL]` |
| Forms: field coverage / label-pairing precision | ≥ 0.95 / ≥ 0.98 | `[GOAL]` |
| Required marking: recall of truly required fields | ≥ 0.95, and never silently "optional" when `required` is declared | `[GOAL]` |
| Wrong **and** confident (confidence ≥ 0.9) | ≤ 1% of decisions | `[GOAL]` |
| Abstention rate (reported, never hidden) | ≤ 10% of pages, each with evidence | `[GOAL]` |
| P95 analysis CPU, ≤ 12,000 nodes, reference slow machine | ≤ 1.0 s | `[GOAL]` |
| Maximum per tool on adversarial input, worst-case machine | the hard cap in [12](12_edge_cases_and_adversity.md) s6; reaching it returns a typed partial result | `[GOAL]` |
| Edge-case catalogue entries pinned per tool | 100% of the entries named for that tool | `[GOAL]` |
| Replay: same observation + parameters + seed → same bytes | 100% | `[GOAL]` |
| Page-world scripts in the default profile when an isolated or protocol read exists | 0 | `[GOAL]` |

"Handled" must be defined (CT-Q-001): *proposed* definition: the page's records
or fields are returned correct, **or** the tool abstains with a named reason and
the engine takes its safe path. A confident wrong answer is never "handled".

## The honest limits of proof

"The tool never fails on any webpage" **cannot be proven, and the blueprint does
not claim it.** The reasons are structural, not a lack of effort:

1. **No ground truth for "any page".** Correctness is a human judgement about a
   rendering ("is this block a job card?"). The set of pages is open-ended and
   includes pages written to defeat readers.
2. **Pages are programs.** What a page does after script runs is a semantic
   property of an arbitrary program; by Rice's theorem it is undecidable in
   general. No static reading of a snapshot can certify behaviour.
3. **Non-stationarity.** Sites redeploy weekly (Bible LR notes rotating class
   names); a guarantee at time *t* expires. Wrapper induction has long been known
   to be limited in expressiveness and brittle under change (Kushmerick 2000,
   *Wrapper induction: efficiency and expressiveness*, Artificial Intelligence
   118).
4. **Finite samples bound only the sampled distribution.** Zero failures in *n*
   independent trials supports only "error rate ≤ about 3/n at 95%" (the rule of
   three; exact: n ≥ ln 0.05 / ln(1-p)). 59 clean trials certify p ≤ 5%; 299
   certify p ≤ 1%. Pages from one site are not independent; the unit of
   inference is the **site or template**, not the page.
5. **Adversaries adapt.** A bot-detection or obfuscation vendor can change its
   output after any published method.
6. **The observer changes the page.** Pass 2 saw the web from a data centre:
   4 of 5 search engines refused it, Notion withheld controls the owner sees, and
   signed-out views differ from signed-in ones. Evidence is always about one
   environment (`cloud` or `owner`) and never transfers silently to the other.

**What the blueprint guarantees instead:**

| Guarantee | Kind | Where |
| --- | --- | --- |
| G1. Every phenomenon in the ledger maps to a tool, or to an explicit `[ ]`/`[?]`; an unhandled case is an unchecked box | structural | [02](02_ledger.md) |
| G2. Each algorithm terminates within a stated bound and preserves stated invariants (no tool can hang). **Not true of today's code** (pass 2 measured cubic label pairing and an uncapped extraction script); it becomes true with the caps of G8 | formal | [06](06_mathematics.md) s12 |
| G3. Same observation, parameters and seed give the same result | formal + replay test | CT-INV-001 |
| G4. Error rates per family and source, with confidence intervals and sample sizes, on a frozen versioned set | empirical | [09](09_verification.md) |
| G5. Where the tool is unsure it abstains with evidence; irreversible actions require stated confidence and the gate | design | CT-INV-004 |
| G6. Any failure is attributable (workflow bug / workflow change / missing tool / tool defect / blocked access / unknown phenomenon) | diagnostic | CT-ALG-026 |
| G7. A state no row describes fails closed, becomes a `[?]` row candidate with evidence, goes to the human, and does not stop other safe work (the unknown-unknown rule) | design + property test | [12](12_edge_cases_and_adversity.md) s2, CT-INV-013 |
| G8. Every tool has a hard cap on time, memory and steps, and states its behaviour on the edge-case catalogue; G2 rests on these caps | formal + measurement | [06](06_mathematics.md) s12, [12](12_edge_cases_and_adversity.md) |

## Counter-arguments

| Objection | Answer | Residual risk |
| --- | --- | --- |
| "Use a vision or language model; it generalises." | Violates Bible 1.1 as a requirement and loses determinism. Kept as an **optional capability** behind the same finding contract (CT-T-001 seam) | A model may out-score the math on odd layouts; the Workbench will show where |
| "Per-site adapters are more reliable." | True per site, false for never-seen sites. They survive as the *last* tier (domain memory, ATS YAML), verified on every use | Memory staleness: bounded and verified (CT-ALG-020) |
| "Pure Python is too slow." | Measured locally: 12,000 nodes build + group in about 0.11 s on a 4-core desktop; the 0.25-0.56 s the owner measured is most likely acquisition cost (script walk, layout, JSON transfer). Hypothesis, to be measured (slice 0) | The worst-case laptop is unmeasured |
| "Many small tools add overhead and complexity." | Cost is quantified in [05](05_architecture.md): under 1% of a pass by derivation | Trace volume; bounded by level |
| "The ledger will rot, like the to-do register." | A sync pin (YAML ↔ Markdown ↔ tests) and a coverage check, the same pattern as the docs gate ([ADR-017](../adr/017_documentation_gate.md)) | Rows can still be wrong; `[x]` requires a recorded live run |
| "A separate library is premature." | The boundary is what enforces purity. First step is an import-boundary pin; separate distribution is a capability | Divergence if never packaged |

## Falsifier

The thesis is false if, after build slices 1-5, any of these holds on the frozen
random-draw set: (a) record-recall lower bound below target in a family; (b)
wrong-and-confident rate above 1%; (c) a failure maps to a row already ticked
`[x]` (the ledger over-claimed) more than once per release; (d) any tool exceeds
its declared time bound on the reference machine. Each is checkable by a script
over traces; none requires judgement.

## Owner rulings (CT-Q)

Each blocks or shapes the item named. Defaults are recommendations, not
decisions.

| ID | Question | Recommendation | Shapes |
| --- | --- | --- | --- |
| CT-Q-001 | What fraction of never-seen pages must be handled, and what does "handled" mean? | The table above; handled = correct or safe abstention | 09, all targets |
| CT-Q-002 | Library name, location (in-tree package vs separate repo) and licence | In-tree `packages/` sibling first; separate repo once the API settles; same licence as AA | 05 packaging |
| CT-Q-003 | Python floor and which optional accelerators are acceptable | Floor 3.10 (docs gate); numpy only as a declared, result-equivalent accelerator | NFR-002 |
| CT-Q-004 | Default footprint posture | Lowest-footprint read that satisfies the capability (07) | 07 |
| CT-Q-005 | May the default profile run scripts in the page's own world? | No when an isolated-world or protocol read exists; yes only as a labelled fallback | 07, CT-T-001 |
| CT-Q-006 | LinkedIn job list and feed, logged in: terms-of-service and ethics | Owner decision per surface; read-only, user's own session, human pacing, no bulk | CT-PH feed rows |
| CT-Q-007 | Google SERP automation: terms of service and robots rules | Owner decision; current behaviour is ADR-020 | Discovery |
| CT-Q-008 | Indeed, ZipRecruiter, Glassdoor automation terms | Owner decision per surface | Discovery |
| CT-Q-009 | Reading ATS pages that require an account | Owner decision; account creation is CT-Q-014 | Applications |
| CT-Q-010 | Google Forms and other third-party forms as live test targets | Project-owned forms only for interaction; observe-only elsewhere | 09 |
| CT-Q-011 | Public posting feeds and vendor job APIs (ADR-020 "accepted, not built") | A sibling Source Channel, not part of this toolkit (05) | 05 |
| CT-Q-012 | Terms of service for each ATS vendor's candidate pages | One owner review per vendor before they enter the live set | 09 |
| CT-Q-013 | "Sign in with …" pop-up windows | Recognise and hand off; AA never types third-party credentials | CT-ALG-025 |
| CT-Q-014 | Creating ATS accounts for the user (email verification, stored credentials) | Defer until the secure document store exists (N-2) | Applications |
| CT-Q-015 | Pressing a non-final "Next" to discover required fields | Allowed only when CT-ALG-011 says "blocked by native validation" or the step is classified non-final and the human policy allows | CT-FR-012/013 |
| CT-Q-016 | Anything that costs money (paid scraping or solving services, residential proxies) | Excluded; listed so it is a decision, not a drift | 05 channels |
| CT-Q-017 | Recording level defaults and what consent each level needs | L0 and L1 always; L2 behind page-copy consent; L3 research only | 08 |
| CT-Q-018 | Hosting the live corpus publicly (third-party page content, copyright) | Hash and fingerprint publicly; copies local only | 09 |
| CT-Q-019 | Who labels the ground truth | Owner plus the existing labelling tool; two labellers on a 20% sample | 09 |
| CT-Q-020 | Tuning scope and default | Project-level tuning on the public corpus; per-user tuning propose-only | CT-ALG-019 |
| CT-Q-021 | The word "channel" is used by ADR-021 for ways to apply a search piece | Call the sibling abstraction **Source Channel** | 05 |
| CT-Q-022 | Workbench home: new app, GUI tab, or CLI | A tab in the GUI plus a CLI trace viewer | CT-T-024 |
| CT-Q-023 | Default on `UNKNOWN` page in unattended mode | Skip and record; stop and ask only at a configured checkpoint | CT-INV-004 |
| CT-Q-024 | Kernel timing | Design now to the seam in 05; no waiting on the refactor | 05 |
| CT-Q-025 | In-place query as a default for low-memory profiles | Only after slice 0 measures it on the worst-case laptop | CT-NFR-005 |
| CT-Q-026 | `robots.txt` disallows paths pass 2 opened once: governmentjobs.com (`Disallow: /` for all agents), linkedin.com (`Disallow: /`), dice.com (`/jobs?q*`), google.com, bing.com, search.brave.com and mojeek.com (`/search`). Pass 2 skipped hh.ru (`*?*`) and akhtaboot.com (`/`). ADR-020 decision 5 does not consult `robots.txt` on the interactive path | Interactive, user-driven browsing stays as ADR-020 rules. Disallowed paths never enter the evaluation set or any bulk or unattended collection. Each listed host gets its own ruling ([07](07_footprint_and_defences.md) s7) | 07, 09, Discovery |
| CT-Q-027 | May specimens captured from a data centre (`cloud`) be frozen as ANCHOR fixtures? | Yes, as unit-test inputs that guard code, tagged with their environment; never as proof of AA's behaviour | 09 |
| CT-Q-028 | A host that rate-limits the first request (Workable 429, Cloudflare 1015) | Bench the host for the session at once, the same as a challenge (ADR-020 decision 6); never retry in-session | T-006, Discovery |
| CT-Q-029 | Notion-hosted careers pages render controls only to some clients (Start Test and Apply were absent signed out) | Treat Notion as a page family. Read in the user's own browser profile only if the owner allows; otherwise report "control not visible" and hand off | CT-PH-180, CT-PH-205 |
| CT-Q-030 | LinkedIn guest pages loaded although `robots.txt` disallows all; the Easy Apply modal needs a signed-in session | **Ruled by the owner (pass 3):** guest views are a supported view in their own right, handled by the alternate-views family ([05](05_architecture.md) s16). An apply control that needs sign-in leads to a sign-in prompt, which is the existing sign-in-wall handling, not a new edge case | CT-PH-048, CT-PH-256, CT-PH-266 |
| CT-Q-031 | Third-party forms that require the provider's account (a Google Form behind Google sign-in) | Hand off; AA never signs in to a third party on the user's behalf | CT-PH-176 |
| CT-Q-032 | Assessments before an application ("Start Test") and other non-standard actions | Never start an assessment; recognise it and hand off with the posting saved | CT-PH-172 |
| CT-Q-033 | Pressing a control whose only effect is to reveal a state (the Rackhouse "Apply" that shows "applications paused") | Allowed only when the control has no form, no navigation target and no submit semantics, under the CT-Q-015 policy, and re-observed after | CT-PH-173 |
| CT-Q-034 | Identity-first steps (Oracle's email screen with hCaptcha; iCIMS and Taleo logins) | A checkpoint, never an auto-fill: entering the user's email creates an account record on a third party (CT-Q-014) | CT-PH-175, FR-127 |
| CT-Q-035 | Lever's `robots.txt` allows `*` but adds stricter rules for some named automated agents and asks that content not be used for model training; no Lever page was captured | Whether AA's `robots.txt` handling (CT-Q-026) follows only the `*` group, which is the one that applies to AA's browser, or also the strictest named group. Options: (a) the `*` group only (recommended: AA does not identify as any named agent); (b) also the strictest named group; (c) ignore | CT-PH-010 |
| CT-Q-036 | Operating filter controls on a results page is one more page state per piece | Operate once per piece and query, verify, then use the learned URL parameter (07 s10). Options: (a) as recommended; (b) URL parameters only, never controls; (c) controls whenever no parameter is known, without learning | CT-FR-035, CT-NFR-027 |
| CT-Q-037 | Vendor posting APIs and feeds are public but some hosts refuse them (401 on robots, `Disallow: /`) and their terms differ | Read only hosts whose `robots.txt` allows the path; never send a key; record the vendor's terms URL in the catalog. Options: (a) as recommended; (b) pages only; (c) APIs only where the vendor documents public use | CT-PH-263, CT-PH-261 |
| CT-Q-038 | `url_ref` in the page record is an unkeyed hash of the URL | Local only, never exported; research uses keyed identities. Options: (a) as recommended; (b) key it with the research key now | CT-FR-108 |

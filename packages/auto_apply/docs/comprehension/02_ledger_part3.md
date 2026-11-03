---
title: "Page Comprehension Toolkit: Ledger Part 3"
status: needs-review
last_verified: 2026-11-02
verified_against: "7701de8 + S1 reply files (pass 3)"
audience: contributors
---

# Master capability ledger, part 3 of 3

Part 3 of 3: engine needs, requirements, research criteria, invariants. Rendering of [02_ledger_part3.yaml](02_ledger_part3.yaml); the summary and the other parts are in [02_ledger.md](02_ledger.md).

**Status legend.** `[x]` proven live on three independent sources by AA's own runs · `[~]` partial: code and/or fixture evidence, no three-source live proof · `[ ]` not capable · `[?]` unknown: evidence recorded, a human decides. **No row is `[x]`**: no built tool has been proven by AA's own live runs on three sources. Pass 2 observed pages live from a data centre (`cloud`); those observations are evidence for the design, never proof of AA's behaviour.

**Source tags.** **O** observed live in pass 2, environment `cloud`, with specimen IDs (pass-2 observations; the archive was not retained, and each row records what was observed; [08](08_evidence_and_research.md) s9) · **R** recorded in AA's own evidence (environment `owner` unless stated) · **K** recalled, unverified. Tool column: `T-nnn` is `CT-T-nnn`, `ALG-nnn` is `CT-ALG-nnn`. Verification codes: U unit pin on fixture · P property test · R replay · L live run · M measurement · A analysis · X experiment.

## Engine needs: Discovery

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-FR-101 | Read records from any search engine results page | Google (O cloud: L01); Bing (O cloud: L02); DuckDuckGo HTML (O cloud: L03); Brave Search (O cloud: L04); Mojeek (O cloud: L05) | `[ ]` | T-008/009 | L | LR-1; pass 2: O: 4 of 5 engines refused the cloud client (L01, L03-L05) |
| CT-FR-102 | Site-restricted results: off-platform cards dropped before any click (LR-4) | Bing (O cloud: L02) | `[ ]` | T-009 + url_evidence | U+L | ADR-022 slice |
| CT-FR-103 | Job-board lists with pagination | Tencent (O cloud: C12); Amazon Jobs (O cloud: C18); Jobvite (O cloud: L06 L07); Workday (O cloud: L10 L11 L12); iCIMS (O cloud: L13 L14 P24); Oracle Recruiting Cloud (O cloud: L27); Oracle Taleo (O cloud: L28); Eightfold (O cloud: L29 L30); NEOGOV (O cloud: L31 L32 L33); DirectEmployers (O cloud: L34 L35 L36); Arbeitsagentur (O cloud: L38); StepStone (O cloud: L39); LinkedIn (O cloud: L43); Dice (O cloud: L45) | `[~]` | T-008 + T-016 | L | Bing only |
| CT-FR-104 | Careers-page mining (all postings on a company page) | Jobvite (O cloud: L06 L07 L08 …); Stripe careers (company site) (O cloud: L15); Databricks careers (company site) (O cloud: L16); Figma careers (company site) (O cloud: L17); Ashby (O cloud: L18 L19 L20); SmartRecruiters (O cloud: L21 L23); Bosch careers (company site) (O cloud: L22); Tencent (O cloud: L41 P23); Notion (O cloud: L60 L61 N60) | `[~]` | T-008 | L | analyzer exists |
| CT-FR-105 | Card destination resolution without clicking off-platform | - | `[~]` | T-009; acts: CardActivator (click-free first, then bounded clicks) | U+L | card_activation clicks |
| CT-FR-106 | Feed posts as candidates | Hacker News (O cloud: L37 P19) | `[ ]` | FR-031 | L | none |
| CT-FR-107 | Yield and page-size signals for the degradation guard | - | `[~]` | Trace | U | baselines read live |
| CT-FR-108 | Per-record provenance: query, page, rank, URL, reason kept or dropped (LR-6) | DirectEmployers (O cloud: P25) | `[~]` | Trace L1 | U | defect 9; pass 3: [ ] -> [~] (S1: every card's fate with an enumerated reason in the page record; every URL found, kept or dropped in the session log (DEBUG) joined by url_ref; unit-pinned) |
| CT-FR-109 | Completeness check: records read against the page's own total count | Oracle Taleo (O cloud: L28); Dice (O cloud: L45); Tencent (O cloud: P23) | `[ ]` | T-009 + FR-107 | U+L | O: totals printed on three sources |
| CT-FR-110 | Duplicate postings across hosts and boards collapsed with provenance kept | DirectEmployers (O cloud: L34 P18 P25) | `[~]` | FR-108 + dedup | U+L | O: same posting ID on dejobs.org and a partner host |

## Engine needs: Vetting

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-FR-111 | Job text from the real posting page with structured data | Remote OK (O cloud: C14); Ashby (O cloud: F02 F03 F04 …); Workday (O cloud: F05 F06 P04 …); Eightfold (O cloud: F12 P17); Jobvite (O cloud: P01 P02 P03); Oracle Recruiting Cloud (O cloud: P15); Arbeitsagentur (O cloud: P20); StepStone (O cloud: P21); Dice (O cloud: P22) | `[~]` | T-017/009 | L | Bible 8.2 |
| CT-FR-112 | Closed / expired / already applied detection | Greenhouse (O cloud: L46 P26); Stripe careers (company site) (O cloud: L47); Oracle Recruiting Cloud (O cloud: L48); Arbeitsagentur (O cloud: L52); Eightfold (O cloud: P17) | `[~]` | T-006 | L | verdict kinds; pass 2: A: 0 of 4 closed or missing postings judged CLOSED |
| CT-FR-113 | Salary, location, work mode extraction | Workday (O cloud: L49); Jobvite (O cloud: P02 P03); Ashby (O cloud: P10 P11 P12); Dice (O cloud: P22) | `[~]` | T-009 | U+L | salary_extraction.py |
| CT-FR-114 | Apply entry point and ATS identification | Workday (O cloud: L49 P04 P05 …); iCIMS (O cloud: L51); LinkedIn (O cloud: L53 L55); Jobvite (O cloud: P01 P02 P03); Ashby (O cloud: P10 P11 P12); SmartRecruiters (O cloud: P13 P14); Oracle Recruiting Cloud (O cloud: P15); Oracle Taleo (O cloud: P16); Eightfold (O cloud: P17); DirectEmployers (O cloud: P18 P25); Arbeitsagentur (O cloud: P20); StepStone (O cloud: P21); Dice (O cloud: P22) | `[~]` | T-009 + registry | U+L | ATSRegistry |
| CT-FR-115 | Posting language detection and structure-only fallback | AllJobs (Hebrew) (O cloud: C01); JobKorea (Korean) (O cloud: C06); Habr Career (Russian) (O cloud: C07); SmartRecruiters (O cloud: P14); Arbeitsagentur (O cloud: P20); StepStone (O cloud: P21) | `[~]` | T-003 | U | NFR-021 |
| CT-FR-116 | Closed, missing and expired postings recognised in any language and status (200, 404, 410, silent redirect) | Greenhouse (O cloud: L46 P26); Stripe careers (company site) (O cloud: L47); Oracle Recruiting Cloud (O cloud: L48); Arbeitsagentur (O cloud: L52) | `[ ]` | T-006 phrases | R+L | A: verdict CLOSED on 0 of 4 closed or missing postings; P26 ERROR_404 by title |
| CT-FR-117 | Structured data checked against the visible page before it is trusted | Workday (O cloud: L49 L50); Arbeitsagentur (O cloud: P20) | `[ ]` | T-017 | U+L | see CT-PH-162 |
| CT-FR-118 | Pay, locations and remote status read from JSON-LD or prose, with which one recorded | Ashby (O cloud: P10 P11 P12); Dice (O cloud: P22) | `[~]` | T-017 + T-009 | U+L | O: four Ashby/Dice postings |
| CT-FR-119 | Posting age and closing date (datePosted, validThrough, relative age) | LinkedIn (O cloud: L53); Oracle Recruiting Cloud (O cloud: P15); Eightfold (O cloud: P17) | `[ ]` | T-017 + T-003 | U+L | see CT-PH-168 |
| CT-FR-135 | Apply target classified: same page, same host, other host, mailto, button without target | Jobvite (O cloud: P01); Workday (O cloud: P04); SmartRecruiters (O cloud: P13); Oracle Recruiting Cloud (O cloud: P15) | `[ ]` | FR-114 | U+L | see CT-PH-170, 171 |
| CT-FR-136 | Description text read from shadow roots and frames, not only light DOM | iCIMS (O cloud: L51); SmartRecruiters (O cloud: P13); Arbeitsagentur (O cloud: P20) | `[ ]` | T-002 | U+L | see CT-PH-164 |
| CT-FR-137 | Assessment-first and paused-application states reported to the user | Notion (O cloud: L59 L62) | `[?]` | T-006 + HITL | L | see CT-PH-172, 173 |

## Engine needs: Applications

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-FR-121 | Form discovery and step flow | Jobvite (O cloud: F01 F14); Ashby (O cloud: F02 F03 F04); Greenhouse (O cloud: F09 P08); Oracle Recruiting Cloud (O cloud: F10); Oracle Taleo (O cloud: F11); Eightfold (O cloud: F12) | `[~]` | T-010 | L | mock forms only |
| CT-FR-122 | Label to control pairing | Jobvite (O cloud: F01 F14); Ashby (O cloud: F02 F03 F04); Greenhouse (O cloud: F09 P08); Oracle Recruiting Cloud (O cloud: F10); Oracle Taleo (O cloud: F11); Eightfold (O cloud: F12) | `[~]` | T-011 | P+L | WIRED |
| CT-FR-123 | Field type and option lists | Jobvite (O cloud: F01 F14); Ashby (O cloud: F02 F03 F04); Greenhouse (O cloud: F09 P08); Oracle Recruiting Cloud (O cloud: F10); Oracle Taleo (O cloud: F11); Eightfold (O cloud: F12) | `[~]` | T-012 | U+L | WIRED |
| CT-FR-124 | Required fields known before submit | Jobvite (O cloud: F01 F14); Ashby (O cloud: F02 F03 F04); Greenhouse (O cloud: F09 P08); Oracle Recruiting Cloud (O cloud: F10) | `[~]` | T-013 | U+L | FR-012; S4 (pass 4): requiredness before submit, read without interacting (validity.valueMissing); R (owner capture form-one-page/20261103-074245_job-boards.greenhouse.io); cloud live check on Greenhouse, Ashby, Lever |
| CT-FR-125 | Widget operation plans (combobox, picker, dropzone) | - | `[~]` | T-014/015 | U+L | partial |
| CT-FR-126 | Resume upload | Ashby (O cloud: F02 F03 F04); Greenhouse (O cloud: F09 P08) | `[~]` | T-014; acts: FileInputHandler | L | handler |
| CT-FR-127 | Login/account gates detected and handed off | iCIMS (O cloud: F07); Oracle Recruiting Cloud (O cloud: F10); Oracle Taleo (O cloud: F11); Eightfold (O cloud: F12) | `[~]` | T-006 | L | verdict; pass 2: A: account walls recognised on 1 of 4 apply steps (F07) |
| CT-FR-128 | In-place CAPTCHA pause hook with understanding exposed | Greenhouse (O cloud: P08) | `[~]` | PauseContext; acts: ApplicationsWorkflow._pause_for_challenge | U+L | pause exists; no context |
| CT-FR-129 | New tab / pop-up handling with epoch | - | `[~]` | T-016; acts: card activation tab handling | U+L | tab switch |
| CT-FR-130 | Submit prediction as input to the gate (never a replacement) | - | `[ ]` | T-026 | P+U | ADR-012 |
| CT-FR-131 | Error mapping and corrective retry | - | `[ ]` | ALG-012 | U+L | FR-014 |
| CT-FR-132 | Confirmation detection | - | `[~]` | T-006 | L | SUCCESS_PAGE |
| CT-FR-133 | Repeating sections filled in order | - | `[ ]` | ALG-002; acts: none | U+L | design |
| CT-FR-134 | Honeypots skipped, recorded | - | `[~]` | ALG-014 | U | WIRED |

## Functional requirements (04)

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-FR-001 | Access through one port with capabilities | - | `[~]` | T-001 | U,L | 04 |
| CT-FR-002 | Observation at levels, region, budget | - | `[~]` | T-002 | U,M | 04 |
| CT-FR-003 | Columnar Doc with shadow/iframe and truncation flags | - | `[~]` | T-004 | U,L | 04 |
| CT-FR-004 | Page family and verdict with abstention | - | `[~]` | T-006/007 | U,R,L | 04; pass 2: A: today's verdict on 119 cloud specimens: see 10 s5 baseline |
| CT-FR-005 | Ranked record runs, tolerant of variants | - | `[~]` | T-008 | P,U,L | 04; pass 2: A (stage 5): 124 of 136 records detected; one group per page |
| CT-FR-006 | Per-record title, link, company, location, date with evidence | - | `[~]` | T-009 | U,L | 04; pass 2: A (stage 5, live, cloud): 0 of 136 list records came back with both a title and a resolved link (Jobvite, Ashby, Taleo, HN); pass 3: S1: 2,201 of 2,959 records with title and link on 55 specimens (head 137 of 3,101); live cloud 417/417 on six boards |
| CT-FR-007 | List movement and virtualization guard | - | `[ ]` | ALG-018 | U,L | 04 |
| CT-FR-008 | JD sections and structured data | - | `[~]` | T-009/017 | U,L | 04 |
| CT-FR-009 | Form, step, section, field segmentation | - | `[~]` | T-010 | U,L | 04 |
| CT-FR-010 | Label pairing ladder plus assignment | - | `[~]` | T-011 | P,U | 04 |
| CT-FR-011 | Field typing with autofill tokens | - | `[~]` | T-012 | U | 04 |
| CT-FR-012 | Requiredness tri-state before submit | - | `[~]` | T-013 | U,L | 04; pass 2: [~] -> [ ] (same evidence as CT-PH-051: the requiredness answer is True for every field); S4 (pass 4): tri-state REQUIRED/OPTIONAL/UNKNOWN from valueMissing, required/aria-required, label word, asterisk (+legend, +red, CSS-drawn), (optional), convention; unit and real-browser pins; R (owner capture form-required-markers/20261103-080138_jobs.ashbyhq.com); no live owner run yet |
| CT-FR-013 | Submit-outcome prediction | - | `[ ]` | T-026 | P,U | 04 |
| CT-FR-014 | Post-submit error mapping | - | `[ ]` | T-013 | U,L | 04 |
| CT-FR-015 | Widget recognition and operation plans | - | `[~]` | T-014 | U,L | 04 |
| CT-FR-016 | Async/paged option list protocol | - | `[ ]` | T-015 | U,L | 04 |
| CT-FR-017 | Visibility, occlusion, honeypot decision | - | `[~]` | T-005 | P,U | 04 |
| CT-FR-018 | Defence recognition recorded as research data | - | `[~]` | T-006 | U,L | 04 |
| CT-FR-019 | Transitions, windows, dialogs, downloads | - | `[~]` | T-016 | U,L | 04 |
| CT-FR-020 | HITL pause exposure and resume re-observation | - | `[ ]` | ALG-024 | U,L | 04 |
| CT-FR-021 | Text, encodings, languages with notices | - | `[~]` | T-003 | P,U | 04 |
| CT-FR-022 | Trace of every tool run at levels | - | `[~]` | T-018 | U,R | 04; pass 3: S1: per-page record (trace L0/L1) built in the discovery extractor, schema 1, unit-pinned; no page text by construction |
| CT-FR-023 | Replay bit-identical | - | `[~]` | T-022 | R | 04 |
| CT-FR-024 | Tuning under the significance rule | - | `[ ]` | T-019 | P,U | 04 |
| CT-FR-025 | Domain memory, bounded and verified | - | `[ ]` | T-020 | U | 04 |
| CT-FR-026 | Resource profiles and duty cycling | - | `[~]` | T-021 | M,U | 04 |
| CT-FR-027 | Ledger load, coverage, UNKNOWN capture | - | `[ ]` | T-023 | U | 04 |
| CT-FR-028 | Workbench review and explore | - | `[ ]` | T-024 | U,manual | 04 |
| CT-FR-029 | Non-HTML payloads for Source Channels | - | `[ ]` | T-002 | U | 04 |
| CT-FR-030 | Compatibility shims for existing ports | - | `[~]` | S6 | U | 04 |
| CT-FR-031 | Feed hiring posts as text-only candidates | - | `[ ]` | T-007/009 | U,L | 04 |
| CT-FR-032 | Login/sign-up/code/OAuth gates handed off | - | `[~]` | T-006 | U,L | 04 |
| CT-FR-033 | Unknown-unknown capture: any unrecognised state fails closed, is recorded as a [?] row candidate with evidence, and is handed to the human while safe work continues | - | `[ ]` | T-006 + T-018 + T-023 | U+L | 12 |
| CT-FR-034 | Edge-case catalogue: every tool declares its behaviour on the catalogue's inputs (returns, raises, hangs), its bound and its trace record | - | `[ ]` | all | U+P | 12 |

## Non-functional requirements (04)

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-NFR-001 | Zero required runtime dependencies | - | `[~]` | boundary pin | pin | 04 |
| CT-NFR-002 | Pure Python 3.10 floor | - | `[~]` | CI | CI | 04 |
| CT-NFR-003 | Determinism | - | `[~]` | INV-001 | R,P | 04 |
| CT-NFR-004 | P95 analysis CPU 1.0 s at 12,000 nodes on the reference machine | - | `[ ]` | profiles | M | 04; pass 2: A: today's verdict alone: median 28 ms, p95 224 ms, max 2.8 s per page (cloud, 119 specimens) |
| CT-NFR-005 | Memory 100 B/node and 25 MB at 100k nodes | - | `[ ]` | T-004 | M | 04; measured 360 B/node objects |
| CT-NFR-006 | Observable footprint budget | - | `[ ]` | script registry | A,X | 04, 07 |
| CT-NFR-007 | Accuracy targets with intervals | - | `[ ]` | evaluation | L | 04, 09 |
| CT-NFR-008 | Calibrated abstention | - | `[ ]` | evaluation | L | 04 |
| CT-NFR-009 | Declared complexity per tool | - | `[ ]` | 06 | A | 04 |
| CT-NFR-010 | No hangs: every wait is capped and typed | - | `[ ]` | ctx budgets | U,fault | LR-5; pass 2: [~] -> [ ] (measured: label pairing is cubic in text nodes with no cap (2 inputs + 300 text nodes 1.6 s); the extraction script has no node or byte cap (30k rows 16 s, 11 MB); see 12) |
| CT-NFR-011 | Library semantic versioning | - | `[ ]` | packaging | review | 04 |
| CT-NFR-012 | OS and browser portability | - | `[~]` | profiles | L matrix | 04 |
| CT-NFR-013 | Container and VM adaptation | - | `[ ]` | EnvFacts | M,U | 04, 07 |
| CT-NFR-014 | Privacy: no PII in traces | - | `[~]` | sentinel | pin | 04 |
| CT-NFR-015 | Research-grade provenance in every trace | - | `[~]` | T-018 | U | 04 |
| CT-NFR-016 | Workbench accessible by keyboard and screen reader | - | `[ ]` | T-024 | manual | 04 |
| CT-NFR-017 | Modularity cost at most 2% | - | `[ ]` | 05 | M | derived under 1% |
| CT-NFR-018 | Nothing slows AA over time | - | `[ ]` | caps, gate | M,CI | 04, 05 |
| CT-NFR-019 | Tuning safety | - | `[ ]` | T-019 | P,U | 04 |
| CT-NFR-020 | Testable without a browser | - | `[~]` | sans-IO | U | 04 |
| CT-NFR-021 | Language-agnostic structure | - | `[~]` | T-003 | U | 04 |
| CT-NFR-022 | Ledger, requirements, tests in sync | - | `[ ]` | T-023 | CI | 04 |
| CT-NFR-023 | Fail closed | - | `[~]` | INV-004 | U | ADR-012 |
| CT-NFR-024 | Bounded stores, O(1) lookups over time | - | `[ ]` | T-018/020 | M | 04 |
| CT-NFR-025 | Tail budgets on the worst-case machine: p95, p99 and maximum stated per tool on adversarial input | - | `[ ]` | all | M | 06 s12 |
| CT-NFR-026 | Bounded acquisition: node cap, byte cap and frame cap on every observation, each with a truncation flag | - | `[ ]` | T-002 | U+M | A: 30k rows -> 11.1 MB in one script result |

## Research and publishability criteria

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-NFR-101 | FAIR4RS Findable (DOI, CITATION.cff, metadata) | - | `[ ]` | packaging | review | Bible 25.1: Missing |
| CT-NFR-102 | FAIR4RS Accessible (open licence, public URL) | - | `[~]` | repo | review | Bible 25.1: Partial |
| CT-NFR-103 | FAIR4RS Interoperable (standard formats, documented API) | - | `[ ]` | trace schema | review | 08 |
| CT-NFR-104 | FAIR4RS Reusable (licence, docs, container) | - | `[~]` | library, image | review | Dockerfile.test |
| CT-NFR-105 | FAIR4RS Reproducible (seeded, versioned, deterministic) | - | `[~]` | INV-001/006 | R | seeded RNG LIVE |
| CT-NFR-106 | FAIR4RS Sustained (changelog, releases, contributing) | - | `[~]` | repo | review | CHANGELOG exists |
| CT-NFR-107 | ACM Functional: smoke test without a browser | - | `[~]` | fixtures | CI | driver=None path |
| CT-NFR-108 | ACM Functional: mock ATS benchmark at least 80% fields | - | `[~]` | CONTROL set | L | tests/benchmarks/ats_forms |
| CT-NFR-109 | ACM Reusable: plug-in tools, pinned image, seed, profile flags | - | `[ ]` | registry | review | Bible 25.2 |
| CT-NFR-110 | Tier 1 property tests (lemmas, pairing, hashing) | - | `[ ]` | 06 | P | Bible 25.4 |
| CT-NFR-111 | Tier 3 reproducibility: seeded twice identical; memory ceiling; perf regression | - | `[ ]` | CI | R,M | Bible 25.4 |
| CT-NFR-112 | Tier 4 validity: ablation of each tool on the benchmark | - | `[ ]` | evaluation | L | Bible 25.4 |
| CT-NFR-113 | Ethics: deon checklist, consent, data minimisation honoured by the trace | - | `[~]` | 08 | review | ETHICS.md |

## Toolkit invariants

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-INV-001 | Tools are pure functions of observation, parameters, seed | - | `[ ]` | all | R,P | 05 |
| CT-INV-002 | Library imports nothing from AA | - | `[ ]` | boundary pin | pin | 05 |
| CT-INV-003 | Never act on stale understanding (epoch) | - | `[ ]` | T-016 | U | 05, 08 |
| CT-INV-004 | Abstain over guess when consequences are irreversible | - | `[~]` | all | U | ADR-012 |
| CT-INV-005 | Evidence attached to every finding | - | `[ ]` | CT-DS-005 | U | defect 9 |
| CT-INV-006 | Parameters immutable within a run | - | `[ ]` | T-019 | U,P | ADR-020 d4 |
| CT-INV-007 | Every tool bounded: declared complexity, hard caps, typed timeout | - | `[ ]` | ctx | A,U | 06 |
| CT-INV-008 | Accelerators optional and result-equivalent | - | `[ ]` | registry | P | 05 |
| CT-INV-009 | Every page-world script registered with justification | - | `[ ]` | script registry | U | 07 |
| CT-INV-010 | Observation tools cannot mutate the page | - | `[ ]` | capability types | U | 05 |
| CT-INV-011 | Nothing deleted; retirements via retire.py | - | `[~]` | process | pin | ADR-016 |
| CT-INV-012 | Memory is never authoritative | - | `[ ]` | T-020 | U | 06 |
| CT-INV-013 | Unknown-unknown rule: fail closed, record [?] with evidence, hand to the human, keep other safe work going | - | `[ ]` | all | U | 12 s5 |
| CT-INV-014 | No loop without a work-unit cap and no wait without a deadline; cubic steps only on capped inputs | - | `[ ]` | all | P+M | A: label pairing is cubic in text nodes today |

## Bible invariants (03)

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-INV-101 | 1.1 Worst-case contract | - | `[~]` | profiles | M | 03 |
| CT-INV-102 | 1.2 Separation of concerns | - | `[~]` | tools | review | 03 |
| CT-INV-103 | 1.2 Single source of truth | - | `[~]` | ParameterSet, ledger | pin | 03 |
| CT-INV-104 | 1.2 DRY | - | `[~]` | tools | review | two hash vocabularies |
| CT-INV-105 | 1.2 Hexagonal Architecture | - | `[~]` | boundary pin | pin | 03 |
| CT-INV-106 | 1.2 Dependency inversion | - | `[~]` | ports | review | 03 |
| CT-INV-107 | 1.2 Worst-case first | - | `[~]` | decision order | review | 03 |
| CT-INV-108 | 1.2 Zero required external keys | - | `[~]` | T-001 | review | 03 |
| CT-INV-109 | 1.2 Agnostic implementations | - | `[~]` | capabilities | review | 03 |
| CT-INV-110 | Rule 1: no domain/application import of infrastructure or adapters | - | `[~]` | pin | pin | architecture pin |
| CT-INV-111 | Rule 2: no default overriding runtime_defaults.yaml | - | `[~]` | ParameterSet | pin | 03 |
| CT-INV-112 | Rule 3: browser never shared across threads without a lease | - | `[~]` | Access | pin | 03 |
| CT-INV-113 | Rule 4: engines never call each other | - | `[~]` | findings only | pin | 03 |
| CT-INV-114 | Rule 5: math is a strategy, not a source | - | `[~]` | findings only | review | 03 |
| CT-INV-115 | Rule 6: absolute imports only | - | `[~]` | lint | pin | 03 |
| CT-INV-116 | 27 Session Supervisor: lease, plan, behaviour parameters, map, watchdog | - | `[ ]` | ctx.tick | U | Bible: PLANNED |
| CT-INV-117 | 26 Sans-IO | - | `[~]` | design | U | 03 |
| CT-INV-118 | 16 Evasion and security framework (policies, thresholds) | - | `[~]` | T-006 | U,L | 03 |
| CT-INV-119 | 30.4 Disk pre-checks for USB safety | - | `[ ]` | T-018 | U | 03 |
| CT-INV-120 | 31 Agnostic trinity: platform, framework, provider | - | `[~]` | capabilities | review | 03 |

## Philosophy principles (03)

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-INV-201 | Core mission: worst-case users first | - | `[~]` | profiles | M | 03 |
| CT-INV-202 | Tool-first: predictable, safe, explains, respects intent | - | `[~]` | tools, trace | L | 03 |
| CT-INV-203 | Worst-case preferences: low memory, offline, deterministic, local | - | `[~]` | design | M | 03 |
| CT-INV-204 | Autonomy with guardrails: never-seen pages, general strategies, HITL, evidence | - | `[ ]` | design | L | 03 |
| CT-INV-205 | Architectural commitments | - | `[~]` | design | review | 03 |
| CT-INV-206 | Progressive enhancement rules | - | `[~]` | capabilities | P | 03 |
| CT-INV-207 | AA as research-grade software | - | `[~]` | design | R | 03 |
| CT-INV-208 | Outputs as research-grade data | - | `[ ]` | trace | R | 08 |
| CT-INV-209 | Safety, security, respect | - | `[~]` | design | review | 03 |
| CT-INV-210 | Structural excellence | - | `[~]` | design | review | 03 |
| CT-INV-211 | Performance and efficiency | - | `[ ]` | profiles | M | S0 |
| CT-INV-212 | Maintainability and developer experience | - | `[~]` | design | review | 03 |
| CT-INV-213 | Adaptability and reusability | - | `[~]` | library | review | 03 |
| CT-INV-214 | Quality and reliability | - | `[~]` | design | L | 03 |
| CT-INV-215 | Repository health traits | - | `[~]` | docs gate, CI | CI | 03 |
| CT-INV-216 | Decision standard | - | `[~]` | decision order | review | 03 |
| CT-INV-217 | Guidance for AI-assisted contributors | - | `[~]` | this suite | review | 03 |
| CT-INV-218 | Documentation interpretation policy (propose changes explicitly) | - | `[~]` | 03 s3 | review | 03 |
| CT-INV-219 | Final principle | - | `[~]` | design | review | 03 |

---
title: "Page Comprehension Toolkit: Risks and Open Questions"
status: needs-review
last_verified: 2026-11-02
verified_against: "1bf7935"
audience: contributors
---

# Risks and open questions

## 1. Risks

| ID | Risk | Likelihood / impact | Mitigation | Signal that it happened |
| --- | --- | --- | --- | --- |
| R1 | Site evidence is from one environment: pass 1 had none, and pass 2 observed 123 pages from a data centre (`cloud`). Owner-machine behaviour is unobserved | certain / medium | environment tag on every observation; slice 0 freezes the set from the owner's machine; `cloud` specimens guard code only (CT-Q-027) | a ledger tick citing only `cloud` evidence |
| R2 | The 0.25-0.56 s cost is acquisition, so the tool redesign does not speed it up | likely / medium | S0 measures stages before S2/S3 commit to a layout strategy | stage timings in the trace |
| R3 | Sibling-run discovery fails on layouts whose records are not sibling-contiguous (grid with row wrappers, table with sub-rows, ads between every card) | medium / high | window size `K`, gap tolerance, lattice regularity; ANCHOR recall per source; fall back to the Workbench `UNKNOWN` row | low recall on a family |
| R4 | A single machine's font/layout differences change geometry-based decisions | medium / medium | relative thresholds; font fingerprint recorded; fixtures with pinned fonts | layout-sensitive tests flaky across machines |
| R5 | Tuning overfits or oscillates | medium / medium | site-level units, exact test, Holm, cooldown, non-inferiority, held-out sites, rollback | parameter set churn |
| R6 | Domain memory serves a stale hint that passes verification by luck | low / high | verification checks invariants not just counts; two-failure quarantine; expiry; memory never authoritative | verify-fail rate rising |
| R7 | Submit prediction wrongly says BLOCKED | low / **severe** | only certified BLOCKED counts; everything else is WILL_SUBMIT; the gate is in Applications | any submission after a BLOCKED prediction |
| R8 | The ledger rots | high / medium | sync pins; coverage check in CI; the Workbench reads it daily | rows with old `ev` dates |
| R9 | Terms-of-service and ethics exposure on LinkedIn, Google, Indeed | certain / high | owner rulings CT-Q-006..009; observe-only evaluation; read-only guard | complaint, account action |
| R10 | The columnar `Doc` hurts readability and slows contributors | medium / low | `NodeView`; a short developer guide; a conformance fixture per tool | review friction |
| R11 | Honeypot cost ratio is wrong (skipping legit fields or filling traps) | low / medium | ratio is a safety parameter, reviewed by the owner; both error types counted in 09 | abstention or trap events |
| R12 | Traces grow unbounded on a USB stick | medium / medium | levels, retention by age and size, L2 off for USB | disk pre-check warnings (Bible 30.4) |
| R13 | A vendor changes a defence; recognition signatures rot | high / medium | structural signatures, vendor annotations are research-only; ANCHOR drift check | defence rows turning `[?]` |
| R14 | A required dependency creeps into the library (for example a parser) | medium / high | import-boundary pin; the repo already owns its HTML text reader for replay | pin failure |
| R15 | Single-link `UNKNOWN` default stops unattended runs | medium / low | CT-Q-023; skip-and-record as default | rising `UNKNOWN` share |
| R16 | A long, text-heavy form container makes today's label pairing run for minutes (cubic, no cap) on the worst-case machine | likely on real pages / high | residual cap `m ≤ 120`; ladder first (S3); fault-injection pin | a pairing step over 1 s in the trace |
| R17 | Today's verdict gates every Ashby form as a CAPTCHA block, so AA would never apply on Ashby | certain at `1bf7935` (A: F02-F04) / high | an invisible badge is `embedded`; pin on the three specimens (S1) | `CAPTCHA_BLOCK` on a page with ≥ 5 controls |
| R18 | Plain block pages and 429s read as `UNKNOWN`, so an engine keeps contacting a host that has refused it | certain at `1bf7935` / medium | block kind in the verdict (EC-21); bench on first refusal (CT-Q-028) | repeated `UNKNOWN` on one host |
| R19 | Real fields are skipped as honeypots on RTL pages and for names such as `address2` | certain at `1bf7935` / high on RTL markets | CT-ALG-014 rule; token matching; computed direction | honeypot share above 10% of a form |
| R20 | Signed-in and signed-out views differ (Notion, LinkedIn), so fixtures from one do not represent the other | certain / medium | environment and session tags; owner rulings CT-Q-029/030 | a control present in the owner's trace and absent in the fixture |
| R21 | `robots.txt` and terms differ per host; the evaluation set could include disallowed paths | medium / high | CT-Q-026; disallowed paths never enter the set | a set entry whose host is in 07 s9 with a matched disallow |

## 2. Open questions (nobody knows yet)

| # | Question | How it will be answered |
| --- | --- | --- |
| Q1 | Does enabling the accessibility protocol domain or reading it change anything a page can observe? | CT-EXP-001 step 4 |
| Q2 | Which of the capability-matrix cells in 05 hold on the current versions of each driver? | S0 contract suite per adapter |
| Q3 | What does a Google results page's anchor/heading structure look like to the new tools, and why was no link "eligible" in the 8-card run? | S1 fixture and trace |
| Q4 | Do public job boards virtualize their lists, and how often? | **Partly answered (pass 2, cloud):** none of the reachable boards did (Ashby renders 803 rows at once, RemoteOK grows without recycling, Eightfold pages). Signed-in surfaces remain unmeasured; the detector stays |
| Q5 | How many ATS forms mark requiredness only after submit? | Required/error-mapping outcomes on observe-only runs plus CONTROL |
| Q6 | What storage does L2 really cost per page, compressed? | S1 measurement |
| Q7 | Is in-place region query faster than a snapshot on the worst-case laptop? | S0 (CT-Q-025) |
| Q8 | What gold-label agreement (Cohen's kappa) do two labellers reach? | 20% double-labelled sample |
| Q9 | Are there page families beyond the three that carry real work (for example employer talent-community sign-ups)? | `UNKNOWN` rows from the Workbench |
| Q10 | Can any selection of the optional accelerators be proven result-equivalent, or must they declare a tolerance? | equivalence test per accelerator |
| Q11 | How do the owner's machine and a data centre differ on the same URLs (blocks, controls withheld, fonts)? | a paired run of the frozen set from both environments, compared per specimen |
| Q12 | Which non-UTF-8 job pages still exist, if any? | pass 2 found none on 34 hosts; the DRAW set will report any it meets |

## 3. What this suite deliberately does not decide

Legal conclusions; the terms of any site; whether AA should sign in to anyone's account;
anything paid; the kernel's final shape; the fit and vetting policy. Each appears as a
CT-Q ruling or a non-goal in [01](01_charter.md).

---
title: "Page Comprehension Toolkit: Master Capability Ledger"
status: needs-review
last_verified: 2026-11-02
verified_against: "7701de8 + S1 reply files (pass 3)"
audience: contributors
---

# Master capability ledger

The checklist of everything AA requires of page comprehension. **The machine-readable source is the YAML: [02_ledger.yaml](02_ledger.yaml) (root and part 1), [02_ledger_part2.yaml](02_ledger_part2.yaml), [02_ledger_part3.yaml](02_ledger_part3.yaml) and [02_ledger_part4.yaml](02_ledger_part4.yaml).** Coverage against frozen reference lists: [02_ledger_coverage.yaml](02_ledger_coverage.yaml) (check in [09](09_verification.md) section 8). Each page of this ledger renders one YAML file; the two must agree row for row and status for status. The ledger is split in four only to keep each file reviewable; the parts are one ledger with one ID space. How to add or comment: [00](00_index.md).

| Part | Categories | Page |
| --- | --- | --- |
| 1 | result lists, careers pages, job descriptions, forms, requiredness, accounts, defences | [02_ledger.md](02_ledger.md) |
| 2 | browser surfaces, page states, text, environments, future capabilities, edge cases | [02_ledger_part2.md](02_ledger_part2.md) |
| 3 | engine needs, requirements, research criteria, invariants | [02_ledger_part3.md](02_ledger_part3.md) |
| 4 | toolbars and filter controls, interaction patterns (APG) and HTML controls, alternate views, pass-3 requirements | [02_ledger_part4.md](02_ledger_part4.md) |

**Status legend.** `[x]` proven live on three independent sources by AA's own runs · `[~]` partial: code and/or fixture evidence, no three-source live proof · `[ ]` not capable · `[?]` unknown: evidence recorded, a human decides. **No row is `[x]`**: no built tool has been proven by AA's own live runs on three sources. Pass 2 observed pages live from a data centre (`cloud`); those observations are evidence for the design, never proof of AA's behaviour.

**Source tags.** **O** observed live in pass 2, environment `cloud`, with specimen IDs (the evidence set, [08](08_evidence_and_research.md)) · **R** recorded in AA's own evidence (environment `owner` unless stated) · **K** recalled, unverified. Tool column: `T-nnn` is `CT-T-nnn`, `ALG-nnn` is `CT-ALG-nnn`. Verification codes: U unit pin on fixture · P property test · R replay · L live run · M measurement · A analysis · X experiment.

## Summary (all parts)

| Status | Rows |
| --- | --- |
| `[x]` | 0 |
| `[~]` | 176 |
| `[ ]` | 203 |
| `[?]` | 42 |
| **Total** | **421** |

| Category | Part | Rows | `[x]` | `[~]` | `[ ]` | `[?]` |
| --- | --- | --- | --- | --- | --- | --- |
| Phenomena: result lists | 1 | 21 | 0 | 9 | 10 | 2 |
| Phenomena: careers pages and list movement | 1 | 10 | 0 | 8 | 2 | 0 |
| Phenomena: job descriptions | 1 | 17 | 0 | 9 | 5 | 3 |
| Phenomena: forms, controls and widgets | 1 | 20 | 0 | 8 | 8 | 4 |
| Phenomena: how 'required' is signalled | 1 | 10 | 0 | 1 | 9 | 0 |
| Phenomena: accounts and authentication | 1 | 12 | 0 | 3 | 5 | 4 |
| Phenomena: defences and obstacles | 1 | 10 | 0 | 8 | 1 | 1 |
| Phenomena: browser surfaces and transitions | 2 | 10 | 0 | 2 | 6 | 2 |
| Phenomena: walls, error pages and page states | 2 | 10 | 0 | 4 | 1 | 5 |
| Phenomena: content, encodings and languages | 2 | 19 | 0 | 8 | 10 | 1 |
| Platforms, browsers, access mechanisms, resource profiles, containers | 2 | 20 | 0 | 10 | 6 | 4 |
| Future capabilities | 2 | 10 | 0 | 0 | 8 | 2 |
| Phenomena: edge cases and adversity (12) | 2 | 34 | 0 | 4 | 24 | 6 |
| Phenomena: toolbars and filter controls | 4 | 17 | 0 | 3 | 12 | 2 |
| Phenomena: interaction patterns (WAI-ARIA APG) and HTML controls | 4 | 24 | 0 | 3 | 18 | 3 |
| Phenomena: alternate views of the same record | 4 | 11 | 0 | 2 | 7 | 2 |
| Engine needs: Discovery | 3 | 10 | 0 | 6 | 4 | 0 |
| Engine needs: Vetting | 3 | 12 | 0 | 6 | 5 | 1 |
| Engine needs: Applications | 3 | 14 | 0 | 10 | 4 | 0 |
| Functional requirements (04) | 3 | 37 | 0 | 20 | 17 | 0 |
| Non-functional requirements (04) | 3 | 27 | 0 | 9 | 18 | 0 |
| Research and publishability criteria | 3 | 13 | 0 | 7 | 6 | 0 |
| Toolkit invariants | 3 | 14 | 0 | 2 | 12 | 0 |
| Bible invariants (03) | 3 | 20 | 0 | 18 | 2 | 0 |
| Philosophy principles (03) | 3 | 19 | 0 | 16 | 3 | 0 |

## Phenomena: result lists

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-PH-001 | Google web results: organic cards (heading inside/near anchor) | Google web (R); Bing (R); DuckDuckGo HTML (K) | `[~]` | T-008/009 | U+L | R: LR-1, 0 jobs read; defects 1,4; cause of 8-card no-link case unexplained; pass 3: S1: full-subtree text and record-root rule pinned on synthetic Google shapes; the Google fixture pin skips until the owner supplies a page (no live run: Google refuses the cloud client) |
| CT-PH-002 | Mixed blocks in a results list: ads, 'people also ask', video, AI answer, related searches interleaved with organic | Google web (R); Bing (R); Bing (O cloud: L02) | `[~]` | T-008 | U+L | R: 12-15 candidate groups per page; one group returned (defect 8) |
| CT-PH-003 | Bing uniform cards with data-* identity | Bing (R); Bing site-restricted (R); Bing (O cloud: L02) | `[~]` | T-008/009 | U+L | R: Bing yields real postings; identity at +10 (CB-1); ignores site: for Jobvite (LR-2); pass 3: S1: fixture pin bing_site_jobvite (10/10 records with title and link, was 0: multi-route from duplicate anchors); not run live (robots.txt disallows /search) |
| CT-PH-004 | DuckDuckGo HTML results list | DuckDuckGo HTML (K); DuckDuckGo lite (K); Brave Search (K) | `[?]` | T-008 | L | no AA evidence; engine not in resources/engines; pass 2: O: L03 html.duckduckgo.com 403 to the cloud client; owner environment untested |
| CT-PH-005 | Google jobs vertical (udm=8): cards open a side panel, no followable URL on the card | Google jobs (R); LinkedIn split pane (K); Indeed side panel (K) | `[~]` | T-008/009 DEFERRED state; acts: CardActivator + PageActionService.click | L | R: CB-9 resolved=0; ADR-020 chose web form for site search; pass 3: [ ] -> [~] (code: CardActivator through the PageActionService click ladder, pinned in tests/adapters/test_card_activation.py; no live proof) |
| CT-PH-006 | LinkedIn public (logged-out) job list: cards with title link, company, place, age | LinkedIn (O cloud: L43); ZipRecruiter (K); Glassdoor (K) | `[~]` | T-008/009 | L | K only; authwall after a few pages (R: 2026-10-07); pass 2: O: L43 guest list loads (cloud) although robots.txt disallows all paths (CT-Q-026); pass 3: [ ] -> [~] (S1: fixture pin linkedin_guest_jobs (records resolved); 48/48 on the full specimen; guest view supported (CT-Q-030 ruled)) |
| CT-PH-007 | LinkedIn logged-in search: split pane, infinite scroll, virtualized rows | LinkedIn jobs (K); Indeed (K); Glassdoor (K) | `[?]` | T-008 + ALG-018 | L | CT-Q-006 first; R-20 recycled-row risk |
| CT-PH-008 | Job board list with detected cards but no identity or titles | Indeed (R); ZipRecruiter (K); Glassdoor (K) | `[ ]` | T-008/009 | L | R: CB-1 Indeed 4 cards marker_frac 0.00, no titles |
| CT-PH-009 | Feed: posts announcing openings (text, hashtags, contact by message/email, link in comments) | Hacker News (O cloud: L37 P19); LinkedIn feed (K); X/Twitter hiring posts (K) | `[ ]` | T-007 feed family + T-009 | L | CT-Q-006; FR-031; no AA code |
| CT-PH-150 | Search engine answers a data-centre client with a challenge or block page instead of results | Google (O cloud: L01); DuckDuckGo HTML (O cloud: L03); Brave Search (O cloud: L04); Mojeek (O cloud: L05) | `[~]` | T-006 | R+L | O: 4 of 5 engines refused (L01 Google sorry+reCAPTCHA, L03 DDG 403, L04 Brave 429 bot check, L05 Mojeek 403); A: today's verdict recognises only L01 (verdict_baseline) |
| CT-PH-151 | Search engine returns results but silently ignores a site: restriction | Bing (R); Bing (O cloud: L02) | `[ ]` | T-008 + ADR-021 verifier | L | O: L02 Bing top hits coursera.org etc. for site:jobs.jobvite.com (cloud), matches LR-2 (owner) |
| CT-PH-152 | Whole board rendered at once in one client-rendered page (hundreds of rows, facet counts beside the list) | Ashby (O cloud: C15 L18 L19 …) | `[~]` | T-008 + T-016 | U+L | O: Ashby 803/172/31 rows; facet counts 'Applied AI (117)' are not records |
| CT-PH-153 | List rendered as a plain table (one row per posting, columns for title and place) | Jobvite (O cloud: L07); Oracle Taleo (O cloud: L28) | `[~]` | T-008 (m>1 windows) | U+L | O: Jobvite /search table, Taleo results table; Bible 9.4 card guard accepts tr but area floor varies; pass 3: [ ] -> [~] (S1: table rows titled by their link (anchor-name title) pinned; Jobvite 106/106 live cloud) |
| CT-PH-154 | Total-count text beside the list ('1 - 25 of 573', '2,232 positions', '30408 results') usable as a completeness check | Oracle Taleo (O cloud: L28); DirectEmployers (O cloud: L34); Dice (O cloud: L45); Tencent (O cloud: P23) | `[ ]` | T-009 + FR-107 | U+L | O: four sources print a total; none is read today |
| CT-PH-155 | List inside an iframe while the outer page is a near-empty shell | iCIMS (O cloud: L13 L14 P24) | `[ ]` | T-002 frames + T-004 | U+L | O: iCIMS outer page 52-502 chars; list only in frame; A: extractor reaches one frame level, count-mismatch skips all frames |
| CT-PH-156 | List built from web components with content in open shadow roots | SmartRecruiters (O cloud: L21 L23); Arbeitsagentur (O cloud: L38) | `[ ]` | T-002 shadow capability | U+L | O: 127, 46 and 11 shadow hosts; A: AA's extractor returns 0 anchors from shadow content (js_extractor_probe) |
| CT-PH-157 | Split pane: list on one side, selected posting on the other, selection in a URL parameter | Eightfold (O cloud: C16 L29 L30); LinkedIn split pane (K) | `[ ]` | T-007 + T-016 | L | O: Eightfold pid= selects the posting; owner state 2 (L54) blocked for a guest |
| CT-PH-158 | Same list copied on several hosts with different counts at the same moment (aggregator partner sites) | DirectEmployers (O cloud: C19 C20 C21 …) | `[ ]` | FR-108 dedup | L | O: DirectEmployers dejobs.org and two partner hosts, all served with HTTP 404 and real content |
| CT-PH-159 | Careers page whose record groups are sub-pages or database views of a general page tool (Notion) | Notion (O cloud: L60 L61 N60) | `[ ]` | T-007 + T-008 | L | O: messold two lists are links to /p/ sub-pages; database view with Open/Gallery/Closed tabs |
| CT-PH-160 | Free-text hiring thread: one record per top-level comment, replies nested, 'More' pagination | Hacker News (O cloud: C13 L37 P19) | `[ ]` | T-007 feed family | L | O: HN 'Who is hiring? (November 2026)', 95k chars |
| CT-PH-161 | Infinite scroll that keeps growing with no end marker | Remote OK (O cloud: C14) | `[~]` | T-016 + caps; acts: Scroller feed scroll + Bible 30.1 page cap | U+L | see C14 scroll record; cap is Bible 30.1 MAX_PAGES |

## Phenomena: careers pages and list movement

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-PH-010 | Lever board: postings grouped under team headings | Jobvite (R); Jobvite (O cloud: L06 L09); Lever (K) | `[~]` | T-008 (per-section runs) | U+L | R: Jobvite is the LR-1 target; descriptor resources/ats/lever.yaml |
| CT-PH-011 | Greenhouse board: rows under department headings, old and new board layouts | Stripe careers (company site) (O cloud: L15); Databricks careers (company site) (O cloud: L16); Figma careers (company site) (O cloud: L17) | `[~]` | T-008 | U+L | descriptor greenhouse.yaml; no live structure evidence |
| CT-PH-012 | Jobvite careers list reached through Google site: restriction | Jobvite via Google (R); Jobvite (O cloud: L06 L07 L08 …); Lever via Google (K) | `[~]` | T-008/009 | L | R: LR-1 six cards dropped 'no title', eight with no eligible link; pass 3: [ ] -> [~] (S1: Jobvite boards read directly: fixture pin jobvite_nutanix; live cloud 106/106 and 15/15; the Google leg is unproven until the owner's Google fixture or run) |
| CT-PH-013 | Ashby / SmartRecruiters / Workable / BambooHR boards (client-rendered lists) | Ashby (O cloud: L18 L19 L20); SmartRecruiters (O cloud: L21 L23); Bosch careers (company site) (O cloud: L22) | `[~]` | T-008 + T-016 settle | L | descriptors exist; rendering evidence none; pass 3: [ ] -> [~] (S1: fixture pin ashby_linear; live cloud Ashby 31/31 and 149/149, SmartRecruiters 96/96) |
| CT-PH-014 | Workday job list: React list, filters, 'load more' | Workday (O cloud: L10 L11 L12); iCIMS (O cloud: L13); Oracle Recruiting Cloud (O cloud: L27); Oracle Taleo (O cloud: L28); Eightfold (O cloud: L29 L30); NEOGOV (O cloud: L31 L32 L33) | `[~]` | T-008 + ALG-016 | L | descriptor workday.yaml; pass 3: [ ] -> [~] (S1: live cloud Workday NVIDIA 20/20 (head 0/20, defect 4)) |
| CT-PH-015 | Records broken by headings or ad rows (runs per section; allow_gap) | Bing ads (R); Google widgets (R); Jobvite (O cloud: L06 L09); Databricks careers (company site) (O cloud: L16); Notion (O cloud: L60 L61 N60) | `[ ]` | ALG-002 | P+U | design only |
| CT-PH-016 | Numbered / next-previous pagination | Tencent (O cloud: C12 P23); Eightfold (O cloud: C16); Amazon Jobs (O cloud: C18); Workday (O cloud: L10); Oracle Taleo (O cloud: L28); Arbeitsagentur (O cloud: L38); StepStone (O cloud: L39); Dice (O cloud: L45) | `[~]` | T-016; acts: VerifiedPageAdvancer (URL template, rel=next, structural, numbered), pinned | U+L | page_advancer.py exists; not under the toolkit |
| CT-PH-017 | 'Load more' / 'show more jobs' button | Workday (K); LinkedIn public (K); Ashby (K) | `[~]` | T-016; acts: VerifiedPageAdvancer load-more rung, growth-verified, pinned | U+L | page_advancer.py; unverified per site |
| CT-PH-018 | Infinite scroll with growth detection and stop rule | Google jobs (R); Remote OK (O cloud: C14); LinkedIn (K) | `[~]` | T-016; acts: Scroller.reveal_page / scroll_container (feed scroll), pinned | U+L | R: harvest scroll loop exists; teleport scroll R-19; pass 2: O: C14 RemoteOK grew for 6 rounds (anchors 1,033 to 6,554) with no end marker |
| CT-PH-019 | Virtualized / recycled rows (R-20): node handles point at a different job after scroll | Ashby (O cloud: C15); LinkedIn (K); Workday (K) | `[ ]` | ALG-018 | U+L | R: R-20 scoped, not built; pass 2: O: no virtualised list found on Ashby (C15, 808 rows at once), Eightfold (C16) or RemoteOK (C14); still unmeasured where it was reported (LinkedIn logged in) |

## Phenomena: job descriptions

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-PH-020 | JD with JSON-LD JobPosting | Remote OK (O cloud: C14); Ashby (O cloud: F02 F03 F04 …); Workday (O cloud: F05 F06 L49 …); Eightfold (O cloud: F12 P17); Jobvite (O cloud: P02 P03); Oracle Recruiting Cloud (O cloud: P15); Arbeitsagentur (O cloud: P20); StepStone (O cloud: P21); Dice (O cloud: P22) | `[~]` | T-017 | U+L | page_assessment.py checks JSON-LD presence only |
| CT-PH-021 | JD without structured data: sections by headings | Greenhouse (O cloud: F09 P08); Workday (O cloud: L49); iCIMS (O cloud: L51); Notion (O cloud: L59 N59); Jobvite (O cloud: P01); SmartRecruiters (O cloud: P13 P14); Oracle Taleo (O cloud: P16); DirectEmployers (O cloud: P18 P25) | `[~]` | T-009 | U+L | vetting reads page text |
| CT-PH-022 | JD embedded in an iframe or loaded after render | iCIMS (O cloud: L51); LinkedIn (O cloud: L53 L55); Jobvite (O cloud: P01 P02 P03); Eightfold (O cloud: P17) | `[ ]` | T-004 frames | L | defect 6; iframe traversal not under toolkit |
| CT-PH-023 | Closed / expired / filled posting, including expired-posting redirects | LinkedIn (R); Greenhouse (O cloud: L46 P26); Stripe careers (company site) (O cloud: L47); Oracle Recruiting Cloud (O cloud: L48); Arbeitsagentur (O cloud: L52) | `[~]` | T-006 | U+L | R: 2026-10-07 expired redirect treated usable; verdict kinds CLOSED exist; pass 2: A (cloud replay): today's verdict returns CLOSED on 0 of 4 closed or missing postings (L46, L47, L48, L52) |
| CT-PH-024 | Apply entry: button opens same page, new tab, modal or external ATS | LinkedIn (O cloud: L53 L55); Notion (O cloud: L59 L62 N59 …); Jobvite (O cloud: P01); Workday (O cloud: P04); Greenhouse (O cloud: P08); Ashby (O cloud: P10); SmartRecruiters (O cloud: P13); Oracle Recruiting Cloud (O cloud: P15); Eightfold (O cloud: P17) | `[~]` | T-009 + T-016; acts: PageActionService.click; ApplicationsWorkflow._navigate_to_application | U+L | R: tab switch exists; redirect-to-list event in Bible 8.3; pass 2: O: apply is a link (P01, P04, P10), a button with no target (P15, L53, P08), a mailto (P01) or another host (P13) |
| CT-PH-162 | Structured data and visible page disagree (JSON-LD on an empty page; visible title differs from URL slug) | Workday (O cloud: L49 L50) | `[ ]` | T-017 + T-009 | U+L | O: L50 JSON-LD JobPosting with 0 visible chars; L49 slug 'Mid-Level-Senior' vs title 'Lead'; A: verdict says JOB_DESCRIPTION 0.8 for L50 |
| CT-PH-163 | Same vendor, some tenants publish JSON-LD and others do not | Jobvite (O cloud: P01 P02 P03) | `[~]` | T-017 + T-009 | U+L | O: Jobvite nutanix none; gigamon, kymanox JobPosting |
| CT-PH-164 | Posting text inside shadow roots (light-DOM text is a small fraction) | SmartRecruiters (O cloud: P13 P14); Arbeitsagentur (O cloud: P20) | `[ ]` | T-002 shadow capability | U+L | O: Arbeitsagentur 627 light-DOM chars with 11 shadow hosts; SmartRecruiters 8-10 |
| CT-PH-165 | Posting in a language different from the site's chrome | SmartRecruiters (O cloud: P14); Arbeitsagentur (O cloud: P20); StepStone (O cloud: P21) | `[~]` | T-003 + FR-115 | U+L | O: Spanish posting on an English marketplace; German postings |
| CT-PH-166 | Several locations in one posting; location also inside the URL path | Workday (O cloud: L49 P04); Ashby (O cloud: P11) | `[~]` | T-009 | U+L | O: Ashby 'New York, NY (HQ); San Francisco, CA'; Workday location in path |
| CT-PH-167 | Pay in structured data on some postings, only in prose or absent on others | Jobvite (O cloud: P02); Ashby (O cloud: P10 P12); Dice (O cloud: P22) | `[~]` | T-017 + T-009 | U+L | O: baseSalary present on P02, P10, P22; absent on P12, P04 |
| CT-PH-168 | Closing date published (validThrough) or age shown relatively ('1 week ago') | LinkedIn (O cloud: L53); Oracle Recruiting Cloud (O cloud: P15); Eightfold (O cloud: P17) | `[ ]` | T-017 + T-003 | U+L | O: Eightfold validThrough 2027-05-01; LinkedIn '1 week ago' |
| CT-PH-169 | Description and application form on one page | Greenhouse (O cloud: F09 P08); Google Forms (O cloud: L57) | `[~]` | T-007 + T-010 | U+L | O: Greenhouse posting pages carry the full form; embedded Google Form carries its own description |
| CT-PH-170 | Apply control is a button with no target (destination unknowable without pressing) | LinkedIn (O cloud: L53 L55); Greenhouse (O cloud: P08); Oracle Recruiting Cloud (O cloud: P15) | `[?]` | T-009 + T-016 | L | O: Oracle APPLY NOW, LinkedIn Apply, Greenhouse Apply buttons have no href |
| CT-PH-171 | Apply target on another host or a mailto: link ('Apply Later') | Eightfold (O cloud: L29); Jobvite (O cloud: P01); SmartRecruiters (O cloud: P13) | `[ ]` | FR-114 | U+L | O: SmartRecruiters -> smartr.me; Jobvite mailto 'Apply Later' |
| CT-PH-172 | Non-standard action label or assessment required before the application ('Start Test') | owner report (R); Notion (O cloud: L59) | `[?]` | T-009 lexicon + HITL | L | O: control absent for a signed-out headless client; owner saw it signed in |
| CT-PH-173 | 'Applications paused' notice revealed only after pressing Apply | owner report (R); Notion (O cloud: L62 N62) | `[?]` | T-006 phrases | L | O: no Apply control in guest DOM, nothing pressed; signalling unobserved |

## Phenomena: forms, controls and widgets

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-PH-030 | Single-page form in a form element | Jobvite (O cloud: F01 F14); Ashby (O cloud: F02 F03 F04); Greenhouse (O cloud: F09 P08); Oracle Recruiting Cloud (O cloud: F10); Oracle Taleo (O cloud: F11); Eightfold (O cloud: F12) | `[~]` | T-010/011/012 | U+L | WIRED; mock ATS fixtures; 0 live submissions (STATUS) |
| CT-PH-031 | Multi-step wizard with next/back and step indicator | Jobvite (O cloud: F01 F14); Oracle Recruiting Cloud (O cloud: F10); Workday (K) | `[~]` | T-010; acts: ApplicationsWorkflow._navigate_multi_page_flow; DOMObserver states | U+L | ats descriptors multi_step flag |
| CT-PH-032 | Formless single-page-app form (no form element) | Ashby (O cloud: F02 F03 F04); Google Forms (O cloud: L57); Notion (O cloud: L58 N58) | `[ ]` | ALG-007 | U+L | design only; pass 2: A: Ashby SPA forms F02-F04 are judged CAPTCHA_BLOCK by today's verdict (invisible reCAPTCHA, no <form>) |
| CT-PH-033 | Text/email/tel/url/number/password inputs with autofill tokens | Greenhouse (O cloud: F09 P08); Oracle Recruiting Cloud (O cloud: F10); Lever (K) | `[~]` | T-012; acts: TextInputHandler / Typer.type_text, pinned (test_handler_protocol) | U+L | classifier WIRED |
| CT-PH-034 | Native select, multiple select, datalist | Jobvite (O cloud: F01 F14); Greenhouse (K); Lever (K) | `[~]` | T-014/012; acts: SelectInputHandler / Typer.select_option, pinned | U+L | handlers/select.py WIRED |
| CT-PH-035 | Radio and checkbox groups with fieldset/legend or custom buttons | Ashby (O cloud: F02 F03 F04); Oracle Recruiting Cloud (O cloud: F10); Greenhouse (K) | `[~]` | T-011/014; acts: CheckableInputHandler / Typer.check_checkbox (browser pin) | U+L | partial |
| CT-PH-036 | Textarea, contenteditable and rich text editors | Ashby (O cloud: F02 F03 F04); Greenhouse (O cloud: F09 P08); Oracle Recruiting Cloud (O cloud: F10); Eightfold (O cloud: F12) | `[ ]` | T-014; acts: TextInputHandler handles contenteditable (no pin) | U+L | handlers/text.py covers inputs |
| CT-PH-037 | Date inputs: native, text with mask, custom pickers | Greenhouse (O cloud: F09); Workday (K); SmartRecruiters (K) | `[~]` | T-014; acts: DateInputHandler (three strategies; no pin) | U+L | handlers/date.py |
| CT-PH-038 | Resume upload: file input, drop zone, hidden input behind a button | Ashby (O cloud: F02 F03 F04); Greenhouse (O cloud: F09 P08); Lever (K) | `[~]` | T-014; acts: FileInputHandler (sets the file input directly), pinned | U+L | handlers/file.py |
| CT-PH-039 | Combobox with asynchronously loaded long option list (school list) | Ashby (O cloud: F02 F03); Greenhouse (O cloud: F09 P08); Oracle Recruiting Cloud (O cloud: F10); Eightfold (O cloud: F12) | `[ ]` | T-015; acts: SelectInputHandler combobox branch, pinned | U+L | owner example; ALG-015 |
| CT-PH-040 | Paged / virtualized listbox (aria-setsize, scroll-to-load) | Greenhouse (O cloud: F09 P08); Oracle Recruiting Cloud (O cloud: F10); Eightfold (O cloud: F12); Google Forms (O cloud: L57) | `[ ]` | T-015 | U+L | ALG-015 S2 |
| CT-PH-041 | Address autocomplete (third-party places widget) | Greenhouse (O cloud: P08); Workday (K); SmartRecruiters (K) | `[?]` | T-014 | L | iframe/overlay results; unknown per site |
| CT-PH-042 | Phone with country-code selector | Greenhouse (O cloud: F09 P08); Lever (K); Workable (K) | `[ ]` | T-014 | U+L | composite widget |
| CT-PH-043 | Repeating sections ('Add another' education/experience) | Ashby (O cloud: F02); Workday (K); iCIMS (K) | `[ ]` | ALG-002 reuse; acts: none (InteractionPlan can express it; no planner step) | U+L | design only |
| CT-PH-044 | Conditional fields (show-if) appearing after an answer | Greenhouse (K); Workday (K); Google Forms (K) | `[ ]` | T-016 diff + T-010 | U+L | design only |
| CT-PH-045 | Demographic/EEO questions with 'decline to answer' | Ashby (O cloud: F02); Greenhouse (O cloud: F09 P08); Eightfold (O cloud: F12) | `[~]` | T-012 | U+L | engine policy |
| CT-PH-046 | Consent checkbox, legal acknowledgement, e-signature field | Jobvite (O cloud: F01 F14); Ashby (O cloud: F02 F03); Oracle Recruiting Cloud (O cloud: F10); Eightfold (O cloud: F12) | `[?]` | T-014 | L | policy needed (CT-Q-009) |
| CT-PH-047 | Google Forms page (listitem blocks, required asterisk, multi-section) | Google Forms (O cloud: L56 L57); Typeform (K); Microsoft Forms (K) | `[?]` | T-010/011 | L (CONTROL form) | owner example; CT-Q-010; pass 2: O: embedded form L57 (listitems, '* Indicates required question', DIV Submit); direct link L56 needs a Google account; verdicts APPLICATION_FORM and LOGIN_REQUIRED |
| CT-PH-048 | LinkedIn Easy Apply modal (multi-step dialog) | LinkedIn (O cloud: L55); Indeed apply (K); Glassdoor apply (K) | `[?]` | T-010 + T-014 dialog; acts: PageActionService.click; DOMObserver | L | CT-Q-006; pass 2: O: guest view L55 Apply is a button with no href; the modal is unreachable signed out; structure [?] for owner runs |
| CT-PH-049 | Resume-parse prefill that rewrites fields after upload | Workday (K); Greenhouse (K); iCIMS (K) | `[ ]` | T-016 diff | U+L | human-owned rule applies |

## Phenomena: how 'required' is signalled

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-PH-050 | Asterisk (with or without a legend defining it) | Greenhouse (O cloud: F09 P08); Eightfold (O cloud: F12); Google Forms (O cloud: L57) | `[ ]` | ALG-010 | U+L | design |
| CT-PH-051 | required / aria-required attribute | Jobvite (O cloud: F01 F14); Ashby (O cloud: F02 F03 F04); Greenhouse (O cloud: F09 P08); Oracle Recruiting Cloud (O cloud: F10); Google Forms (O cloud: L57) | `[~]` | ALG-010 | U | is_required read; pass 2: [~] -> [ ] (A (stage 5, live, cloud): every field on Greenhouse, Ashby and Google Forms pages reported required (34/34, 40/40, 14/14), because _is_required tests get_attribute('required') is not None and get_attribute returns '' when absent); pass 3: [ ] -> [~] (presence test on the attribute tuple, unit-pinned (7701de8); no live proof yet) |
| CT-PH-052 | Note at top: 'all fields required' / '* indicates required' | Greenhouse (O cloud: F09 P08); Oracle Taleo (O cloud: F11); Google Forms (O cloud: L57) | `[ ]` | ALG-010 | U+L | design |
| CT-PH-053 | Optional marked instead of required ('(optional)') | Eightfold (O cloud: F12); Lever (K); Typeform (K) | `[ ]` | ALG-010 convention | U+L | design |
| CT-PH-054 | Colour only (red label or border) | Ashby (O cloud: F02); custom forms (K); Workday (K) | `[ ]` | ALG-010 + computed style | U+L | needs computed style (defect 5) |
| CT-PH-055 | Nothing until submit; then inline errors | Workday (K); Greenhouse (K); Ashby (K) | `[ ]` | ALG-011/012 | U+L | ADR-012 gate |
| CT-PH-056 | Error summary at top with links to fields | gov forms (K); Workday (K); iCIMS (K) | `[ ]` | ALG-012 | U+L | design |
| CT-PH-057 | Toast / snackbar errors that disappear | Ashby (K); LinkedIn Easy Apply (K); Workable (K) | `[ ]` | ALG-012 + settle | U+L | timing-sensitive |
| CT-PH-058 | Focus jumps to the first invalid field | Greenhouse (K); Lever (K); SmartRecruiters (K) | `[ ]` | ALG-012 | U+L | needs activeElement read |
| CT-PH-059 | Submit changes the page / re-renders the form (handles go stale) | Workday (K); Ashby (K); iCIMS (K) | `[ ]` | T-016 epoch | U+L | epoch rule |

## Phenomena: accounts and authentication

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-PH-060 | Login wall before content | LinkedIn authwall (R); iCIMS (O cloud: F07); Oracle Recruiting Cloud (O cloud: F10); Oracle Taleo (O cloud: F11); Eightfold (O cloud: F12); Google Forms (O cloud: L56) | `[~]` | T-006 | U+L | R: LOGIN_REQUIRED [LIVE]; 2026-10-07 nine revisits |
| CT-PH-061 | Account creation required to apply (Workday-style) | Workday (O cloud: F05 F06); iCIMS (O cloud: F07); Oracle Taleo (O cloud: F11); Eightfold (O cloud: F12) | `[ ]` | T-006/010 | L | CT-Q-014; pass 2: [?] -> [ ] (O: account walls at apply on Workday F05/F06, iCIMS F07, Taleo F11, Eightfold F12; today's verdict recognises only F07) |
| CT-PH-062 | 'Sign in with Google/LinkedIn/Apple' pop-up window (OAuth) | Eightfold (O cloud: F12); Workday (K); Indeed (K) | `[ ]` | ALG-025; acts: ApprovalGate hand-off (HITL) | U+L | CT-Q-013; owner example |
| CT-PH-063 | Email verification link or one-time code | Oracle Recruiting Cloud (O cloud: F10); Workday (K); Ashby (K) | `[ ]` | T-006 hand-off | L | human step; pass 2: [?] -> [ ] (O: Oracle email-first screen F10; today's verdict calls it APPLICATION_FORM, so AA would treat an identity step as the form) |
| CT-PH-064 | Passkey / WebAuthn prompt | Google (K); LinkedIn (K); Microsoft (K) | `[?]` | hand-off | L | cannot be automated |
| CT-PH-174 | Apply step redirects to the vendor's sign-in page (account required) | Workday (O cloud: F05 F06); iCIMS (O cloud: F07); Oracle Taleo (O cloud: F11); Eightfold (O cloud: F12) | `[~]` | T-006 + FR-127 | L | O: Workday /apply, iCIMS mode=apply -> /login, Taleo -> accessmanagement/login.jsf |
| CT-PH-175 | Email-first verification before any form | Oracle Recruiting Cloud (O cloud: F10) | `[?]` | T-006 + FR-127 | L | see F10 |
| CT-PH-176 | Third-party form requires its own provider account (Google Forms sign-in) | Google Forms (O cloud: L56) | `[~]` | T-006 | L | O: docs.google.com form redirects to accounts.google.com; A: verdict LOGIN_REQUIRED |
| CT-PH-177 | Sign-in widgets embedded on a public posting (Google identity buttons, Microsoft login iframe) | LinkedIn (O cloud: L53 L55); Eightfold (O cloud: P17) | `[ ]` | T-006 | U+L | O: LinkedIn gsi/button iframes x8; Microsoft login.microsoftonline.com iframe; not a wall |
| CT-PH-178 | Legacy portal shows 'You are not signed in' on public pages | Oracle Taleo (O cloud: L28 P16) | `[ ]` | T-006 | U+L | O: Taleo banner; content still public |
| CT-PH-179 | One-click apply on a separate host that refuses a guest (403/404) | SmartRecruiters (O cloud: F08); SmartRecruiters oneclick (O cloud: F13) | `[?]` | T-006 + FR-114 | L | O: SmartRecruiters oneclick-ui 403; smartr.me 404 |
| CT-PH-180 | Owner-only view: a page that renders differently signed in (control present) and signed out (control absent) | LinkedIn (O cloud: L54 L55); Notion (O cloud: L59 L62) | `[?]` | T-006 + T-016 | L | O: Notion buttons absent, LinkedIn Easy Apply modal unreachable signed out |

## Phenomena: defences and obstacles

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-PH-070 | reCAPTCHA v2 challenge vs v3 invisible badge | ATS pages (R); LinkedIn (R); Google (O cloud: L01); Greenhouse (O cloud: P08); Eightfold (O cloud: P17) | `[~]` | T-006; acts: ApplicationsWorkflow._pause_for_challenge (in-place pause) | U+L | R: 20/20 on triage; js_variables must be empty; pass 2: A: invisible reCAPTCHA judged gated on Ashby F02-F04 but embedded on Greenhouse P08/F09 and Eightfold P17 |
| CT-PH-071 | hCaptcha and Cloudflare Turnstile | iCIMS (O cloud: F07); Oracle Recruiting Cloud (O cloud: F10); hCaptcha demo (K) | `[~]` | T-006 | U+L | vendor annotations only; pass 2: O: hCaptcha frames beside the iCIMS login (F07) and the Oracle email step (F10) |
| CT-PH-072 | Arkose/FunCaptcha, GeeTest | LinkedIn (K); Indeed (K); Glassdoor (K) | `[?]` | T-006 | L | no signature yet |
| CT-PH-073 | Interstitial bot walls (Cloudflare, Akamai, HUMAN, DataDome) | Work.ua (Ukrainian) (O cloud: C08); We Work Remotely (O cloud: C17); SmartRecruiters (O cloud: F08); Bayt (O cloud: L40); Glassdoor (O cloud: L44); LinkedIn (O cloud: L53 L55) | `[~]` | T-006 | U+L | vendor annotations; handling is bench/pause; pass 2: A: recognised Cloudflare/DataDome pages L40, L44, C08, C17, F08; plain block pages L03, L05, L42, C02, C10 judged UNKNOWN |
| CT-PH-074 | Search-engine 'unusual traffic' page | Google /sorry (R); Google (O cloud: L01); Bing (K) | `[~]` | T-006 | U+L | R: LR-8, benched (ADR-020); pass 2: A: Google /sorry/ recognised (L01) |
| CT-PH-075 | Rate limit (429, Retry-After, soft throttle) | Workable (O cloud: L24 L25 L26); Google (K); LinkedIn (K) | `[~]` | T-006 + pacing | U+L | HostPacer WIRED; pass 2: A: Workable 429 (L24-L26) judged UNKNOWN |
| CT-PH-076 | Silent thinning of results after suspicion | Google (R); Bing (R); Indeed (R) | `[~]` | degradation detector | U+L | R: baseline guard LIVE path; read live today |
| CT-PH-077 | Honeypot fields (hidden, off-screen, unlabelled, trap names) | Bing (O cloud: L02); Stripe careers (company site) (O cloud: L15); Eightfold (O cloud: L29) | `[~]` | ALG-013/014 | P+U | WIRED; entropy false-positive risk; pass 2: A: false positives on address2, attestation, latest_employer, extracurricular, email_verification_code, contest_entry; RTL label and label 70 px above also flagged; stage 5 (live, cloud): flagged on 13 of 34, 7 of 40 and 2 of 14 controls of real forms |
| CT-PH-078 | Time-based traps and JS-issued tokens | custom forms (K); WordPress forms (K); ATS (K) | `[ ]` | pacing profile | L | not visible statically |
| CT-PH-079 | DOM obfuscation: hashed classes, shuffled order, canvas text, CSS content, zero-width characters | Google (R); We Work Remotely (O cloud: C17); Workday (O cloud: F05 F06 L10 …); Bayt (O cloud: L40) | `[~]` | T-003/008 | U+L | R: class rotation in Bible |

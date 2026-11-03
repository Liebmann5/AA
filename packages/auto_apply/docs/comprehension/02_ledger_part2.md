---
title: "Page Comprehension Toolkit: Ledger Part 2"
status: needs-review
last_verified: 2026-11-02
verified_against: "7701de8 + S1 reply files (pass 3)"
audience: contributors
---

# Master capability ledger, part 2 of 3

Part 2 of 3: browser surfaces, page states, text, environments, future capabilities, edge cases. Rendering of [02_ledger_part2.yaml](02_ledger_part2.yaml); the summary and the other parts are in [02_ledger.md](02_ledger.md).

**Status legend.** `[x]` proven live on three independent sources by AA's own runs · `[~]` partial: code and/or fixture evidence, no three-source live proof · `[ ]` not capable · `[?]` unknown: evidence recorded, a human decides. **No row is `[x]`**: no built tool has been proven by AA's own live runs on three sources. Pass 2 observed pages live from a data centre (`cloud`); those observations are evidence for the design, never proof of AA's behaviour.

**Source tags.** **O** observed live in pass 2, environment `cloud`, with specimen IDs (pass-2 observations; the archive was not retained, and each row records what was observed; [08](08_evidence_and_research.md) s9) · **R** recorded in AA's own evidence (environment `owner` unless stated) · **K** recalled, unverified. Tool column: `T-nnn` is `CT-T-nnn`, `ALG-nnn` is `CT-ALG-nnn`. Verification codes: U unit pin on fixture · P property test · R replay · L live run · M measurement · A analysis · X experiment.

## Phenomena: browser surfaces and transitions

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-PH-080 | Cross-origin iframe content (embedded ATS, CAPTCHA, payment-style widgets) | reCAPTCHA (R); Eightfold (O cloud: C16 F12 P17); Ashby (O cloud: F02 F03 F04); iCIMS (O cloud: F07 L13 L14 …); Greenhouse (O cloud: F09 P08); Figma careers (company site) (O cloud: L17); Notion (O cloud: L58 N58); Oracle Taleo (O cloud: P16) | `[ ]` | T-001/004 | U+L | defect 6; pass 2: O: lists and postings only in frames (L13, L14, L51); nested frames depth 3 (L17); A: extractor sees one frame level |
| CT-PH-081 | Open shadow DOM | JobKorea (Korean) (O cloud: C06); SmartRecruiters (O cloud: L21 L23 P13 …); Arbeitsagentur (O cloud: L38 P20); Dice (O cloud: P22); iCIMS (O cloud: P24) | `[ ]` | T-001 SHADOW_PIERCING | U+L | defect 6; pass 2: O: 127/46/11 shadow hosts (L21, L23, L38); A: AA extractor returns no shadow content |
| CT-PH-082 | Closed shadow DOM | embedded widgets (K); video players (K); payment widgets (K) | `[?]` | protocol capability | X | script cannot reach; protocol may |
| CT-PH-083 | Click opens a new tab; return to working tab | Google results (R); AllJobs (Hebrew) (O cloud: C01); 51job (Chinese) (O cloud: C04); e-aidem (Japanese) (O cloud: C05); JobKorea (Korean) (O cloud: C06); Habr Career (Russian) (O cloud: C07); Remote OK (O cloud: C14); Ashby (O cloud: C15 F02 F03 …); Eightfold (O cloud: C16 F12 L29 …); We Work Remotely (O cloud: C17); Amazon Jobs (O cloud: C18); DirectEmployers (O cloud: C19 C20 C21 …); Jobvite (O cloud: F01 L06 L07 …); Workday (O cloud: F05 F06 L10 …); iCIMS (O cloud: F07 L13 L14 …); Greenhouse (O cloud: F09 L46 P08); Oracle Recruiting Cloud (O cloud: F10 L27 L48 …); Bing (O cloud: L02); Brave Search (O cloud: L04); Stripe careers (company site) (O cloud: L15); Databricks careers (company site) (O cloud: L16); Figma careers (company site) (O cloud: L17); SmartRecruiters (O cloud: L21 L23 P13 …); Bosch careers (company site) (O cloud: L22); NEOGOV (O cloud: L31 L32 L33); StepStone (O cloud: L39 P21); Bayt (O cloud: L40); LinkedIn (O cloud: L43 L53 L54 …); Dice (O cloud: L45 P22); Google Forms (O cloud: L56 L57); Notion (O cloud: L60 L61 N60); Arbeitsagentur (O cloud: P20) | `[~]` | T-016; acts: existing tab handling in card activation; ADR-022 decision 4 planned | U+L | R: context_manager.switch_to_new_tab |
| CT-PH-084 | window.open pop-up (OAuth, share, print) | OAuth (K); Workday (K); LinkedIn (K) | `[ ]` | ALG-025 | U+L | owner example |
| CT-PH-085 | JS dialogs: alert, confirm, prompt, beforeunload | custom forms (K); Workday (K); Indeed (K) | `[?]` | T-001 WINDOW_EVENTS; acts: none | L | unhandled dialog fails every command |
| CT-PH-086 | Downloads, mailto/tel links, PDF viewer, about:blank | AllJobs (Hebrew) (O cloud: C01); 51job (Chinese) (O cloud: C04); Hacker News (O cloud: C13 L37 P19); Remote OK (O cloud: C14); DirectEmployers (O cloud: C21 L36); Ashby (O cloud: F02 P10); Oracle Recruiting Cloud (O cloud: F10); Oracle Taleo (O cloud: F11 L28 P16); DuckDuckGo HTML (O cloud: L03); Stripe careers (company site) (O cloud: L15 L47); Figma careers (company site) (O cloud: L17); Workable (O cloud: L24 L25 L26); NEOGOV (O cloud: L31 L32 L33); Workday (O cloud: L49 P05); Google Forms (O cloud: L57); Jobvite (O cloud: P01 P02 P03); Greenhouse (O cloud: P08); SmartRecruiters (O cloud: P13 P14) | `[ ]` | T-006 kinds | U+L | ADR-022 edge cases |
| CT-PH-087 | SPA navigation: URL changes without load; content changes without URL | Eightfold (O cloud: L29 L30); Workday (K); LinkedIn (K) | `[ ]` | T-016 | U+L | ADR-022 open question 2 |
| CT-PH-088 | Back/forward cache restores stale content | Chrome (K); Firefox (K); Edge (K) | `[ ]` | T-016 epoch | X | ADR-022 edge case |
| CT-PH-089 | Redirect chains: 3xx, meta refresh, script redirect | Google wrappers (R); expired postings (R); DirectEmployers (O cloud: C20 C21); iCIMS (O cloud: F07); Oracle Taleo (O cloud: F11); Eightfold (O cloud: L29); Greenhouse (O cloud: P08) | `[~]` | T-016 | U+L | R: redirect handling Bible 11.4 |

## Phenomena: walls, error pages and page states

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-PH-090 | Cookie/consent banner or wall (CMP overlays) | DirectEmployers (O cloud: C21); Workday (O cloud: F05 F06 L11 …); Jobvite (O cloud: F14); NEOGOV (O cloud: L31 L32 L33) | `[?]` | T-006 consent kind; acts: none (dismissal only per user policy) | L | policy: dismiss per user setting; pass 2: O: consent or privacy overlays on L11, L12, P05, P06, L31 |
| CT-PH-091 | Age gate, geo-block, region redirect | company sites (K); Indeed (K); Google (K) | `[?]` | T-006 | L | none |
| CT-PH-092 | Browser permission prompts (notifications, location) | LinkedIn (K); Indeed (K); Glassdoor (K) | `[?]` | T-001 | L | profile flags |
| CT-PH-093 | HTTP auth prompt, certificate warning, chrome-error page | intranet ATS (K); expired certs (K); offline (K) | `[?]` | T-006 | L | none |
| CT-PH-094 | 404/410/soft-404 and empty-results pages | DirectEmployers (O cloud: C19 C20 C21); Workday (O cloud: F05 F06); SmartRecruiters oneclick (O cloud: F13); Arbeitsagentur (O cloud: L52); iCIMS (O cloud: P24); Greenhouse (O cloud: P26) | `[~]` | T-006 | U+L | title-only 404 is debt (confidence 0.6); pass 2: A: 404-with-content L34-L36 and 410 L52 judged UNKNOWN; P26 ERROR_404 by title |
| CT-PH-095 | Session expiry mid-flow; CSRF token expiry | Workday (K); iCIMS (K); LinkedIn (K) | `[ ]` | ALG-024 | U+L | resume protocol |
| CT-PH-096 | Single-use or tokenised apply links | Stripe careers (company site) (O cloud: L47); Indeed (K); email links (K) | `[?]` | T-016 | L | none |
| CT-PH-097 | 'Already applied' state | Notion (O cloud: L62 N62); LinkedIn (K); Indeed (K) | `[~]` | T-006 | U+L | phrase tables, locale-keyed |
| CT-PH-098 | Confirmation / success page | Greenhouse (K); Lever (K); Workday (K) | `[~]` | T-006 | U+L | SUCCESS_PAGE kind; 0 live submissions; pass 2: A: a sign-in page (F12) judged SUCCESS_PAGE |
| CT-PH-099 | Sticky headers, floating chat widgets, overlays covering targets | AllJobs (Hebrew) (O cloud: C01); JobKorea (Korean) (O cloud: C06); Remote OK (O cloud: C14); Eightfold (O cloud: C16 F12 L29 …); Amazon Jobs (O cloud: C18); Ashby (O cloud: F02 F03 F04); Greenhouse (O cloud: F09 P08); Oracle Recruiting Cloud (O cloud: F10 L27 L48 …); Google (O cloud: L01); Workday (O cloud: L11 P05); NEOGOV (O cloud: L31 L32 L33); StepStone (O cloud: L39 P21); LinkedIn (O cloud: L43 L53 L55); Dice (O cloud: L45 P22); Notion (O cloud: L58 L59 L60 …) | `[~]` | ALG-013; acts: TargetProbe occlusion check, pinned (test_probe_real_browser) | U+L | ADR-012 occlusion guard DONE |

## Phenomena: content, encodings and languages

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-PH-100 | UTF-8 pages with correct declaration | AllJobs (Hebrew) (O cloud: C01); 51job (Chinese) (O cloud: C04); e-aidem (Japanese) (O cloud: C05); JobKorea (Korean) (O cloud: C06); Habr Career (Russian) (O cloud: C07); Tencent (O cloud: C12 P23); Hacker News (O cloud: C13 P19); Remote OK (O cloud: C14); Ashby (O cloud: C15 F02 F03 …); Eightfold (O cloud: C16 P17); Amazon Jobs (O cloud: C18); DirectEmployers (O cloud: C19 C20 C21 …); Jobvite (O cloud: F01 F14 L08 …); Greenhouse (O cloud: F09 P08); Workday (O cloud: L10 L11 L12 …); iCIMS (O cloud: L51); SmartRecruiters (O cloud: P13 P14); Oracle Recruiting Cloud (O cloud: P15); Oracle Taleo (O cloud: P16); Arbeitsagentur (O cloud: P20); StepStone (O cloud: P21); Dice (O cloud: P22) | `[~]` | T-003 | U | baseline |
| CT-PH-101 | Other or undeclared encodings in saved copies (windows-1252, Shift_JIS, GBK, EUC-KR, UTF-16 BOM) | Drushim (Hebrew) (O cloud: C02); Baitoru (Japanese) (O cloud: C10); legacy company sites (K) | `[ ]` | T-003 sniff | U | affects replay and copies; the DOM is already decoded; pass 2: O: 0 of 34 probed job hosts served non-UTF-8; block pages C02 (no declaration, windows-1252 fallback) and C10 (iso-8859-1) |
| CT-PH-102 | Mojibake in text or in AA's own output (console, CSV) | legacy sites (K); Windows console (K); Excel CSV (K) | `[ ]` | T-003 | U | suggest repair, never silent |
| CT-PH-103 | Unicode normalisation differences (NFC/NFKC) in labels and options | macOS-authored pages (K); school lists (K); names (K) | `[~]` | T-003 | P | locale_normalization.py partial |
| CT-PH-104 | Zero-width characters and confusable letters used to obfuscate | e-aidem (Japanese) (O cloud: C05); Habr Career (Russian) (O cloud: C07); Remote OK (O cloud: C14) | `[ ]` | T-003 | U | keys strip Cf; values untouched |
| CT-PH-105 | Right-to-left and bidirectional text; start side flips | AllJobs (Hebrew) (O cloud: C01); Arabic boards (K); Hebrew boards (K) | `[~]` | T-003 + ALG-008 | U | geometry assumes left=before; pass 2: O: C01 Hebrew dir=rtl; A: honeypot rule flags fields whose label is on the right; S4 (pass 4): RTL start side in pairing; real-browser RTL pin; no live RTL form yet |
| CT-PH-106 | CJK text: no spaces, full-width forms | 51job (Chinese) (O cloud: C04); e-aidem (Japanese) (O cloud: C05); JobKorea (Korean) (O cloud: C06); Tencent (O cloud: C12 L41 P23) | `[ ]` | T-003 bigrams | U | design |
| CT-PH-107 | Emoji and ZWJ sequences in titles | e-aidem (Japanese) (O cloud: C05); Habr Career (Russian) (O cloud: C07); Remote OK (O cloud: C14); NEOGOV (O cloud: L31 L32 L33) | `[ ]` | T-003 | U | grapheme limits stated |
| CT-PH-108 | Mixed scripts within one page or field | AllJobs (Hebrew) (O cloud: C01); 51job (Chinese) (O cloud: C04); e-aidem (Japanese) (O cloud: C05); JobKorea (Korean) (O cloud: C06); Habr Career (Russian) (O cloud: C07); Tencent (O cloud: C12 L41 P23); Remote OK (O cloud: C14) | `[ ]` | T-003 | U | design |
| CT-PH-109 | Language AA's lexicons do not cover (structure must still work) | AllJobs (Hebrew) (O cloud: C01); JobKorea (Korean) (O cloud: C06); Habr Career (Russian) (O cloud: C07); Work.ua (Ukrainian) (O cloud: C08); Arbeitsagentur (O cloud: L38 L52 P20); StepStone (O cloud: L39 P21); SmartRecruiters (O cloud: P14) | `[~]` | structure-only mode | U | NFR-021 |
| CT-PH-110 | Locale formats: dates, phone, currency, salary ranges, address order | e-aidem (Japanese) (O cloud: C05); Hacker News (O cloud: C13 P19); Remote OK (O cloud: C14); Ashby (O cloud: C15 F02 F03 …); Eightfold (O cloud: C16 L29 L30 …); Oracle Recruiting Cloud (O cloud: F10 P15); Bing (O cloud: L02); NEOGOV (O cloud: L31 L32 L33); Dice (O cloud: L45 P22); LinkedIn (O cloud: L53 L55); Notion (O cloud: L59 N59); Workday (O cloud: P06) | `[~]` | T-009/012 | U | salary_extraction.py |
| CT-PH-111 | Name order (family name first), honorifics, single-name fields | Japan forms (K); Spain forms (K); India forms (K) | `[ ]` | T-012 | U | profile mapping is an engine concern |
| CT-PH-112 | Browser translation overlay rewriting the DOM | Arbeitsagentur (O cloud: L38); Chrome translate (K); Edge translate (K) | `[ ]` | T-016 diff | X | changes text, not structure |
| CT-PH-113 | Very large pages (over 12,000 nodes) | Google (R); Remote OK (O cloud: C14); Databricks careers (company site) (O cloud: L16); Oracle Recruiting Cloud (O cloud: L27); Hacker News (O cloud: P19) | `[~]` | profiles | M | R: 1,513 nodes at 630 KB measured; node cap silent; pass 2: A: AA extractor 30k rows 16 s and 11 MB; today's verdict 2.8 s on C14 (cloud, 4-core Xeon) |
| CT-PH-114 | No results / spelling correction / 'did you mean' blocks | Google (K); Bing (K); Indeed (K) | `[ ]` | T-007 | U+L | must not be read as records |
| CT-PH-115 | Sponsored / promoted records | Google ads (R); Bing ads (R); 51job (Chinese) (O cloud: C04); StepStone (O cloud: L39); Dice (O cloud: L45) | `[~]` | url_evidence + ALG-003 | U+L | R: ad_leak in SERPStructure |
| CT-PH-116 | Generated answer / overview blocks above results | Google AI overview (K); Bing Copilot (K); DuckDuckGo AI (K) | `[?]` | T-007 | L | AI-era change; not in AA evidence |
| CT-PH-117 | Lazy-loaded content and images | e-aidem (Japanese) (O cloud: C05); JobKorea (Korean) (O cloud: C06); DirectEmployers (O cloud: C19 L34 P18); Bing (O cloud: L02); Workday (O cloud: L10 L50); Databricks careers (company site) (O cloud: L16); Figma careers (company site) (O cloud: L17); Bosch careers (company site) (O cloud: L22); Dice (O cloud: L45); Notion (O cloud: L61 L62 N62) | `[~]` | T-016 settle; acts: Scroller.reveal_page, pinned | U+L | scroll loop |
| CT-PH-118 | Hidden text for search engines or screen readers (visually hidden labels) | AllJobs (Hebrew) (O cloud: C01); JobKorea (Korean) (O cloud: C06); Habr Career (Russian) (O cloud: C07); Eightfold (O cloud: C16 L29 L30 …); Amazon Jobs (O cloud: C18); iCIMS (O cloud: F07 L13 L14 …); Greenhouse (O cloud: F09 L46 P08); Jobvite (O cloud: L06 L07 L08 …); Databricks careers (company site) (O cloud: L16); SmartRecruiters (O cloud: L21); NEOGOV (O cloud: L31 L32 L33); Arbeitsagentur (O cloud: L38 L52 P20); LinkedIn (O cloud: L43 L53 L55); Dice (O cloud: L45) | `[~]` | ALG-013 | U | visually-hidden is a label, not a trap |

## Platforms, browsers, access mechanisms, resource profiles, containers

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-PH-120 | Windows 10/11 (primary worst-case OS) | Windows (R); owner machine (R) | `[~]` | profiles | M | R: live runs on Windows |
| CT-PH-121 | macOS | macOS (K); Safari/WebKit (K); Chrome (K) | `[ ]` | profiles | L matrix | none |
| CT-PH-122 | Linux desktop and server | Linux (R); CI (R); Docker (R) | `[~]` | profiles | L matrix | R: docs gate runs under a virtual display |
| CT-PH-123 | Chrome / Chromium | Chrome (R); Chromium (K); Edge (K) | `[~]` | T-001 | L matrix | primary |
| CT-PH-124 | Microsoft Edge (installed, no admin) | Edge (K); Windows library PC (K); Chrome (K) | `[?]` | T-001 | L matrix | cascade candidate |
| CT-PH-125 | Firefox | Firefox (R); Gecko (K); LibreWolf (K) | `[~]` | T-001 | L matrix | R: fallback in LR-8 raises CAPTCHA |
| CT-PH-126 | WebKit via Playwright | Playwright WebKit (K); Safari (K); GNOME Web (K) | `[ ]` | T-001 | L matrix | none |
| CT-PH-127 | Access: Selenium classic | Selenium (R); chromedriver (R); geckodriver (R) | `[~]` | T-001 | contract suite | WIRED |
| CT-PH-128 | Access: Selenium BiDi | Selenium (K); Chrome BiDi (K); Firefox BiDi (K) | `[ ]` | T-001 | contract suite | none |
| CT-PH-129 | Access: Playwright (bundled or installed browsers) | Playwright (R); playwright_adapter (R); Chrome channel (K) | `[~]` | T-001 | contract suite | adapter exists |
| CT-PH-130 | Access: direct protocol (DOMSnapshot, AX, DOM) | CDP (R); aom_adapter (R); Chromium (K) | `[~]` | T-001 | contract suite | AX only |
| CT-PH-131 | Access: replay of a stored copy | replay (R); page copies (R); fixtures (R) | `[~]` | T-022 | R | LIVE for detectors |
| CT-PH-132 | Access: future AI browser or agent as an adapter | agent browsers (K); MCP browser tools (K); AI browsers (K) | `[ ]` | T-001 seam | contract suite | capability only |
| CT-PH-133 | Profile library: 2 GB, no admin, USB, duty cycled | Bible 1.1 (R); Philosophy (R); owner brief (R) | `[ ]` | T-021 | M | unmeasured |
| CT-PH-134 | Profile standard and workstation | owner machine (R); 12-core desktop (R); CI (R) | `[~]` | T-021 | M | R: 0.25-0.56 s per pass on 12-core |
| CT-PH-135 | Docker container (Dockerfile.test) | Docker (R); CI (R); dev container (K) | `[?]` | EnvFacts | M | image exists; footprint untested |
| CT-PH-136 | Virtual machine, remote desktop, cloud VM | VM (K); RDP (K); cloud VM (K) | `[?]` | EnvFacts | M | IP reputation outside toolkit |
| CT-PH-137 | Headless and virtual display (Xvfb) | Xvfb (R); new headless (K); old headless (K) | `[~]` | EnvFacts | M | R: gate under xvfb-run; pass 2: O: all pass-2 captures ran headless Chromium in a container |
| CT-PH-138 | No GPU; software rendering | SwiftShader (K); llvmpipe (K); CI (K) | `[?]` | EnvFacts | X | recorded not hidden; pass 2: O: all pass-2 captures rendered without a GPU; geometry not compared with the owner's machine |
| CT-PH-139 | Different fonts change geometry | Windows (K); Linux container (K); macOS (K) | `[ ]` | relative thresholds | U | font fingerprint in observation |

## Future capabilities

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-PH-140 | Public posting feeds / vendor job APIs as a Source Channel | Greenhouse board API (K); Lever postings API (K); SmartRecruiters posting API (K) | `[ ]` | seam: payload_kind | U | ADR-020 accepted, not built; CT-Q-011 |
| CT-PH-141 | ATS chatbot screening, assessments, video interviews | Notion (O cloud: L59 N59); HireVue (K); Paradox (K) | `[?]` | T-006 kind | L | human hand-off |
| CT-PH-142 | Ghost / AI-generated postings | LinkedIn (K); Indeed (K); Glassdoor (K) | `[?]` | Structured + signals | L | signals_taxonomy GJ |
| CT-PH-143 | Agent-facing page interfaces and machine-readable apply endpoints | emerging standards (K); site manifests (K); MCP-style tools (K) | `[ ]` | T-001/017 seam | A | GOAL; no committed design |
| CT-PH-144 | Post-submission outcome tracking (N-1): keep attempt_id + page_index join | AA N-1 (R); ATS emails (K); portals (K) | `[ ]` | Trace key | U | R: AA_TODO_ADDITIONS N-1 |
| CT-PH-145 | Secure document store (N-2) and file preview (N-3) for uploads | AA N-2 (R); AA N-3 (R); library PCs (R) | `[ ]` | engine | U | outside toolkit; seam named |
| CT-PH-146 | Plug-in tools and ATS adapters without core changes (pluggy) | Bible 22.2 (R); Bible 25.2 (R); ADR-008 (R) | `[ ]` | tool registry | U | registry swap by ID |
| CT-PH-147 | Optional model-based capability behind the finding contract | Bible 17 (R); Bible 22.2 (R); Philosophy (R) | `[ ]` | T-001 seam | A | never required |
| CT-PH-148 | Shared or borrowed device: per-session scoping, no residue | LR-9 (R); library PC (R); USB (R) | `[ ]` | outside toolkit | U | R: LR-9 queue not scoped |
| CT-PH-149 | Human phrasing learned from user edits | owner idea (R); AA N-3 (R); HITL (R) | `[ ]` | 08 human events | U | local only, consent |

## Phenomena: edge cases and adversity (12)

| ID | Item | Sources | Status | Tool | Verification | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| CT-PH-181 | Empty or never-rendering page (0 visible characters after the settle cap) | Workday (O cloud: F05 L50); iCIMS (O cloud: L14 P24) | `[ ]` | T-006 + T-016 | U+L | O: Adobe Workday posting 0 chars after 15 s; iCIMS shells |
| CT-PH-182 | List with exactly one record | small careers pages (K) | `[ ]` | ALG-002 (r_min=2) | U | A: run detection needs two members; a single card is missed |
| CT-PH-183 | Ten thousand or more sibling records | Remote OK (O cloud: C14); Ashby (O cloud: L18) | `[~]` | T-002 node cap + T-008 | M | A: AA extractor 10k rows 6.0 s and 3.7 MB JSON, 30k rows 16.1 s and 11.1 MB (cloud, 4-core Xeon) |
| CT-PH-184 | DOM deeper than the extraction cap | Oracle Recruiting Cloud (O cloud: L27); Notion (O cloud: L58 L61) | `[ ]` | T-002 truncation flag | U | O: depth 41, 35, 36; A: depth-60 link silently dropped, no flag (js_extractor_probe) |
| CT-PH-185 | Duplicate element IDs (label[for] and aria-labelledby ambiguous) | Bosch careers (company site) (O cloud: L22); StepStone (O cloud: L39); LinkedIn (O cloud: L43); Dice (O cloud: L45) | `[~]` | ALG-008 ladder | U | O: 8, 8, 10, 4 duplicated ids; S4 (pass 4): label[for] goes to the first element with the id; duplicates counted in the form record; real-browser pin |
| CT-PH-186 | Anchors with no href, or script-only links (role=link, data-href, onclick) | Bing (O cloud: L02); Jobvite (O cloud: L06); Oracle Taleo (O cloud: L28) | `[ ]` | ALG-004 | U | O: Taleo 38 anchors without href; A: extractor keeps the node but no destination; pass 3: S1: an anchor without href is never a candidate (pin); role=link and data-href candidates remain S2 |
| CT-PH-187 | Structurally identical cards (identical subtrees) | Jobvite (O cloud: L07) | `[~]` | T-004 ids | P | A: node-keyed build_parent_map collapses 50 identical cards to 3 keys; dom_segmentation is id-keyed (fixed); pass 3: S1: identical cards are separate records with one fate each (pins) |
| CT-PH-188 | Card markup differs per record by classes or optional children (badges, salary) | Google web (R); Ashby (O cloud: L18); LinkedIn (O cloud: L43) | `[ ]` | ALG-002 tolerance | P | R: exact hash splits groups (defect 1) |
| CT-PH-189 | Page content changes while it is read (counts or comments grow between observations) | Hacker News (O cloud: C13 P19); DirectEmployers (O cloud: L34) | `[ ]` | T-016 epoch | L | O: compare P19 and C13 (same thread, later) |
| CT-PH-190 | HTTP status contradicts the content (404 with a full list; 200 with 'no longer available') | DirectEmployers (O cloud: C19 C20 C21 …); Oracle Recruiting Cloud (O cloud: L48) | `[ ]` | T-006 | U+L | O: dejobs 404 + 2,170 jobs; JPMC 200 + closed notice; A: verdict UNKNOWN for all four |
| CT-PH-191 | Missing posting silently redirects to a search page with no message | Stripe careers (company site) (O cloud: L47) | `[ ]` | T-006 + T-016 | U+L | O: stripe/jobs/1 -> stripe.com/careers/search |
| CT-PH-192 | Vendor URL redirects to another host (company site, portal, locale page) | Stripe careers (company site) (O cloud: L15); Databricks careers (company site) (O cloud: L16); Figma careers (company site) (O cloud: L17); Bosch careers (company site) (O cloud: L22); Tencent (O cloud: L41) | `[~]` | T-016 + ADR-022 | L | O: five cross-host redirects |
| CT-PH-193 | Tenant path silently becomes a generic marketplace page | SmartRecruiters (O cloud: L21) | `[ ]` | T-006 | L | O: jobs.smartrecruiters.com/Visa -> / |
| CT-PH-194 | Rate limit on the first request of a session | Workable (O cloud: L24 L25 L26) | `[ ]` | T-006 | R | O: Workable 429 Cloudflare 1015; A: verdict UNKNOWN |
| CT-PH-195 | Block page with site chrome (looks like content) and no challenge markup | Drushim (Hebrew) (O cloud: C02); Baitoru (Japanese) (O cloud: C10); DuckDuckGo HTML (O cloud: L03); Mojeek (O cloud: L05); Indeed (O cloud: L42) | `[ ]` | T-006 | R | A: today's verdict returns UNKNOWN/clear for all three |
| CT-PH-196 | Block that arrives as a redirect to a login URL (block misread as a login wall) | LinkedIn (O cloud: L54) | `[ ]` | T-006 | R | A: verdict LOGIN_REQUIRED for a Cloudflare block |
| CT-PH-197 | Invisible challenge on a working form (reCAPTCHA Enterprise anchor) | Greenhouse (O cloud: F09 P08); Eightfold (O cloud: P17) | `[~]` | T-006 embedded | R | A: verdict 'embedded', correct; S4 (pass 4): invisible badge on a formless form is embedded, not a gate; R (owner capture form-required-markers/20261103-080138_jobs.ashbyhq.com) and form-radio-checkbox-questions/20261103-075245_jobs.ashbyhq.com now APPLICATION_FORM |
| CT-PH-198 | Obfuscated JavaScript cookie challenge served instead of HTML | - | `[?]` | T-006 | L | O: scs.gov.cn returns an obfuscated script that sets EO_Bot_Ssid (curl); the browser could not reach it through the cloud proxy (C09) |
| CT-PH-199 | Search box on a list page makes the page look like an application form | Bing (O cloud: L02); Jobvite (O cloud: L06); Dice (O cloud: L45) | `[ ]` | T-007 family model | R | A: verdict APPLICATION_FORM 0.85 on Bing results, a Jobvite home, Dice results |
| CT-PH-200 | Legitimate field names that contain trap tokens (address2, attestation, latest_employer, verification code) | Greenhouse address line 2 (K) | `[ ]` | ALG-014 | U | A: HoneypotDetector flags all six probe names |
| CT-PH-201 | Label placed to the right (RTL) or more than 50 px above its control | AllJobs (Hebrew) (O cloud: C01); e-aidem (Japanese) (O cloud: C05) | `[~]` | ALG-008 orient + ALG-014 | U | A: _is_honeypot True for RTL and label-above layouts, so the field is skipped; S4 (pass 4): direction-aware orientation (computed direction), label above at any distance; RTL and far-above real-browser pins |
| CT-PH-202 | Form container with hundreds of text nodes (cubic label assignment) | Ashby (O cloud: F02); Databricks careers (company site) (O cloud: L16) | `[~]` | ALG-008 caps | M | A: 2 inputs + 300 text nodes 1.6 s, cubic growth; 1,000 nodes extrapolates to about a minute; pass 3: S1: discovery no longer runs label pairing (listings-only analyze_serp); 165 s on C13 at head; S4 (pass 4): ladder first, residual Hungarian capped m<=120 per section, 8 nearest candidates, truncation in the form record; 150-control pin bounded |
| CT-PH-203 | Required control hidden by CSS (display:none) or replaced by a custom widget | Greenhouse (O cloud: F09 P08) | `[~]` | T-013 | U | A: hidden required input has no geometry, is excluded from interactables and never reported; S4 (pass 4): hidden required controls reported, flagged hidden (display-none, opacity, zero-size); backing inputs of visible widgets never traps; R (owner capture form-required-markers/20261103-080138_jobs.ashbyhq.com) |
| CT-PH-204 | Very large rendered payload (megabytes of DOM JSON in one script result) | Databricks careers (company site) (O cloud: L16); Ashby (O cloud: L18); Hacker News (O cloud: P19) | `[ ]` | T-002 budget | M | A: 11.1 MB for 90k nodes; a 2 GB machine holds several copies during json.dumps/loads |
| CT-PH-205 | Page degraded for this client (offline placeholders, controls withheld) | Notion (O cloud: L59 L62) | `[?]` | T-006 | L | O: 'Go online to view this image' in a headless cloud client |
| CT-PH-206 | Zero-width or bidi control characters inside visible text | Oracle Taleo (O cloud: L28); Eightfold (O cloud: L29); Google Forms (O cloud: L56) | `[ ]` | T-003 | U | O: 25 zero-width chars on a Taleo list; 12 bidi marks in a language list |
| CT-PH-207 | Page language undeclared or wrong (empty lang on a Chinese page) | e-aidem (Japanese) (O cloud: C05); Tencent (O cloud: L41 P23) | `[ ]` | T-003 | U | O: Tencent zh page lang='' |
| CT-PH-208 | Non-UTF-8 job page (Shift_JIS, GBK, EUC-KR, windows-1251) | Drushim (Hebrew) (O cloud: C02); Baitoru (Japanese) (O cloud: C10) | `[?]` | T-003 | U | O: 0 of 34 probed job hosts in 7 languages served a non-UTF-8 page; only a 403 page declared iso-8859-1 (C10) |
| CT-PH-209 | Window resized, zoomed or scrolled between observation and action (geometry stale) | owner machine (K) | `[ ]` | T-016 epoch | U | A: geometry is document-relative at capture; no epoch today |
| CT-PH-210 | Container with different fonts, no GPU, software rendering (geometry differs from the owner's machine) | State Civil Service (China) (O cloud: C09); Google (O cloud: L01); Ashby (O cloud: L18) | `[?]` | T-002 env fingerprint | M | O: every cloud screenshot is rendered with server fonts |
| CT-PH-211 | Thermal throttling or a busy machine stretches every step (wall-clock budgets fire early) | worst-case laptop (K) | `[ ]` | ALG-022 work units | M | design: budgets in work units, not seconds |
| CT-PH-212 | Something no ledger row describes (the unknown-unknown) | - | `[?]` | CT-INV-013 | L | rule: fail closed, record [?] with evidence, hand to the human, continue other work (12) |
| CT-PH-213 | robots.txt disallows the path that the engine would open | NEOGOV (O cloud: L31 L32 L33); LinkedIn (O cloud: L43 L53); Dice (O cloud: L45) | `[?]` | policy (CT-Q-026) | U (policy pin once CT-Q-026 is ruled) | O: NEOGOV, LinkedIn: Disallow /; Dice /jobs?q*; search engines /search |
| CT-PH-214 | Record or page with no text: only images, canvas or icon fonts | Notion (O cloud: L62); image-only cards (K) | `[ ]` | T-003 + T-009 | U | O: L62 images replaced by an offline placeholder; alt and aria-label are the only text |

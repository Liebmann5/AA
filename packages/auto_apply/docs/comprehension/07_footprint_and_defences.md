---
title: "Page Comprehension Toolkit: Footprint and Defences"
status: needs-review
last_verified: 2026-11-02
verified_against: "1bf7935"
audience: contributors
---

# Observable footprint and defences

**Honesty first.** Bot-detection internals are proprietary. Nobody outside the
vendors can say what they "watch most", and this page does not pretend to. Every
footprint statement below is derived from public standards and documented browser
behaviour, is labelled `[GOAL]` (unverified in a live run), and is paired with an
experiment (CT-EXP-001) that the project can run **on a page it owns** to settle it.
The design rule that survives uncertainty is: **minimise footprint by construction,
do not guess what is watched.**

## 1. What versus how

Two independent questions: *what* data is read (the content) and *how* it is read (the
mechanism, its timing and its side effects). A site can observe only (a) effects inside
its own page realm, (b) network requests and their timing, (c) input events and
behaviour, (d) properties of the browser and machine, and (e) the origin of the
connection. It cannot observe which attributes a reader looked at unless the page has
installed a hook in the same realm.

## 2. The owner's claim, analysed (CT-FR-018, CT-NFR-006)

> "Reading accessibility attributes is a rookie mistake because security systems watch
> them most."

**Verdict: mostly mistaken about reading; partly right about methods.**

| Point | Evidence | Status |
| --- | --- | --- |
| `role` and `aria-*` are static markup the site wrote. Reading them with `getAttribute`, `outerHTML` or a protocol snapshot is the same operation as reading `class` or `href`. A page cannot tell *which* attribute a reader consulted | HTML and WAI-ARIA are plain attributes; no browser API reports attribute reads to the page | `[GOAL]` analysis |
| Accessibility attributes are everywhere and are read constantly by assistive technology, search crawlers, test tools and password managers. A policy that treated reading them as hostile would flag its own users | WAI-ARIA Authoring Practices patterns are ubiquitous in forms and comboboxes | `[GOAL]` |
| The browser deliberately does **not** tell a page whether assistive technology is active (a privacy rule). Reading the accessibility *tree* over the protocol (`Accessibility.getFullAXTree`, used in `aom_adapter.py`) happens outside the page realm | W3C accessibility privacy guidance; protocol design | `[GOAL]` unverified; CT-EXP-001 step 4 measures CPU/timing side effects of enabling the domain |
| What detectors are publicly documented to look for: automation flags (`navigator.webdriver`), protocol side effects (for example behaviour triggered by enabling the Runtime domain), headless and GPU/font tells, patched native functions (a spoofed getter whose `toString` is not native), TLS and HTTP/2 fingerprints, IP reputation, and **behaviour** (pointer paths, key timing, scroll, uniform pacing) | vendor documentation and public research; none of it is attribute reads | `[GOAL]` |
| Where the claim has a kernel of truth | (1) A reader that runs *its own scripts in the page's world* can be seen by hooks the page installed on DOM APIs, **whatever it reads**. (2) Honeypots use `aria-hidden`, off-screen and `display:none` to trap **writers and clickers**: the trap fires on *filling or clicking*, not on reading. That is why the visibility predicate matters (CT-ALG-013) | `[GOAL]` |

**Correction and better alternative.** The risk is not *which attributes*; it is *where
the script runs, how many round trips are made, and what the actions look like*.
Reading the accessibility tree through the protocol is a **lower**-footprint method
than walking the DOM with a page-world script. Prefer, in order: a protocol snapshot
(out of the page), an isolated-world read, and only then a page-world script.

## 3. Reading methods: footprint and lowest alternative

*Footprint classes.* F0 none (post-hoc) · F1 out-of-page protocol read · F2 isolated
realm script · F3 page-realm script · F4 page-visible modification (init script,
patched natives, request interception).

| Method | Class | What the page can observe | Known detection vectors (public) | Lowest-footprint alternative |
| --- | --- | --- | --- | --- |
| Replay of a stored copy | F0 | nothing | none | n/a (post-hoc only) |
| Driver "get page source" | F1-F3 (driver-dependent: classic drivers may run an atom in the page) | possibly a script run in page realm | executing in the main realm exposes it to realm hooks | protocol snapshot where available |
| `DOMSnapshot.captureSnapshot` (Chromium) | F1 | nothing in the page realm; one protocol call; layout cost | protocol attachment itself (a debugger is attached) | already the lowest for layout+style |
| `Accessibility.getFullAXTree` | F1 | none directly; browser work | domain-enable side effects (to be measured) | prefer snapshot; use AX only when roles/names needed |
| BiDi `script.callFunction` with a `sandbox` | F2 | isolated realm: page globals and prototype patches are not shared | little documented | the recommended script route |
| Playwright locators / utility-world evaluate | F2 | injected helper runs in a utility world | injected-script artefacts | same as above |
| Playwright `evaluate` default, Selenium `execute_script` (today's single DOM walk) | F3 | the script runs in the page realm: visible to wrapped `getAttribute`/`getBoundingClientRect` hooks | hooks on DOM APIs; script-injection stack traces | move to F1/F2; if F3, one batched read, registered |
| Per-element `find_element` + `get_attribute` loops | F3 + many round trips | bursty, regular request pattern | timing regularity | one batched snapshot |
| Layout reads for every node (`getBoundingClientRect`) | F3 + forced layout | reflow cost; page layout observers | none specific | `DOMSnapshot` bounds; sample only needed nodes |
| `addScriptToEvaluateOnNewDocument`, fingerprint spoofing (`evasion/`) | F4 | altered natives | patched-native detection, inconsistency between spoofed and real values | **do not rely on spoofing as the footprint strategy**; AA's existing spoofing is a separate decision (Bible 16) and is recorded in the trace when active |
| Network interception | F4 | request path and timing changes | cache and header differences | observe network events only (`NETWORK_EVENTS`), do not rewrite |

## 4. Interaction methods: footprint and alternative

| Action | Higher footprint | Lower footprint | Status |
| --- | --- | --- | --- |
| Click | script `element.click()` (untrusted event; AA's synthetic fallback) | trusted input through the driver's input pipeline, after a human-plausible pointer path | `[PARTIAL]` motion profiles exist |
| Typing | set `.value` by script (no key events) | per-key trusted events at profile cadence; paste only where a human would | `[PARTIAL]` |
| Scrolling | instant jump (teleport; R-19 open) | stepped wheel scrolling at profile cadence | `[PARTIAL]` |
| Timing | uniform intervals | seeded jitter from `HostPacer` (ADR-020) | `[WIRED]` |
| File upload | OS file dialog automation | set the file input directly (no chooser) | `[WIRED]` |
| Many reads per action | N small scripts | one batched read per epoch | `[GOAL]` |

Timing determinism is separate from finding determinism: seeds for pacing should differ
per user while the *findings* stay a pure function of the observation.

## 5. The footprint budget (CT-NFR-006)

- A **script registry** lists every page-realm script by ID, purpose, size, and run
  count. An unregistered script cannot run.
- Default profile: zero F3 scripts when an F1/F2 read exists; otherwise at most two per
  observation, recorded.
- Each observation's trace names the method class used and why (capability missing,
  user choice, cost model).
- `ISOLATED_WORLD` absent and layout needed → one batched F3 walk, labelled
  `FOOTPRINT_FALLBACK`.

## 6. Experiment CT-EXP-001 (settles the claim without touching a third-party site)

A project-owned local "tripwire" page installs: wrapped `Element.prototype.getAttribute`,
`hasAttribute`, `querySelector(All)`, `getBoundingClientRect`, `getComputedStyle`,
`Document.prototype.elementsFromPoint`; a `MutationObserver`; the Error-stack
getter probe for Runtime-domain side effects; checks of `navigator.webdriver`; and a
high-resolution timing log. Drive it with each method in section 3 and fill: *hook
fired? realm visible? timing delta?* Step 4 repeats with and without
`Accessibility.enable`. The output is the table that replaces `[GOAL]` with a
measurement. Legal: only the project's own page. `[PLANNED]` slice 0.

## 7. Defences taxonomy: recognition and handling

**Recognition rule (from the STATUS.md correction of 2026-09-10).** Signals come from
*structure and visible text*, never a substring scan of raw source: a page that merely
mentions a vendor inside a comment is not a challenge. `js_variables` stay empty in the
challenge config (Bible 7.5). Handling is policy, not evasion: ADR-012 (gate), ADR-020
(bench), the in-place CAPTCHA pause (Applications), Bible 16.2/16.3. Everything is
recorded as research data (`defence_kind`, `vendor`, `signals`, `confidence`, copy
fingerprint) without payloads.

| Defence | Recognition signature (structural) | Policy | Status |
| --- | --- | --- | --- |
| reCAPTCHA v2 checkbox/image | challenge iframe from the vendor's API origin plus visible challenge text; widget container | in-place pause (Applications); bench engine (Discovery) | `[LIVE]` |
| reCAPTCHA v3 (score only) | badge, no challenge UI | **not** a block (Bible 7.5) | `[PARTIAL]` pass 2: an invisible reCAPTCHA on Ashby forms with no `<form>` is judged gated (A: F02-F04, EC-40); judged embedded on Greenhouse and Eightfold (P08, F09, P17) |
| hCaptcha, Cloudflare Turnstile | vendor iframe origins; widget container | as above | `[PARTIAL]` |
| Arkose / FunCaptcha, GeeTest | vendor iframe/script origins plus challenge UI | as above | `[?]` |
| Interstitial "checking your browser" (Cloudflare, Akamai, PerimeterX/HUMAN "press and hold", DataDome) | near-empty body, challenge platform path, hold-button UI, vendor script origin | treat as challenge; bench; never retry in a loop | `[PARTIAL]` vendor annotations only |
| Search-engine "unusual traffic" (path `/sorry/`) | URL path + visible text + form | bench engine; name the cause plainly (LR-8) | `[LIVE]` |
| Rate limits (HTTP 429, `Retry-After`, "too many requests") | status/headers where visible, else text | bench the host for the session (CT-Q-028); no retry storm | `[PARTIAL]` pass 2: Workable 429 on the first request judged `UNKNOWN` (A: L24-L26) |
| Silent throttling / shadow thinning | yield and page-size collapse vs the provider baseline | degradation detector benches (ADR-020 decision 6) | `[LIVE]` |
| Login walls (LinkedIn `/authwall`, ATS sign-in) | login form + redirect target + wall text; URL path | `LOGIN_REQUIRED`; no repeated visits (the 2026-10-07 nine-revisit bug) | `[LIVE]` |
| Account creation, email verification, one-time codes, passkeys | sign-up form, code input, WebAuthn prompt | human hand-off; never AA-typed third-party credentials (CT-Q-013/014) | `[?]` |
| "Sign in with …" pop-up window | new window with OAuth parameters | CT-ALG-025: record, hand off, re-observe | `[ ]` |
| Consent walls (TCF-style CMP banners) | fixed overlay + accept/reject controls + vendor container ids | dismiss only per user policy; record | `[?]` |
| Age gate, geo-block, closed posting, already applied | visible-phrase tables (locale-keyed) plus structure (status 404/410, no apply control, redirect to a list) | existing verdict kinds | `[PARTIAL]` pass 2: 0 of 4 closed or missing postings judged `CLOSED` (A: L46, L47, L48, L52) |
| Honeypot fields | CSS-hidden or off-screen, no label, trap names | CT-ALG-014 decision rule; skip and record | `[WIRED]` |
| Time-based traps (submit too fast), JS-issued tokens | not visible statically | pacing profile; record outcome | `[ ]` |
| DOM obfuscation (hashed classes, shuffled order vs visual order, canvas text, CSS `content`, zero-width injection) | class entropy; reading order != visual order; text drawn on canvas; Cf characters in text | structure-and-geometry methods; keys strip Cf; canvas text → `UNREADABLE` finding | `[PARTIAL]` |
| Session expiry, CSRF, single-use apply links | redirects to login/home after idle; stale tokens | re-observe on resume (CT-ALG-024) | `[?]` |

## 8. Containers, VMs, headless, no GPU (item 19)

| Item | What changes | Detected how | Adaptation |
| --- | --- | --- | --- |
| Headless mode (new vs old) | window/screen metrics, UA tokens in old headless | UA/feature probes | record `EnvFacts`; prefer headful in a virtual display (the repo's docs gate already uses a virtual display) |
| No GPU | software rasteriser renderer strings | WebGL renderer probe | record only; AA does not claim to hide it |
| Fonts | missing fonts change text metrics and thus **all geometry** | font probes; layout differences | relative thresholds (em, viewport); font fingerprint in `PageObservation`; pinned fonts for fixtures |
| Shared memory and cgroup limits | browser crashes at small `/dev/shm`; OOM kills | crash, not detection | adapter flags and a pre-flight check; `library` profile caps nodes |
| Sandbox flags | running as root needs relaxed sandbox | none from page | adapter sets flags; recorded |
| Timezone and locale | `Accept-Language`, `Intl` vs IP geolocation incoherence | coherence checks | profile sets locale deliberately; dates parsed by the page's own locale |
| Screen size and device pixel ratio | small defaults | viewport probes | explicit viewport in the request |
| Datacenter IP / VM network | the connection's origin | IP reputation (the largest signal) | outside the toolkit; recorded as a research covariate; ADR-020 pacing and benching apply |
| Ephemeral or shared storage | profile and cookies lost | session continuity | warm-up and persona rules stay in Evasion (Bible 16); the trace notes a cold profile |

`[GOAL]` Each row becomes a CT-NFR-013 test on the Docker image
(`Dockerfile.test`), measured, not asserted.

## 9. Defences observed live (pass 2, environment `cloud`)

What a data-centre client met on 2026-11-02, one request per page, with polite
pacing. "Today's verdict" is AA's `assess_page` at `1bf7935` replayed offline
over the saved page ([10](10_gap_analysis_and_build_plan.md) section 5). This is evidence about a data-centre
client; the owner's machine sees a different web (LR-1 to LR-8).

| Defence seen | Hosts (specimens) | Signature observed | Today's verdict |
| --- | --- | --- | --- |
| Search-engine "unusual traffic" with reCAPTCHA | google.com (L01) | redirect to `/sorry/index?continue=…`, 3 reCAPTCHA frames | `CAPTCHA_BLOCK`, correct |
| Proof-of-work bot check with CAPTCHA fallback | search.brave.com (L04) | 429, "Verifying you're not a bot … Switch to traditional CAPTCHA" | `UNKNOWN` |
| Plain block page | html.duckduckgo.com (L03), mojeek.com (L05), indeed.com (L42), drushim.co.il (C02), baitoru.com (C10) | 403, short text, no challenge markup; Indeed keeps full site chrome | `UNKNOWN` |
| Cloudflare managed challenge | bayt.com (L40), glassdoor.com (L44), work.ua (C08, Ukrainian text), weworkremotely.com (C17) | "Just a moment…", challenge-platform script | `CAPTCHA_BLOCK`, correct |
| Cloudflare rate limit 1015 | apply.workable.com (L24-L26) | 429 on the first request, "You've sent too many requests too fast" | `UNKNOWN` |
| Block after a login redirect | linkedin.com (L54) | `/uas/login?session_redirect=…` then 403 "Sorry, you have been blocked" | `LOGIN_REQUIRED` (misattributed) |
| DataDome on an apply route | jobs.smartrecruiters.com one-click (F08) | 403, empty body, DataDome script | `CAPTCHA_BLOCK` |
| hCaptcha beside an identity step | careers-rambus.icims.com (F07), jpmc.fa.oraclecloud.com (F10) | hCaptcha frames next to a login or email form | `LOGIN_REQUIRED` (F07), `APPLICATION_FORM` embedded (F10) |
| Invisible reCAPTCHA on a working form | job-boards.greenhouse.io (P08, F09), apply.careers.microsoft.com (P17, F12), jobs.ashbyhq.com (F02-F04) | anchor iframe, no challenge UI | embedded on Greenhouse and Eightfold; **gated** on Ashby |
| Bot-detection script on content | linkedin.com guest pages (L53, L55) | PerimeterX frame `li.protechts.net/…&uc=scraping` | `UNKNOWN` embedded |
| Obfuscated JavaScript cookie challenge | scs.gov.cn (curl body in the evidence set) | script sets `EO_Bot_Ssid` and reloads | not reached by the browser (the cloud proxy accepts HTTPS only, C09) |

**What this changes.** Recognition built only on challenge markup misses the
commonest refusal a data-centre client meets: a plain block page with a 403 or
429 status and no widget. The verdict needs a block kind that reads status,
near-empty content, the absence of forms and records, and a block lexicon in
any language (EC-21, EC-22).

### robots.txt per host (pass 2)

`robots.txt` was fetched once per host with `curl` and evaluated for
`User-agent: *` (longest match wins). A host that answered the fetch itself
with 3xx, 403, 422 or 429 is "unknown". Paths that `robots.txt` disallowed were opened
**at most once**, only to record what a guest sees. Two hosts were not opened
at all. Every disallowed host is listed as owner ruling CT-Q-026 in
[01](01_charter.md).

| Host | `robots.txt` result for the opened paths | Disallow rule matched | Specimens |
| --- | --- | --- | --- |
| adobe.wd5.myworkdayjobs.com | allowed | - | L50 |
| apply.careers.microsoft.com | allowed | - | C16 F12 L30 P17 |
| apply.workable.com | status 429 (unknown) | - | L24 L25 L26 |
| applyatscale.notion.site | allowed | - | L59 |
| boards.greenhouse.io | allowed | - | L17 P08 |
| career.habr.com | allowed | - | C07 |
| careers-emcorgroup.icims.com | allowed | - | L14 P24 |
| careers-rambus.icims.com | allowed | - | F07 L13 L51 |
| careers.smartrecruiters.com | status 302 (unknown) | - | L22 |
| careers.tencent.com | status 302 (unknown) | - | C12 L41 P23 |
| codeandcocom.notion.site | allowed | - | L58 |
| dejobs.org | allowed | - | C19 L34 P18 |
| docs.google.com | allowed | - | L56 L57 |
| drhorton.taleo.net | none (404) | - | F11 L28 P16 |
| enableamerica.dejobs.org | allowed | - | C21 L36 |
| hh.ru | DISALLOWED; not opened | disallow: *?* | C11 |
| html.duckduckgo.com | allowed | - | L03 |
| job-boards.greenhouse.io | no * group | - | F09 L15 L16 L46 L47 P26 |
| jobs.ashbyhq.com | allowed | - | C15 F02 F03 F04 L18 L19 L20 P10 P11 P12 |
| jobs.careers.microsoft.com | status 301 (unknown) | - | L29 |
| jobs.jobvite.com | none (404) | - | F01 F14 L06 L07 L08 L09 P01 P02 P03 |
| jobs.smartrecruiters.com | none (404) | - | F08 L21 L23 P13 P14 |
| jpmc.fa.oraclecloud.com | status 403 (unknown) | - | F10 L27 L48 P15 |
| messold.notion.site | allowed | - | L60 L61 |
| nationalmssociety.dejobs.org | allowed | - | C20 L35 P25 |
| news.ycombinator.com | allowed | - | C13 L37 P19 |
| nvidia.wd5.myworkdayjobs.com | allowed | - | F05 L10 P04 |
| rackhousevc.notion.site | allowed | - | L62 |
| remoteok.com | allowed | - | C14 |
| salesforce.wd12.myworkdayjobs.com | allowed | - | F06 L11 L49 P05 |
| search.brave.com | DISALLOWED | disallow: /search | L04 |
| wd1.myworkdaysite.com | status 422 (unknown) | - | L12 P06 |
| weworkremotely.com | allowed | - | C17 |
| www.51job.com | status 302 (unknown) | - | C04 |
| www.akhtaboot.com | DISALLOWED; not opened | disallow: / | C03 |
| www.alljobs.co.il | allowed | - | C01 |
| www.amazon.jobs | allowed | - | C18 |
| www.arbeitsagentur.de | allowed | - | L38 L52 P20 |
| www.baitoru.com | status 403 (unknown) | - | C10 |
| www.bayt.com | status 403 (unknown) | - | L40 |
| www.bing.com | DISALLOWED | disallow: /search | L02 |
| www.dice.com | DISALLOWED; allowed | disallow: /jobs?q* | L45 P22 |
| www.drushim.co.il | allowed | - | C02 |
| www.e-aidem.com | no * group | - | C05 |
| www.glassdoor.com | allowed | - | L44 |
| www.google.com | DISALLOWED | disallow: /search | L01 |
| www.governmentjobs.com | DISALLOWED | disallow: / | L31 L32 L33 |
| www.indeed.com | allowed | - | L42 |
| www.jobkorea.co.kr | allowed | - | C06 |
| www.linkedin.com | DISALLOWED | disallow: / | L43 L53 L54 L55 |
| www.mojeek.com | DISALLOWED | disallow: /search | L05 |
| www.scs.gov.cn | no * group | - | C09 |
| www.smartr.me | none (404) | - | F13 |
| www.stepstone.de | allowed | - | L39 P21 |
| www.work.ua | allowed | - | C08 |

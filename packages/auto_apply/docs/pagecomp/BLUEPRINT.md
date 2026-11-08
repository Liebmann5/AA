---
title: "pagecomp blueprint, evidence and hand-off"
status: needs-review
last_verified: 2026-11-08
verified_against: "every claim names its evidence (tests, owner captures, measurements); see section 3"
audience: contributors
---

# pagecomp v0.5.0: blueprint, evidence and hand-off

Status: draft for the three-reviewer loop. Every claim below names its
evidence: **T** a test in `tests/`, **C** the owner-capture corpus
(the owner's private capture set, 97 pages, captured 2026-11-03; not shipped), **M** a
measurement on the build machine (a cloud Linux desktop, not the worst-case
laptop), **L** a measurement on the owner's laptop (Lubuntu, 2 CPUs,
Python 3.14, `python -m pagecomp bench`, 2026-11-08), **A** an argument
written here. Nothing here is a live-internet
result, so nothing here ticks a ledger box (owner rule: proof comes from
live runs only).

## 1. What this is

This is the Page Comprehension Toolkit of `docs/comprehension/` (the CT-*
suite), built as the standalone library that 05 section 10 asks for:

* pure Python, standard library only, Python ≥ 3.10 (tested on 3.11 and 3.13);
* sans-IO (Bible §26): tools see one immutable observation, never a browser;
* no import of `auto_apply` (T: `test_boundary.py`).

It is a **restart of the comprehension layer, not of AA**. Proven pieces of
AA were ported, and each module names where its code came from. AA's engines,
ports, browser cascade and fillers are untouched; section 7 says how AA
adopts the library.

### Why a restart rather than patching AA in place

The S1 and S4 slices landed inside AA as `domain/services/*`, written against
the `DOMNode` object tree. That tree cannot hold shadow roots or frames
(defects 5 and 6). It costs about 360 B per node, and its hash includes CSS
classes (defect 1). Patching each service would mean changing the shared data
model under all of them at once. The blueprint's own plan (S3, S6) puts the
new `Doc` and the library boundary first, so v0.1 builds those, then ports
the services onto them.

## 2. Layout

```
src/pagecomp/
  results.py      Ok / Abstain / Timeout / Stale, Evidence, fingerprint      CT-DS-005
  params.py       ParamSpec, ParameterSet (hashed, versioned, safety-locked)   CT-DS-007
  trace.py        ToolRun, Trace (bounded, no URLs or text by construction)    CT-T-018, CT-DS-006
  text.py         keys, tokens, script, direction, mojibake                    CT-T-003
  doc.py          columnar Doc: HTML parser, CDP pierced-DOM builder, caps     CT-T-004, CT-DS-002
  observation.py  PageObservation, content hash, capabilities                  CT-T-002, CT-DS-001
  registry.py     ToolSpec, Registry (declared needs, acyclic check)           05 s2 seam rule
  analyzer.py     demand-driven memoized query graph, budgets, epochs          section 3 below
  links.py        URL evidence + destination ladder (direct/unwrapped/opaque)   CT-ALG-004 (links)
  linkage.py      cross-page record linkage: resolve, dedupe, arrival by id     new (section 4a)
  hungarian.py    assignment with dummy padding                                CT-T-011
  capture.py      replay adapter for owner captures                            CT-T-022
  access.py       AccessPort, ObservationRequest, CapabilitySet, frame graft   CT-T-001, CT-DS-010 (S3)
  transitions.py  DocDiff, settle, conditional fields, errors, windows, resume CT-T-016, ALG-012/016/017/024/025 (S5)
  effect.py       filter effect check, URL-parameter learning                 ALG-027 (S9a)
  viewmath.py     view equivalence, merge, cheapest verified view, sampling   ALG-028/029 (S9b)
  channels.py     RSS / Atom / sitemap parsers, robots Sitemap: lines         Source Channel seam (S9)
  memory.py       domain memory: verified on use, expiring, quarantine, LRU   ALG-020 (S7)
  tuning.py       sign test, Holm, Wilson/Newcombe guard, bounded steps       ALG-019 (S7)
  workbench.py    failure classes, self-contained review page, ledger counts  ALG-026, CT-FR-027/028 (S8)
  bench.py        S0: measure time/memory on this machine, derive the caps    05 s14, 06 s11 (S0)
  __main__.py     python -m pagecomp analyze | review | bench | version       S6
  tools/
    visibility    static visibility evidence per node                          CT-T-005, ALG-013
    pagetext      visible text once, prose blocks                              (shared)
    structured    JSON-LD JobPosting                                           CT-T-017
    forms         controls (all scopes), form roots, purpose, groups, buttons  CT-T-010, ALG-007
    formread      pairing ladder, typing, requiredness, trap decision          CT-T-011..013, ALG-008..010, 014
    verdict       challenge / login wall / overlays / closed / applied / error CT-T-006
    records       skeleton multisets, sibling runs, ranked                     CT-T-008, ALG-001..003
    listing       title, links, resolution state per record                    CT-T-009, ALG-004
    joblist       the job-list gate                                            new (problem 6)
    family        the single "what page is this" answer                        CT-T-007, ALG-006 (LR-18)
    arrival       requested vs landed surface                                  LR-16/17 rule
    controls      filters, sort, chips, pagination, search boxes → bindings     CT-T-027 (S9a)
    views         alternate views a page advertises, guest view, record key    CT-T-028 (S9b)
```

Dependency graph (declared, checked acyclic at start-up):

```
visibility ─┬─ pagetext ─┬─ verdict ─┐
            ├─ forms ────┼─ formread ┼─ family
            ├─ records ── listing ── joblist ┘
structured ─┘ (verdict, family)            arrival (none)
forms, visibility ── controls          structured, verdict, pagetext, forms ── views
```

## 3. The owner's architecture idea, evaluated

**The idea:** read the page once, offer every tool, and re-read
incrementally, maybe without bounding what is suggested.

**What was adopted.** A shared read plus memoized tools is the right shape.
It is the demand-driven query pattern: LLVM's AnalysisManager, Salsa in
rust-analyzer, the blackboard pattern. `Analyzer` implements it. One `Doc`
is built per observation. Each tool runs at most once per observation and
parameter set, and a tool reaches any other tool through `q.need(...)`.

**What was changed, and why.**

| Risk in the idea as stated | What v0.1 does | Evidence |
| --- | --- | --- |
| A stale cache. Keying results on an epoch counter reuses old results after a change nobody observed (timers, push updates). | The cache key is the observation's **content hash** plus the versions and parameters of the tool's dependency closure. The epoch is stamped on results for consumers (`Analyzer.check` returns `Stale`) and is never a key. | T `test_cache_keys_on_content_not_epoch`, `test_stale_findings_are_refused` |
| A service locator: "offer every tool" lets any tool call any tool, so coupling grows hidden and cycles appear. | Each tool **declares** its needs. An undeclared call raises; the graph is checked acyclic when the registry is built. | T `test_undeclared_dependency_fails_loudly` |
| Hidden state breaks determinism. | Tools get only `q` (observation, params, needs, meter). No clock, file, network or randomness: an AST test forbids those imports in `tools/`. | T `test_tools_touch_no_clock_file_or_network`, `test_replay_is_deterministic` |
| Unbounded memory or time on a 2 GB machine. | LRU cache with an entry cap; a work-unit budget per analysis and per tool (deterministic, no clock), returning `Timeout`; every observation capped (nodes, depth, frames, script bytes, text), with each cut recorded. | T `test_cache_is_bounded`, `test_budget_gives_timeout_not_hang`, `test_node_cap_truncates_and_reports`, `test_depth_cap_iterative_no_recursion_error` |
| "Initial full read" means eager work. | Nothing runs until asked. Discovery asks for `joblist`; Applications asks for `formread`; neither pays for the other. | T `test_demand_driven_and_memoized_within_analysis` |
| "Not bounding what is suggested through the math." | Tools return **all** ranked candidates with features (records returns every run), so nothing is pruned early. Decisions still abstain under a margin. Unbounded *suggestions* are fine; unbounded *decisions* are not. | `records` returns ranked runs; `family` abstains below p 0.6 / margin 0.2 |
| Incremental re-read. | v0.1 re-reads the whole page. A byte-identical page reuses every result through the content key. True incremental re-read (region diff, CT-T-016) is **not built**: section 8 item 5. | A |

## 4. Corrections to the blueprint found while building

Each correction is either recorded in the code's docstring or pinned by a test.

1. **ALG-002 cost.** 06 section 1 says `O(n·D·K)`. Windows of width `m` at
   `m` offsets each re-sum `m` child multisets, so the total is
   `O(n·D·K²)`: 30 passes per parent at K=4. (`records.py` docstring.)
2. **The ALG-003 record-root lift is vacuous for sibling runs.** Members of a
   sibling run share a parent, so every lift ℓ ≥ 1 collapses them (Lemma 3).
   ℓ = 0 is the only level. The lift's third criterion (title plus anchor in
   ≥ 80% of members) is kept as the `carries` ranking feature. The lift
   applies only to non-sibling seeds, such as S1's heading climb.
3. **The "partition of C" claim in ALG-007 is false.** Controls that sit in
   no qualifying node, such as a lone newsletter box, are covered by none.
   They now go to a per-scope `residual` group, whose purpose is always
   `unknown` (T `test_lone_control_goes_to_residual_never_dropped`).
4. **A maximal qualifying node can be the whole document.** It is shrunk to
   the lowest common ancestor of its controls
   (T `test_formless_spa_form_is_found_and_shrunk_to_its_controls`).
5. **The requiredness score had no prior.** Its thresholds silently assumed
   a 50% base rate. `prior_logodds` (b0) is now an explicit, tunable
   parameter (default 0).
6. **The asterisk convention was missing.** When a form marks some labels
   with `*` and not others, `*` is the form's required marker: +4, as with
   a legend, and an unmarked field leans optional at -2.5. Without this,
   every BambooHR `First Name *` read UNKNOWN (C: bamboohr;
   T `test_requiredness_conventions`).
7. **Visual vs accessible text.** MUI renders the required asterisk inside
   `aria-hidden`. Names skip it; requiredness must read it. `text_content`
   now has a `visual` mode (T `test_aria_hidden_is_skipped_for_names_but_kept_visually`).
8. **The order of the last pairing rungs.** 06 section 4 puts
   `title`/`placeholder` before the residual assignment. AA's pass-4 reader
   puts them after, because a placeholder vanishes when typed. v0.1 follows
   AA and claims `aria-labelledby` targets so the residual cannot reuse them
   (T `test_pairing_ladder_order`).
9. **Sample size (from the earlier review, unchanged).** 09 section 9 uses
   α = 0.05 while its decision rule uses α = 0.01, which needs about 25–30
   sites per source. MinHash over multisets needs multiset expansion or
   weighted MinHash. v0.1 uses exact Ruzicka, so no MinHash is needed yet.

10. **(S3) `DOMSnapshot.captureSnapshot` flattens shadow DOM.** Measured on
    headless Chromium (Playwright 1.x, 2026-11-05): the snapshot has no
    shadow-root nodes and inlines shadow content in composed order, so
    `label[for]` scopes and open/closed modes are lost. 05 section 5 reads
    as if the snapshot alone gives `SNAPSHOT_LAYOUT` with the tree. Fix: the
    tree comes from `DOM.getDocument(pierce)` and layout is joined on by
    `backendNodeId` (`from_snapshot(snapshot, dom=...)`); without `dom` the
    source is `cdp-snapshot-flat` (T `test_snapshot_flattens_shadow_so_tree_comes_from_pierced_dom`).
11. **(S3) Deep pages break both read paths silently.** Measured on a
    5,000-deep chain: `DOM.getDocument(depth=-1)` fails with "CBOR: stack
    limit exceeded", and a nested script-walk result fails Playwright
    serialisation ("object reference chain is too long"). Before the fix both
    rungs returned an empty document with no flag. Fix: the CDP rung retries
    at `depth = max_depth` and records a `depth` cut; the walk emits a flat
    list (parent index + relation) rebuilt iteratively; any unreadable result
    is a `read-failed` truncation (AA pin `test_node_and_depth_caps_fire_tree_stays_valid`).
12. **(S3) A 5,000-deep *rendered* chain crashes Chromium's renderer** (the
    page, not the reader). The pin hides the chain with `display:none`; the
    DOM depth is unchanged. A live page doing this would crash before any
    read, which the adapter reports as a typed probe failure.
13. **(S3) A page script cannot see closed shadow roots at all**, so the
    script-walk rung always declares the `CLOSED_SHADOW_UNSEEN` gap and
    counts defined custom elements with no open root as suspects
    (`closed-shadow-suspect` truncation). It never claims the content absent.
14. **(S3) Same-origin is not same-process.** Site isolation splits by
    *site*; `localhost:a` vs `localhost:b` are cross-origin but same-site
    and arrive inside the pierced tree. Only cross-*site* frames are
    out-of-process and need a per-frame CDP session; the pins use
    `localhost` vs `127.0.0.1` for that reason.
15. **(S5) Diff keys.** 06 section 8 keys on `(parent key, tag,
    id|name|aria-label|role, ordinal)`. `for` is added to the identity list
    (labels are otherwise keyed by position). Recycled virtual-list rows
    show up as *changed* (same key, new payload), which is the R-20 signal V2.

16. **(S2) Lists of lists.** Two sibling `<ul>` lists form a "run" whose
    members are whole lists. A run whose members each contain a *record
    list* (an inner run of ≥ 3 members, ≥ 80% carrying heading and link) is
    demoted (`w_nested`) and never passes the job-list gate. A card's own
    repeats (skill chips, badges) are runs but not record lists, so they
    do not demote it (C: BuiltIn Chicago, Intel, which a first version of
    the rule broke; T `test_a_list_split_across_sibling_lists_is_read_whole`).
17. **(S2) Menus need no headings.** "Every member a short link" also
    describes a list of short job titles ("Nurse", "Engineer II"). A menu
    is that *and* no member under a heading
    (T `test_workflow_change_when_plan_lacks_a_needed_step`).
18. **(S2) Gap bridging and split lists.** One foreign sibling between
    cards (an ad, Brave's "Find elsewhere" box) is bridged when both sides'
    consensus skeletons agree (`max_gaps = 1`); two foreign blocks never
    are. Lists split into several sibling runs (Indeed) are merged by
    consensus-signature similarity (`JobList.records`). On the Brave capture
    this recovered 9 more records, and Google's betterme result then
    linked by ID to Brave's direct URL, a second true link.
19. **(S2) A bare hostname is not a title.** Brave's `<cite>` host outscored
    the title line by 0.02 because it was longer. A name that is only a
    host, or sits in `<cite>`, takes -1.0.
20. **(family) Application entry steps.** Workday's chooser ("Autofill with
    Resume / Apply Manually / Use My Last Application") is its own family,
    `application_entry`: ≥ 2 distinct shown controls that each start an
    application a different way, no identity form, little prose. The same
    chooser as a modal over a posting stays `job_description` with a
    `dialog` overlay (C: Home Depot, AT&T, Comcast; page text verified).
21. **(forms) Filter panels and search bars.** A group of choices with no
    text or file field and no Next/Submit of its own is a `filter`, not an
    application step; an EEO step of only choices keeps its Next, so it
    stays `application`. A keyword box plus a location box (no identity
    field) is `search`. A "Show results" submit does not make a form an
    application.
22. **(S0) Measuring time under tracemalloc is wrong.** It slows every
    allocation 2–3×. `bench` measures time untraced (median of 3) and
    memory in a separate traced pass. A run in which any tool raised is
    reported as **invalid**, and no cap is recommended from it: an early
    benchmark here "measured" tools that had silently errored.
23. **(caps) Per-attribute cap.** One 1.1 MB inline `style` (an embedded
    data: image) on Siemens made the style regex take 0.5 s on an 896-node
    page. Attribute values are cut at 65,536 characters, the cut is
    recorded (`attr-chars`), the byte budget charges the cut length, and the
    visibility check reads the first 4 KB of a style
    (T `test_huge_attribute_is_cut_and_reported_not_scanned`).
24. **(perf) Quadratic membership.** `c in free` on dataclasses compared
    fields pairwise, and controls were filtered per form, so 2,000 shadow
    hosts (one residual group per shadow scope) took O(F·C). Both are now
    indexed, and accessible names are memoised per Doc (it is immutable).
25. **(S0) The node cap was set by the wrong time figure.** v0.4 derived
    `max_nodes` from the 1.0 s target (CT-NFR-004). On the owner's laptop
    (L) that gave 8,000 nodes, and 8 of the 97 captures are larger (C),
    among them every SmartRecruiters application form (12,080-12,899
    nodes): those forms would have been cut and lost questions. A cap
    trades completeness for time, so it must not be set by a *typical*
    page's budget. `bench` now reports two figures: the **target** (1.0 s,
    reported as "nodes that meet it", does not set the cap) and the
    **ceiling** (3.0 s, which sets the cap with memory). The ceiling is an
    operational budget (`--ceiling-s`), not a measured worst case: 3 s is
    about what the browser spent reaching and settling one page on the
    laptop in one live log (2026-11-07: 3-4 s from navigation to a
    validated page), so a page at the cap takes about as long to read as to
    reach. The bench runs with no browser competing for the CPU; that is
    what the 2× margin over the largest real page is for (review, round 1:
    the earlier wording claimed more than one log shows). The cap stays a
    guard against pathological pages, not a speed control
    (T `test_owner_laptop_measurement_gives_the_shipped_default`).
26. **(parser) Implied closes scanned the whole open-element stack.** Each
    `<div>` looks for an open `<p>` to close, and each stray end tag looked
    for a match, by walking the stack: O(nodes × depth). A 2,000-deep page
    took 0.45 s to parse on the laptop (L). The stack now keeps a count of
    open tag names and only walks when a match is open. Trees are
    byte-identical to v0.4 on 400 fuzz pages and all 97 captures at two
    depth caps (M); 2,000-deep parse 0.129 s → 0.019 s here (M). With the
    walk gone, **`max_depth` rises from 64 to 256**: the deepest capture is
    54 levels (C), which left only 10 levels of headroom before a deeper
    React or Workday page would silently lose its innermost fields
    (T `test_a_page_nested_to_the_depth_cap_analyzes_strictly`,
    `test_parser_open_element_counts_match_the_stack`).
27. **(packaging) `pyproject.toml` said 0.3.0** while the code said 0.4.0.
    Both are 0.4.1, and a test now keeps them equal.

Corrections 28-36 come from the first outside review round (2026-11-08:
ChatGPT ran the code, Gemini read it). Every finding was reproduced here
before it was fixed; the measurements are on the build machine.

28. **(parser) Bounded output did not mean bounded work.** The caps
    limited what a `Doc` keeps, not what the parser reads. Measured before
    the fix: a 50 MB text node took 12 s and 678 MiB and then lost its text
    to the byte cap; nesting 1.6 M levels past the depth cap took 6.4 s;
    a million attributes on one element took 13 s. Now: serialized HTML is
    read up to `max_input_chars` (8,000,000; the largest capture is
    2,476,428); parsing stops the moment the builder is full (a callback
    raises, so `html.parser` does no further work); a text node is cut to
    4× `max_text_chars` *before* whitespace is collapsed; and elements
    dropped past the depth cap count against the node cap. Each case now
    takes 0.02-1.3 s on Python 3.10, 3.13 and 3.14. A lesson along the way:
    feeding `html.parser` in chunks made 3.10 and 3.14 rescan a tag that
    spans chunks, which is quadratic (29 s for the million-attribute tag);
    one feed call is linear on every version (C, M;
    T `test_parser_work_is_bounded_not_only_its_output`).
29. **(caps) Attributes per element.** None was capped, and an attribute
    with an empty name cost 0 bytes, so a DevTools payload could store 2
    million of them. Now at most `max_attrs` (256) per element, sliced
    before pairing, each attribute costs at least 1 unit, and the cut is
    recorded (`attrs`).
30. **(depth) Shadow roots were not checked against the depth cap.** In
    HTML a declarative shadow root landed one level past it; in a DevTools
    payload, shadow roots nested directly in shadow roots had no depth cap
    at all (20,001 levels measured). Both paths now check a shadow root
    like any other level (T `test_shadow_roots_count_against_the_depth_cap`).
    Gemini reported the HTML case as unbounded: it is not (each shadow root
    needs a host element, which is checked), but the DevTools case was.
31. **(caps) Script text was cut at 20,000 characters, not 65,536.** The
    builder applied the ordinary text-node cap to script and style text the
    parser had already capped at `max_script_chars`. Real JSON-LD blocks
    reach 16,098 characters in the captures, so a long posting's block
    would have been cut into malformed JSON. Found while checking finding
    33. The only tree change from v0.4 is longer script and style text (C:
    497 pages, same shape, no other text differs).
32. **(DevTools) Chrome cuts every text node at 10,000 characters.** Blink's
    DOM agent sends at most `maxTextSize = 10000` characters of a node's
    value and appends U+2026 (Chromium `InspectorDOMAgent.cpp`). 48 text
    nodes on 27 captured pages are cut this way, including Lever's JSON-LD
    block, the one "malformed" block in the corpus. The cut is now recorded
    (`cdp-text`). **For AA's adapter (S3):** read JSON-LD blocks' text
    separately (one in-page call for `script[type="application/ld+json"]`),
    since `DOM.getDocument` cannot return them whole.
33. **(views) The JSON-LD view claimed a description it never read.**
    `description` is now extracted (HTML and HTML-escaped HTML unescaped,
    tags removed, at most 20,000 characters), and the view lists only the
    fields the block actually has.
34. **(S0) The bench rounded an impossible cap up.** Budgets that fit
    fewer than 1,000 nodes still got a 1,000-node recommendation that broke
    both. Now no cap is recommended, the reason is given, and the command
    exits with 1.
35. **(tuning) Missing evidence passed non-inferiority.** A guard family
    with no observations, or no guards at all, let a change through. Now
    both block it; `guards={}` is the caller stating no other family
    exists. Note what the 1-point margin costs: equal 95% accuracy on both
    sides needs about 3,700 observations per side before the Newcombe bound
    clears -0.01 (950 at 99%). Self-tuning will therefore change little
    until AA has a large labelled history; that is the rule working, not a
    defect.
36. **(parser) The open-element stack is no longer a `list` subclass.**
    Nothing used an unmanaged list method, but nothing prevented it. It is
    now a small class over a private list, so the tag counts cannot drift.

Round 2 (2026-11-08, Gemini, read only; each claim checked here):

37. **(listing) A heading wrapping its link lost the posting evidence.**
    For `<h3><a href=…>Title</a></h3>` the "leads to a posting address"
    bonus looked only for an anchor *around* the candidate, never inside
    it. On the 97 captures no title changes (the heading already won), but
    a card whose first heading links to the company page picked the
    company name (T `test_a_heading_wrapping_a_posting_link_beats_one_wrapping_a_company_link`,
    which fails without the fix).
38. **(parser) Attribute slice.** Reported as keeping 257 attributes: it
    kept 256 and counted the cut correctly (the extra one was handed to the
    builder so it would record the cut). Rewritten to slice at the cap
    directly, which says what it does.
39. **(formread) Dead condition.** `b > node and not is_ancestor(b, node)`:
    in pre-order a later node cannot be an ancestor, so the second half was
    always true. Removed; behaviour unchanged.

Found while wiring pagecomp into AA (2026-11-08):

40. **(joblist 0.3.0) The gate chose Indeed's related searches over its
    real cards.** On the owner's Indeed capture, a run of "related search"
    links (`/q-junior-web-developer-l-los-angeles,-ca-jobs.html`) passed:
    a posting word in the path (0.5) plus a role word (0.5) made each one
    "job-like". The real cards failed: Indeed links them as `/rc/clk?jk=…`
    (no posting word, so path 0), and the capture's URL carries no query
    for echo. This is the failure of the live run of 2026-11-07 (29
    "jobs" that were salary pages, searches and advice). A record is now
    job-like only when its destination is **specific**
    (`links.specific_destination`): an identifier in the path; a posting
    word as a whole segment followed by a non-category segment
    (`/jobs/head-of-product-design_paris`); or an identifier in a
    non-tracking query value of a URL that is not itself a search
    (`?jk=…`, never `?q=…&ved=…`); or a posting host (AA's ATS registry). An
    identified item with no posting word scores path 0.5. On the 97
    captures (C): Indeed now yields its 14 real cards; LinkedIn's closed
    posting yields its 10 similar postings instead of 25 "X jobs" category
    links; Apple's careers page, read as no list before, yields its 20
    postings; Google's plain web results (category pages) are no longer a
    *posting* list (T `test_related_searches_are_not_the_job_list_real_cards_are`,
    `test_specific_destination_names_one_item_not_a_search`).
41. **(family 0.3.0) A list of job-related results is still a result list.**
    The page family used the gate's share; with 40 a Google page of
    category results would have become `unknown`. When the gate abstains,
    the family now uses `joblist.job_related_list` (the pre-0.3.0 reading,
    without the specificity test), so page kinds are unchanged on all 97
    captures while discovery gets the stricter list.

## 4a. Opaque links solved as record linkage (owner ruling 2026-11-04: opaque routes count)

**The problem, restated.** A Google `/goto?url=CAES...` link cannot be
decoded, and its token changes per page load. Visiting resolves it, but a
visit costs time and footprint, and a queued visit may meet an expired token
(**unverified**: the token lifetime has not been measured live).

**The observation that changes it.** The page still leaks part of the
destination: the breadcrumb under the result shows host and path start. On
the site-restricted capture, 6 of Google's 8 results show a 12–14 character
hex posting ID (`› 4151651bd442-senior-backe...`). That ID is about 40
usable bits. Brave and Yahoo, running the same search, return direct URLs
carrying the same IDs.

**The mathematics** (`linkage.py`, Fellegi–Sunter record linkage with
likelihoods derived from token entropy instead of fitted):
`W = Σ log2 P(agree|same)/P(agree|different)`, in bits. An ID agreement
adds its entropy (alphabet × shown length − 8 bits for non-uniform IDs).
Differing IDs subtract 30. Title similarity adds or subtracts at most 6.
Comparisons happen only within the same host. On a multi-tenant ATS the
subdomain is the company, so `zact-inc.breezy.hr` is never compared with
`onedome.breezy.hr`.

**No tuned threshold.** Over `n` compared pairs, the expected number of false
links is at most `n·2^-W`. Requiring it to stay ≤ ε gives
`W_min = log2 n + log2(1/ε)`. ε = 10^-3 is a risk level, not a score, and
the bar rises with the work done.

**One mechanism, four jobs:**
1. resolve an opaque link to a direct URL another page already showed;
2. de-duplicate across engines and URL variants (`/p/x` and `/p/x/apply`),
   so a posting is never vetted or applied to twice;
3. check arrival by ID, not only by host, so a redirect to another posting
   on the same host fails (`arrival_bits`);
4. tell reposts apart: same title, different ID.

**Evidence (C, T).** On the three site-restricted captures, Google's
zact-inc result links to Brave's direct URL at 43 bits against a 12-bit bar.
The inallmedia result shows no ID and Brave has two inallmedia postings, so
it correctly stays unresolved. The Volt Labs posting from Brave, Yahoo and
its `/apply` variant collapses to one. The 7 unresolved Google records still
carry their ID, and 5 of them already have a dedup key before any visit.

**What the engine does with it.**
* Link first, at zero network cost.
* Visit only what stays unresolved, and order those visits by value.
* After a visit, check `arrival_bits` against the record's ID.

Not done: learning a host's URL template from its direct examples, so a
candidate URL could be proposed from an ID alone. That would need
verify-on-use (domain memory, CT-FR-025).

## 5. Results on the owner captures (in-sample)

**These are replays, and the weights were set while looking at these pages.**
The figures are training-set figures, not generalisation. They guard against
regressions; they prove nothing about new sites.

* **Page family (v0.4).** 93 of 97 pages match the capture's category.
  Nine category labels are corrected, each with its reason in
  `tests/corpus_labels.py`: four from the screenshot (BambooHR, Avature,
  Comcast, Home Depot), three from the page's own text (Oracle email step,
  AT&T, energy.gov), two from the URL (JPMC posting, Yahoo results). The 4 misses are listed in
  `test_corpus.py::KNOWN_MISSES`:
  * 3 abstentions (`unknown`, the safe answer);
  * 1 **confident miss**: a marketing page's demo-request form read as an
    application form.

  That is 1.03% wrong-and-confident, just over **CT-NFR-008's ≤ 1%**. The
  two Workday choosers are fixed by the `application_entry` family
  (correction 20).
* **EC-41 fixed.** No search-results page reads as an application form. AA's
  verdict at capture time called both Google pages `APPLICATION_FORM` (C:
  each capture's `meta.json`).
* **Google `/goto`.** Every organic result on the site-restricted Google page
  is an `opaque` route whose expected host comes from the breadcrumb
  (`*.breezy.hr`). Titles are clean.
* **Brave.** Titles are the title line, not the breadcrumb-bearing link name.
* **SmartRecruiters.** The application form lives in open shadow roots; AA
  sees zero fields on it today. v0.1 reads ≥ 20 controls there with labels
  from `label[for]` inside each shadow scope.
* **BambooHR.** The reCAPTCHA is classed `embedded`, not a block. Required
  and optional fields match the screenshot, and the "Please leave this field
  blank" honeypot is `TRAP`.
* **Memory (M).** 54 B/node on the SmartRecruiters pierced DOM (12,080
  nodes) and 98 B/node on the BuiltIn Chicago HTML (6,886 nodes). The
  blueprint targets ≤ 100 B/node; AA's object tree measured about 360.
* **Time (M, v0.4, all 13 tools).** Median 0.042 s, p95 0.28 s, max 0.37 s
  per page (SmartRecruiters, 12,080 nodes); loading plus parsing: median
  0.018 s, p95 0.10 s. Synthetic scaling (`python -m pagecomp bench`): a
  27,277-node result list takes 0.19 s to parse plus 0.40 s to analyse,
  about 234 bytes/node peak including every analysis structure.
* **Owner's laptop (L, 2026-11-08).** About 3.5-4× slower than the build
  machine: T(n) = 0.123 s + 98.5 µs/node, 230 bytes/node. Pages up to
  8,900 nodes meet the 1.0 s target; the 3.0 s ceiling allows 29,000
  nodes (about 7.6 MiB), so AA's laptop config uses `max_nodes: 29000`
  (correction 25). Predicted there for the 97 captures: median page
  (1,589 nodes) 0.28 s, p90 (6,928) 0.81 s, largest (12,899) 1.4 s. The
  bench ran with no browser open; on 2 CPUs a running Chrome competes for
  the same cores, which the ceiling's margin over the largest real page
  (2×) is there to absorb. Tests pass on Python 3.10, 3.11, 3.13 and 3.14.
* **Worst-shaped inputs (M, v0.4.2).** Within the 8 M input cap the
  slowest shapes are 8 MB of comments (about 1.0 s) and a single start tag
  holding a million attributes (1.1-1.3 s; most of it inside the standard
  library's tokenizer). Expect 3.5-4× that on the owner's laptop. Real
  pages are far from these shapes.
* **Robustness (T).** Every tool survives 55 fuzz runs in strict mode (any
  exception fails): 40 hostile tag-soup pages and 15 malformed DevTools DOM
  payloads. A 500-unit budget yields `Timeout`/`Abstain`, never a hang;
  every tool is deterministic on the corpus; no trace carries page text or
  URLs. `mypy` (Python 3.10 target) reports no issues in 37 files.

## 6. Bible conformance

| Bible item | Status in v0.1 | How / gap |
| --- | --- | --- |
| §1.1 worst-case user (2 GB, no admin, no keys, maybe offline) | met by design; measured (L) | stdlib only; no network; caps; bounded cache. Laptop: 29,000-node cap at 3 s and about 7.6 MiB; the largest real page about 1.4 s (section 5). Python 3.10-3.14. |
| §1.2 SoC / SRP | met | one concern per tool; `pagetext` and `posting_path` are shared, not duplicated |
| §1.2 single source of truth | partly | parameters live in one `ParameterSet`. The library holds its own defaults; **AA must pass `runtime_defaults.yaml` values in** (rule 2) — section 7 step 3. The posting-host list comes from AA's ATS registry, never from the library. |
| §1.2 DRY | partly | one structural vocabulary in the library. Until AA's `structural_hashing`, `url_evidence`, `form_fields` and `page_assessment` become shims, two copies exist: section 7 step 5 retires them. |
| §1.2 hexagonal / dependency inversion | met | library ← AA adapter; T `test_boundary` |
| §1.2 agnostic implementations | met | no site names in tools; ATS hosts come in as a parameter; browser facts arrive only as capabilities |
| §1.3 rule 1 (no infra/adapter imports in domain) | met | the library imports nothing from AA |
| §1.3 rule 2 (no default overriding YAML) | **open** | needs the YAML keys and the adapter (section 7 step 3) |
| §1.3 rule 3 (browser lease) | n/a here | the library never touches a browser |
| §1.3 rule 4 (engines never call each other) | met | the library has no engine knowledge |
| §1.3 rule 5 (no MathDiscoveryProvider) | met | findings only, no provider logic |
| §1.3 rule 6 (absolute imports) | met | T `test_boundary` |
| §9 math subsystem is a page-analysis toolkit | met | this library is that toolkit |
| §22.3 extensibility checklist | partly | port/adapter, YAML keys and the Bible update land with the integration slice |
| §23 Pydantic | by design | library values are frozen dataclasses: pure algorithm outputs, §23.3. AA's adapter maps them into AA's Pydantic models (`WebpageStructure`, `UIModel`) at the boundary, which is where §23.2 applies. |
| §24 hardcoded values | met inside the library | every threshold is a declared `ParamSpec` with bounds; safety thresholds are locked |
| §26 sans-IO | met | the whole design |
| §16 CAPTCHA policy | met | detection only; the verdict separates `gated` from `embedded`; handling stays in AA policy |

## 7. How AA adopts it (slice S6, small steps, each reversible)

1. **Vendor the library.** Add it as `packages/pagecomp/` with its own
   `pyproject`. AA depends on it; it never depends on AA.
2. **AccessPort adapter in AA.** Use `browser_page_snapshot` →
   `observe_html` as the default. Where Chromium exposes CDP
   (`execute_cdp_cmd`), use `DOM.getDocument(depth=-1, pierce=true)` →
   `observe_cdp`, which is what makes shadow-DOM forms visible. Each
   observation carries `requested_url` (from `ResilientDriver._requested_url`,
   which `fix_universal_arrival.py` adds), `query` (the search words AA
   already holds) and an `epoch` that AA increments on every action.
3. **Parameters from YAML.** Add a `comprehension:` block to
   `runtime_defaults.yaml` holding exactly the `ParamSpec` names, and build
   the `ParameterSet` from it with `with_overrides(..., reason="runtime_defaults.yaml")`.
   Pass `joblist.posting_hosts` from AA's ATS registry (§15), so the registry
   stays the single source.
4. **Behind one key.** Add `perception.engine: legacy | pagecomp`, default
   `legacy` until the owner's live run passes (13 s3). Map consumers:
   * Discovery: `joblist` → candidates. `opaque` routes are visited as-is,
     and after arrival AA calls `links.arrival_integrity(expected_host,
     landed_url)`; on `False` it drops the candidate and records why. This is
     resolution ladder option C, with no out-of-browser request.
   * Vetting: `family`, `verdict` (closed/applied), `structured`.
   * Applications: `formread` → one filler (problem 3). `decision == FILL`
     only. `sensitive` fields take only the user's explicit answers (owner
     ruling). `UNKNOWN` requiredness is filled if data exists, otherwise
     asked, never skipped.
   * One page verdict: replace the five "page usable?" checks (LR-18) with
     `family` and `verdict`.
5. **Retire duplicates.** Once the key flips, AA's `url_evidence`,
   `navigation_landing`, `page_assessment`, `challenge_assessment`,
   `form_fields`, `label_input_pairing` and `structural_hashing` become thin
   shims over the library (CT-FR-030), then are removed with `retire.py`.

## 8. Not built yet (work list for the next passes)

Ordered by what unblocks a live application. Each item names its acceptance test.
**Status after v0.4 (2026-11-05):** item 6 done (correction 18), item 9 done
(correction 20); everything else as the S3/S5 pass left it. Previous status:
Status after the S3/S5 pass (2026-11-05): **1 open, 2 done (layout capability
built; visibility reads computed style; geometric residual pairing and XY-cut
still open), 3 half (error mapping done in `transitions.map_errors`;
SubmitPredictor open), 4 done for diff, settle and window set (pure parts;
AA wiring open), 5 half (DocDiff done; region-scoped re-read exists as
`ObservationRequest.region_root` on the script rung only), 6 open, 7 open,
8 open, 9 open, 10 done (pure loop, `transitions.ConditionalLoop`), 11 done
(pure, `transitions.map_errors`; "press Next only" is the engine's rule and
is not enforced here), 12 open.**

1. **Widgets and option lists (CT-T-014/015).** BambooHR's State and Country
   are custom dropdowns with no native or ARIA control, so they are not seen
   at all (C: bamboohr screenshot vs `formread`). Accept: those two
   questions appear as `choice` with their options. A recorded open-dropdown
   observation exists in `form-dropdown-open/`.
2. **Layout capability.** `SNAPSHOT_LAYOUT` (CDP `DOMSnapshot`) for
   computed style and boxes. That gives true visibility (CSS-class hiding is
   invisible today: `visible-unproven`), geometric residual pairing, and
   XY-cut regions (CT-ALG-005). Accept: the trap tests pass with class-based
   hiding, and the residual pairing uses distance in em.
3. **Submit prediction and error mapping (CT-T-026, ALG-011/012).**
   Advisory only; `UNKNOWN` counts as will-submit.
4. **Steps and transitions (CT-T-016).** Next/back/final classification
   exists on buttons; diff, settle and window events do not.
5. **Incremental re-read.** Region-scoped observation and DocDiff, so a
   typed character does not re-parse the page.
6. **Records with gaps** (`allow_gap = 1`: an ad between cards) and merging
   split lists. Indeed splits its cards across several runs; `joblist.others`
   lists them, but nothing merges them.
7. **A held-out gold set** (09 s8) before any weight is fitted, and before
   any accuracy figure is quoted outside this file.
8. **Locales.** The phrase tables and field lexicons are English. Structure
   does not depend on them (CT-NFR-021); recall on non-English pages does.
9. **Application entry steps.** Workday's "Start Your Application" chooser
   (autofill / apply manually / last application) is neither a posting nor
   a form. It needs its own family or a step finding, with the choice
   buttons as an operation plan. Accept: both Workday captures leave
   `KNOWN_MISSES`.

10. **Conditional fields (owner report: answers reveal fields).** Design:
    a fixpoint loop over question **keys**, not node indexes, which change
    between observations. A key is (form-root path, name, id, label).
    * Let `F_t` be the visible questions at epoch t.
    * After each action on a *choice* question q (radio, select, checkbox,
      combobox), re-observe the form region and diff: `Δ+ = F_t+1 \ F_t`
      are revealed (record the edge q → Δ+ in the trace, and later in
      domain memory); `Δ− = F_t \ F_t+1` are withdrawn (drop their values).
    * Insert revealed questions right after q in the agenda.
    * Terminate when the agenda is empty. Cap the rounds at `|F| + 10`.
      Stop and hand to the human if a (questions, answers) state repeats,
      since that is a cycle.
    * Text inputs do not trigger a re-read, except comboboxes.
    * Accept: a recorded before/after pair (choose "Yes" → a follow-up
      field appears) is read as one revealed question after one round.
11. **Requirements revealed only on submit (owner report).** Pressing a
    *final* submit to discover requirements stays forbidden: it submits
    when validation passes (ADR-012). Design:
    * Fill what the profile answers, and ask for what it doesn't.
    * Press "Next" on step pages (non-final, permitted).
    * After any attempt, diff the before and after observations. Map new
      `role=alert` / `aria-live` / `aria-invalid` / `aria-errormessage` /
      error-lexicon nodes to their control by the CT-ALG-012 ladder.
    * Then generalise from the first mapped error. Its subtree skeleton
      (ALG-001) is the form's error template. Every other new node whose
      skeleton is within τ of it is also an error, even with no word from
      the lexicon. That is how a form's own convention is learned on one
      page, and why the owner finds it easy to spot by eye.
    * Accept: each recorded failed attempt maps every visible error to a
      field, and unmapped errors are reported, never dropped.
12. **Kernel fit.** The tool unit is `run(tool, observation) -> Ok |
    Abstain | Timeout`: pure, content-keyed, needing no browser lease. It
    maps onto a `WorkUnit` with these lifecycle states: COMPLETED,
    SKIPPED/WAITING_HUMAN, RETRY_SCHEDULED. `Stale` means re-observe.
    Opaque routes that linkage cannot resolve fit the existing
    `RESOLVE_JOB_URL` task (it already navigates when a driver is present),
    carrying `expected_host` and the shown ID as its postcondition.

## 8a. Slice status (10_gap_analysis s3), library side

| Slice | What exists now | Still open |
| --- | --- | --- |
| S0 measure and cap | `bench`: synthetic list/form/shadow/deep pages; untraced timing plus a separate memory pass; linear cost models; cap derived from budgets; invalid runs refused; target vs ceiling (correction 25). Per-attribute and every other cap with a truncation flag. **Run on the owner's laptop 2026-11-08 (L)** | put `max_nodes: 29000` into AA's YAML (S6) |
| S2 records | skeleton multisets, sibling runs with consensus, gap bridging, list-of-lists demotion, menu rule, ranked output, split-list merge, Lemma 1–2 property tests | recall on ANCHOR with intervals (needs the held-out set); live regression on Bing |
| S3 access | done in the cloud pass (see corrections 10–14) | Selenium/Firefox runs; the busy-loop window |
| S5 transitions | done (pure) in the cloud pass | AA-side window and settle adapters |
| S6 standalone library | stdlib only, typed (`py.typed`, mypy clean), `python -m pagecomp`, `pyproject` script entry, absolute imports, boundary tests | vendoring into AA (section 7) |
| S7 memory and tuning | `memory.DomainMemory` (ALG-020: verify on every use, quarantine at 2, 30-day expiry, renewal after 3, LRU 2,000, JSON, snapshot hash); `tuning.Tuner` (ALG-019: exact sign test over discordant sites, Holm, Newcombe non-inferiority, held-out split by site hash, ≤ 10% step, cooldown 5, rollback, safety locked, no change on thin evidence) | the trace corpus to feed it; AA persistence path |
| S8 Workbench | review mode: `workbench.review_html` (tools used/unused, engines' stages, findings), `classify_failure` (ALG-026), ledger counts; `python -m pagecomp review` | Explore mode (live, AA-side) |
| S9 capabilities | Source Channel seam: RSS, Atom, sitemaps (DOCTYPE/ENTITY refused), robots `Sitemap:` lines | vendor APIs (catalog, AA-side) |
| S9a filters and toolbars | `controls` (CT-T-027): select, checkbox/radio groups, switch, menu button, listbox, slider/range, chip, pagination kinds, search and location boxes; consent controls excluded; `effect` (ALG-027): APPLIED / NO_EFFECT / CONTRADICTED / UNKNOWN / RESET, count mismatch, one-key parameter candidate, two-query promotion | the keyboard slider operation and live verification on three sources (AA-side) |
| S9b alternate views | `views` (CT-T-028): canonical/mirror, feeds, AMP, print, language, embedded/own URL, JSON-LD, guest view, record key; `viewmath` (ALG-028/029): equivalent/compatible/distinct, kept disagreements, cheapest verified public view, seeded re-verification sample | ViewTemplate learning on `n_min` records (store exists in `memory`); live choice of a cheaper verified view |

## 9. Protocol for the three-reviewer loop

To keep each pass checkable, every reviewer:

1. Runs `python -m pytest -q` with `PAGECOMP_CAPTURES` set and pastes the
   last line. A pass that changes behaviour adds or changes a test that fails
   before and passes after.
2. Never loosens `KNOWN_MISSES` or `corpus_labels.py` to make a change pass.
   A label change needs a reason from the screenshot, written next to it.
3. Keeps the boundary tests green: stdlib only, no `auto_apply`, no clock,
   file or network in `tools/`.
4. Records any correction to the comprehension suite in section 4 of this
   file, with its evidence.
5. Leaves no AI or tool attribution in code, commits or docs (owner rule).

## 10. Owner rulings (2026-11-04)

1. Opaque routes count as routes. Linkage resolves them where it can;
   otherwise the visit resolves them (section 4a).
2. Unmarked fields in a form that marks required with `*` lean OPTIONAL
   (`w_unstarred = -2.5`, the default).
3. A held-out batch of about 30 pages from sites not in the 97 is coming.
   It is used for measurement only, never for setting weights.

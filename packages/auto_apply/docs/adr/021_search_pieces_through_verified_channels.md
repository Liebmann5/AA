---
title: "ADR-021: Applying Each Piece of a Search Through a Verified Channel, and Checking Results Against the Search AA Built"
status: needs-review
last_verified: 2026-10-30
verified_against: "live runs 2026-10-30 (sessions 8335d23d, d4c17fc3, 5f9566fd), hand-run engine checks 2026-10-30, domain/services/query_composer.py, domain/services/search_planner.py, application/services/auditing/discovery_verification.py"
audience: contributors
---

# ADR-021: Applying Each Piece of a Search Through a Verified Channel, and Checking Results Against the Search AA Built

**Status:** Proposed — design recorded, nothing built `[PLANNED]`
**Date:** 2026-10-30
**Deciders:** Nicholas Liebmann
**Builds on:** [ADR-019](019_search_surface_catalog_and_query_builder.md), [ADR-020](020_automated_site_search.md)
**Companion:** [ADR-022](022_every_page_identified_bounded_recorded.md) (every page AA reaches is identified and recorded)

This record states a requirement and a proposed shape. It is written before the
code on purpose: the first live runs of automated site search (2026-10-30)
showed that the search side of AA assumes things nobody checks, and the
requirement is larger than any one fix. The implementer who builds it rules the
open questions at the end, against
[ENGINEERING_PHILOSOPHY.md](../ENGINEERING_PHILOSOPHY.md), and may overrule the
proposed shape with reasons.

## Context

### A search is made of pieces, and each piece can travel by more than one route

Every search AA runs — on a search engine, a job board, an ATS host or a
company's careers page — is a bundle of separate pieces of the user's intent:

| Piece | Example |
| --- | --- |
| Job title or keywords | `Backend Engineer` |
| Exact phrase | `"Backend Engineer"` |
| Words to exclude | `-intern` |
| Site or platform restriction | `site:jobs.jobvite.com` |
| Location | `Chicago, IL` |
| Workplace type | remote / hybrid / on-site |
| Date posted | last 24 hours, last week |
| Employment type, seniority, salary, company, language | where a surface offers them |

A single piece can reach a surface by several different **channels**, and which
ones work differs per surface, per piece, per value, per region and over time —
and is sometimes undocumented because the surface's code is proprietary:

1. **Typed into the query** as words or an operator (`site:`, quotes, `-`).
2. **A URL parameter** (`l=Chicago` on a job board, Google's time filter, which
   exists only as a URL parameter).
3. **The site's own search box**, typed the way a person types — the natural
   channel on a job board such as Indeed.
4. **A filter control on the results page** — menus, toolbars, chips,
   checkboxes, drop-downs. A company careers page often has no search box at
   all, only a menu of locations or departments to pick from.
5. **Not applicable on this surface** — the piece is then applied later, in
   vetting, or the user is told it could not be applied.

### What was measured on 2026-10-30

Five searches were run by hand in an ordinary browser to see what each engine
does with a Jobvite site restriction:

| # | Query | Results on `jobs.jobvite.com` | What came back instead |
| --- | --- | --- | --- |
| 1 | Google: `site:jobs.jobvite.com ("Backend Engineer") Chicago, IL` | none | Indeed listing pages |
| 2 | Bing: same query | none | generic pages (geeksforgeeks, roadmap.sh, Wikipedia) |
| 3 | Bing: `site:jobs.jobvite.com "Backend Engineer" Chicago` | none | the same generic pages |
| 4 | Bing: `site:jobs.jobvite.com "Backend Engineer"` | none | Lever postings — the restriction was ignored |
| 5 | Google: `site:jobs.jobvite.com "Backend Engineer"` | all | — |

Three live sessions the same day agree:

- Session `8335d23d`: Google and Bing were sent query 1 and its Bing twin,
  exactly as previewed. Neither result page held Jobvite postings; a click on a
  generic Bing result opened roadmap.sh.
- Session `5f9566fd`: with the location left out (commit `9243714`), Google
  returned only Jobvite postings for `("Fullstack Engineer")`, and mixed results
  for `("Backend Engineer")`. The hand-run check 5 used the phrase **without**
  parentheses; whether the parentheses matter is unmeasured.

So, measured:

- **Words after `site:` make Google drop the restriction.** A piece applied
  through one channel (location as typed words) silently voided another piece
  (the site restriction).
- **Bing does not honour `site:jobs.jobvite.com` at all**, with or without
  other words. Its `site` operator is vendor-documented in
  `resources/search_surfaces/bing.surface.yaml`, and Jobvite's restriction is
  recorded as measured for both engines in
  [verifying_platform_search.md](../developer_guide/verifying_platform_search.md).
  Evidence about a platform is not evidence about every engine that carries it.

### What exists today

| Piece of the system | Status | What it does |
| --- | --- | --- |
| Search-surface catalog (`resources/search_surfaces/*.surface.yaml`, `domain/models/search_surface.py`) | `[LIVE]` | Declares, per surface, its URL templates and parameters, and its typed operators with an evidence status (`vendor`, `measured`, ...) |
| Query composer (`domain/services/query_composer.py`) | `[LIVE]` | Builds every query in one place; refuses what a surface cannot carry instead of degrading it |
| Site-search planner (`domain/services/search_planner.py`) | `[WIRED]` | Plans site-restricted queries; admits only `measured`/`vendor` platforms |
| Off-platform drop (`application/workflows/discovery_workflow.py`, "off-shape hit dropped") | `[WIRED]` | Drops and counts a result that is not a posting of the platform searched — after it was found, never before a click |
| Discovery output check (`application/services/auditing/discovery_verification.py`, `DiscoveryVerifier`) | `[LIVE]` | Checks each harvest's output invariants: fields present, deduplicated, under the cap |
| Location stopgap (commit `9243714`) | `[LIVE]` | Locations are no longer typed into site-restricted queries; the preview says so; vetting checks the location |

### What is missing

1. **Evidence per surface × piece × channel.** A platform is "measured"
   globally; nothing records that one engine honours it and another ignores it.
2. **Knowledge of how pieces interact.** Nothing records that location words
   void a site restriction on Google.
3. **A check after the search that each piece actually held.**
   `DiscoveryVerifier` checks the shape of the output, not whether the results
   honour the search that produced them.
4. **A fallback ladder.** When a piece did not hold, nothing tries the next
   channel, and nothing decides whether the search is still useful without it.
5. **User-interface channels.** Search boxes and filter controls on results
   pages and careers pages are not channels at all yet.
6. **Provenance of channels.** A job records the query that found it
   (ADR-020 decision 8), but not which piece travelled by which channel and
   whether it held — the evidence a researcher needs to trust the sample.

## Decision (proposed)

### 1. One capability with two halves: apply, then verify

Applying a piece and verifying that it held are one capability, used by every
engine and by company-page mining. No provider, adapter or workflow formats or
checks a piece on its own.

### 2. Channels are data, in the catalog that already exists

The catalog grows, per surface and per piece, an **ordered list of channels**,
each with:

- its evidence status (`vendor`, `measured`, `reported`, `unverified`) and
  date — for a platform restriction, **per engine**, not per platform;
- the value forms it accepts (free text, a fixed list read from the page, a
  date range);
- known **interactions** — for example, on Google, "typed words after `site:`
  void the site restriction" (measured 2026-10-30).

There is one source of this knowledge. No second registry is created. Evidence
changes only through the human checklist in
[verifying_platform_search.md](../developer_guide/verifying_platform_search.md);
the running program never rewrites the catalog, so a seeded run and its replay
stay comparable (ADR-020 decision 4).

### 3. Choosing a channel

For each piece, one channel is used at a time, chosen in this order:

1. the **user's own search settings** — the user's choice of tool and surface is
   sovereign (philosophy: AA accommodates every user);
2. the strongest evidence;
3. the lowest cost — no extra page load or request when the channel can be
   applied in the request itself (worst-case user on a metered connection);
4. no interaction with a piece already applied.

A piece is never applied twice through two channels at once.

### 4. Verification from the search AA built

The verifier derives its expectations from the request AA itself built — the
`QueryRequest` / planned query, the surface's known restrictions, and the
user's saved criteria — and judges the results against them, piece by piece:

| Piece | Expectation checked against the results |
| --- | --- |
| Site / platform | Every result's host matches the restriction (the off-platform drop already measures this per result) |
| Location | Result locations match the place, a recognised equivalent, or remote where the user accepts remote |
| Title / phrase | Result titles contain the phrase or a close match |
| Date posted | Posted dates fall in range where the page shows them |
| Other filters | Whatever the result card or page exposes |

Each expectation yields **held**, **not held**, or **not observable** (the
page does not show the evidence — never guessed). Judgement is made over the
harvest, with thresholds, deterministically, from a snapshot — so it runs again
on the replay path from kept page copies with no browser.

### 5. Fallback, and deciding whether the search still worked

When a piece did not hold, the verifier distinguishes:

- **the search still served its purpose** — for example, the site restriction
  held but the location did not: keep the results and apply the location in
  vetting. Asking the page's filter controls would cost requests and gain
  nothing.
- **the search failed** — for example, the site restriction did not hold: the
  harvest is not what was asked for. Discard it (counted, never laundered),
  then try the next channel for that piece (a filter control, another engine
  whose evidence is stronger), or end the attempt with a plain-words note.

Attempts are bounded and count against the session budget (ADR-020 decision 4);
every contact is paced by `HostPacer`; a challenged surface is benched
(ADR-020 decision 6). A channel that fails verification is benched for the rest
of the session, the same way an engine is.

### 6. Careers pages use the same model

A company careers page with no search box but a menu of locations is a surface
whose location channel is "pick from this list". Page understanding finds the
control and its options; the value the user gave is matched to a listed option
(or reported as not offered); the shared interaction tool applies it; the
listing is re-read to verify. The same apply-then-verify capability serves it.

### 7. Research and provenance

Per query, the record holds which channel carried each piece and whether it
held — names and outcomes, never the words searched for (ADR-020 decision 9),
behind research consent. A results export can say how far each search honoured
the user's intent.

## Proposed home

The implementer confirms or overrules this with reasons:

| Part | Proposed location | Why there |
| --- | --- | --- |
| The verifier: (request AA built, observed results) → verdict per piece | `domain/services/search_result_verification.py` (new) | Pure, deterministic and replayable, beside `search_planner.py` and `page_assessment.py` |
| Channels, evidence per engine, interactions | `domain/models/search_surface.py` and `resources/search_surfaces/*.surface.yaml`; per-engine restriction evidence with the ATS descriptors in `resources/ats/` if that reads better | The catalog already is the one source of what a surface accepts |
| Choosing a channel, applying it, running the verifier, falling back | `application/services/search_application/` (new package) | Application layer; applies UI channels only through the shared interaction tool in `application/services/page_action/`, never by touching the driver |
| Where it runs | `DiscoveryWorkflow`, after each harvest, beside `DiscoveryVerifier`; company-page mining for careers pages | The two places searches happen |

## Edge cases to design for

- An engine rewrites or loosens the query and says so ("Showing results for",
  "Did you mean"), or says nothing at all (Bing, measured).
- AI answers, overviews, ads, sponsored results and aggregator widgets (an
  Indeed box) inside an otherwise restricted result page.
- Partial honouring: some results on the platform, some not.
- Zero results: the restriction held and nothing matches, versus the
  restriction was dropped — a different outcome with a different next step.
- Regional hosts and redirects (`google.de`, Bing's `rdr=1`) that change
  behaviour.
- Location synonyms and shapes: `Chicago, IL`, `Chicago`, `Chicagoland`,
  "Remote (US)", multi-location postings, remote roles tied to a place.
- Relative dates ("3 days ago") and missing dates.
- Filter controls that take only values from a fixed list; filters that change
  the URL and filters that do not; filters that need an Apply button; filters
  that reset pagination or switch to infinite scroll.
- The user's own raw query: verify only what can be read from it; never rewrite
  it.
- Non-English interfaces: channel controls are found by structure, not by
  English label text.
- Consent banners and challenges in front of the results (ADR-020 bench,
  ADR-022 verdict).
- Worst-case user: verification must read what is already on the page; it never
  costs an extra page load when the evidence is present.

## Options considered

**Per-provider fixes for each surface's quirks.** Rejected — knowledge scattered
across provider files, the defect ADR-004 and ADR-019 removed.

**Learning channels at run time and rewriting the catalog.** Rejected — a run
would change the next run's behaviour invisibly, and a seeded run could no
longer be replayed. A session may bench a channel; only the human checklist
changes evidence.

**Verifying only the platform (today's off-platform drop).** Rejected as the
end state — it misses location, dates and every other piece, and it acts after
clicks, not before.

**Applying every piece through every available channel at once.** Rejected —
pieces interact (measured), requests multiply, and the result cannot be
attributed to a channel.

## Consequences

- Easier: a search can say, per piece, whether it held; research samples carry
  their own precision; a broken surface is found by the run, not by a person
  reading screenshots.
- Harder: every channel needs evidence and every piece needs an expectation the
  page can show. Pieces whose evidence is never on the page stay "not
  observable", honestly.
- **Not part of the first submission.** The first submission needs only the
  stopgaps already in place (location, engine choice) and the discovery fixes
  listed in the Bible's issue register (§21, LR rows). This record is built
  after it.

## Open questions for the implementer

1. The thresholds for "held" over a harvest, and whether they are per piece.
2. How interactions between pieces are represented in the catalog.
3. Where per-engine restriction evidence lives: the engine's surface file or the
   platform's ATS descriptor.
4. Whether location verification belongs here or stays entirely in vetting's
   location filter, with this capability only reporting.
5. Whether the parentheses the composer adds (`("Backend Engineer")`) change
   Google's behaviour — measure before deciding.

## References

- [ADR-019](019_search_surface_catalog_and_query_builder.md), [ADR-020](020_automated_site_search.md), [ADR-022](022_every_page_identified_bounded_recorded.md), [ADR-004](004_ats_platform_registry.md)
- [verifying_platform_search.md](../developer_guide/verifying_platform_search.md)
- [STATUS.md](../STATUS.md) — readiness of automated site search
- [AA_ARCHITECTURE_BIBLE.md](../AA_ARCHITECTURE_BIBLE.md) §21 — live-run findings LR-1 to LR-3

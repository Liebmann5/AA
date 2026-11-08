---
title: "Verifying Platform Search Data"
status: needs-review
last_verified: 2026-11-08
verified_against: "resources/ats/*.yaml as of the query-builder platform expansion"
audience: contributors
---

# Verifying Platform Search Data

Every platform descriptor in `resources/ats/` carries a `search_restriction`
with a status — `vendor`, `measured`, `third_party`, or `unverified` — a
source, and a date when measured. Most start `unverified`. This checklist is
how a person upgrades one, by hand, in a browser. Nothing in AA automates this.

## How to record an outcome

In the platform's YAML file:

- The query works as written → set `search_restriction_status: measured`,
  set `search_restriction_verified_on: "<today's date>"`, and set
  `search_restriction_source` to one line saying what you did
  (e.g. `"Hand-run on Google, 2026-11-02: results were all Jobvite postings"`).
- The query works only in a different form → fix `search_restriction` to the
  form that worked, keep the status `third_party` until a second run confirms
  it, and note the old form in the source line.
- The query does not work → keep `unverified` and say what happened in the
  source line. A wrong restriction is worse than an honest unverified one.

## What verification admits

A platform whose restriction reaches `measured` or `vendor` becomes eligible
for **automated** site-restricted search: it turns selectable in the session
wizards and the settings editor, and the planner may build queries for it.
(`third_party` and `unverified` platforms stay visible in the query builder —
a person can judge a label — but automation never plans them.)

Confirm admission without starting a session, offline:

```bash
python -m auto_apply --print-plan --platforms <name>
```

The preview prints the composed `site:`-restricted query the session would
send for that platform, per enabled engine — or says why none was planned.

## What each engine documents (read 2026-11-08)

Only the engine's own pages count as `vendor`. Everything else is
`third_party` until measured.

- **Google** ("Refine Google searches"; Search Central, "site: search
  operator"): quotes, `site:`, `-`, `before:`, `after:` and `filetype:`.
  `site:example.com` includes every subdomain (`www.`, `recipes.`); a path
  limits results to that URL prefix; Google says a `site:` search is not a
  complete list. `OR`, `intitle:` and `inurl:` are not on the current pages.
  `OR` with `site:` was measured on 2026-11-08 (`google.surface.yaml`).
- **Bing** ("Advanced search keywords", "Advanced search options"): `site:`
  works on a domain, a top-level domain or a directory "not more than two
  levels deep", and several sites can be grouped with uppercase `OR` in
  parentheses. Precedence is `()`, `""`, `NOT`/`-`, `AND`, `OR`, so `OR`
  terms go in parentheses. `intitle:`, `inbody:` and `inanchor:` take one
  term each.
- **DuckDuckGo** (help page, "advanced syntax"): `site:`, `-site:`,
  quotes, `intitle:`, `inurl:`, `filetype:`. `OR` is not documented (two
  words already mean either). The page says that when advanced syntax finds
  nothing it shows related results instead, and that some advanced syntax
  "isn't operating 100% correctly".

What follows for verification: an engine can **silently** widen a search
(Bing answered `site:jobs.jobvite.com "Backend Engineer"` with 3,090
Greenhouse postings on 2026-11-08, while honouring `site:jobs.gohire.io`
the same day). A query "works" only when the results are on the platform.
Count them; do not trust a non-empty page.

## How to measure (owner's browser, aa_capture)

1. Type the query exactly as the table below gives it, on google.com and
   then on bing.com (web results, not a jobs tab).
2. Capture each results page with `aa_capture.py` (label
   `serp-site-restricted`), upload the captures, and record them here.
3. The measurement is the share of organic results whose address is on the
   platform's hosts (`hosts:` in the descriptor), read by pagecomp. All on
   the platform → `measured` for that engine; some → note the share; none
   → the engine does not honour the restriction for that platform.

## Two measurements that apply to many platforms

1. **Subdomain tenancy + shared path.** For platforms like BambooHR
   (`<company>.bamboohr.com/careers`), check whether
   `site:bamboohr.com/careers ("Software Engineer")` on Google actually covers
   the tenant subdomains, or whether `site:bamboohr.com inurl:careers ("Software Engineer")`
   is required. Record which form worked in the descriptor.
2. **Bing's two-level limit.** Bing documents `site:` as working only to two
   directory levels. For restrictions with a path (`jobs.gusto.com/boards`),
   paste the same query into Bing and check whether results come back at all;
   if not, that platform's Bing searches stay host-only.

## Per-platform checklist

For each platform: paste the Google query, then the Bing query. A correct
result shows only postings from that platform's hosts.

| Platform | Paste into Google | Paste into Bing |
|---|---|---|
| greenhouse | `site:boards.greenhouse.io ("Software Engineer")`, then `site:job-boards.greenhouse.io ("Software Engineer")` (the newer board host: every Greenhouse posting Bing returned on 2026-11-08 was on it) | same, on bing.com (web results) |
| lever | `site:jobs.lever.co ("Software Engineer")` | same |
| workday | `site:myworkdayjobs.com ("Software Engineer")` | same |
| icims | `site:icims.com ("Software Engineer")` | same |
| taleo | `site:taleo.net ("Software Engineer")` | same |
| ashby | `site:jobs.ashbyhq.com ("Software Engineer")` | same |
| bamboohr | `site:bamboohr.com/careers ("Software Engineer")` + the `inurl:careers` variant | host-only variant |
| rippling | `site:ats.rippling.com ("Software Engineer")` | same |
| workable | `site:apply.workable.com ("Software Engineer")` | same |
| smartrecruiters | `site:jobs.smartrecruiters.com ("Software Engineer")` | same |
| jobvite | `site:jobs.jobvite.com ("Software Engineer")` — measured (reported 2026-10-27); holds only with no other words in the query (measured 2026-10-30) | **not honoured** — measured 2026-10-30: Bing returned other sites with and without extra words |
| recruitee | `site:recruitee.com ("Software Engineer")` | same |
| gusto | `site:jobs.gusto.com/boards ("Software Engineer")` | host-only variant |
| pinpointhq | `site:pinpointhq.com ("Software Engineer")` | same |
| eightfold | `site:eightfold.ai ("Software Engineer")` | same |
| keka | `site:keka.com ("Software Engineer")` | same |
| dover | `site:app.dover.io ("Software Engineer")` | same |
| zohorecruit | `site:zohorecruit.com ("Software Engineer")` | same |
| jazzhr | `site:applytojob.com ("Software Engineer")`; repeat with `site:theresumator.com` | same |
| gohire | `site:jobs.gohire.io ("Software Engineer")` | same |
| recruiterflow | `site:recruiterflow.com ("Software Engineer")` | same |
| comeet | `site:comeet.com ("Software Engineer")` | same |
| saashr | `site:saashr.com ("Software Engineer")` | same |
| catsone | `site:catsone.com ("Software Engineer")` | same |
| adp | `site:workforcenow.adp.com ("Software Engineer")` | same |
| freshteam | `site:freshteam.com ("Software Engineer")` | same |
| careers-page | `site:careers-page.com ("Software Engineer")` | same |
| paylocity | `site:recruiting.paylocity.com ("Software Engineer")` | same |
| oasisrecruit | `site:oasisrecruit.com ("Software Engineer")` | same |
| jobscore | `site:careers.jobscore.com ("Software Engineer")` | same |
| crelate | `site:jobs.crelate.com ("Software Engineer")` | same |
| homerun | `site:homerun.co ("Software Engineer")` | same |
| loxo | `site:app.loxo.co ("Software Engineer")` | same |
| dayforce | `site:jobs.dayforcehcm.com ("Software Engineer")` | same |

## Not platforms (recorded so the absence is deliberate)

- **AP Recruit** (`aprecruit.berkeley.edu`) — one institution's own portal,
  not an ATS. A `site:aprecruit.berkeley.edu` engine query works without a
  descriptor; none is registered.
- **gitjobs.dev, techjobsforgood.com** — job boards, not ATS platforms. If
  their search URLs are verified, they become catalog surfaces
  (`resources/search_surfaces/`), not ATS descriptors.
- **Bing jobs vertical** — a catalog surface (`bing.surface.yaml`), retired by
  Bing in early November 2026 (the page moves itself to Bing's home page);
  see the Bible's issue register, LR-17.

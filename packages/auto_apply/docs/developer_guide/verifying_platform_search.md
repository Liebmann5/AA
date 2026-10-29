---
title: "Verifying Platform Search Data"
status: needs-review
last_verified: 2026-10-28
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
| greenhouse | `site:boards.greenhouse.io ("Software Engineer")` | same, on bing.com (web results) |
| lever | `site:jobs.lever.co ("Software Engineer")` | same |
| workday | `site:myworkdayjobs.com ("Software Engineer")` | same |
| icims | `site:icims.com ("Software Engineer")` | same |
| taleo | `site:taleo.net ("Software Engineer")` | same |
| ashby | `site:jobs.ashbyhq.com ("Software Engineer")` | same |
| bamboohr | `site:bamboohr.com/careers ("Software Engineer")` + the `inurl:careers` variant | host-only variant |
| rippling | `site:ats.rippling.com ("Software Engineer")` | same |
| workable | `site:apply.workable.com ("Software Engineer")` | same |
| smartrecruiters | `site:jobs.smartrecruiters.com ("Software Engineer")` | same |
| jobvite | `site:jobs.jobvite.com ("Software Engineer")` — measured (reported 2026-10-27) | same |
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
- **Bing jobs vertical** — already a catalog surface (`bing.surface.yaml`).

---
title: "ADR-022: Every Page AA Reaches Is Identified, Bounded and Recorded"
status: needs-review
last_verified: 2026-10-30
verified_against: "live runs 2026-10-30 (sessions 8335d23d, 5f9566fd), domain/services/page_assessment.py, adapters/secondary/discovery/components/card_activation.py, infrastructure/resilient_driver.py"
audience: contributors
---

# ADR-022: Every Page AA Reaches Is Identified, Bounded and Recorded

**Status:** Proposed — design recorded, nothing built `[PLANNED]`
**Date:** 2026-10-30
**Deciders:** Nicholas Liebmann
**Companion:** [ADR-021](021_search_pieces_through_verified_channels.md) (applying and verifying each piece of a search)

This record states a requirement and a proposed shape, written before the code.
It includes a **minimum slice** that the first submission needs, and a full
design for afterwards. The implementer rules the open questions against
[ENGINEERING_PHILOSOPHY.md](../ENGINEERING_PHILOSOPHY.md) and may overrule the
proposed shape with reasons.

## Context

### The one page verdict exists — but only answers when asked

`domain/services/page_assessment.py` is AA's single answer to "what is this
page?" `[LIVE]`. It reads a snapshot (URL, title, rendered HTML) and returns a
page kind: challenge, login wall, 404, already applied, closed, posting, form,
and so on, composed from `domain/services/challenge_assessment.py`. It runs on
the replay path with no browser, deterministically.

It is a pure function that callers ask at chosen moments — the Indeed provider,
the DOM observer, the perception adapter. **Nothing asks it every time the page
changes.** The web can move AA to a new page in many ways: a navigation, a
click on a link or a result card, a server redirect, a meta-refresh or script
redirect, a new tab or window, a pop-up, a 404 or 410, an expired-posting
redirect, a login wall, a download, a PDF viewer, `about:blank`. Each of these
is a moment where AA should know where it is before it acts again.

### What the first live runs showed (2026-10-30)

Session `8335d23d`:

- Discovery's card-activation step (`adapters/secondary/discovery/components/card_activation.py`)
  clicked Bing result cards to work out their links. It records only the
  **effect** of a click — navigation, DOM change, or none — and never asks the
  page verdict. One click opened roadmap.sh, a page with no job on it. Nothing
  identified it.
- From 22:57:35 a single browser command blocked for **87 seconds**, until the
  user pressed Stop. The health monitor logged "driver busy with another
  command" nine times and could not intervene. Navigation through
  `ResilientDriver.get` sets a page-load timeout (`infrastructure/resilient_driver.py:138`,
  a hard-coded 30 s, `_NAV_TIMEOUT_SECONDS`); the configured
  `page_load_timeout_seconds` is computed into the timing profile and read by
  nothing. Clicks, scripts and the other driver commands have no deadline at
  all.
- After Stop, clicks were still being attempted for about 20 seconds, including
  a synthetic JS-click fallback against a browser that was already closing.
- The log recorded how many cards were found and how many were resolved, but
  **not one URL** that was found or opened. The run cannot be audited.

Session `5f9566fd`: an activation click resolved a ZipRecruiter page during a
Jobvite-restricted search. ADR-020's off-platform drop removed it correctly —
after the click, not before it.

Earlier, on 2026-10-07: a LinkedIn `/authwall` page was judged usable and
re-visited about nine times, and an expired-posting redirect was treated as a
usable page.

### The map of where AA went

The Architecture Bible plans an `ExecutionMap` with heartbeats and a watchdog
that publishes `WORKER_STUCK` (§13.2, §27.4; register item P2-8) `[PLANNED]`.
The kernel refactor was removed from the task list on 2026-10-01 until AA has
submitted an application. The trail this record proposes is the data such a map
needs: an ordered record of every page AA reached, how it got there, and what
the page was. It is designed to work without the kernel, and to feed it later.

## Decision (proposed)

### 1. One checkpoint for every page change

After any action that can change the page — navigate, click, submit, key press
that submits, script, new tab or window — the shared interaction tool takes one
snapshot and asks `page_assessment` once. Callers act on the **verdict**, not on
raw effects. No caller re-implements "is this page usable?".

### 2. Every browser command has a deadline

Every driver command — not only page loads — runs under a deadline from one
configured place. The configured `page_load_timeout_seconds` reaches the
browser. A command that exceeds its deadline is abandoned under the driver
recovery policy and recorded as a **timeout step**; nothing waits without bound.
A Stop request is checked between steps, and no new browser command starts
after Stop.

### 3. Every page change is recorded as a step

Each step records: session, step number, trigger (navigate, click, redirect,
new tab, script), source page, destination URL, the verdict kind, and timings.
The ordered steps are the session's **navigation trail** — the map of where AA
went and how far it branched out from the page it started on. The watchdog
planned in Bible §13.2 reads the latest step's timestamp to find stuck work.

### 4. Tabs and windows are tracked

A click that opens a new tab or window is followed to it, the step recorded,
and AA returns to its working tab afterwards; tabs AA opened are closed. No
orphan tabs.

### 5. What discovery does with the verdict

In a site-restricted harvest (ADR-020), a card whose visible host is not the
restricted platform is dropped and counted **before** any click. A click that
lands on a challenge, login wall, 404, expired posting or a page that is not a
posting is recorded, AA returns, and the card is dropped with that reason.

### 6. Research and privacy

The full trail stays local, in the session record. Research receives, behind
consent, hosts and verdict kinds only — never full URLs that carry the user's
search words (ADR-020 decision 9).

## Minimum slice for the first submission

These are the parts the first submission needs now. They map to the Bible's
issue register rows LR-4 to LR-7:

1. A deadline on every browser command on discovery's card-activation path.
2. Card activation asks the page verdict and records the destination URL and
   verdict.
3. In a site-restricted harvest, off-platform cards are dropped before any
   click.
4. Every URL found, kept, dropped or opened during discovery is written to the
   log with its reason.
5. No browser command starts after Stop.

## Proposed home

The implementer confirms or overrules this with reasons:

| Part | Proposed location | Why there |
| --- | --- | --- |
| The checkpoint and the deadline | `application/services/page_action/` (the shared interaction tool, `PageActionService`) and `infrastructure/resilient_driver.py` | Every click and navigation already goes through them |
| The verdict | `domain/services/page_assessment.py`, unchanged | It is already the one verdict |
| The step record | `domain/models/navigation_step.py` (new), persisted with the session record | A small value type, replayable |
| Discovery's use of it | `adapters/secondary/discovery/components/card_activation.py` and `application/workflows/discovery_workflow.py` | Where the clicks and the off-platform decision happen |

## Edge cases to design for

- Redirect chains, and pages that change content without changing the URL
  (single-page applications, hash changes).
- A challenge inside an iframe.
- Downloads, `mailto:` and `tel:` links, PDF viewers, `about:blank`.
- A page that never fires its load event but is usable, and a page that fires
  it and then spins forever.
- Going back to a page the browser restores from its cache with stale content.
- The browser or driver dying in the middle of a step.
- Cross-origin new tabs and pop-up blockers.

## Options considered

**Leave each caller to check pages itself (today).** Rejected — the gaps are
where the 2026-10-30 hang and the roadmap.sh click happened.

**Browser network events via the Chrome DevTools Protocol.** Rejected as the
baseline — Chromium only, against the principle that the user's browser choice
is sovereign. It may be added later as an optional enhancement where available.

**A local proxy that watches traffic.** Rejected — it changes the user's network
set-up, which AA never does without knowledge and consent, and it is heavy for
the worst-case machine.

## Consequences

- Easier: every run can be audited page by page; a hang is a recorded timeout,
  not a frozen session; vetting and applying get the same protection as
  discovery.
- Harder: one more snapshot per page change, which costs time on the worst-case
  machine. The snapshot is the one the verdict already reads, so it is taken
  once and shared.

## Open questions for the implementer

1. The deadline per command type, and the recovery policy after a timeout.
2. Whether the snapshot is taken after every action or only when the URL, the
   window set, or the top-level document changes.
3. Where the trail is persisted (session report, job metadata, its own table)
   and how it is exported.
4. How this record feeds the `ExecutionMap` and watchdog of Bible §13.2 without
   waiting for the kernel refactor.

## References

- [ADR-020](020_automated_site_search.md), [ADR-021](021_search_pieces_through_verified_channels.md)
- [AA_ARCHITECTURE_BIBLE.md](../AA_ARCHITECTURE_BIBLE.md) §13.2, §21 (LR rows), §27.4
- [STATUS.md](../STATUS.md)


# ADR‑011: Discovery Pipeline Priority Bands

**Status:** Accepted  
**Date:** 2026‑07‑22  
**Deciders:** Nick Liebmann  
**Technical Story:** A full discovery run executed every search query before any result was vetted or applied to. The orchestrator was suspected of running a hardcoded "discover everything, then vet, then apply" batch, but tracing showed the cause was subtler: DISCOVER and VET `WorkUnit`s were both created at priority `5`. Because DISCOVER tasks are seeded up front and the work queue breaks priority ties oldest‑first, every discovery drained before the first vetting task even existed. The batch behaviour was a priority tie, not a structural limitation.

---

## Context

The agent orchestrator is a single, synchronous, priority‑queue event loop. It repeatedly pulls the most‑urgent pending `WorkUnit` — `get_next_task()` in the persistence adapter orders `WHERE status = 'PENDING' ORDER BY priority ASC, created_at ASC` — and dispatches it to the matching workflow. Lower priority numbers are more urgent.

Discovery is already search‑grained end to end: the session controller seeds one DISCOVER `WorkUnit` per `(title, location)` search, and the discovery handler processes exactly that one search across all providers, enqueueing one VET `WorkUnit` per unique job it finds. Vetting, in turn, enqueues an APPLY `WorkUnit` per approved job. The machinery for "one search → vet → apply → next search" is therefore already present; only the ordering was wrong.

At the time of this decision the relevant priorities were:

| Stage | Priority | Effect |
| --- | --- | --- |
| DISCOVER | `5` | seeded up front |
| VET | `5` | tie with DISCOVER → loses on `created_at` |
| APPLY | `1`–`11` (by fit score) | best‑fit first |

Because DISCOVER and VET tie, and all DISCOVER tasks are older, the queue drains every search's discovery before any vetting — the observed batch behaviour.

The execution‑mode system (`SessionExecutionMode`) already gates which stages run: `DISCOVER_ONLY` does not enqueue vetting at all, so it is already the exhaustive discovery‑only loop.

## Decision

Introduce a named, single‑source priority scheme for the discovery pipeline (`domain/models/task_priority.py`, class `TaskPriority`) with three separated bands, lower being more urgent:

- **APPLY** — `10`–`19`, fit‑ordered (`apply_for_fit(fit)`), best fit most urgent.
- **VET** — `50`.
- **DISCOVER** — `100`.

Because a discovered search's applications (`10`–`19`) outrank its vetting (`50`), which outranks the next search's discovery (`100`), the priority queue now interleaves on its own: each search flows discover → vet → apply before the next search is discovered. Applications remain fit‑ordered *within* their band, so within a single search the strongest matches are applied to first.

This is a **hybrid** of the two obvious orderings: per‑search pipelining across searches, best‑fit‑first within a search.

Direct user‑initiated and reactive work — resolving a pasted apply URL, handling a live CAPTCHA, scraping a user‑supplied careers page — keeps its existing priorities (`1`–`4`) and therefore stays *above* the discovery pipeline by design. The user's explicit requests and in‑flight blockers come first. This ADR governs only the discovery‑pipeline bands; it does not re‑home those separate, correctly‑more‑urgent priorities.

## Alternatives Considered

- **Strict per‑search, fit ignored.** Applications ordered purely by discovery order. Rejected: discards the existing, useful best‑fit‑first behaviour for no benefit.
- **Fit‑first global.** Best‑fit jobs applied first across *all* searches, with no per‑search guarantee. Rejected: contradicts the stated "one search → vet → apply → next search" goal and makes runs harder to reason about and reproduce.
- **Restructure the loop** so discovery drives vetting and application inline. Rejected: couples discovery to vetting, fights the priority‑queue architecture, and is far larger and riskier than a priority change for the same outcome.

## Consequences

- The pipeline interleaves per search by working *with* the priority queue — no loop rewrite, no new coupling. Small, readable, and reversible.
- Pipeline priorities are centralized and named in one module instead of scattered magic numbers; the ordering rationale lives with the constants.
- One test that pinned the literal DISCOVER priority (`== 5`) was updated to assert the named constant.
- `DISCOVER_ONLY` mode is unaffected and remains the exhaustive discovery‑only loop.
- The direct‑user and reactive priorities (`1`–`4`) are intentionally left in place; a future ADR may fold them into the same named scheme if a reason arises, but they are not part of this decision.

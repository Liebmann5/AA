---
title: "ADR-013: Retirement of the Zero-Browser Static Path"
status: reviewed
last_verified: 2026-09-19
verified_against: "capability_profile.py:11, registry.py:691, browser_cascade.py:126"
audience: contributors
---

# ADR-013: Retirement of the Zero-Browser Static Path

**Status:** Accepted
**Date:** 2026-09-08 (implemented) · 2026-09-19 (recorded)
**Supersedes:** [ADR-006 — BeautifulSoup Zero-Browser Fallback](006_bs4_zero_browser_fallback.md)
**Deciders:** Nicholas Liebmann

> This ADR is written eleven days after the change it records. That delay is
> itself the reason [ADR-017](017_documentation_gate.md) exists: for those
> eleven days, eight documents advertised a capability the code had removed.

## Context

ADR-006 committed AA to a complete static-HTML perception path for machines
where no browser can be launched. It was implemented: `BS4PerceptionAdapter`
(438 lines), `UrllibHTTPClient` (94 lines, standard library only) and
`HTTPClientPort` (62 lines). The composition root constructed the adapter on its
`driver is None` branch, and a session mode named `STATIC_ASSISTED` described
the resulting capability.

The claim mattered more than most: AA's first commitment is a library computer
with no administrator rights, and "works with no browser at all" is the
strongest possible form of that commitment.

**The measurement that ended it.** During the 2026-09-08 Lubuntu runs, a session
whose cascade exhausted did not degrade to static operation. It *idled*. Tracing
found why: `STATIC_ASSISTED` named a mode, and the perception adapter existed,
but **no discovery provider exists that runs without a browser.** Every provider
navigates. The static perception adapter was constructed on the driver-`None`
branch and then never reached by anything, because there was no producer
upstream of it.

The capability was present at the adapter and absent at the pipeline. A user on
a machine that could not launch a browser received a session that claimed to be
running and did nothing — the worst available outcome, and precisely AA's
defining defect class: capability built, never connected.

## Decision

**Retire the static path and make the absence explicit.**

1. `BS4PerceptionAdapter`, `UrllibHTTPClient`, `HTTPClientPort` and their tests
   are **retired, not deleted** — they live in `docs/old_retired_files/` with
   their origin stamped and their completeness recorded in the ledger
   ([ADR-016](016_retirement_over_deletion.md)).
2. `STATIC_ASSISTED` is removed. A mode name with no implementation behind it is
   a lie the type system helps tell.
3. When the browser cascade exhausts, **`build_orchestrator` refuses to
   construct a session.** It does not build a degraded one.
4. `ResolvedCapabilityProfile` with `has_browser=False` reports an **empty**
   `allowed_task_types`, because the orchestrator requires a live browser for
   every task type. The profile says what is true rather than what was hoped.
5. **A browser is now a documented requirement**, stated in the README, the
   installation guide and `STATUS.md`.

## Options considered

**A. Keep the adapter and build the missing static provider.**
Rejected *for now*, not on merit. A static discovery provider is real work —
search engines serve results through JavaScript, and AA's own URL research
established that Google's redirect wrapper is encrypted protobuf with no DOM
anchor to climb. Building it while the browser path has never completed a single
submission would be optimising the second route before the first one works.

**B. Keep the mode, make it fail loudly.**
Rejected. A mode that always fails loudly is a worse version of refusing, with a
name that still appears in every menu, document and config file.

**C. Delete everything and stop claiming it.**
Rejected on policy. Four modules were once deleted as "unimportable dead code",
and within hours the pin that proved them dead turned out to be the broken
thing. Retirement preserves 594 lines of working implementation for the day
option A is taken.

**D. Retire the implementation, keep the capability as a named seam.** — **Chosen.**
It tells the truth today and forecloses nothing.

## Consequences

**What becomes true**

- AA's behaviour matches its documentation: no browser, no session, stated
  clearly and early.
- The port inventory stops carrying a promise nothing keeps.
- One fewer mode, one fewer branch in the composition root, three fewer files in
  `src/`.

**What becomes harder**

- **AA's reach narrows.** A machine that cannot launch any browser is no longer
  supported. That is a real reduction against the worst-case-user commitment,
  and it is recorded here rather than absorbed quietly.
- The static path's re-entry cost is now a provider, not an adapter.

**Cost recorded at the decision site:** a Tier 0 property (worst-case user
reach) was traded for a Tier 1 property (honesty about what the system does).
Under AA's lexicographic ordering that trade should normally fail. It is
accepted because the reach was **never real** — the mode could not produce a
single posting — so nothing was lost except the claim.

## The capability is deferred, not cancelled

Writing "out of scope" in a way that removes a future possibility is the wrong
call, not merely wrong wording. **Deferral is written as deferral.**

`CAP-STATIC` — *AA must remain able to operate without a browser.*

| Requirement | Where the seam is |
| --- | --- |
| Perception stays behind a port | `PerceptionPort`; the retired adapter satisfies it as written |
| Fetching stays behind a port | `HTTPClientPort`, retired intact — **recall it first** if this is revived |
| Discovery providers must not assume a driver | `DiscoveryPort`; a static provider is a sibling, not a special case |
| The capability profile stays honest | `ResolvedCapabilityProfile` reports absence rather than substituting |

**Restoration trigger.** Revisit when *either* (a) a live run proves discovery
and application work through a browser end to end, so a second route is worth
building, *or* (b) a target deployment is found where no browser can be launched
at all — at which point CAP-STATIC becomes a commitment and this ADR is
superseded.

**Nothing may be merged that forecloses it.** A change that moves fetching into a
browser adapter, or that lets a workflow assume a driver exists rather than
asking the capability profile, breaks this seam and must be rejected on those
grounds.

## References

- `src/auto_apply/domain/models/capability_profile.py:11` — the ruling, in code
- `src/auto_apply/infrastructure/registry.py:691` — empty `allowed_task_types`
- `src/auto_apply/infrastructure/browser_cascade.py:126`
- `src/auto_apply/infrastructure/composition_root.py:103,168` — refusal path
- `docs/old_retired_files/README.md` — ledger rows dated 2026-09-09
- [ADR-006](006_bs4_zero_browser_fallback.md) — superseded by this record

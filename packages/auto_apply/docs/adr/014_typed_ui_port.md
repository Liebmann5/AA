---
title: "ADR-014: A Typed UI Port as the Boundary Between Surfaces and the Agent"
status: reviewed
last_verified: 2026-09-19
verified_against: "domain/models/ui_contract.py, domain/ports/ui_port.py"
audience: contributors
---

# ADR-014: A Typed UI Port as the Boundary Between Surfaces and the Agent

**Status:** Accepted
**Date:** 2026-09-15
**Deciders:** Nicholas Liebmann

## Context

AA ships two user-facing surfaces, a Tkinter GUI and a terminal CLI. Before this
decision, the entire interface between them and the agent was **an untyped
dict**. Three defects followed from that, all found by tracing rather than by
tests:

1. **The CLI wizard discarded everything the user typed.** It asked five
   questions and assembled a dict whose keys no consumer read.
2. **A first-run GUI user received someone else's identity.** Onboarding seeded
   the new profile from the bundled template, so a new user's first session
   carried the template's name, school and contact details.
3. **No request-scoped value reached the workflows at all.** The orchestrator
   replaced its session plan object while `DiscoveryWorkflow` and
   `ApplicationsWorkflow` each held a reference to the *boot* plan built in the
   composition root. A result cap a user typed had never once been applied. A
   plan-level test passed while the scraper read a stale plan.

The third is the important one. It is not a UI defect; it is a **contract**
defect that a UI happened to surface. An untyped dict cannot be checked at a
boundary, so the boundary was not a boundary.

Meanwhile, the mobile capability (CAP-2) had already established that a phone
cannot drive a desktop browser, so mobile must be a *client* to a headless
agent — which requires exactly the same seam.

## Decision

**The UI contract is a real port in `domain/ports/`, with the GUI and the CLI as
adapters.**

1. `domain/models/ui_contract.py` defines frozen, validated DTOs.
   `SessionRequest` carries the **entry axis** (how jobs arrive) and the **exit
   axis** (how far the run goes) as *separate fields*, because they are
   independent and were previously conflated into one "mode".
2. `domain/ports/ui_port.py` defines a driving `Protocol`, satisfied
   **structurally** by `SessionController` — no wrapper class, per AA's
   structural-satisfaction rule.
3. The legacy `initialize_session(dict)` becomes a **translating shim**, not a
   rejecting one, so the five previously discarded CLI answers are honoured one
   stage earlier than they otherwise would have been.
4. The port returns a **null-object snapshot** rather than `None` when no session
   is running, so no adapter has to branch on absence.

## Options considered

**A. A service-facing interface in `application/`.**
Rejected. It would have been consistent with nothing: AA's hexagonal pins point
at `domain/ports/`, and a second kind of interface in a second place is the
accretion that produced 35 ports of mixed provenance in the first place.

**B. A typed DTO but no port — just a dataclass passed to `SessionController`.**
Rejected. It fixes the discarded-answers defect and none of the coupling. The
parity guarantee between surfaces has nothing to attach to, and CAP-2 still has
no seam.

**C. Reject the legacy dict outright.**
Rejected. Roughly 1,200 tests predated the port. Translating preserves the
evidence that the port did not break them; rejecting would have forced a rewrite
of that evidence at the same moment it was most needed.

**D. A port in `domain/ports/` with structural satisfaction.** — **Chosen.**

## Consequences

**What becomes possible**

- A **parity pin** between the two surfaces, pointing at the port.
- CAP-2 (a mobile client) and CAP-3 (LAN deployment) inherit the same seam at no
  extra cost.
- Contract violations become type errors caught by gate 3, not runtime surprises.

**What becomes harder**

- A new UI capability now requires touching the port, both adapters and the
  parity pin — deliberately, since the cost of a divergent surface is the defect
  class this removes.

**Known incompleteness, recorded honestly**

- `UIPort` is **17 methods and session-shaped**. Identity and custody parity
  cannot be pinned until it widens.
- **`UIPort` has no typed consumer yet.** Both surfaces still import
  `SessionController` directly, so the port carries WIRE-LATER exemptions in both
  `KNOWN_UNWIRED_PORTS` and `KNOWN_UNREACHABLE`. Removal trigger, recorded so it
  cannot rot: delete both exemptions when `gui/app.py` and `cli/startup.py` type
  against `UIPort`.

**Correction on record.** The legacy `vet` label maps to `VET_AND_APPLY`, not
`VET_ONLY`. The first mapping was taken from an enum name; the legacy docstring
showed that `vet` had always applied to whatever passed vetting, so `VET_ONLY`
would have silently narrowed a mode that users already relied on.

## References

- `src/auto_apply/domain/models/ui_contract.py`
- `src/auto_apply/domain/ports/ui_port.py`
- `tests/architecture/test_safety_pins.py`
- [ADR-015](015_polled_ui_state.md) — how state crosses this port

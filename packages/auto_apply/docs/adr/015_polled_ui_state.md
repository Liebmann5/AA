---
title: "ADR-015: User Interfaces Poll the Port; They Do Not Subscribe to the Bus"
status: reviewed
last_verified: 2026-09-19
verified_against: "gui/dashboard.py, cli/dashboard.py, tests/architecture/test_safety_pins.py"
audience: contributors
---

# ADR-015: User Interfaces Poll the Port; They Do Not Subscribe to the Bus

**Status:** Accepted
**Date:** 2026-09-15
**Deciders:** Nicholas Liebmann

## Context

AA publishes 47 internal events. The dashboards needed to show activity, and the
obvious design was for each surface to subscribe to the event bus.

Two facts made that less obvious on inspection.

First, **a subscription is a coupling in the wrong direction.** To subscribe, a
primary adapter must import `domain.events` and reach `orchestrator.event_bus` —
exactly the reach that [ADR-014](014_typed_ui_port.md) exists to remove. It
would have to be unwound again at the next stage.

Second, **both surfaces already ran refresh loops** — the CLI at 1.0 s and the
GUI at 500 ms — for state they were already polling. Adding subscriptions would
not have introduced push; it would have created *two* update mechanisms per
surface, which is the condition under which they disagree.

The internal `Event` is also the wrong object to show a person. It carries
payloads shaped for the agent's own use, and any of them may contain personal
data.

## Decision

**Both surfaces poll the UI port. Neither subscribes to the event bus.**

1. The 47 internal events project onto a small `ActivityKind` set. **The raw
   `Event` never crosses the port.**
2. Both dashboards render the projected stream from their existing refresh loop.
3. A structural pin asserts that `.subscribe(` appears in **neither** dashboard
   module.
4. The human-in-the-loop gate is polled like everything else.

## Options considered

**A. Subscribe both surfaces to the bus.**
Rejected: reintroduces the coupling ADR-014 removes; needs unwinding later;
creates two update paths per surface.

**B. Subscribe, but through an adapter that re-publishes over the port.**
Rejected: this is polling with extra machinery and a thread-safety problem. The
GUI's Tk main loop cannot be touched from a publisher thread, so the adapter
would need a queue — which is the refresh loop, rebuilt.

**C. Poll the port.** — **Chosen.**

## Consequences

**What becomes true**

- One update mechanism per surface. Two surfaces cannot disagree about what
  happened.
- The projection is a **PII boundary** with a name: anything not in
  `ActivityKind` cannot reach a screen.
- `Dashboard.log_message` finally has a caller. `UIMessageHandler` became
  genuinely unused and was retired, removing its reachability exemption.

**What is given up**

- **Up to one second of notice** on a gate that holds for as long as 300 s.
  Accepted explicitly: the worst case is a user seeing an approval prompt one
  second late.

**The trade recorded at the site:** responsiveness (Tier 4) was traded for
decoupling and single-source (Tier 2). Under AA's ordering the higher tier wins,
and the measured cost is one second.

**Known scope gap.** The PII sentinel pin walks attribute chains in
`session_controller.py` only. The surface formatters —
`gui/app.py::format_results_lines`, `format_history_lines`, `cli/dashboard.py` —
are not covered, so a formatter interpolating a profile field would slip past it.
Tracked as F-9 in [STATUS.md](../STATUS.md).

## References

- `src/auto_apply/adapters/primary/gui/dashboard.py`
- `src/auto_apply/adapters/primary/cli/dashboard.py`
- `tests/architecture/test_safety_pins.py`

---
title: The UI Port Layer
status: reviewed
last_verified: 2026-09-19
verified_against: "domain/ports/ui_port.py, domain/models/ui_contract.py, both dashboards"
audience: contributors
---

# The UI Port Layer

How the GUI and the CLI talk to the agent, and why that boundary is shaped the
way it is.

Decisions: [ADR-014](../adr/014_typed_ui_port.md) (the port),
[ADR-015](../adr/015_polled_ui_state.md) (polling rather than subscribing).

---

## The defect this layer exists to remove

Before 2026-09-15 the entire interface between a surface and the agent was an
untyped dictionary. Three things were true at once, and all three were found by
tracing rather than by a failing test:

- The CLI wizard asked five questions and **discarded every answer** — it built
  a dict whose keys nothing read.
- A first-run GUI user was seeded with **the bundled template's identity**.
- **No request-scoped value reached the workflows at all.** The orchestrator
  replaced its session plan while `DiscoveryWorkflow` and `ApplicationsWorkflow`
  each held a reference to the boot plan from the composition root. The result
  cap a user typed had never once been applied — and a plan-level test passed
  the whole time, because it checked the plan rather than the reader.

The third is the general case. An untyped dict cannot be checked at a boundary,
so it is not a boundary.

---

## Shape

```
adapters/primary/gui/app.py  ─┐
                              ├─► SessionRequest ─► UIPort ─► SessionController ─► Orchestrator
adapters/primary/cli/startup.py ┘                      ▲
                                                       │
     GUI dashboard ─┐                                  │
                    ├── poll ──► SessionSnapshot ──────┘
     CLI dashboard ─┘            ActivityKind stream
```

- **`domain/models/ui_contract.py`** `[LIVE]` — frozen, validated DTOs.
- **`domain/ports/ui_port.py`** `[LIVE]` — a driving `Protocol`, satisfied
  **structurally** by `SessionController`. There is no wrapper class; AA's rule
  is that structural satisfaction beats an adapter that exists only to satisfy.
- Both surfaces are **adapters**. Neither contains logic that decides anything.

---

## Two axes, not one mode

The single most useful thing this layer got right is separating two questions
that had been conflated into one word:

| Axis | Question | Values |
| --- | --- | --- |
| **Entry** | How do jobs arrive? | Search · Direct links · Company pages · Resume a session |
| **Exit** | How far does the run go? | Collect only · Collect and check · Collect, check and apply |

A user who wants to see what AA finds without it applying to anything picks the
collect-only exit. That is a *structural* guarantee, not a setting AA promises
to respect: with no application stage in the plan, there is no path to a
submission. It is the only no-submit guarantee AA has, since there is no
`--dry-run` anywhere.

---

## State goes one way: polled

Both dashboards **poll** the port. Neither subscribes to the event bus, and a
structural pin asserts `.subscribe(` appears in neither module. `[LIVE]`

Both surfaces already ran refresh loops — CLI at 1.0 s, GUI at 500 ms — so this
removed the last two push paths rather than adding polling. The cost is up to
one second of notice on a gate that can hold for 300 s, and that cost is
accepted explicitly in [ADR-015](../adr/015_polled_ui_state.md).

### The activity stream is a privacy boundary

47 internal events project onto a small `ActivityKind` set. **The raw `Event`
never crosses the port.** Anything not in `ActivityKind` cannot reach a screen,
which makes the projection the enforcement point rather than a convenience.

`[PARTIAL]` — the PII sentinel pin walks attribute chains in
`session_controller.py` only. The surface formatters are not yet covered (F-9 in
[STATUS.md](../STATUS.md)).

---

## Autonomy

Autonomy is a real control on both surfaces, reached through the port. `[LIVE]`

- `set_autonomy` **refuses with fewer than two acknowledgements**, so a surface
  cannot skip a warning screen by calling the method directly.
- The interrupt policy is **frozen at composition**. `set_autonomy` writes the
  profile and never touches a built policy, and AST guards pin that it never
  starts to.

The sharpest part of the reasoning: if `set_autonomy` also rebuilt a live
policy, the immutability guarantee would become false *by design* rather than by
accident. So the control deliberately does not rebuild.

---

## Parity

Both surfaces read labels from one source and expose the same four entry points
and the same three exits. `[LIVE]`

`[PLANNED]` — a real parity pin, asserting that the two adapters implement the
same port surface, requires both to type against `UIPort`. Today both still
import `SessionController` directly, so the port carries WIRE-LATER exemptions.
**Removal trigger:** delete both exemptions when `gui/app.py` and
`cli/startup.py` type against `UIPort` (F-11 in [STATUS.md](../STATUS.md)).

---

## What this layer does not yet do

| Gap | Consequence |
| --- | --- |
| `UIPort` is 17 methods and session-shaped | Identity and custody parity cannot be pinned until it widens |
| `UIPort` has no typed consumer | Two WIRE-LATER exemptions, two raised ceilings |
| `approval_evidence()` is in-memory only | Authorisation stamps exist during a run and not after it — a research-durability gap |
| Five print sites sit outside the primary adapters | Four are the Profile Check advisory, which goes to stdout, so **a GUI user never sees it** |

---

## Why the port lives in `domain/ports/`

Because the alternative — a service-facing interface in `application/` — would
have been consistent with nothing. AA's hexagonal pins point at `domain/ports/`,
and it is the same seam a mobile client would need: a phone cannot drive a
desktop browser, so mobile must be a *client to a headless agent*, which is this
port with a different adapter on the front.

One seam, three payers: testability today, parity tomorrow, mobile later.

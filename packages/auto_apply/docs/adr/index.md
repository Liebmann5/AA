---
title: Architecture Decision Records
status: reviewed
last_verified: 2026-09-19
verified_against: "docs/adr/ directory listing"
audience: contributors
---

# Architecture Decision Records

An ADR records a decision that shaped AA: the problem, the options weighed, the
option chosen, **why the others were rejected**, and what the decision costs.

An ADR that lists only the decision has recorded the least useful half of it.
The rejected alternatives are what let a future reader tell "we considered that
and here is why not" from "nobody thought of it".

## Rules

1. **ADRs are immutable once accepted.** They record history, not current state.
2. **A reversed decision gets a new ADR**, and the old one is marked
   `Superseded` with a link. It is never edited to look correct in hindsight.
3. **The next number is `018`.** Take it by creating the file; if two people
   collide, the second renumbers.
4. Write an ADR when a change alters a layer boundary, a port contract, a data
   format, a user-visible guarantee, or reverses an earlier decision.
5. The ADR lands in the **same pull request** as the change it records. ADR-013
   was written eleven days late, and for those eleven days eight documents
   advertised a capability the code had removed.

## Register

| ADR | Title | Status | Decided |
| --- | --- | --- | --- |
| [001](001_hexagonal_architecture.md) | Hexagonal (ports and adapters) architecture | Accepted | 2025-09 |
| [002](002_dependency_injection_refactor.md) | Universal constructor dependency injection | Accepted | 2025-10 |
| [003](003_pra_loop_and_state_machine.md) | PRA loop and dual state machines | **Partially stale** | 2025-10 |
| [004](004_ats_platform_registry.md) | YAML-driven ATS platform registry | Accepted | 2025-10 |
| [005](005_human_in_the_loop.md) | Human-in-the-loop checkpoint architecture | Accepted | 2025-11 |
| [006](006_bs4_zero_browser_fallback.md) | BeautifulSoup zero-browser fallback | **Superseded by 013** | 2025-11 |
| [007](007_profile_and_schema_driven_ui.md) | Pydantic schema-driven user interface | Accepted | 2025-12 |
| [008](008_plugin_architecture.md) | Protocol-based plugin architecture | Accepted | 2025-12 |
| [009](009_research_module.md) | Consent-gated, zero-PII research module | Accepted | 2026-01 |
| [010](010_remediation_changelog.md) | Architecture audit and remediation sprint | Accepted (historical) | 2026-02 |
| [011](011_discovery_pipeline_priority.md) | Discovery pipeline priority bands | Accepted | 2026-07 |
| [012](012_fail_closed_submission_gate.md) | Fail-closed submission gate | Accepted | 2026-08 |
| [013](013_static_path_retirement.md) | Retirement of the zero-browser static path | Accepted | 2026-09-08 |
| [014](014_typed_ui_port.md) | A typed UI port between surfaces and the agent | Accepted | 2026-09-15 |
| [015](015_polled_ui_state.md) | Interfaces poll the port; they do not subscribe | Accepted | 2026-09-15 |
| [016](016_retirement_over_deletion.md) | Retirement replaces deletion | Accepted | 2026-08-30 |
| [017](017_documentation_gate.md) | Documentation is enforced by a gate | Accepted | 2026-09-19 |

`tests/infrastructure/test_docs_gate.py` asserts that this table and the
directory contain the same set of records.

## Records needing attention

Recorded here rather than quietly, because a register that hides its own debt is
worse than no register.

| ADR | Problem |
| --- | --- |
| 003 | Names `application/use_cases/applications_use_case.py` and `domain/applications/fsm/universal.py`. **Neither file exists.** The decision's intent survives; its implementation references do not. Needs a superseding record describing the loop as actually built. |
| 010 | A historical audit changelog rather than a decision. Accurate for its date; several files it names have since been retired. Kept as history, not as guidance. |
| 006 | Superseded by 013. Left unedited, as the rules require. |

## Decisions still unrecorded

These were made, are in force, and have no ADR. Listed so the gap is visible.

| Decision | Where it currently lives |
| --- | --- |
| Typed frozen `EffectiveConfig` as the configuration foundation | Code and commit messages |
| Committed fallback route (the DOM miner behind the SERP port) | ADR-011's neighbourhood, never written |
| Two hashes, two purposes (dedup identity vs. research anonymisation) | Code |
| Fail direction by consequence (closed on submit, open on click) | Partially in ADR-012 |
| The six-tier priority ordering | `ENGINEERING_PHILOSOPHY.md`, `GOVERNANCE.md` |
| The custody model (family computer vs. enforced library custody) | Design notes |
| Cadence as data rather than as evasion | Code |
| Tool with injected strategies (the interaction tool template) | `AA_ARCHITECTURE_BIBLE.md` |

Writing these is tracked work, not a backlog wish: each one is a decision
somebody will otherwise re-litigate from scratch.

## Template

Copy this into `adr/018_your_decision.md`.

````markdown
---
title: "ADR-018: Title"
status: reviewed
last_verified: YYYY-MM-DD
verified_against: "what you checked it against"
audience: contributors
---

# ADR-018: Title

**Status:** Proposed | Accepted | Rejected | Superseded | Deprecated
**Date:** YYYY-MM-DD
**Deciders:** names
**Supersedes / Superseded by:** link, if any

## Context

What problem is this solving? What constraints apply? **What measurement
prompted it?** A decision with no triggering evidence is usually a preference.

## Decision

What was decided, stated so that a reader can tell whether a future change
violates it.

## Options considered

Each rejected option, and why it was rejected. If there was only one option,
say so — that is informative too.

## Consequences

What becomes easier. What becomes harder. **What this costs, and which tier the
cost falls on** (see GOVERNANCE.md). What the migration path is.

## References

Code paths with line numbers, tests, related ADRs.
````

## Status definitions

| Status | Meaning |
| --- | --- |
| **Proposed** | Under discussion; not adopted |
| **Accepted** | Agreed and implemented |
| **Rejected** | Considered, not adopted — kept because the reasoning is useful |
| **Superseded** | Replaced by a later ADR, which is linked |
| **Deprecated** | No longer relevant; nothing replaced it |
| **Partially stale** | The decision stands; some references in it no longer resolve |

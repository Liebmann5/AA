# Architecture Decision Records

Architecture Decision Records (ADRs) capture the significant technical choices
made during the development of AutoApply. Each record describes a decision,
the context in which it was made, the options considered, and the
consequences.

ADRs are immutable once accepted — they record history, not current state. If
a decision is reversed or replaced, a new ADR is written and the old one is
marked **Superseded**.

---

## Active Records

| ADR | Title | Status |
| --- | ----- | ------ |
| [ADR‑001](001_hexagonal_architecture.md) | Hexagonal (Ports & Adapters) Architecture | Accepted |
| [ADR‑002](002_dependency_injection_refactor.md) | Universal Constructor Dependency Injection | Accepted |
| [ADR‑003](003_pra_loop_and_state_machine.md) | PRA Loop and Dual State Machines | Accepted |
| [ADR‑004](004_ats_platform_registry.md) | YAML‑Driven ATS Platform Registry | Accepted |
| [ADR‑005](005_human_in_the_loop.md) | Human‑in‑the‑Loop Checkpoint Architecture | Accepted |
| [ADR‑006](006_bs4_zero_browser_fallback.md) | BeautifulSoup Zero‑Browser Fallback | Accepted |
| [ADR‑007](007_profile_and_schema_driven_ui.md) | Pydantic Schema‑Driven User Interface | Accepted |
| [ADR‑008](008_plugin_architecture.md) | Protocol‑Based Plugin Architecture | Accepted |
| [ADR‑009](009_research_module.md) | Consent‑Gated, Zero‑PII Research Module | Accepted |
| [ADR‑010](010_remediation_changelog.md) | Architecture Audit and Remediation Sprint | Accepted |
| [ADR‑011](011_discovery_pipeline_priority.md) | Discovery Pipeline Priority Bands | Accepted |
| [ADR‑012](012_fail_closed_submission_gate.md) | Fail‑Closed Submission Gate | Accepted |

---

## Record Summaries

### ADR‑001 — Hexagonal (Ports & Adapters) Architecture
**Decided:** 2025‑09  
**Decider:** Nick Liebmann

The codebase is organised into four concentric layers — domain, application,
adapters, and infrastructure — with dependencies pointing strictly inward.
Every external capability (browser automation, HTTP, persistence) is
represented by an abstract port in the domain layer; concrete adapters
implement those ports. The composition root is the only place that wires them
together. This gives us framework‑agnostic design, effortless testability, and
graceful degradation.

### ADR‑002 — Universal Constructor Dependency Injection
**Decided:** 2025‑10  
**Decider:** Nick Liebmann

All dependencies are passed via constructor injection. No class constructs its
own collaborators. This makes the object graph visible in a single file
(`composition_root.py`), enables isolated unit testing with mocks, and
eliminates hidden coupling. The refactor involved converting `DatabaseManager`,
`ProfileRepository`, and `HealthMonitor` references from internal construction
to injected parameters.

### ADR‑003 — PRA Loop and Dual State Machines
**Decided:** 2025‑10  
**Decider:** Nick Liebmann

The Application Engine uses a Scan‑Plan‑Act loop governed by a 17‑state FSM
(`ApplicationState`), while the AgentOrchestrator uses a separate 14‑state FSM
(`AgentState`). Both have explicit transition tables that prevent impossible
states. The PRA loop collapses duplicate page‑classification heuristics into
`PerceptionPort.get_current_state()`, making the engine dispatch on a single
enum value rather than scattered boolean checks.

### ADR‑004 — YAML‑Driven ATS Platform Registry
**Decided:** 2025‑10  
**Decider:** Nick Liebmann

All knowledge about specific Applicant Tracking Systems — URL patterns, login
wall signals, success signals, form selectors — is stored in YAML files under
`resources/ats/`. The `ATSRegistry` loads them at startup and provides
`match(url)` → `ATSDescriptor`. Adding a new ATS requires zero Python code
changes; creating a YAML file is sufficient.

### ADR‑005 — Human‑in‑the‑Loop Checkpoint Architecture
**Decided:** 2025‑11  
**Decider:** Nick Liebmann

The agent pauses at configurable checkpoints (`BEFORE_FORM_SUBMIT`,
`ON_SUSPICIOUS_REDIRECT`, `ON_LOW_CONFIDENCE_FIELD`) and waits for explicit
user approval before proceeding. The `InterruptPolicy` port allows different
policies (profile‑based, never, always) to be injected. The approval gate uses
a `threading.Event` to block the agent thread until the GUI or CLI provides a
response, with a 5‑minute timeout defaulting to skip.

### ADR‑006 — BeautifulSoup Zero‑Browser Fallback
**Decided:** 2025‑11  
**Decider:** Nick Liebmann

For users who cannot launch any browser (library computers, headless servers,
machines without Chrome/Firefox), AA provides a complete static‑HTML
perception path via `BS4PerceptionAdapter`. This adapter fetches pages with
`urllib`, parses them with BeautifulSoup, and classifies page states using
keyword tables and structural heuristics. It allows job discovery and vetting
without a live browser.

### ADR‑007 — Pydantic Schema‑Driven User Interface
**Decided:** 2025‑12  
**Decider:** Nick Liebmann

Both the GUI settings editor and CLI wizard derive their field lists, labels,
option sets, and defaults from `UserProfile.model_json_schema()`. Adding a new
profile field automatically populates all user interfaces. The UI schema
supports i18n resolution and admin‑policy field locking without any UI‑specific
code.

### ADR‑008 — Protocol‑Based Plugin Architecture
**Decided:** 2025‑12  
**Decider:** Nick Liebmann

AA's "plugin system" is the natural consequence of the hexagonal architecture.
Every port in `domain/ports/` is an extension point. A new discovery provider,
perception adapter, or health monitor is added by implementing the
corresponding Protocol and registering it in the composition root — no plugin
framework, entry‑point scanning, or lifecycle hooks needed.

### ADR‑009 — Consent‑Gated, Zero‑PII Research Module
**Decided:** 2026‑01  
**Decider:** Nick Liebmann

AA includes a passive research data collector that records anonymised hiring
market signals. It is opt‑in only, records no personal information (no URLs,
company names, or user identifiers), runs on a background thread, and is
designed for academic‑grade statistical analysis. The taxonomy includes both
negative signals (hidden requirements, ghosting) and positive signals (salary
disclosure, inclusive language) for balanced research.

### ADR‑010 — Architecture Audit and Remediation Sprint
**Decided:** 2026‑02  
**Decider:** Nick Liebmann

A systematic audit of the entire codebase identified layering violations
(domain importing adapters, adapters importing application), missing dependency
injections, duplicate state management, and a crash caused by a missing
`AgentState` value. All P1–P3 issues were resolved; P4 items (JSON Resume I/O,
accessibility wiring, `BrowserInterface` split) were deferred. The changelog
is the authoritative record of every change made.

---

## Proposing a New ADR

1. Copy the template below into a new file `adr/011_your_decision.md`.
2. Fill in the sections.
3. Open a pull request. The ADR will be discussed and either **Accepted**,
   **Proposed**, or **Rejected**.

### Template

```markdown
# ADR‑011: [Title]

**Status:** Proposed
**Date:** YYYY‑MM‑DD
**Deciders:** [names]
**Technical Story:** [link to issue or discussion]

## Context
What problem are we solving? What constraints are we under?

## Decision
What did we decide to do?

## Options Considered
What were the alternatives and why were they rejected?

## Consequences
What becomes easier? What becomes harder? What is the migration path?

## References
Any links to code, discussions, or external resources.
```

---

## Status Definitions

| Status | Meaning |
| ------ | ------- |
| **Proposed** | Under discussion; not yet adopted. |
| **Accepted** | Agreed upon and implemented. |
| **Rejected** | Considered but not adopted. |
| **Superseded** | Replaced by a later ADR. |
| **Deprecated** | No longer relevant. |
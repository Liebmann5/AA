# ADR‑001: Hexagonal (Ports & Adapters) Architecture

**Status:** Accepted  
**Date:** 2025‑09‑15  
**Deciders:** Nick Liebmann  
**Technical Story:** AutoApply began as a collection of browser‑automation scripts that directly imported Selenium, SQLite, and site‑specific DOM selectors. Adding a new job board or swapping a browser engine required touching dozens of files. Testing was impossible without a real browser. The architecture needed to support the “worst‑case user first” philosophy — the application had to run on library computers with no admin rights, 2 GB RAM, and no guaranteed browser.

---

## Context

AutoApply must be:

1.  **Framework‑agnostic** — it should work with Selenium, Playwright, or any future automation tool without rewriting business logic.
2.  **Testable** — domain logic (vetting, form filling, research) must be verifiable without any browser, database, or network.
3.  **Replaceable** — swapping Playwright for Selenium, or SQLite for Postgres, should require touching one file.
4.  **Gracefully degradable** — the application must function even when no browser can be launched, falling back to static HTML parsing.

A traditional layered architecture (presentation → business → data) would not suffice because the business logic would still depend on concrete infrastructure implementations. We needed a pattern that inverted those dependencies.

---

## Decision

We adopted the **Hexagonal Architecture** (also known as Ports & Adapters), as described by Alistair Cockburn, with a strict four‑layer organisation:

```
infrastructure/       ← wires everything together (composition root)
adapters/             ← implements ports (browser drivers, HTTP clients, DB, GUI, CLI)
application/          ← orchestrates the domain via ports (engines, workflows, services)
domain/               ← pure business logic (models, ports, filters, domain services)
```

**The only legal dependency direction is inward:**

```
infrastructure → adapters → application → domain
```

No arrow ever points outward. The `domain/` directory never imports from `adapters/`. The `application/` directory never imports from `infrastructure/`. The composition root (`infrastructure/composition_root.py`) is the **single place** that may import from both `adapters/` and `domain/` simultaneously.

### Ports

Every capability the domain needs from the outside world is expressed as an abstract interface — a **Port** — in `domain/ports/`. Ports are either `ABC` classes or `typing.Protocol` definitions:

- `BrowserInterface` — navigation, element location, script execution
- `PerceptionPort` — page state classification and element scanning
- `InteractionPort` — clicking, typing, uploading, executing interaction plans
- `ReasoningPort` — generating interaction plans from page snapshots
- `DiscoveryProviderPort` — searching for jobs on a specific platform
- `JobRepositoryPort` — persisting and querying application history
- `HTTPClientPort` — fetching URLs with plain HTTP
- `HealthMonitor` — background health checks for browser and network

### Adapters

Concrete implementations of ports live in `adapters/`. They are the only places where third‑party library imports are permitted:

| Port | Example Adapters |
|------|------------------|
| `BrowserInterface` | `SeleniumAdapter`, `PlaywrightAdapter` |
| `PerceptionPort` | `MathPerceptionAdapter`, `BS4PerceptionAdapter` |
| `InteractionPort` | `InteractionExecutor` (with pluggable execution strategies) |
| `ReasoningPort` | `FormSolver`, `ClingoFormSolver` |
| `DiscoveryProviderPort` | `GoogleProvider`, `BingProvider`, `IndeedProvider` |
| `JobRepositoryPort` | `JobRepository` (backed by `DatabaseManager`) |
| `HTTPClientPort` | `UrllibHTTPClient` |
| `HealthMonitor` | `BrowserHealthMonitor`, `NetworkHealthMonitor` |

Adapters are divided into **primary** (GUI, CLI — things that drive the application) and **secondary** (browser, database, network — things the application drives).

### The Composition Root

`infrastructure/composition_root.py` is the wiring diagram made executable. It constructs every concrete adapter, creates every domain engine, and injects them into the orchestrator. Nothing constructs its own dependencies — all objects are assembled here and passed down via constructor injection.

---

## Options Considered

### 1. Traditional layered architecture (presentation → business → data)
**Rejected.** Business logic would directly import database and browser classes, making testing and replacement impossible without mocking at the import level. Every new job board would require changes in multiple layers.

### 2. Microservices with separate browser‑agent and API services
**Rejected.** This would violate the “worst‑case user first” constraint. A library computer cannot run Docker or multiple services. The application must be a single process.

### 3. Plugin framework with setuptools entry points
**Rejected.** Entry‑point scanning adds complexity and a dependency on packaging tooling. Our “plugin system” is the natural consequence of the hexagonal architecture: implementing a port and wiring it in the composition root is simpler and more explicit.

---

## Consequences

### What becomes easier

- **Testing:** Every engine, filter, and workflow can be tested with mock ports. No real browser, database, or network is required for unit tests.
- **Extensibility:** Adding a new job board is one file (implementing `DiscoveryProviderPort`) and one registration line in the composition root. Adding a new browser automation tool is one provider + one adapter.
- **Replaceability:** Swapping a persistence backend, a reasoning engine, or an entire browser automation framework requires changing exactly one adapter and one wiring line.
- **Onboarding:** A new contributor can read `composition_root.py` and understand the entire application’s dependency graph in one file.
- **Graceful degradation:** The composition root decides at runtime whether to inject a live‑browser perception adapter or a static‑HTML fallback. The engines never branch on this condition.

### What becomes harder

- **Initial design:** Defining ports requires thinking about abstractions before writing concrete code. This is a discipline, not a convenience.
- **Layering discipline:** Contributors must be vigilant about import direction. A single `from adapters import ...` in `domain/` is a violation. This is enforced by code review, not by tooling.
- **Boilerplate:** Every new capability requires a port, an adapter, and wiring. For very simple features, this can feel like overhead. The long‑term maintainability payoff justifies it.

### What is the migration path

No migration is needed — the architecture was adopted early and all subsequent code was written to conform. The [ADR‑010 remediation sprint](010_remediation_changelog.md) fixed the few violations that had crept in (e.g., `domain/applications/field_classifier.py` importing from `adapters/`, `navigators.py` importing from `application/`).

---

## The Pydantic Exception

There is one deliberate exception to the “no framework imports in `domain/`” rule: **Pydantic** is permitted in `domain/models/` for data validation and schema generation.

`UserProfile.model_json_schema()` is the single source of truth for the schema‑driven UI (see [ADR‑007](007_profile_and_schema_driven_ui.md)). Banning Pydantic from `domain/` would force either a duplicate schema definition or moving schema generation to `application/`, which would still need to import domain models anyway.

This exception is bounded to:
- `domain/models/profile.py` — `UserProfile` and all sub‑models
- `domain/models/job.py` — `Job` model
- `domain/models/ui.py` — `UIElement`, `UIModel`, `InteractionPlan`
- `domain/models/location.py` — `Coordinate`

No other Pydantic usage is allowed in `domain/`. Domain services (`convex_hull.py`, `entropy.py`, `structural_hashing.py`, etc.) remain pure Python stdlib.

---

## References

- Alistair Cockburn, “Hexagonal Architecture” (2005)
- [ADR‑002: Dependency Injection Refactor](002_dependency_injection_refactor.md)
- [ADR‑010: Architecture Audit and Remediation Changelog](010_remediation_changelog.md)
- [Core Abstractions (Architecture Deep Dive)](../architecture/core_abstractions.md)
- `infrastructure/composition_root.py` — the single wiring authority
- `domain/ports/` — all port definitions
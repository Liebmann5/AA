# Architecture Overview

AutoApply follows a **hexagonal (ports & adapters) architecture** — a strict
layered design where business logic is completely isolated from infrastructure
concerns like browser automation, database access, and the user interface.
If you understand the four layers and the dependency rule, you can navigate
the entire codebase.

---

## The Four Layers

```
infrastructure/       ← Wires everything together.  The only place that may
                         import from both adapters/ and domain/.
    ↓ depends on
adapters/             ← Implements the ports defined in domain/.
                         Concrete browser drivers, HTTP clients, database
                         repositories, GUI windows, CLI prompts.
    ↓ depends on
application/          ← Orchestrates the domain.  Engines, workflows,
                         event bus, session controller, services.
    ↓ depends on
domain/               ← Pure business logic.  Models, ports (abstract
                         interfaces), vetting filters, mathematical domain
                         services.  No framework or I/O imports.
```

The arrows point **inward**.  An inner layer never imports from an outer
layer.  This is the single most important rule in the codebase.

---

## The Dependency Rule

| If you are in … | You may import from … | You may NEVER import from … |
|-----------------|-----------------------|------------------------------|
| `domain/`       | Python stdlib, Pydantic (in `models/` only) | `adapters/`, `application/`, `infrastructure/` |
| `application/`  | `domain/` | `adapters/`, `infrastructure/` |
| `adapters/`     | `domain/`, `application/` | `infrastructure/` (except through injection) |
| `infrastructure/` | `domain/`, `application/`, `adapters/` | *(nothing — it’s the outermost layer)* |

If you see an import that goes the wrong way — for example, a file in
`domain/` importing from `adapters/` — it is a **layering violation**
and must be fixed.

---

## Layer‑by‑Layer Tour

### 1. `domain/` — Pure Business Logic

The domain layer defines **what** the application does, without knowing
**how** it is done.  It contains:

- **Models** (`models/`) — `UserProfile`, `Job`, `UIModel`, `InteractionPlan`,
  `WorkUnit`, `AdminPolicy`, and immutable mathematical structures like
  `DOMNode` and `Geometry`.
- **Ports** (`ports/`) — abstract interfaces (ABCs or `Protocols`) that
  describe every capability the domain needs from the outside world:
  `BrowserInterface`, `PerceptionPort`, `ReasoningPort`,
  `DiscoveryProviderPort`, `JobRepositoryPort`, etc.
- **Domain Services** (`services/`) — pure, deterministic algorithms with
  zero side effects: convex hull computation, Hungarian assignment for
  label‑input pairing, ray‑casting occlusion detection, Shannon entropy
  for trap‑field identification, affine transform parsing, structural
  hashing.
- **Vetting Filters** (`vetting/`) — the composable filter chain
  (`ThrottlingFilter`, `SpatialLocationFilter`, `TitleLogicFilter`, …)
  that decides which jobs are worth applying to.
- **FSM Definitions** (`applications/fsm/`) — the `ApplicationState` enum
  and `VALID_APPLICATION_TRANSITIONS` table that govern the form‑filling
  state machine.

**Exception:** Pydantic is permitted in `domain/models/` for data
validation and schema generation (`model_json_schema()`).  This is the
only framework import allowed in the domain layer (see
[ADR‑001](../adr/001_hexagonal_architecture.md)).

### 2. `application/` — Orchestration & Use Cases

The application layer coordinates the domain.  It depends on domain ports
and never on concrete adapters.  Key components:

- **`agent/orchestrator.py`** — `AgentOrchestrator`: the main event loop
  that processes a priority work queue, dispatches tasks to engines, and
  manages the session lifecycle.
- **`agent/state_machine.py`** — `AgentState` enum and `StateMachine`
  class that enforce valid session‑level state transitions.
- **`use_cases/`** — `DiscoveryEngine`, `VettingEngine`, `ApplicationEngine`:
  the three pure engines that perform work without managing browser
  lifecycle or work queues themselves.
- **`workflows/`** — richer, step‑by‑step workflow orchestrations
  (`DiscoveryWorkflow`, `VettingWorkflow`, `ApplicationsWorkflow`) that
  assemble engines with NLP parsing, AI reasoning, and telemetry hooks.
- **`services/`** — shared services: `PageActionService` (unified browser
  interaction with micro/macro timing), `SessionController` (session
  lifecycle and HITL gate), `EventBus` (thread‑safe pub/sub),
  `TextMatcher` (SpaCy → difflib fallback), `i18n`, `ui_schema`, and more.

### 3. `adapters/` — Concrete Implementations of Ports

Adapters are the only places where third‑party library imports (Selenium,
Playwright, SQLite, Tkinter, BeautifulSoup, `urllib`, …) are permitted.

**Primary adapters** (`primary/`) drive the application:
- `gui/` — Tkinter windows: `AutoApplyApp`, `Dashboard`, `SettingsEditor`,
  `SessionConfigWizard`.
- `cli/` — terminal interface: `CLIStartup`, `CLIDashboard`, `CLIWizard`.

**Secondary adapters** (`secondary/`) are driven by the application:
- `browser/` — `SeleniumAdapter`, `PlaywrightAdapter` (implement
  `BrowserInterface`), plus `BrowserHealthMonitor`.
- `perception/` — `MathPerceptionAdapter` (geometry‑aware),
  `BS4PerceptionAdapter` (static HTML fallback), `DOMScanner`.
- `interaction/` — `InteractionExecutor`, input handlers
  (`TextInputHandler`, `SelectInputHandler`, …), execution strategies
  (stealth vs. instant).
- `discovery/` — `GoogleProvider`, `BingProvider`, `IndeedProvider`
  (implement `DiscoveryProviderPort`), `ATSRegistry`, `GenericSERPStrategy`.
- `persistence/` — `DatabaseManager`, `JobRepository`, `ProfileRepository`,
  `GeoDatabaseRepository`.
- `network/` — `UrllibHTTPClient`, `NetworkHealthMonitor`, `RobotsPolicy`,
  `DomainThrottler`.
- `reasoning/` — `FormSolver`, `GPT4AllAdapter`, `ClingoFormSolver`.
- `evasion/` — `EvasionManager`, fingerprinting scripts, CAPTCHA handler.
- `security/` — `DataVault` (AES‑256 encryption), `ProvenanceSigner`,
  `PolicyEnforcement`.

### 4. `infrastructure/` — The Composition Root

The infrastructure layer is the **only place** that may import from both
`adapters/` and `domain/` simultaneously.  It contains:

- **`composition_root.py`** — `build_orchestrator()`: the central wiring
  function that constructs every concrete adapter, every domain filter,
  every engine, and injects them into the orchestrator.  If you want to
  understand the entire object graph, read this file.
- **`registry.py`** — `CapabilitiesRegistry`: the single source of truth
  for “what is available and allowed in this environment”.  All components
  query the registry rather than reading configs or probing the OS directly.
- **`browser_cascade.py`** — `BrowserCascade`: the ordered fallback loop
  that tries Playwright → Selenium → static until a working browser is
  found.
- **`driver_registry.py`** — `DriverRegistry`: holds registered
  `DriverProvider` instances (one per automation tool).
- **`providers/`** — `SeleniumProvider`, `PlaywrightProvider`: encapsulate
  all setup logic for their respective frameworks.
- **`candidates.py`** — `AutomationCandidate` and `CANDIDATE_PRIORITY`:
  the hardcoded priority order for browser selection.

---

## Key Design Decisions

All major architectural choices are recorded as **Architecture Decision
Records (ADRs)**.  Read them in `docs/adr/` for full context, but here are
the highlights:

| ADR | Decision | Summary |
|-----|----------|---------|
| [001](../adr/001_hexagonal_architecture.md) | Hexagonal architecture | Four strict layers, ports & adapters, dependency inversion. |
| [002](../adr/002_dependency_injection_refactor.md) | Constructor injection everywhere | No class constructs its own dependencies. |
| [003](../adr/003_pra_loop_and_state_machine.md) | Dual state machines | Separate FSMs for per‑form page state and session‑level agent state. |
| [004](../adr/004_ats_platform_registry.md) | YAML‑driven ATS registry | New ATS platforms require zero Python changes. |
| [005](../adr/005_human_in_the_loop.md) | HITL checkpoint architecture | Pluggable policy, threading gate, GUI + CLI support. |
| [006](../adr/006_bs4_zero_browser_fallback.md) | Static HTML fallback perception | Works when no browser can be launched. |
| [007](../adr/007_profile_and_schema_driven_ui.md) | Pydantic schema‑driven UI | Adding a profile field automatically updates all UIs. |
| [008](../adr/008_plugin_architecture.md) | Protocol‑based plugin system | Ports are extension points; no plugin framework needed. |
| [009](../adr/009_research_module.md) | Consent‑gated, zero‑PII research | Ethical, passive, anonymised data collection. |
| [010](../adr/010_remediation_changelog.md) | Architecture audit & remediation | Every violation found and fixed in the pre‑alpha cleanup. |

---

## Folder Map

```
src/auto_apply/
├── domain/
│   ├── models/               # Pydantic models (UserProfile, Job, UI, …)
│   ├── ports/                 # Abstract interfaces (BrowserInterface, …)
│   ├── services/              # Pure mathematical algorithms
│   ├── vetting/               # Composable filter chain
│   ├── applications/          # ApplicationState FSM, field classifier
│   ├── config.py              # AppSettings, path constants
│   ├── events.py              # Event enum (all EventBus events)
│   ├── exceptions.py          # Custom exception hierarchy
│   ├── types.py               # Enums (JobStatus, PageType, Keys, Locator)
│   └── logging.py             # Logging setup
│
├── application/
│   ├── agent/                 # AgentOrchestrator, EventBus, StateMachine, ExecutionContext
│   ├── use_cases/             # DiscoveryEngine, VettingEngine, ApplicationEngine
│   ├── workflows/             # DiscoveryWorkflow, VettingWorkflow, ApplicationsWorkflow
│   └── services/              # SessionController, PageActionService, TextMatcher, …
│
├── adapters/
│   ├── primary/
│   │   ├── gui/               # Tkinter GUI (app, dashboard, wizard, settings)
│   │   └── cli/               # Terminal CLI (startup, dashboard, wizard)
│   └── secondary/
│       ├── browser/           # SeleniumAdapter, PlaywrightAdapter, BrowserHealthMonitor
│       ├── perception/        # MathPerceptionAdapter, BS4PerceptionAdapter, DOMScanner
│       ├── interaction/       # InteractionExecutor, input handlers, execution strategies
│       ├── discovery/         # GoogleProvider, BingProvider, IndeedProvider, ATSRegistry
│       ├── persistence/       # DatabaseManager, JobRepository, ProfileRepository
│       ├── network/           # UrllibHTTPClient, NetworkHealthMonitor, throttler
│       ├── reasoning/         # FormSolver, GPT4AllAdapter, ClingoFormSolver
│       ├── evasion/           # EvasionManager, fingerprinting scripts, CAPTCHA handler
│       ├── resolution/        # CaptchaResolutionService
│       ├── security/          # DataVault (AES‑256), ProvenanceSigner, PolicyEnforcement
│       └── os/                # Hardware/OS detectors (BrowserDetector, ToolDetector, …)
│
├── infrastructure/
│   ├── composition_root.py    # THE wiring file — builds the entire object graph
│   ├── registry.py            # CapabilitiesRegistry — single source of truth
│   ├── browser_cascade.py     # Ordered browser fallback loop
│   ├── driver_registry.py     # Provider registry
│   ├── candidates.py          # AutomationCandidate priority list
│   ├── providers/             # SeleniumProvider, PlaywrightProvider (DriverProvider impls)
│   ├── resilient_driver.py    # Decorator for browser resilience
│   ├── lifecycle.py           # BrowserManager context manager
│   ├── factory.py             # Deprecated — kept for compatibility warnings only
│   └── options.py             # Deprecated — kept for compatibility warnings only
│
├── resources/
│   ├── ats/                   # ATS descriptor YAML files (greenhouse, lever, workday, …)
│   ├── config/                # runtime_defaults.yaml
│   ├── locales/               # i18n translation bundles (en.json, es.json, …)
│   └── templates/             # Profile templates
│
└── main.py                    # Application entry point
```

---

## Adding a New Feature

The most common extension tasks follow these patterns:

### New job board (e.g. LinkedIn)
1. Implement `DiscoveryProviderPort` in
   `adapters/secondary/discovery/providers/linkedin.py`.
2. Register it in `infrastructure/composition_root.py` by appending to
   the `providers` list.
3. (Optional) add any LinkedIn‑specific configuration to
   `resources/config/runtime_defaults.yaml`.

No other files need to change.

### New ATS platform (e.g. Ashby)
1. Create `resources/ats/ashby.yaml` following the existing format
   (URL patterns, login wall signals, success signals, selectors).
2. Restart AA. The `ATSRegistry` loads it automatically.

No Python code changes required.

### New perception adapter (e.g. LLM‑based)
1. Implement `PerceptionPort` in
   `adapters/secondary/perception/llm_perception_adapter.py`.
2. Wire it in the perception selection block of `composition_root.py`.

The `ApplicationEngine` receives a `PerceptionPort` — it does not know
which adapter is active.

---

## Testing Philosophy

- **Unit tests** use `MagicMock` to satisfy port contracts.  No real
  browser, database, or network is needed.  See `tests/conftest.py` for
  shared fixtures.
- **Integration tests** use a real `:memory:` SQLite database and mocked
  engines to verify orchestrator logic (checkpoint recovery, retries,
  batching).
- **Smoke tests** verify that `build_orchestrator()` completes without
  crashing.
- All tests live under `tests/` and mirror the `src/` structure.

Run the full suite:

```bash
uv run pytest tests/ -x -q
```

---

## Where to Go Next

- [Contribution Workflow](contribution_workflow.md) — how to open a PR
  that gets merged quickly.
- [Project Setup](project_setup.md) — clone, uv, IDE configuration.
- [Running Tests](running_tests.md) — test markers, fixtures, writing
  new tests.
- [Adding an ATS Platform](adding_an_ats_platform.md) — the quickest way
  to make a meaningful contribution.
- [Architecture Deep Dive](../architecture/index.md) — detailed walk‑throughs
  of every engine, the cascade, evasion, and the application FSM.
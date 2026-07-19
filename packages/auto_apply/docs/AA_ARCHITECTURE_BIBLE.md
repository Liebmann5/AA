# AutoApply (AA) — Architecture Bible
**Version 1.0 | June 2026 | Author: Nicholas Liebmann**

> This document is the single authoritative reference for every architectural decision,
> layer boundary, subsystem contract, control flow, and integration rule in AA.
> When any piece of code, any new feature, or any external tool conflicts with a rule
> defined in this document, the document wins — the code is wrong, not the rule.
> When this document is wrong, update the document first, then the code.

---

## Table of Contents

1. [Foundational Invariants](#1-foundational-invariants)
2. [Architecture Map](#2-architecture-map)
3. [Layer Boundaries and Hard Cut-offs](#3-layer-boundaries-and-hard-cut-offs)
4. [Domain Layer Reference](#4-domain-layer-reference)
5. [Application Layer Reference](#5-application-layer-reference)
6. [Infrastructure Layer Reference](#6-infrastructure-layer-reference)
7. [Adapter Reference](#7-adapter-reference)
8. [The Three Engines](#8-the-three-engines)
9. [Math Subsystem — Correct Architecture](#9-math-subsystem--correct-architecture)
10. [Browser Layer](#10-browser-layer)
11. [Session Lifecycle and Control Flow](#11-session-lifecycle-and-control-flow)
12. [PRA Loop — Formal Definition](#12-pra-loop--formal-definition)
13. [Session Supervisor — The Missing Layer](#13-session-supervisor--the-missing-layer)
14. [Configuration System](#14-configuration-system)
15. [ATS Platform Registry](#15-ats-platform-registry)
16. [Evasion and Security Framework](#16-evasion-and-security-framework)
17. [NLP and Reasoning Layer](#17-nlp-and-reasoning-layer)
18. [Research Module](#18-research-module)
19. [User-Facing Options Reference](#19-user-facing-options-reference)
20. [Integration Guide](#20-integration-guide)
21. [Issue Triage and Priority Register](#21-issue-triage-and-priority-register)
22. [Future Roadmap](#22-future-roadmap)

---

## 1. Foundational Invariants

These rules are not guidelines. They are permanent invariants. If any new feature,
refactor, or external integration would require violating one of these, the approach
is wrong and must be reconsidered.

### 1.1 The Worst-Case User Contract

AA's **primary** user is someone on a library computer with:
- 2 GB RAM (possibly shared with OS)
- No admin rights (cannot install system packages)
- No external API keys
- Possibly no internet beyond the browser session
- A USB drive as their only persistent storage
- Windows (most common), but potentially macOS or Linux

Every feature must degrade gracefully for this user. Features that require
GPU, cloud APIs, large model downloads (>500MB), or admin rights are
**opt-in enhancements only** and must never be in the critical path.

This constraint drives everything downstream: why Python, why SQLite WAL,
why Selenium as primary browser, why rule-based NLP is the fallback, why
the hexagonal port pattern (swap implementations per environment).

### 1.2 Core Design Principles (Non-Negotiable)

| Principle | What It Means for AA |
|---|---|
| Separation of Concerns | Each class has one reason to change |
| Single Source of Truth | Every configurable value defined in exactly one place |
| DRY | No logic duplicated across engines or layers |
| Hexagonal Architecture | Domain/Application never import from Infrastructure/Adapters |
| Dependency Inversion | High-level modules define interfaces; low-level modules implement them |
| Worst-Case First | Every feature works at library-computer spec before being enhanced |
| Zero Required External Keys | All LLM/AI features have local fallbacks |
| Agnostic Implementations | No tool, library, OS, or browser is hardcoded in domain/application |

### 1.3 The Six Absolute Rules

These six rules, if violated, mean the code must be fixed before merging:

1. **No domain/application layer import shall reference infrastructure or any adapter.**
   - `from auto_apply.infrastructure` anywhere in `domain/` or `application/` is a bug.
   - `from auto_apply.adapters` anywhere in `domain/` or `application/` is a bug.

2. **No component shall define a default that overrides runtime_defaults.yaml.**
   - If a config value is in the YAML, its Python default must be read from the YAML.
   - Hardcoded Python defaults like `max_concurrent_sources: int = 4` when YAML says 1 are bugs.

3. **The browser is never shared across threads without a lease.**
   - Concurrent access to a single browser instance is always a bug.
   - `BrowserLeaseManager` is the sole enforcement mechanism.

4. **Engines never call each other directly.**
   - Discovery, Vetting, and Application engines communicate exclusively through
     the orchestrator and the EventBus. No engine imports another engine.

5. **MathDiscoveryProvider does not exist.**
   - The Math subsystem is a PageUnderstandingStrategy, not a discovery source.
   - See Section 9 for the correct architecture.

6. **All imports are absolute: `from auto_apply.X import Y`.**
   - Relative imports are forbidden codebase-wide.

---

## 2. Architecture Map

```
┌──────────────────────────────────────────────────────────────────┐
│  PRIMARY ADAPTERS (Driving)                                       │
│  GUI (tkinter)  │  CLI (argparse)  │  Tests (pytest)              │
└────────────────────────┬─────────────────────────────────────────┘
                         │ calls
┌────────────────────────▼─────────────────────────────────────────┐
│  APPLICATION LAYER                                                │
│  AgentOrchestrator  │  StateMachine  │  EventBus                  │
│  DiscoveryWorkflow  │  VettingWorkflow  │  ApplicationsWorkflow    │
│  Services: TextMatcher, ResourceManager, CheckpointManager, etc. │
└────────────────────────┬─────────────────────────────────────────┘
                         │ depends on (through ports)
┌────────────────────────▼─────────────────────────────────────────┐
│  DOMAIN LAYER                                                     │
│  Models: Job, UserProfile, WorkUnit, RuntimeProfile, etc.        │
│  Ports: BrowserPort, DiscoveryPort, PerceptionPort, etc.         │
│  Domain Services: Hungarian, ConvexHull, StructuralHash, etc.   │
│  FSMs: AgentState, ApplicationState                              │
└──────────────────────────────────────────────────────────────────┘
                         │ implemented by
┌────────────────────────▼─────────────────────────────────────────┐
│  SECONDARY ADAPTERS (Driven)                                      │
│  Browser: SeleniumAdapter, PlaywrightAdapter, StaticFetchAdapter  │
│  Discovery: GoogleProvider, BingProvider, IndeedProvider, etc.   │
│  Perception: MathPerceptionAdapter, BS4PerceptionAdapter         │
│  Evasion: EvasionManager, DetectionStrategy, BehaviorSimulator   │
│  Reasoning: FormSolver, LLMAdapter, ASPAdapter                   │
│  Persistence: DatabaseManager, JobRepository, ProfileRepository  │
│  Network: DomainThrottler, RobotsPolicy, NetworkMonitor          │
└────────────────────────┬─────────────────────────────────────────┘
                         │ wired by
┌────────────────────────▼─────────────────────────────────────────┐
│  INFRASTRUCTURE LAYER                                             │
│  CompositionRoot (build_orchestrator)  │  BrowserCascade          │
│  CapabilitiesRegistry  │  DriverRegistry  │  BrowserLeaseManager  │
│  SessionPlan  │  ResilientDriver  │  Factory  │  Options           │
└──────────────────────────────────────────────────────────────────┘
```

**Dependency flow: Primary Adapters → Application → Domain ← Secondary Adapters ← Infrastructure**

The domain layer has NO arrows pointing outward. It defines interfaces (ports)
that others implement. Nothing flows from domain to anything else.

---

## 3. Layer Boundaries and Hard Cut-offs

### 3.1 What Belongs in Each Layer

#### Domain Layer (`domain/`)
**Allowed:**
- Pure Python data models (Pydantic, dataclasses, enums)
- Abstract port interfaces (`Protocol` or `ABC`)
- Pure domain logic with zero I/O (algorithms, calculations)
- Business rules and invariants
- Domain exceptions

**Forbidden:**
- Any import from `adapters/`, `infrastructure/`, `application/`
- Any I/O (file reads, network calls, database queries)
- Any browser interaction
- Any config file reads
- Any threading
- Concrete adapter classes

**Examples of correct domain code:**
- `Job` model, `UserProfile`, `WorkUnit`, `RuntimeProfile`
- `BrowserInterface` (Protocol), `DiscoveryProviderPort` (Protocol)
- Hungarian algorithm (`label_input_pairing.py`)
- `ApplicationState` FSM enum + transition table

**Examples of violations that must be fixed:**
- `research_collector.py` importing `CapabilitiesRegistry` from infrastructure ← BUG
- `domain/config.py` defining `settings` object that reads YAML ← Config reads belong in infrastructure
- Any domain model calling `Path.exists()` ← I/O

#### Application Layer (`application/`)
**Allowed:**
- Orchestration logic (coordinates ports, never implements them)
- Application services (TextMatcher, CheckpointManager, etc.)
- Workflow classes (Discovery/Vetting/Application workflows)
- Event definitions and EventBus
- State machine logic
- Use case classes

**Forbidden:**
- Any import from `adapters/` or `infrastructure/`
- Creating concrete adapter instances (that's infrastructure's job)
- Direct browser interaction
- Filesystem reads except through injected ports
- Thread creation (orchestrator is single-threaded; monitors are infrastructure)

**Examples of correct application code:**
- `AgentOrchestrator` — coordinates workflows, publishes events, manages state
- `DiscoveryWorkflow` — calls providers through `DiscoveryProviderPort`, never directly
- `TextMatcher` — pure NLP service, receives spacy model through DI
- `EventBus` — thread-safe pub/sub, no business logic

**Examples of violations:**
- `SessionController` currently in `infrastructure/` ← Should be `application/services/`
- Any workflow directly instantiating `SeleniumAdapter` ← Must go through port

#### Infrastructure Layer (`infrastructure/`)
**Allowed:**
- `CompositionRoot` — the one place that wires everything together
- `BrowserCascade` — tries browser implementations in order
- `CapabilitiesRegistry` — hardware detection and capability resolution
- `ResilientDriver` — wraps BrowserInterface with fault tolerance
- `BrowserLeaseManager` — enforces concurrency limits
- `SessionPlan` — immutable, serializable session configuration
- Factory and option builder classes

**This layer is allowed to import from everywhere.** It's the wiring layer.
Its job is to know about everything so nothing else has to.

#### Secondary Adapters (`adapters/secondary/`)
**Allowed:**
- Concrete implementations of domain ports
- Framework-specific code (Selenium, Playwright, BS4, spacy)
- External service clients
- Hardware-specific code

**Forbidden:**
- Business logic
- Cross-adapter imports (browser adapter should not import from evasion adapter)
- Direct use of other adapters (go through ports)

### 3.2 The Composition Root Contract

`build_orchestrator()` in `infrastructure/composition_root.py` is the ONLY
place in the entire codebase where concrete implementations are instantiated
and wired together. This is not a suggestion — it is an architectural law.

If you find yourself doing this anywhere else:
```python
from auto_apply.adapters.secondary.browser.selenium_adapter import SeleniumAdapter
adapter = SeleniumAdapter(driver)
```
...in a workflow, service, or engine, it is a violation that must be moved to
the composition root.

### 3.3 Violation Detection Checklist

Run this check before any commit:

```bash
# Should return ZERO results:
grep -r "from auto_apply.infrastructure" auto_apply/domain/
grep -r "from auto_apply.adapters" auto_apply/domain/
grep -r "from auto_apply.infrastructure" auto_apply/application/
grep -r "from auto_apply.adapters" auto_apply/application/
grep -r "import auto_apply.infrastructure" auto_apply/domain/
grep -r "import auto_apply.adapters" auto_apply/domain/
```

---

## 4. Domain Layer Reference

### 4.1 Models (Complete Reference)

| Model | File | Purpose | Mutable? |
|---|---|---|---|
| `Job` | `models/job.py` | Represents a discovered job listing | Yes (metadata enriched) |
| `UserProfile` | `models/profile.py` | All user personal and preference data | No (loaded once) |
| `JobSearchPreferences` | `models/profile.py` | Search criteria subset of profile | No |
| `WorkUnit` | `models/work_unit.py` | Task queue entry (DISCOVER/VET/APPLY etc) | No (frozen) |
| `RuntimeProfile` | `models/resources.py` | Hardware-resolved session capabilities | No (frozen after build) |
| `SessionReport` | `models/session_report.py` | Running stats for a session | Yes (incremented) |
| `InteractionPlan` | `models/ui.py` | Planned sequence of form interactions | No |
| `UIModel` | `models/ui.py` | Snapshot of page interactable elements | No |
| `UIElement` | `models/ui.py` | Single interactable element on page | No |
| `DOMNode` | `models/math_dom.py` | Node in the mathematical DOM tree | **Must be immutable/hashable** |
| `Geometry` | `models/math_dom.py` | Bounding box + scroll-adjusted coords | No |
| `WebpageStructure` | `models/math_webpage.py` | Full mathematical page analysis result | No |
| `ParsedJobDescription` | `models/parsed_job_description.py` | NLP-extracted structured job data | No |
| `Plan` | `models/plan.py` | Application strategy plan | No |
| `ExecutionContext` | `agent/context.py` | Live session state | Yes (accumulates stats) |
| `ResearchSignal` | `models/research_signals.py` | Anonymized research data point | No (frozen) |

**Critical: `DOMNode` must be frozen and hashable.**
See Section 9. The current implementation using mutable dict for attributes
causes `TypeError: unhashable type` on any dict lookup. This breaks
Hungarian algorithm, `build_parent_map`, `tree_distance`, and structural hashing.

### 4.2 Ports (Complete Reference)

Ports are `Protocol` or `ABC` classes in `domain/ports/`. They define contracts
that adapters must fulfill. Domain and application code depends ONLY on ports,
never on concrete adapters.

| Port | File | Implemented By |
|---|---|---|
| `BrowserInterface` | `browser_port.py` | `SeleniumAdapter`, `PlaywrightAdapter`, `StaticFetchAdapter` |
| `DiscoveryProviderPort` | `discovery_port.py` | `GoogleProvider`, `BingProvider`, `IndeedProvider` |
| `PerceptionPort` | `perception_port.py` | `MathPerceptionAdapter`, `BS4Adapter`, `HeuristicAdapter` |
| `PageUnderstandingPort` | **TO BE CREATED** | `MathPageUnderstandingAdapter`, `BS4PageUnderstandingAdapter` |
| `ReasoningPort` | `reasoning_port.py` | `FormSolver`, `ASPAdapter`, `GPT4AllAdapter` |
| `MathPerceptionPort` | `math_perception_port.py` | `MathPerceptionAdapter`, `CDPDOMAdapter` |
| `MathReasoningPort` | `math_reasoning_port.py` | `MathFormUnderstandingService` |
| `TextGenerationPort` | `text_generation_port.py` | `GPT4AllAdapter`, `OpenAIStubAdapter` |
| `TextSimilarityPort` | `text_similarity_port.py` | `SpacyNLPAdapter`, `RuleBasedNLPAdapter` |
| `InteractionPort` | `interaction_port.py` | `HumanLikeAdapter`, `APIDirectAdapter` |
| `WorkQueuePort` | `work_queue_port.py` | `DatabaseManager` |
| `RepositoryPort` | `repository_port.py` | `JobRepository`, `ProfileRepository` |
| `HTTPClientPort` | `http_client_port.py` | `UrllibHTTPClient`, `HTTPXAdapter` |
| `AccessibilityPort` | `accessibility_port.py` | `AOMAdapter`, `BS4AccessibilityAdapter` |
| `LocationPort` | `location_port.py` | `HaversineService` |
| `ResolutionPort` | `resolution_port.py` | `LogicAdapter`, `CaptchaAdapter` |
| `ATSPort` | `ats_port.py` | Per-platform ATS adapters |
| `HealthMonitorPort` | `health_monitor_port.py` | `BrowserHealthMonitor`, `NetworkHealthMonitor` |
| `InterruptPolicyPort` | `interrupt_policy_port.py` | `InterruptionHandler` |

### 4.3 Domain Services (Pure Algorithms)

These are pure Python algorithms with zero I/O. They live in `domain/services/`
and are callable from anywhere without injection (they are stateless functions).

| Service | File | Algorithm |
|---|---|---|
| Hungarian Assignment | `label_input_pairing.py` | O(n³) optimal label-input matching |
| Convex Hull | `convex_hull.py` | Graham scan for geometric clustering |
| Structural Hashing | `structural_hashing.py` | DOM subtree fingerprinting |
| DOM Segmentation | `dom_segmentation.py` | VIPS-inspired page region detection |
| Entropy | `entropy.py` | Shannon entropy for field ambiguity scoring |
| Honeypot Detection | `honeypot_detection.py` | CSS + geometry-based trap detection |
| Occlusion | `occlusion.py` | Z-index + geometry overlap detection |
| Field Type Inference | `field_type_inference.py` | Multi-signal field classification |
| Transformations | `transformations.py` | CSS transform matrix → true polygon |

**Known bug in Hungarian padding:** Cost matrix is padded with `0.0` instead of `1e9`.
This causes the algorithm to prefer dummy assignments over real pairings.
See Issue P0-3 in Section 21.

---

## 5. Application Layer Reference

### 5.1 AgentOrchestrator

**Location:** `application/agent/orchestrator.py`
**Role:** The main loop. Dequeues `WorkUnit` objects and dispatches to engine handlers.
**Does NOT:**
- Create any adapters or infrastructure
- Import from adapters or infrastructure
- Run browser operations directly
- Know about Selenium, Playwright, or any concrete technology

**Task Dispatch Table:**

| TaskType | Handler | Resulting State |
|---|---|---|
| `DISCOVER` | `_handle_discovery` | `DISCOVERING → RUNNING` |
| `DISCOVER_COMPANY` | `_handle_company_discovery` | `DISCOVERING → RUNNING` |
| `VET` | `_handle_vetting` | `VETTING → RUNNING` |
| `APPLY` | `_buffer_application` | (buffered) |
| `HANDLE_CAPTCHA` | `_handle_captcha` | `RESOLVING_CAPTCHA → RUNNING` |

**Batch flushing:** When the work queue is empty, `_flush_all_batches()` fires.
When a company batch reaches `BATCH_THRESHOLD` (default 3), `_process_ready_batch()` fires.

**Company batching disable rule:** Company batching is disabled for linear-mode platforms
(LinkedIn, any platform where applications must be processed strictly one-by-one).
If `task.context_data.get("linear_mode") is True`, the job bypasses the buffer and
applies immediately. This prevents state confusion on platforms that detect multi-tab
behavior.

### 5.2 Dual State Machines

AA has two orthogonal FSMs that must never be merged:

**AgentState** — Governs the session as a whole:
```
IDLE → INITIALIZING → RUNNING ↔ DISCOVERING / VETTING / APPLYING
RUNNING → PAUSED → RUNNING
RUNNING → RESOLVING_CAPTCHA → RUNNING
RUNNING → ERROR_RECOVERY → RUNNING
RUNNING → STOPPING → STOPPED
Any → FAILED (terminal)
```

**ApplicationState** — Governs a single form interaction:
```
UNKNOWN → INITIAL_START → FORM_STEP → REVIEW_STEP → SUBMITTING → SUCCESS
FORM_STEP → UPLOAD_STEP → FORM_STEP
FORM_STEP → MODAL_OPEN → FORM_STEP
Any → LOGIN_WALL (requires human intervention)
Any → ALREADY_APPLIED (terminal for this job)
Any → ERROR (terminal for this job)
Any → CRITICAL_FAILURE (terminal for this job)
```

**Critical missing transition (Bug P0-5):**
`DISCOVERING → IDLE` is not in `VALID_TRANSITIONS`. When all discovery tasks fail
permanently, the orchestrator tries to transition to `IDLE` but the state machine
rejects it, leaving the agent stuck in `DISCOVERING`. Must be added.

### 5.3 EventBus

**Thread safety contract:** Handlers are called on the publishing thread.
Handlers must complete in <5ms. No disk I/O, no network calls, no blocking
operations inside handlers. If a handler needs to do heavy work, it must
enqueue to a background thread using `queue.Queue.put_nowait()`.

**Verified safe handlers:**
- Orchestrator's `_on_browser_unhealthy` — sets a flag only ✓
- `ResearchCollector._on_application_submitted` — uses `queue.put_nowait()` ✓
- GUI's dashboard handlers — use `widget.after(0, callback)` ✓

**Handlers requiring audit:**
- `telemetry.py` — potentially writes to disk ← must use queue
- Any handler that calls `logger.info()` with format strings ← use `%s` style

### 5.4 Workflows

#### DiscoveryWorkflow
**Steps (in order):**
1. `_initialize_sources` — filter providers by runtime availability
2. `_build_search_queries` — cross-product of titles × locations × workplace types
3. `_execute_serp_discovery` — run providers (SERIALLY when `max_concurrent_sources=1`)
4. `_scrape_company_pages` — optional direct careers page mining
5. `_prefilter_with_spacy` — drop blocked vocab/company/location
6. `_normalize_and_deduplicate` — URL deduplication
7. `_classify_job_source` — stamp ATS platform and provider
8. `_enqueue_vet_tasks` — push VET WorkUnits to queue
9. `_emit_completion_summary` — publish DISCOVERY_COMPLETE

**Concurrency rule:** `max_concurrent_sources` MUST come from `_cfg("discovery.max_concurrent_sources", 1)`.
It must NEVER have a Python constructor default that overrides the YAML value.
When the value is 1, skip ThreadPoolExecutor entirely and use a `for` loop.

#### VettingWorkflow
**Filter chain (fail-fast, ordered by cost):**
1. `ThrottlingFilter` — has this URL been applied to before? (DB lookup, cheap)
2. `SpatialLocationFilter` — is this location acceptable? (haversine math, cheap)
3. `LogicFilters` — work authorization, sponsorship? (rule-based, cheap)
4. `ExperienceFilter` — years of experience match? (NLP tier 3, medium cost)
5. `HardSkillsFilter` — required skills overlap? (NLP tier 3, medium cost)
6. `RoleAlignmentFilter` — job title similarity? (NLP tier 3, medium cost)

NLP-dependent filters only run if `TextMatcher` is available. If SpaCy is not
installed, those filters pass vacuously (fail-open, not fail-closed).

**Job description fetching:** Vetting must navigate to `job.url` to get the description.
The current `_fetch_job_description` uses `ui_model.text_content` which doesn't exist
on `UIModel`. See Bug P0-4 in Section 21.

#### ApplicationsWorkflow
**Steps (PRA Loop applied to forms):**
1. `_navigate_to_application` — get to the form URL
2. `_handle_interruptions` — dismiss cookie banners, modals
3. Loop:
   a. `_analyze_form_mathematically` — Math subsystem scans the form
   b. `_instantiate_form_fsm` — set ApplicationState to FORM_STEP
   c. `_classify_all_fields` — SpaCy/rule-based field classification
   d. `_fill_standard_fields` — fill known fields from profile
   e. `_generate_custom_answers` — LLM/rule-based for unknown fields
   f. `_handle_file_uploads` — resume/cover letter uploads
   g. `_handle_interruptions` — handle any new modals
   h. `_navigate_multi_page_flow` — click Next, advance form
4. `_submit_application` — click Submit
5. `_record_application_outcome` — persist result, publish event

---

## 6. Infrastructure Layer Reference

### 6.1 CompositionRoot — `build_orchestrator()`

This function is the sole wiring point for the entire system. The call order matters:

```
1. Load config: CapabilitiesRegistry.load() → _effective_config
2. Detect hardware: CapabilitiesRegistry.detect_hardware() → RuntimeProfile
3. Build SessionPlan from _effective_config + RuntimeProfile  ← TO BE ADDED
4. Acquire browser: BrowserCascade.acquire_driver() → ResilientDriver
5. Build BrowserLeaseManager(driver, plan.max_concurrency)  ← TO BE ADDED
6. Build adapters: SeleniumAdapter/PlaywrightAdapter wrapping driver
7. Build text_matcher (ONE instance, shared everywhere)
8. Build perception_port, reasoning_port, interaction_port
9. Build providers with injected adapters
10. Build workflows with injected providers and services
11. Build orchestrator with injected workflows
12. Return orchestrator
```

**Single instance rule:** `text_matcher` (SpaCy, 685MB) MUST be built exactly once
and injected into every component that needs it. Currently it is being instantiated
in `SelectInputHandler`, `FormSolver`, and `build_orchestrator` — that is 3x the
memory footprint. See Bug P1-2 in Section 21.

### 6.2 BrowserCascade

Tries browser implementations in priority order until one succeeds:
```
1. playwright/chromium (bundled, best stealth)
2. playwright/firefox (bundled)
3. playwright/webkit (bundled)
4. selenium/chrome (OS-installed)
5. selenium/firefox (OS-installed)
6. selenium/edge (OS-installed)
7. static (no browser, BS4 fallback)
```

**Known bug:** Playwright candidates (1, 2, 3) each trigger a separate binary download
check instead of sharing one. On a library computer this is three 100MB+ downloads.
Fix: add idempotency check to `PlaywrightProvider` — if binary exists, skip. See Bug P1-3.

**Telemetry-based learning (missing feature):** When a candidate fails, that failure
should be logged to `TelemetryService`. On the next session, failed candidates should
be tried last or skipped. Currently `TelemetryService` exists but is not wired into
`BrowserCascade`. This is P2 work.

### 6.3 CapabilitiesRegistry

Manages the three-tier config hierarchy and hardware detection.

**Config merge order (lower overrides higher):**
```
1. runtime_defaults.yaml (base)
2. admin_policy.json (if present)
3. UserProfile.app_config (user preferences)
```

The resulting `_effective_config` dict is the single source of truth for all
runtime parameters. No component may define its own default that contradicts it.

### 6.4 ResilientDriver

**Current bug:** `ResilientDriver` wraps `BrowserInterface` but does not inherit from it.
This means it cannot be used as a `BrowserInterface` substitutively — any component
typed to `BrowserInterface` will reject it. Fix: `ResilientDriver` must inherit from
`BrowserInterface` and explicitly implement every abstract method. See Bug P0-1.

**Missing methods (confirmed):**
- `perform_mouse_fidget` ← breaks evasion behavior
- `find_elements` ← breaks JSON-LD extraction
- `switch_to_iframe` ← breaks iframe form filling
- `get_cookies`, `add_cookie` ← breaks session persistence
- `scroll_by_offset`, `move_mouse_to_element` ← breaks human behavior simulation
- All other `BrowserInterface` methods not in the current implementation

**`is_alive()` false positive fix:**
Selenium: `try: driver.execute_script("return 1"); return True` — this is the only
reliable session check.
Playwright: `return not page.is_closed()`
Add `_is_navigating: bool` flag: set to `True` at start of `get()`, `False` on
completion. Health monitor must not emit `BROWSER_UNHEALTHY` while `_is_navigating` is True.

### 6.5 SessionPlan (To Be Added)

`SessionPlan` is a frozen, serializable configuration object assembled by
`build_orchestrator()` before anything else runs. It is the single authoritative
answer to "how should this session run?"

```python
@dataclass(frozen=True)
class SessionPlan:
    session_id: str
    max_concurrency: int          # from config, enforced by BrowserLeaseManager
    max_results_per_query: int
    max_applications_per_session: int
    max_applications_per_company: int
    enable_company_page_mining: bool
    use_ats_site_search: bool
    date_range: str | None        # "day" | "week" | "month" | None
    providers: list[str]          # which providers to use
    linear_mode_platforms: set[str]  # platforms that disable batching
    research_enabled: bool
    random_seed: int | None       # for deterministic research runs
    nlp_tier: Literal["basic", "spacy", "transformer"]
    browser_framework: Literal["selenium", "playwright", "static"]
    headless: bool
    stealth_mode: bool
```

Serializing `SessionPlan` to disk = saving the complete experiment parameters,
which is the research-grade reproducibility requirement.

### 6.6 BrowserLeaseManager (To Be Added)

```python
class BrowserLeaseManager:
    def __init__(self, driver: BrowserInterface, max_concurrent: int = 1):
        self._driver = driver
        self._semaphore = threading.Semaphore(max_concurrent)

    @contextmanager
    def acquire(self):
        self._semaphore.acquire()
        try:
            yield self._driver
        finally:
            self._semaphore.release()
```

Every component that performs browser navigation must call:
```python
with lease_manager.acquire() as browser:
    browser.get(url)
    # ... use browser
```

This makes it structurally impossible for concurrent threads to fight over the browser.
When `max_concurrent=1`, only one provider runs at a time. No YAML value can be ignored
because the semaphore is the enforcement, not a config check inside workflow code.

---

## 7. Adapter Reference

### 7.1 Browser Adapters

| Adapter | File | Backend | Best For |
|---|---|---|---|
| `SeleniumAdapter` | `browser/selenium_adapter.py` | Selenium WebDriver | Worst-case users, OS browsers |
| `PlaywrightAdapter` | `browser/playwright_adapter.py` | Playwright | Better stealth, bundled browsers |
| `StaticFetchAdapter` | `browser/static_fetch_adapter.py` | urllib + BS4 | No browser, reading-only pages |

All three implement `BrowserInterface`. The orchestrator never knows which one
it has — it only sees `BrowserInterface`.

### 7.2 Discovery Adapters

#### Valid Providers (Sources of Job Data)
These answer: "where do I look for jobs?"

| Provider | Requires Browser | Method |
|---|---|---|
| `GoogleProvider` | Yes (or static) | SERP scraping + JSON-LD |
| `BingProvider` | Yes (or static) | SERP scraping |
| `IndeedProvider` | Yes | Human search navigation + CSS |
| `LinkedInProvider` | Yes | Human search navigation (linear mode) |
| `DuckDuckGoProvider` | Yes (or static) | SERP scraping |
| `ATSSiteSerpProvider` | Yes | ATS-targeted site: query strategy |

#### NOT a Provider (Architecture Violation)
`MathDiscoveryProvider` — This does not belong in the provider list.
See Section 9 for the correct placement of the math subsystem.

### 7.3 Perception Adapters

These answer: "what is on this page?"

| Adapter | Port | Strategy | When Used |
|---|---|---|---|
| `MathPerceptionAdapter` | `MathPerceptionPort` | JS DOM extraction + math | Primary, all pages |
| `BS4PerceptionAdapter` | `PerceptionPort` | BeautifulSoup HTML parsing | Fallback, no browser |
| `DOMScanner` | `PerceptionPort` | Selenium AOM traversal | Interactive pages |
| `AOMAdapter` | `AccessibilityPort` | Accessibility tree | Secondary validation |
| `CDPDOMAdapter` | `MathPerceptionPort` | CDP snapshot (stealth) | Chrome only, future |

### 7.4 Interaction Adapters

These answer: "how do I interact with elements?"

| Adapter | Port | When Used |
|---|---|---|
| `HumanLikeAdapter` | `InteractionPort` | Always (default, Bezier curves, human timing) |
| `APIDirectAdapter` | `InteractionPort` | Headless mode, no anti-bot risk |

### 7.5 Evasion Adapters

| Adapter | Role |
|---|---|
| `EvasionManager` | Central coordinator for all evasion |
| `DefaultDetectionStrategy` | Detects CAPTCHA challenges (confidence-weighted) |
| `BehaviorSimulator` | Human-like browser behavior (mouse moves, scrolls) |
| `SessionManager` | Cookie/storage persona persistence |
| `FingerprintChrome/Firefox` | TLS + WebGL + Canvas fingerprint spoofing |

**CAPTCHA detection policy:**
The `js_variables` array in `detection_config.json` MUST be empty `[]`.
Presence of `window.grecaptcha` is NOT a CAPTCHA challenge — it is a login widget.
Only flag CAPTCHA if ALL of: `iframe_keywords` match AND (`text_keywords` match OR `url_keywords` match).

---

## 8. The Three Engines

### 8.1 Discovery Engine

**Purpose:** Find job listings from external sources.
**Input:** Search criteria (job titles, locations, workplace types)
**Output:** List of `Job` objects enqueued as VET WorkUnits
**Does NOT:** Vet jobs, fill forms, make decisions about fit

**The Discovery-Vetting boundary:**
Discovery creates raw job listings. Vetting decides if the user should apply.
Discovery must never apply business rules about the user's fit — it only finds jobs
that might exist. This keeps discovery reusable for the "list mode" feature where AA
returns links without applying.

**Supported discovery modes:**
1. **SERP Search** — query Google/Bing/DDG, extract result links
2. **Direct Provider** — navigate to Indeed/LinkedIn, extract from their UI
3. **ATS Site Search** — build `site:jobs.ashbyhq.com | ...` query, execute on SERP
4. **Company Page Mining** — given a careers URL, scrape all jobs on it
5. **Static Fetch** — no browser, BS4 + HTTP client for simple pages

### 8.2 Vetting Engine

**Purpose:** Decide if the user should apply to a discovered job.
**Input:** A `Job` object with URL
**Output:** Pass (enqueue APPLY task) or Fail (log reason, discard)
**Does NOT:** Apply to jobs, interact with forms, navigate to new pages beyond the job description

**Vetting must navigate to the job URL** to read the actual job description.
Vetting the Google SERP page or a job aggregator summary is garbage — the
description text must come from the real job posting page.

### 8.3 Application Engine

**Purpose:** Fill out and submit a job application.
**Input:** A `Job` object with application URL + metadata
**Output:** Success/Failure + outcome recorded in DB
**Does NOT:** Discover jobs, vet jobs, make "should I apply" decisions

**Tab redirect handling:**
When clicking "Apply" opens a new tab, the Application Engine must:
1. Detect the new window handle (`browser.window_handles` increased)
2. Switch to the new tab
3. Continue the PRA loop in the new context
4. When done, close the new tab and return to the previous one

The Application Engine must NEVER accidentally run Discovery logic when
a redirect lands on a company's job listings page. If the redirect target
is detected as a job list page, the Engine must publish a `RedirectToListDetected`
event and return `False` for the current job. The orchestrator then decides
whether to enqueue a new DISCOVER_COMPANY task.

**Linear mode (LinkedIn, per-tab platforms):**
When `linear_mode=True`:
- Company batching is disabled
- Jobs are processed one at a time
- After each application, a human pause is required before proceeding
- The state machine uses `AWAITING_HUMAN` state between applications

---

## 9. Math Subsystem — Correct Architecture

### 9.1 What the Math Subsystem Actually Is

The Math subsystem is a **page analysis toolkit** — a collection of algorithms
that analyze a web page's structure, geometry, and element relationships.
It is NOT a job discovery source.

**What it can do:**
- Extract the DOM tree with full geometry (coordinates, dimensions, z-index)
- Detect repeated structural patterns (job cards on a SERP, form fields)
- Pair form labels to their input elements (Hungarian algorithm)
- Calculate element spatial relationships (convex hull, occlusion, tree distance)
- Detect honeypot fields via geometry + entropy analysis
- Hash structural subtrees for change detection

**What it cannot do:**
- Search the internet for jobs (not a source)
- Navigate to a URL (requires a browser adapter)
- Make decisions about jobs (not a vetting tool)

### 9.2 The Violation: MathDiscoveryProvider

`MathDiscoveryProvider` currently appears in the providers list alongside
`GoogleProvider`, `BingProvider`, and `IndeedProvider`.

This is wrong because:
1. It conflates "where to find jobs" with "how to understand a page"
2. It requires a browser AND a search query — it's not a source, it's an analysis layer
3. It violates Single Responsibility: a provider should source data, not analyze it

### 9.3 The Correct Architecture

```
domain/ports/page_understanding_port.py:

class PageUnderstandingPort(Protocol):
    def analyze_serp(self, page_context: PageContext) -> SERPStructure: ...
    def analyze_form(self, page_context: PageContext) -> FormStructure: ...
    def analyze_job_listing(self, page_context: PageContext) -> JobListingStructure: ...
```

```
adapters/secondary/perception/math_page_understanding_adapter.py:
class MathPageUnderstandingAdapter:
    """Implements PageUnderstandingPort using the mathematical DOM subsystem."""
    def analyze_serp(self, ctx) -> SERPStructure:
        tree = self._math_dom.extract_dom_tree()
        cards = dom_segmentation.find_repeated_patterns(tree)
        return SERPStructure(job_cards=cards, ...)
```

```
adapters/secondary/perception/bs4_page_understanding_adapter.py:
class BS4PageUnderstandingAdapter:
    """Implements PageUnderstandingPort using BeautifulSoup (fallback)."""
```

Each provider then receives `page_understanding: PageUnderstandingPort` via DI:
```python
class GoogleProvider:
    def __init__(self, browser, prefs, page_understanding: PageUnderstandingPort):
        self._page_understanding = page_understanding
    
    def run(self):
        # Navigate...
        structure = self._page_understanding.analyze_serp(context)
        jobs = self._extract_from_structure(structure)
```

`MathDiscoveryProvider` is deleted. The math capability is now available to ALL
providers, not just one.

### 9.4 Known Math Subsystem Bugs (Priority Order)

**P0 — Blocks operation entirely:**
1. `find_by_tags` typo in `_is_likely_card()` → `find_by_tag` (singular)
2. `DOMNode` is not hashable — mutable dict/list fields break all parent maps
3. Scroll offset missing: `getBoundingClientRect()` returns viewport-relative coords.
   Fix: add `window.scrollX` / `window.scrollY` to all geometry calculations.
4. Hungarian cost matrix padded with `0.0` instead of `1e9`

**P1 — Degrades accuracy:**
5. `_is_likely_card()` checks CSS class names ("job", "card") — fails on Tailwind/CSS-in-JS
   Fix: use `find_repeated_patterns()` with area > 2500px² + contains `<a href>` check
6. `ParsedJobDescription` constructor called with wrong field names in `analyze_job_description()`
7. VettingEngine calls `analyze_job_description()` without first navigating to `job.url`

---

## 10. Browser Layer

### 10.1 BrowserInterface Contract (Complete)

Every method listed below MUST be implemented by ALL browser adapters.
If a new method is added to `BrowserInterface`, ALL adapters must implement it.

```python
# Navigation
get(url: str) -> None
back() -> None
close() -> None

# Properties
framework_name: str
title: str
page_source: str
current_url: str

# Element finding
find_element(by: str, selector: str) -> ElementInterface | None
find_elements(by: str, selector: str) -> list[ElementInterface]
wait_for_element(by: str, selector: str, timeout: int = 10) -> ElementInterface | None

# Scripting
execute_script(script: str, *args) -> Any
switch_to_iframe(iframe_element: ElementInterface) -> None
switch_to_default_content() -> None

# Cookies / Storage
get_cookies() -> list[dict]
add_cookie(cookie: dict) -> None

# Mouse / Scroll
scroll_by_offset(x: int, y: int) -> None
move_mouse_by_offset(x: int, y: int) -> None
move_mouse_to_element(element: ElementInterface, offset_x: int, offset_y: int) -> None
perform_mouse_fidget() -> None

# Human interaction
human_click(selector: str) -> None
human_type(element_or_selector, text: str, wpm: int = 60) -> None

# Utility
save_screenshot(filepath: str) -> None
is_alive() -> bool
```

### 10.2 ResilientDriver

`ResilientDriver` MUST inherit from `BrowserInterface`.

```python
class ResilientDriver(BrowserInterface):
    def __init__(self, driver: BrowserInterface): ...
```

Methods with added resilience logic (retry, lock, error suppression):
- `get()` — adds lock + "target window already closed" suppression
- `find_element()` — adds iframe traversal fallback
- `is_alive()` — always `execute_script("return 1")` for Selenium, `not page.is_closed()` for Playwright
- `save_screenshot()` — uses `LOG_DIR` for cross-platform paths

All other methods: pure delegation to `self._driver`.

### 10.3 Human Behavior in Browser

The `BehaviorSimulator` (in `evasion/components/behavior.py`) is the sole
authority on human-like browser behavior. Do not implement human timing anywhere else.

**Session-level idle behavior:**
When the agent is running (states: DISCOVERING, VETTING, APPLYING), the browser
must never be stationary for >8 seconds. An idle behavior daemon fires every 5-10
seconds (random) to perform one of: `perform_mouse_fidget()`, slight scroll,
move to random position. This daemon must:
- Run as a daemon thread
- Check `_is_navigating` flag before acting (never interrupt an active navigation)
- Stop immediately when state is IDLE, STOPPED, or FAILED

**Between-provider pauses:**
A random 2.0–5.0 second pause between providers in a single discovery run.
This is already present in `behavior.py` — verify it is actually called and
not silently skipped.

---

## 11. Session Lifecycle and Control Flow

### 11.1 High-Level Flow

```
User launches AA
    ↓
main.py → SessionController.start()
    ↓
SessionController determines mode:
  - GUI mode: launch tkinter, wait for wizard completion
  - CLI mode: parse arguments, build criteria
    ↓
SessionController.run_session(profile, criteria)
    ↓
build_orchestrator(profile, criteria) → AgentOrchestrator
    ↓
orchestrator.seed_work_queue([WorkUnit(DISCOVER, criteria)])
orchestrator.run()
    ↓
[MAIN LOOP - single thread]
while running:
    task = task_queue.dequeue()
    if not task:
        _flush_all_batches()
        break
    _ensure_browser_ready(task)
    _dispatch_task(task)
    checkpoint_manager.save()
```

### 11.2 Discovery → Vetting → Application Flow

```
DISCOVER task dequeued
    ↓
DiscoveryWorkflow.run()
    ↓
For each provider (serially):
    with BrowserLeaseManager.acquire() as browser:
        provider.run(criteria)
        → returns list[Job]
    ↓
prefilter → dedup → classify
    ↓
For each unique job:
    task_queue.enqueue(WorkUnit(VET, job))
    ↓
VET task dequeued
    ↓
VettingWorkflow.run(job)
    ↓
browser.get(job.url)  ← MUST navigate first
    ↓
filter_chain.apply(job)
    ↓
if passes:
    task_queue.enqueue(WorkUnit(APPLY, job))
    ↓
APPLY task dequeued
    ↓
orchestrator._buffer_application(job)
    ↓
When batch full OR queue empty:
    ApplicationsWorkflow.run(job)
    ↓
PRA Loop (form filling)
    ↓
record outcome → DB
publish APPLICATION_SUBMITTED / APPLICATION_FAILED
```

### 11.3 State Machine Transitions (Complete Valid Set)

Current `VALID_TRANSITIONS` must include:
```python
AgentState.DISCOVERING: {AgentState.RUNNING, AgentState.IDLE, AgentState.ERROR_RECOVERY, AgentState.STOPPING},
# ↑ IDLE must be here — currently missing, causes stuck-in-DISCOVERING bug
```

### 11.4 Redirect Handling

When Application Engine detects a redirect:

```
Redirect detected
    ↓
Classify redirect target:
    ├── Is it a job listing page? → publish RedirectToListDetected, return False
    ├── Is it the application form? → continue PRA loop
    ├── Is it the company homepage? → return False (job not accessible)
    ├── Is it a dead link (404)? → return False, log
    ├── Is it a new tab? → switch_to_new_tab(), continue loop
    └── Is it suspicious? → SecurityPolicy.handle(), return False
```

**LinkedIn-specific:**
After clicking Apply, if a side panel opens (same tab, layout shifts):
→ The popup is the application form. Continue in the popup context.
If a new tab opens:
→ switch_to_new_tab(), continue.
If redirected to company site:
→ return False (manual follow-up needed).

**Indeed-specific:**
After clicking Apply, check result:
1. In-page redirect to company form → continue PRA loop
2. New tab → switch_to_new_tab(), continue
3. Lands on related jobs list → publish RedirectToListDetected, return False
4. Application confirmation page → SUCCESS

### 11.5 Session Resume (Checkpoint)

`CheckpointManager.load()` MUST be implemented (currently missing — Bug P0-4).
On session start, if a checkpoint file exists:
1. Load the partial session state
2. Verify DB integrity (jobs that were "in progress" need re-evaluation)
3. Re-enqueue any incomplete tasks
4. Verify max-applications-per-company counters are consistent
5. Resume from the last stable state

---

## 12. PRA Loop — Formal Definition

The PRA (Perceive-Read-Act) Loop is a universal protocol for interacting with
any webpage. It is the architectural contract that enables engine autonomy.

```python
class PRAStrategy(Protocol):
    def perceive(self, context: PageContext) -> PerceptionResult:
        """
        Access the webpage content.
        HOW to access it is up to the implementation.
        MAY use: browser.get(), static fetch, CDP snapshot, accessibility tree.
        MUST NOT make decisions about the content.
        MUST return something even if perception fails (graceful degradation).
        """
    
    def read(self, perception: PerceptionResult) -> ReadingResult:
        """
        Understand what was perceived.
        MUST verify that what was found is what was expected.
        MUST NOT take action based on findings.
        MUST return confidence score along with findings.
        """
    
    def act(self, reading: ReadingResult) -> ActionResult:
        """
        Take the appropriate action based on verified understanding.
        ONLY called when read() returned sufficient confidence.
        MUST handle all edge cases (empty results, unexpected states, security blocks).
        """
```

**The PRA loop is the ticket to autonomy because:**
- `perceive()` is implementation-agnostic: swap BS4 for Math DOM without changing `read()` or `act()`
- `read()` enforces verification: AA cannot act on unverified data
- The loop can be applied to: SERP pages, job descriptions, application forms, company pages

**Concrete implementations:**
- `MathPRAStrategy` — Math DOM adapter for perceive, semantic analysis for read
- `BS4PRAStrategy` — BeautifulSoup for perceive, CSS pattern matching for read
- `HybridPRAStrategy` — tries Math first, falls back to BS4

---

## 13. Session Supervisor — The Missing Layer

### 13.1 What It Is

The Session Supervisor is the missing architectural component that makes AA's
orchestration safe, observable, and deterministic. It is not a new layer —
it is an upgrade to the existing `AgentOrchestrator` that adds three capabilities:

1. **Resource Arbitration** — via `BrowserLeaseManager` (see Section 6.6)
2. **Execution Observability** — via `ExecutionMap` added to `ExecutionContext`
3. **Session Planning** — via `SessionPlan` (see Section 6.5)

### 13.2 ExecutionMap

Added to `ExecutionContext`:

```python
@dataclass
class WorkerStatus:
    worker_id: str
    provider_name: str
    started_at: float
    last_heartbeat: float
    current_action: str
    status: Literal["running", "waiting", "completed", "failed"]

class ExecutionContext:
    # ... existing fields ...
    _execution_map: dict[str, WorkerStatus] = field(default_factory=dict)
    _map_lock: threading.Lock = field(default_factory=threading.Lock)
    
    def register_worker(self, worker_id: str, provider_name: str) -> None: ...
    def heartbeat(self, worker_id: str, action: str) -> None: ...
    def complete_worker(self, worker_id: str) -> None: ...
    def get_stuck_workers(self, timeout_seconds: float = 30.0) -> list[WorkerStatus]: ...
```

**The "git status" for your session:** `orchestrator.context.get_execution_map()`
returns a real-time view of everything currently running. The watchdog daemon
polls this every 10 seconds and publishes `WORKER_STUCK` if any worker hasn't
sent a heartbeat in >30 seconds.

---

## 14. Configuration System

### 14.1 Three-Tier Hierarchy

```
AdminPolicy (highest precedence)
    ↓ overrides
UserProfile.app_config
    ↓ overrides
runtime_defaults.yaml (base, all defaults)
```

### 14.2 runtime_defaults.yaml — Complete Reference

All configurable values with types, defaults, and descriptions:

```yaml
# ─── Browser ───────────────────────────────────────────────────────────
browser:
  headless: true                    # bool: run without visible window
  stealth_mode: true                # bool: apply anti-detection patches
  default_timeout_seconds: 30       # int: page load timeout
  navigation_retries: 3             # int: retries before giving up on URL
  min_navigation_delay_seconds: 1.5 # float: min pause between navigations
  max_navigation_delay_seconds: 4.0 # float: max pause between navigations
  idle_action_max_interval_seconds: 8  # float: max idle before micro-action

# ─── Discovery ─────────────────────────────────────────────────────────
discovery:
  max_concurrent_sources: 1    # int: MUST BE 1 when sharing single browser!
  max_queries_per_session: 20  # int: cap on title×location cross-product
  max_results_per_query: 30    # int: jobs per provider per query
  enable_company_page_mining: false  # bool: follow company careers URLs
  use_ats_site_search: false   # bool: build site: operator queries
  date_range: null             # str: null | "day" | "week" | "month"
  providers:                   # list: which providers to activate
    - google
    - bing
    - indeed
  between_provider_pause_min: 2.0  # float: seconds between providers
  between_provider_pause_max: 5.0

# ─── Vetting ───────────────────────────────────────────────────────────
vetting:
  hard_skills_min_overlap: 0.5     # float: fraction of required skills needed
  role_alignment_threshold: 0.6   # float: SpaCy title similarity minimum
  borderline_band: [0.0, 0.0]     # [float, float]: score range for LLM review
  filter_weights:
    ThrottlingFilter: 0.10
    SpatialLocationFilter: 0.15
    LogicFilters: 0.15
    ExperienceFilter: 0.15
    HardSkillsFilter: 0.20
    RoleAlignmentFilter: 0.25

# ─── Applications ──────────────────────────────────────────────────────
applications:
  max_applications_per_session: 50    # int: hard cap per run
  max_applications_per_company: 3     # int: prevent over-applying
  batch_threshold: 3                  # int: jobs per company before batch applies
  inter_action_delay_ms: 1200         # int: ms between form interactions
  macro_pause_min_seconds: 0.8        # float: longer pauses between steps
  macro_pause_max_seconds: 2.5
  micro_delay_peak_ms: 50             # int: per-keystroke jitter peak
  max_form_steps: 25                  # int: PRA loop circuit breaker
  enable_cover_letter_generation: false  # bool: LLM-generated cover letters
  cover_letter_llm_tier: "rule_based"    # str: rule_based | local_llm | api

# ─── Evasion ───────────────────────────────────────────────────────────
evasion:
  on_captcha_detected: "skip"     # str: skip | retry | stop | manual
  captcha_retry_wait_seconds: 5   # int: wait before retry
  rotate_user_agent: true         # bool: different UA each session
  session_warmup: true            # bool: simulate human browsing before search
  fingerprint_spoofing: true      # bool: randomize canvas/WebGL fingerprint

# ─── Health Monitoring ─────────────────────────────────────────────────
health:
  browser_check_interval_seconds: 30   # int: how often to probe browser
  browser_check_timeout_seconds: 5     # int: probe timeout
  browser_unhealthy_threshold: 3       # int: failures before BROWSER_UNHEALTHY
  browser_max_failures: 10             # int: failures before monitor stops ← MISSING
  disable_monitor_on_low_resource: true  # bool: no monitor if RAM < 2.5GB

# ─── Session ───────────────────────────────────────────────────────────
session:
  max_session_duration_minutes: 60   # int: auto-stop after this
  checkpoint_interval_tasks: 10      # int: save state every N tasks
  log_retention_days: 7              # int: rotate logs after this
  store_debug_logs: false            # bool: verbose logs, only with --debug

# ─── Research ──────────────────────────────────────────────────────────
research:
  enabled: false                     # bool: must be explicitly opted in
  consent_required: true             # bool: always require consent
  pii_anonymization: true            # bool: SHA-256 salted hashing
  export_format: "sqlite"            # str: sqlite | csv | parquet
```

### 14.3 Adding a New Config Value

1. Add to `runtime_defaults.yaml` with a comment explaining purpose and safe range
2. Read it in the relevant component via `self._cfg("section.key", default_value)`
3. If the component doesn't have `_cfg`, inject `config: dict` and add the helper
4. NEVER add a Python default that differs from the YAML value
5. Add to Section 19 (User-Facing Options) if user-configurable

---

## 15. ATS Platform Registry

### 15.1 What It Is

A registry of known ATS (Applicant Tracking System) platforms with their URL patterns,
form strategies, and site-search domains. Every supported ATS has one YAML file
in `resources/ats/`.

### 15.2 Currently Supported Platforms

| Platform | File | URL Pattern | Form Strategy |
|---|---|---|---|
| Greenhouse | `greenhouse.yaml` | `boards.greenhouse.io` | Multi-step, iframes |
| Lever | `lever.yaml` | `jobs.lever.co` | Single-page, clean |
| Workday | `workday.yaml` | `*.wd1.myworkdayjobs.com` | Complex, JS-heavy |
| iCIMS | `icims.yaml` | `careers.icims.com` | Multi-step, legacy |
| Taleo | `taleo.yaml` | `*.taleo.net` | Very legacy, complex |
| Ashby | `ashby.yaml` | `jobs.ashbyhq.com` | Modern, clean |

### 15.3 Platforms To Add (From Job Websites Table)

Based on the user's job website table, these need YAML files and adapters:

| Platform | Domain | Priority |
|---|---|---|
| BambooHR | `bamboohr.com/careers` | High |
| Rippling | `ats.rippling.com` | High |
| Workable | `apply.workable.com` | High |
| SmartRecruiters | `jobs.smartrecruiters.com` | High |
| Jobvite | `jobs.jobvite.com` | High |
| Recruitee | `*.recruitee.com` | Medium |
| Gusto | `jobs.gusto.com` | Medium |
| PinpointHQ | `*.pinpointhq.com` | Medium |
| Eightfold | `*.eightfold.ai/careers` | Medium |
| Keka | `*.keka.com/careers` | Low |
| Dover | `app.dover.io/apply` | Low |
| ZohoRecruit | `*.zohorecruit.com/jobs` | Low |

### 15.4 How to Add a New ATS Platform

1. Create `resources/ats/platform_name.yaml`:
```yaml
name: bamboohr
display_name: BambooHR
url_patterns:
  - "*.bamboohr.com/careers/*"
  - "*.bamboohr.com/jobs/*"
site_search_domain: "bamboohr.com/careers"
form_strategy: "single_page_iframe"
known_challenges:
  - type: "file_upload"
    selector: "input[type=file][name=resume]"
  - type: "cover_letter"
    selector: "textarea[name=coverLetter]"
pagination: null
```

2. ATSRegistry automatically loads it at startup — no code changes needed.

3. If the platform needs a custom form strategy, create:
   `adapters/secondary/discovery/providers/bamboohr_provider.py`
   implementing `ATSPort`.

---

## 16. Evasion and Security Framework

### 16.1 The Evasion Layers (In Order of Activation)

| Layer | When | What It Does |
|---|---|---|
| Session Warmup | Before first search | Simulate human browsing (news articles) |
| Fingerprint Spoofing | On browser init | Randomize canvas, WebGL, navigator properties |
| User-Agent Rotation | On browser init | Fresh UA per session |
| Request Throttling | Before every navigation | Respect robots.txt crawl-delay |
| Human Navigation | During search | Type queries, pause between keystrokes |
| Idle Behavior | During any wait | Mouse movements, micro-scrolls |
| Challenge Detection | After every navigation | Check for CAPTCHA/bot wall |
| CAPTCHA Handling | When detected | Skip/retry/manual per policy |

### 16.2 CAPTCHA Policy Options

Configured via `evasion.on_captcha_detected` in `runtime_defaults.yaml`:

| Value | Behavior | When to Use |
|---|---|---|
| `"skip"` | Log warning, return empty for this URL, continue | Default for most providers |
| `"retry"` | Wait `captcha_retry_wait_seconds`, try once more | When challenge might be transient |
| `"stop"` | Stop this provider entirely, others continue | Never the right choice now |
| `"manual"` | Pause session, publish CAPTCHA_REQUIRES_MANUAL_SOLVE event, wait for human | LinkedIn, high-priority applications |

**CAPTCHA detection confidence threshold:**
A challenge is only flagged when confidence ≥ 70. Signal weights:
- `js_variables` present: 20 (weak — background widget, not a challenge)
- URL keyword match: 30 (moderate)
- Title keyword match: 30 (moderate)
- iframe keyword match: 40 (strong — actual challenge widget rendered)
- Text keyword match: 40 (strong — explicit bot detection message)

### 16.3 Security Options for Users

When a security feature is encountered, users have options (Human-in-the-Loop integration):

1. **Try automatic bypass** — use evasion capabilities (selenium-stealth, fingerprint rotation)
2. **Use installed browser extension** — if user has Camoufox or similar
3. **Solve manually (HITL)** — pause session, user solves, resume
4. **Skip this listing** — move on to next job
5. **Abort session** — stop entirely

This must be presented as a non-blocking UI prompt. The session pauses
(`PAUSED` state), UI shows options, user selects, session resumes.

---

## 17. NLP and Reasoning Layer

### 17.1 Three-Tier NLP Architecture

| Tier | Implementation | RAM | Accuracy | When Active |
|---|---|---|---|---|
| 0 (always) | `RuleBasedNLPAdapter` | <10MB | 70% | Always, fallback |
| 1 (recommended) | `SpacyNLPAdapter` (en_core_web_lg) | ~685MB | 88% | When SpaCy installed |
| 2 (optional) | `SentenceTransformersAdapter` | ~80MB | 92% | For semantic matching |
| 3 (opt-in, paid) | API adapter (OpenAI/Anthropic) | 0 (remote) | 97% | User provides key |

**Single instance rule:** SpaCy model is loaded ONCE in `build_orchestrator()` and
injected everywhere. Loading it in `SelectInputHandler`, `FormSolver`, etc. is a bug.

### 17.2 LLM for Cover Letters and Custom Answers

Governed by `applications.enable_cover_letter_generation` and
`applications.cover_letter_llm_tier`.

```
cover_letter_llm_tier: "rule_based"
    → Template-based generation from profile data (worst-case fallback)

cover_letter_llm_tier: "local_llm"  
    → GPT4All (gguf model, CPU-capable, requires ~4GB disk for model)
    
cover_letter_llm_tier: "api"
    → External API (user must provide key via secure vault)
```

**Answer memory (HITL learning):**
When a user manually answers a miscellaneous question during HITL:
1. Question text + user answer are stored in `UserProfile.answer_history`
2. Question is embedded (if sentence-transformers available) for similarity lookup
3. Future identical/similar questions use the stored answer
4. User can review/edit answer history via Settings

### 17.3 Clingo / ASP Integration

`clingo` is already in dependencies. Its role is formal logic reasoning for:
- Work authorization eligibility (citizenship + location rules)
- Sponsorship requirement determination  
- "Do I meet the requirements?" determination
- Resolving conflicts in form field assignments

`ASPAdapter` in `adapters/secondary/reasoning/asp_adapter.py` implements
`ReasoningPort` using clingo. Use clingo when:
- The answer is provably true/false (binary)
- The rules are static and verifiable
- No "creativity" is needed

Use GPT4All when:
- The answer requires natural language generation
- The question is open-ended
- The answer needs to match the user's writing style

---

## 18. Research Module

### 18.1 Design Principles

The research module is **completely isolated** from the production path.
It NEVER affects job discovery, vetting, or application outcomes.
It ONLY observes and records.

**Data collection gate:** User must explicitly opt in. `research.enabled: false` is
the default. Setting it to `true` in settings triggers a consent dialog that must
be accepted before any data is collected.

### 18.2 PII Anonymization

All user-identifiable data is anonymized using salted SHA-256 before storage:
- Profile name, email → `HMAC-SHA256(user_id + SITE_SALT)`
- Company names → stored as-is (company data, not user data)
- Application outcomes → recorded as pass/fail, not linked to user identity

### 18.3 What Is Collected

Research signals (from `domain/models/research_signals.py`):
- Application outcome (submitted/failed) per ATS platform
- Number of form fields filled per session
- Filter rejection reasons (which filter failed most)
- CAPTCHA encounter rate per domain
- Discovery provider success rates
- Session duration and completion percentage

**What is explicitly NOT collected:**
- Resume content
- Cover letter text
- User answers to form questions
- Login credentials (never stored or logged)
- Job description full text

### 18.4 Research Requirements for PhD-Grade Use

For this software to be cited in academic research:

| Requirement | Status | Notes |
|---|---|---|
| IRB consent language | Missing | Need explicit consent dialog text approved by IRB analog |
| Data retention policy | Documented here | 90 days default, configurable |
| Versioned data schemas | Partial | `ResearchSignal` models need version field |
| Longitudinal study support | Missing | Need session ID linking across runs |
| Export to standard formats | Partial | SQLite only; need CSV/Parquet export |
| Reproducibility | Missing | Needs `SessionPlan` with `random_seed` |
| Ethics statement | Missing | Need `deon` checklist integration |

---

## 19. User-Facing Options Reference

### 19.1 Session Configuration (What Users Set)

| Option | Type | Default | Edge Cases |
|---|---|---|---|
| Job titles to search | `list[str]` | Required | Max 10; empty = nothing runs |
| Preferred locations | `list[str]` | `["Remote"]` | "Remote" bypasses geographic filter |
| Workplace type | `str` | `"remote"` | onsite/hybrid/remote |
| Blocked companies | `list[str]` | `[]` | Case-insensitive partial match |
| Blocked vocabulary | `list[str]` | `[]` | Applied to title + description |
| Max applications/session | `int` | `50` | Hard cap, cannot exceed admin policy |
| Max applications/company | `int` | `3` | Prevents over-applying to one company |
| Provider selection | `list[str]` | All active | Must have ≥1 provider or session fails |
| Linear mode | `bool` | `false` | LinkedIn always forces linear mode |
| Search date range | `str\|null` | `null` | `day`/`week`/`month` |
| Enable company page mining | `bool` | `false` | Can significantly extend runtime |
| Enable cover letters | `bool` | `false` | Requires LLM tier ≥ local_llm |
| Enable research collection | `bool` | `false` | Requires explicit consent |
| Human in the loop | `bool` | `true` | If false, CAPTCHA → skip (never manual) |
| CAPTCHA policy | `str` | `"skip"` | Options: skip/retry/manual |

### 19.2 "List Mode" (Discovery Only)

When `applications.max_applications_per_session: 0` or when launched with `--list-only`:
AA runs Discovery + Vetting but never applies. The output is a list of job links
that match the user's criteria, saved to a file. This is the "research for users"
feature mentioned in the issue list.

### 19.3 Profile Data Fields

The user profile follows `jsonresume` schema extended with AA-specific fields:
```
Personal: name, email, phone, location, website, summary paragraph
Work: list of positions (company, title, dates, description)
Education: list of degrees
Skills: list of skill keywords
Legal: work_authorization, requires_sponsorship, citizenships
Preferences: job_titles, locations, salary_range, workplace_type
Application: max_per_session, max_per_company, blocked_companies, blocked_vocabulary
Answers: stored HITL answers for future reuse
```

All fields are defined in `domain/models/profile.py`. The GUI/CLI renders these
dynamically — no field names are hardcoded in the UI layer.

---

## 20. Integration Guide

### 20.1 Adding a New Discovery Provider

1. Create `adapters/secondary/discovery/providers/new_provider.py`
2. Implement `DiscoveryProviderPort`:
   ```python
   class NewProvider(DiscoveryProviderPort):
       @property
       def name(self) -> str: return "newprovider"
       @property
       def requires_live_browser(self) -> bool: return True
       def run(self, override_criteria=None) -> list[Job]: ...
   ```
3. Register in `composition_root.py` providers list
4. Add to `runtime_defaults.yaml` discovery.providers list

### 20.2 Adding a New Browser Framework

1. Create `adapters/secondary/browser/new_framework_adapter.py`
2. Implement ALL methods of `BrowserInterface`
3. Create `infrastructure/providers/new_framework_provider.py`
4. Register in `DriverRegistry`
5. Add to `CANDIDATE_PRIORITY` in `candidates.py`

### 20.3 Adding a New ATS Platform

See Section 15.4.

### 20.4 Adding a New Reasoning Engine

1. Create `adapters/secondary/reasoning/new_llm_adapter.py`
2. Implement `ReasoningPort` and/or `TextGenerationPort`
3. Make the import lazy (wrapped in `try/except ImportError`)
4. Register in `composition_root.py` with graceful fallback to `RuleBasedAdapter`
5. Add configuration key to `runtime_defaults.yaml`

### 20.5 Adding a New Config Value

See Section 14.3.

---

## 21. Issue Triage and Priority Register

### P0 — Blocks Core Operation (Fix Before Testing)

| ID | Description | File | Fix |
|---|---|---|---|
| P0-1 | `ResilientDriver` doesn't inherit `BrowserInterface` | `resilient_driver.py` | Add inheritance, implement all methods |
| P0-2 | `max_concurrent_sources` ignores YAML, defaults to 4 | `discovery_workflow.py` + `composition_root.py` | Read from `_cfg()`, pass in constructor |
| P0-3 | Hungarian cost matrix padded with `0.0` not `1e9` | `dom_segmentation.py` | Change padding to `_DUMMY_COST = 1e9` |
| P0-4 | `CheckpointManager.load()` not implemented | `checkpoint_manager.py` | Implement load + state recovery |
| P0-5 | `DISCOVERING → IDLE` missing from state machine | `state_machine.py` | Add transition |
| P0-6 | `find_by_tags` typo → `find_by_tag` | `dom_segmentation.py` | Fix typo |
| P0-7 | `DOMNode` not hashable (mutable dict/list fields) | `math_dom.py` | Make frozen + use tuples |
| P0-8 | Scroll offset missing in DOM geometry extraction | `math_dom_adapter.py` | Add `window.scrollX/scrollY` |
| P0-9 | CAPTCHA false positives from `js_variables` | `detection_config.json` | Empty `js_variables` array |
| P0-10 | `ParsedJobDescription` constructed with wrong fields | `mathematical_web_analyzer.py` | Fix field names |
| P0-11 | `VettingEngine` analyzes wrong page (no navigation) | `vetting_use_case.py` | Navigate to `job.url` first |
| P0-12 | `_fetch_job_description` reads non-existent field | `vetting_workflow.py` | Use `execute_script("return document.body.innerText")` |
| P0-13 | Tab switch after clicking Apply not implemented | `applications_workflow.py` | Detect new tab, switch to it |
| P0-14 | `HumanSearchNavigation` search selectors too narrow | `navigators.py` | Expand selector list |

### P1 — Degrades Reliability (Fix Before Alpha)

| ID | Description | File | Fix |
|---|---|---|---|
| P1-1 | BrowserHealthMonitor no ceiling, loops forever | `browser_monitor.py` | Add `max_failures` + `_stop_event` |
| P1-2 | SpaCy loaded 3 times (~2GB RAM waste) | `composition_root.py`, `select.py`, `rule_based_adapter.py` | Inject shared instance |
| P1-3 | Playwright downloads 3× (one per candidate) | `playwright_provider.py` | Idempotency check before download |
| P1-4 | Orchestrator 10-second shutdown hang | `browser_monitor.py` | Use `threading.Event` for stop signal |
| P1-5 | `SessionController` in wrong layer | `infrastructure/session_controller.py` | Move to `application/services/` |
| P1-6 | `research_collector.py` imports from infrastructure | `research_collector.py` | Remove, inject via port |
| P1-7 | `NetworkAuditor` requires `throttler` (not optional) | `network_auditor.py` | Make `throttler` optional |
| P1-8 | `MathDiscoveryProvider` architectural violation | `composition_root.py`, `discovery_workflow.py` | Remove from providers, create `PageUnderstandingPort` |
| P1-9 | `PageClassifier` using dummy objects as band-aid | `serp_strategy.py` | Proper DI injection |
| P1-10 | `PaginationStrategy` over-constrains `InfiniteScrollStrategy` | `serp_strategy.py` | Make `interactor` optional |
| P1-11 | `_handle_detection` raises RuntimeError instead of returning False | `manager.py` | Return False, never raise from validator chain |
| P1-12 | `Pydantic Config` vs `model_config` incorrect usage | `job.py` | Replace `class Config` with `model_config = ConfigDict(...)` |
| P1-13 | `_is_likely_card()` checks CSS class names | `dom_segmentation.py` | Use structural hash + geometry + `<a href>` |
| P1-14 | `_is_descendant()` rebuilds parent map on every call | `dom_segmentation.py` | Use cached `self._parent_map` |
| P1-15 | Audit label "Google" showing Indeed URL | `discovery_math_auditor.py` | Capture URL from query object, not from browser |
| P1-16 | `about:blank` log noise | `resilient_driver.py` | Suppress log for about:blank navigations |

### P2 — Feature Gaps (Implement for Beta)

| ID | Description | Notes |
|---|---|---|
| P2-1 | `SessionPlan` immutable config object | See Section 6.5 |
| P2-2 | `BrowserLeaseManager` for structural concurrency enforcement | See Section 6.6 |
| P2-3 | `PageUnderstandingPort` + correct math integration | See Section 9 |
| P2-4 | PRA Loop formalized as typed Protocol | See Section 12 |
| P2-5 | `EngineRegistry` for search engine YAML configs | See Section 7.2 (EngineConfig) |
| P2-6 | `HumanTypedNavigation` strategy | See Issue #70 |
| P2-7 | ATS site: query generation utility | See Issue #69 |
| P2-8 | `ExecutionMap` for session observability | See Section 13.2 |
| P2-9 | Analysis log file (`analysis_log_NNNN.txt`) | See Issue #0 |
| P2-10 | Database wipe / corruption recovery utility | See Issue #101 |
| P2-11 | `run.bat wipe` clears pytest cache + DB | See Issue #25 |
| P2-12 | CAPTCHA solver API support | See Issue #37 |
| P2-13 | Cover letter LLM generation | See Issue #96 |
| P2-14 | "List mode" (discovery + vetting without applying) | See Issue #2 |
| P2-15 | Vimium-style keyboard navigation option | See Issue list |
| P2-16 | Visual telemetry (draw math engine overlay on page) | See Issue #92 |

### P3 — Research and Future Features

| ID | Description | Notes |
|---|---|---|
| P3-1 | `pluggy` plugin system | See Section 1 peer discussion |
| P3-2 | CDP DOM snapshot adapter (stealth extraction) | See Issue #91 |
| P3-3 | Telemetry-based browser cascade learning | See Issue #4 |
| P3-4 | `sentence-transformers` semantic matching | See Issue #75 |
| P3-5 | Clingo ASP form reasoning integration | See Issue #60 |
| P3-6 | `jsonresume` schema adoption for UserProfile | See peer discussion |
| P3-7 | Research module IRB consent language | See Section 18.4 |
| P3-8 | `deon` ethics checklist integration | See tool list |
| P3-9 | Property-based testing with Hypothesis | See Issue #58 |
| P3-10 | DuckDuckGo provider | See Issue #69 |
| P3-11 | Mobile-first GUI redesign | See Issue list |
| P3-12 | `Pyodide` WebAssembly distribution | See tool list |
| P3-13 | LinkedIn Easy Apply custom strategy | Already partial in `linkedin_easy_apply.py` |

---

## 22. Future Roadmap

### 22.1 The Path to True Autonomy

True autonomy for never-before-seen webpages requires:

1. **Formalized PRA Loop** (P2-4) — the foundation
2. **PageUnderstandingPort** (P2-3) — pluggable perception
3. **Session Supervisor** (P2-1, P2-2, P2-8) — control and observability
4. **Feedback Loop** — learning from operation

The feedback loop (not yet in the codebase) is the most important missing piece
for long-term reliability. The path:

```
ApplicationsWorkflow records: which form fields were filled successfully?
    ↓
Outcome stored in ResearchCollector with field types + strategies used
    ↓
Weekly aggregation: "Strategy X succeeded 94% of time on Greenhouse forms"
    ↓
StrategySelector reads aggregated stats
    ↓
Next session: Greenhouse forms prefer Strategy X over Strategy Y
```

This is what makes AA learn over time without requiring any code changes.

### 22.2 Tool Integration Priority

From the provided tool list, recommended integration order:

**Immediate value (align with existing architecture):**
- `pluggy` — for the plugin system (P3-1)
- `psutil` — for low-resource detection (already partially used)
- `Parsel` — as alternative to BS4 for XPath/CSS (drop-in upgrade to static adapter)
- `HTTPX` — for async-capable HTTP client (upgrade to `UrllibHTTPClient`)
- `Camoufox` / `Zendriver` — study their stealth approach, adopt techniques

**Medium-term (meaningful capability addition):**
- `sentence-transformers` — for semantic vetting (P3-4)
- `BrowserForge` — fingerprint generation, replace current fingerprint files
- `Pa11y` / `Axe-core` — accessibility validation in research module
- `jsonresume` — profile schema standardization (P3-6)
- `deon` — ethics checklist (P3-8)

**Do not integrate:**
- DRAKVUF, T-Pot, TANNER, SNARE, Conpot — honeypot defense infrastructure, wrong purpose
- CuPy, LAPACK, SageMath — GPU/scientific computing, violates worst-case constraint
- MikroORM — JavaScript ORM, wrong language
- Kivy, BeeWare — mobile GUI, wrong target platform
- Apache Nutch, Heritrix3 — Java internet-scale crawlers, architectural mismatch
- Puppeteer — JavaScript, wrong language (Playwright covers the same niche)
- aiohttp — asyncio-based, violates AA's no-asyncio constraint

### 22.3 Extensibility Checklist

When adding any new capability, verify:

- [ ] New port defined in `domain/ports/` (if it crosses the domain boundary)
- [ ] New adapter implements the port completely
- [ ] Composition root wires the new adapter with graceful fallback
- [ ] New config values added to `runtime_defaults.yaml` with comments
- [ ] Worst-case user: does it degrade gracefully if the feature is unavailable?
- [ ] No circular imports (run violation check from Section 3.3)
- [ ] Single SpaCy instance maintained (no new TextMatcher instantiation)
- [ ] Thread safety: if the new component touches shared state, it uses locks
- [ ] This Bible updated with the new component in the appropriate section

---

*End of AA Architecture Bible v1.0*
*Next review: when any P0 or P1 issue is resolved, or before any major feature addition*

---

## 23. Pydantic — Standardization Reference

### 23.1 The Correct Mental Model

The term for what Pydantic provides in this codebase is "schema-validated domain models"
or more formally in Domain-Driven Design: "Value Objects with enforced invariants."
Pydantic is the right choice. The problem is inconsistent use.

### 23.2 Where Pydantic MUST Be Used

Use `pydantic.BaseModel` (v2) for every class that satisfies ANY of these:
- Crosses a layer boundary (serialized to/from JSON, SQLite, or disk)
- Needs field validation on construction (wrong type → immediate error, not silent bug)
- Represents data provided by users or external systems
- Will be diffed, compared, or logged as structured data

**Complete list of models that must use Pydantic:**

| Model | Current State | Must Change? |
|---|---|---|
| `Job` | Pydantic v1 `class Config` | Yes — migrate to v2 `model_config` |
| `UserProfile` | Pydantic v2 | Correct |
| `ParsedJobDescription` | Pydantic (frozen) | Correct |
| `WorkUnit` | Likely plain dataclass | Yes — needs validation |
| `RuntimeProfile` | Unknown | Yes — resource numbers must validate |
| `ResearchSignal` | Frozen dataclass | Yes — add Pydantic for serialization |
| `WebpageStructure` | Dataclass | Yes — add Pydantic |
| `UIModel` | Dataclass | Yes — add Pydantic |
| `SessionPlan` | Does not exist yet | Create as Pydantic frozen model |
| `BehaviorParameters` | Does not exist yet | Create as Pydantic frozen model |
| `EvasionConfig` | Config object | Yes — add Pydantic validation |
| `AppSettings` | Thin, unvalidated | Yes — migrate to full Pydantic model |

### 23.3 Where Pydantic Must NOT Be Used

- `Protocol` port interfaces — these are structural contracts, not data containers
- Abstract service classes with behavior (methods with logic)
- Pure algorithm classes (`Hungarian`, `ConvexHull`, etc.)
- Adapter classes that wrap external frameworks

### 23.4 Pydantic v1 → v2 Migration Rule

The `Job` model and possibly others have this bug:
```python
# WRONG (v1 inside v2):
class Job(BaseModel):
    class Config:
        frozen = False

# CORRECT (v2):
from pydantic import BaseModel, ConfigDict
class Job(BaseModel):
    model_config = ConfigDict(frozen=False)
```

The `class Config` inner class is a Pydantic v1 pattern. `model_config = ConfigDict(...)` 
is a v2 class-level attribute. They cannot be mixed. Any model with a `class Config` 
nested inside it is using v1 syntax inside a v2 installation — it silently ignores the config.

### 23.5 File Organization

Models with related data live in the same module file — not one class per file.
The pattern:
```
domain/models/
  job.py          — Job, JobStatus, JobSource, ApplicationOutcome
  profile.py      — UserProfile, JobSearchPreferences, WorkAuthorization
  work_unit.py    — WorkUnit, TaskType, TaskPriority
  timing.py       — BehaviorParameters, TimingProfile (NEW)
  session.py      — SessionPlan, ExecutionContext, WorkerStatus (NEW)
  math_dom.py     — DOMNode, Geometry, TreeStructure (NEEDS IMMUTABILITY FIX)
  research.py     — ResearchSignal, MarketFaultSignal, SessionReport
```

---

## 24. Hardcoded Values — Centralization Plan

### 24.1 The Four Categories

**Category 1: Behavioral/timing parameters** — belong in `BehaviorParameters`
All timing is currently scattered as magic numbers. Examples:
- `time.sleep(random.uniform(2.0, 5.0))` in provider loops
- `inter_action_delay_ms = 1200` inline in form-filling code
- `wpm=60` as a default argument in `human_type()`
- `secrets.SystemRandom()` ranges (50-200px for mouse offsets)

All of these must read from `BehaviorParameters`, itself built from `_effective_config`.

**Category 2: Detection/scoring thresholds** — belong in `runtime_defaults.yaml` only
- CAPTCHA confidence weights (20, 30, 40) in `DefaultDetectionStrategy`
- Vetting filter weights in `VettingWorkflow`
- `hard_skills_min_overlap: 0.5` threshold
- `role_alignment_threshold: 0.6` threshold

These are already in `runtime_defaults.yaml` for most cases. The bug is that some
are also hardcoded as Python defaults that shadow the YAML values.

**Category 3: Fixed external identifiers** — belong in `domain/constants.py`
Strings that are dictated by external libraries or browser internals, not configurable:
```python
# domain/constants.py
BROWSER_CLOSED_ERRORS = frozenset({
    "target window already closed",
    "invalid session id",
    "no such window",
    "disconnected: not connected to devtools",
})
ABOUT_BLANK = "about:blank"
DOCUMENT_READY_STATES = frozenset({"complete", "interactive"})
```

**Category 4: Platform/site-specific selectors and identifiers** — belong in YAML registries
CSS selectors, base URLs, pagination parameters for each search engine belong in
`resources/engines/google.yaml`, `bing.yaml`, `duckduckgo.yaml`.
ATS platform identifiers and URL patterns belong in `resources/ats/*.yaml`.

### 24.2 BehaviorParameters Model

```python
# domain/models/timing.py
from pydantic import BaseModel, ConfigDict, Field

class TimingProfile(BaseModel):
    model_config = ConfigDict(frozen=True)
    
    # Human-like interaction timing
    inter_action_delay_ms: int = 1200
    macro_pause_min_seconds: float = 0.8
    macro_pause_max_seconds: float = 2.5
    micro_delay_peak_ms: int = 50
    typing_wpm: int = 60
    typing_jitter_fraction: float = 0.20  # ±20% per keystroke
    thinking_pause_probability: float = 1/15  # 1 in 15 chars
    thinking_pause_min: float = 0.3
    thinking_pause_max: float = 0.8
    
    # Mouse behavior
    mouse_move_steps: int = 5       # moves per fidget
    mouse_offset_min_px: int = 50   # min single-move distance
    mouse_offset_max_px: int = 200  # max single-move distance
    mouse_step_delay_min: float = 0.2
    mouse_step_delay_max: float = 0.8
    
    # Navigation
    between_provider_pause_min: float = 2.0
    between_provider_pause_max: float = 5.0
    idle_action_max_interval: float = 8.0
    page_load_timeout: int = 30
    navigation_retries: int = 3

class BehaviorParameters(BaseModel):
    model_config = ConfigDict(frozen=True)
    
    timing: TimingProfile = Field(default_factory=TimingProfile)
    random_seed: int | None = None  # None = non-deterministic production mode
    
    @classmethod
    def from_config(cls, config: dict) -> "BehaviorParameters":
        browser_cfg = config.get("browser", {})
        discovery_cfg = config.get("discovery", {})
        apps_cfg = config.get("applications", {})
        return cls(
            timing=TimingProfile(
                inter_action_delay_ms=apps_cfg.get("inter_action_delay_ms", 1200),
                # ... all fields from config
            ),
            random_seed=config.get("session", {}).get("random_seed"),
        )
```

### 24.3 Deterministic Random Usage

When `random_seed` is set, ALL random calls in AA use a seeded `random.Random` instance:
```python
# In composition_root.py:
if behavior_params.random_seed is not None:
    _rng = random.Random(behavior_params.random_seed)
else:
    _rng = random.Random()  # non-seeded = production mode

# Injected into: BehaviorSimulator, HumanLikeAdapter, BrowserCascade, SessionManager
```

No component uses `random.uniform()`, `random.choice()`, or `secrets.SystemRandom()` 
directly. All use the injected `_rng` instance. This makes sessions fully reproducible
when a seed is provided — identical execution traces, identical discovery ordering,
identical timing jitter.

---

## 25. Academic Publishability — Complete Requirements

### 25.1 The Formal Framework: FAIR4RS

**FAIR4RS** (FAIR for Research Software) is the community-endorsed standard as of 2022.
The six properties AA must demonstrate:

| Property | What It Requires for AA | Status |
|---|---|---|
| **Findable** | DOI via Zenodo, `CITATION.cff`, searchable metadata | Missing |
| **Accessible** | Open source license, public URL, downloadable without registration | Partial (Codeberg) |
| **Interoperable** | Standard formats for data output, documented APIs | Partial |
| **Reusable** | Open license, sufficient documentation, container support | Partial |
| **Reproducible** | Seeded randomness, versioned schemas, deterministic output | Missing |
| **Sustained** | Changelog, versioned releases, contribution guidelines | Missing |

### 25.2 ACM Artifact Badges (Required for Conference Submission)

**Artifacts Available** (minimum):
- [ ] Public Zenodo DOI (Codeberg → Zenodo integration, one-click)
- [ ] `LICENSE` file (already have, verify it's OSI-approved)
- [ ] `CITATION.cff` file (structured citation metadata)
- [ ] Stable URL that won't change

**Artifacts Functional** (for acceptance):
- [ ] `INSTALL.md` — complete, tested step-by-step from a clean environment
- [ ] Smoke test that runs without a real browser (driver=None path)
- [ ] Mock ATS benchmark suite (5 local HTML files + expected outputs)
- [ ] Verified on: Windows 10, Ubuntu 22.04, macOS (Intel)
- [ ] All documented features work as described in the Bible

**Artifacts Reusable** (for top-tier venue):
- [ ] `pluggy`-based plugin system so researchers can add ATS adapters without core changes
- [ ] Docker image with all dependencies pinned
- [ ] `--seed N` flag for deterministic execution
- [ ] `--profile` flag writing structured JSON performance output
- [ ] `CONTRIBUTING.md` with architecture guide

### 25.3 What the Scientific Community Wants to Run

When a researcher cites AA in a paper, the AEC reviewer will try to:

1. **Clone and install from scratch** — without AA's context. `INSTALL.md` must work
   for a Linux box with Python 3.11, nothing else.

2. **Run a smoke test** — confirm AA starts and terminates cleanly without errors.
   Currently: `python -m pytest tests/ -k smoke` must pass in <60 seconds.

3. **Run the mock ATS benchmark** — feed AA five known HTML forms, check that it
   fills ≥80% of fields correctly. This is the validity evidence for the math engine.
   Currently: does not exist. Must be created.

4. **Run with a fixed seed** — execute the same session twice with `--seed 42`,
   verify the execution traces are identical. Currently: impossible.

5. **Inspect performance output** — run with `--profile`, verify RAM stays <2GB
   on the library-computer config. Currently: no profiling output exists.

6. **Add a new ATS plugin** — follow `CONTRIBUTING.md` to create a test ATS adapter
   and verify it works without touching core code. Currently: requires manual wiring.

### 25.4 Scientific Test Suite (What Must Exist)

**Tier 1 — Unit tests (already partially exist, gaps to fill):**
- Property-based tests for Hungarian algorithm (Hypothesis): verify optimal assignment,
  verify no field left unassigned when solvable, verify handles n=0 and n=1 edge cases
- Property-based tests for ConvexHull: verify output is always convex
- Property-based tests for structural hashing: identical subtrees → identical hashes
- Property-based tests for DeduplicationManager: no job URL appears twice in output

**Tier 2 — Integration tests (mostly missing):**
- Mock ATS benchmark: 5 HTML forms, measure fill accuracy
- Discovery pipeline with static HTML fixtures (no live browser required)
- Vetting pipeline: synthetic Job objects through all filter combinations
- CAPTCHA detection: inject `window.grecaptcha` → verify NOT flagged (fix test)
- State machine: verify all valid transitions are reachable, all invalid are rejected

**Tier 3 — Reproducibility tests (entirely missing):**
- Seeded session test: `--seed 42` twice → identical `analysis_log` outputs
- Memory ceiling test: `tracemalloc` peak must be <1800MB on worst-case config
- Performance regression test: `--profile` output compared to baseline on merge

**Tier 4 — Research validation (future, required before paper submission):**
- Ablation: math engine on vs off, measure form fill rate on mock ATS benchmark
- Differential NLP: Tier 0 vs Tier 1 vetting decisions on 100 synthetic job descriptions
- CAPTCHA encounter simulation: inject challenges at N% of navigations, measure recovery

### 25.5 Required Files for Academic Submission

```
AA/
  CITATION.cff          ← Academic citation metadata
  LICENSE               ← OSI-approved open source license
  INSTALL.md            ← Step-by-step from clean environment
  CONTRIBUTING.md       ← Architecture + plugin guide
  CHANGELOG.md          ← Semantic versioning changelog
  docs/
    ARCHITECTURE.md     ← Points to the Bible
    DATA_MANAGEMENT.md  ← Research data collection policy
    ETHICS.md           ← deon checklist + IRB-analog consent language
    REPRODUCIBILITY.md  ← How to run deterministically
  tests/
    benchmarks/
      ats_forms/        ← 5 mock ATS HTML files
        greenhouse_simple.html
        workday_multi_step.html
        lever_single_page.html
        custom_file_upload.html
        custom_sponsorship_question.html
      run_benchmark.py  ← Runs AA against all 5, reports accuracy
    property_based/     ← Hypothesis tests for math algorithms
    smoke/              ← Quick sanity check, no browser
```

---

## 26. Sans-IO Principle Applied to AA

The sans-IO design principle (as documented at sans-io.readthedocs.io) states:
write the core logic completely separated from I/O. The logic operates on data
structures; I/O is handled by the caller. This makes the logic testable in
complete isolation and composable with any I/O backend.

AA's hexagonal architecture already implements this principle for the domain layer.
But it should be applied more consistently in two specific areas:

**PRA Loop logic should be sans-IO:**
The perceive → read → act algorithm should operate on data structures
(a `PageContext` dict of raw HTML/DOM data), not on a live browser.
The browser produces the `PageContext`; the algorithm processes it.
This means the entire PRA decision tree can be tested without Selenium.

**Provider SERP parsing should be sans-IO:**
`GoogleProvider._extract_jobs_from_serp()` should accept raw HTML string,
not a live driver. The driver fetches the HTML; the parser processes it.
Test: pass a saved HTML fixture, verify extraction output.

This is the right architectural path for the mock ATS benchmark: the benchmark
passes raw HTML to the parsing logic directly, never needing a browser.

---

## 27. Session Supervisor — Final Validated Design

After full architectural review, the Session Supervisor is confirmed correct.
The five final components (four original + one addition):

### 27.1 Component 1: BrowserLeaseManager
**Priority: P0 (implement in Phase 1)**
Resolves the concurrency race condition structurally.
See Section 6.6 for implementation.

### 27.2 Component 2: SessionPlan
**Priority: P1 (implement in Phase 5)**
Immutable frozen Pydantic model. Contains:
- All session configuration resolved at startup
- `random_seed: int | None` for deterministic/research mode
- Serializable to disk (complete experiment parameters)
See Section 6.5 for current design + add `random_seed` field.

### 27.3 Component 3: BehaviorParameters
**Priority: P1 (implement in Phase 4, feeds into SessionPlan)**
All timing and behavioral parameters centralized.
See Section 24.2 for implementation.
This is the fifth component not in the original four — it belongs here because
it is the behavioral contract that the SessionSupervisor enforces.

### 27.4 Component 4: ExecutionMap
**Priority: P2 (implement in Phase 5)**
Thread-safe status map for all active workers.
"git status for your session."
See Section 13.2 for current design — no changes needed.

### 27.5 Component 5: ProviderWatchdog
**Priority: P2 (implement in Phase 5)**
Daemon thread that polls `ExecutionMap` every 10 seconds.
If any provider thread hasn't sent a heartbeat in >configured timeout:
1. Attempt graceful cancellation (set thread stop event if one exists)
2. Re-enqueue the work unit back to the task queue as a new DISCOVER task
3. Publish `PROVIDER_TIMED_OUT` event with provider name and last action
4. Increment the task's retry counter — if it exceeds `max_retries`, discard

**Clarification on "watchdog over work units" from original description:**
Work units in SQLite cannot go silent — they are either pending or claimed.
What goes silent is a provider THREAD. The watchdog monitors thread heartbeats
via ExecutionMap, not the queue directly. This is more accurate than the
original description.

---

## 28. Integration Order — The Final Plan

### Phase 1: Browser and Concurrency Foundation
**Goal: Complete a discovery run without crashing**
**Files touched: resilient_driver.py, discovery_workflow.py, composition_root.py, 
detection_config.json, state_machine.py**

1. `ResilientDriver` inherits `BrowserInterface`, implements all methods
2. `max_concurrent_sources` read from `_cfg()` in `DiscoveryWorkflow`, YAML value respected
3. `js_variables` array emptied in `detection_config.json`
4. `DISCOVERING → IDLE` added to state machine valid transitions
5. `is_alive()` replaced with `execute_script("return 1")` in Selenium path
6. `BrowserLeaseManager` (40 lines) added to infrastructure, wired in composition root
7. `about:blank` log suppressed in ResilientDriver

**Proof Phase 1 is done:** AA completes a discovery run, logs jobs found, 
transitions to VETTING without crashing.

### Phase 2: Math Subsystem Correctness
**Goal: Math engine returns non-empty analysis on real pages**
**Files touched: math_dom.py, math_dom_adapter.py, dom_segmentation.py, 
label_input_pairing.py**

1. `DOMNode` immutable: attributes → `tuple[tuple[str,str],...]`, children → `tuple`
2. Scroll offset added to JS geometry extraction
3. Hungarian cost matrix padding changed from `0.0` to `1e9`
4. `find_by_tags` typo fixed to `find_by_tag`
5. `_is_likely_card()` rewritten to use structural pattern matching + geometry

**Proof Phase 2 is done:** Math analyzer returns non-empty `WebpageStructure` 
on a live Greenhouse application page.

### Phase 3: Vetting and End-to-End Correctness
**Goal: Discovery → Vetting → Application completes on a real job**
**Files touched: vetting_workflow.py, mathematical_web_analyzer.py, 
vetting_use_case.py, checkpoint_manager.py**

1. `_fetch_job_description` uses `execute_script("return document.body.innerText")`
2. `ParsedJobDescription` constructed with correct field names
3. `VettingEngine.run()` navigates to `job.url` before analysis
4. `CheckpointManager.load()` implemented
5. Tab switch detection added to ApplicationsWorkflow

**Proof Phase 3 is done:** End-to-end log shows DISCOVERING → VETTING → APPLYING
with at least one job reaching the form stage.

### Phase 4: Architectural Corrections
**Goal: Eliminate all layer violations, prepare for features**
**Files touched: Many, structural only**

1. `SessionController` moved to `application/services/`
2. `MathDiscoveryProvider` removed; `PageUnderstandingPort` + adapters created
3. SpaCy single-instance injection (remove from `SelectInputHandler` + `FormSolver`)
4. `BrowserHealthMonitor` threading.Event fix
5. Pydantic v2 migration across all models
6. `research_collector.py` import violation removed
7. `NetworkAuditor.throttler` made optional
8. `_is_descendant()` uses cached parent map
9. All `class Config` → `model_config = ConfigDict(...)` in every model

**Proof Phase 4 is done:** Violation check from Section 3.3 returns zero results.

### Phase 5: Session Supervisor
**Goal: Safe, observable, reproducible sessions**
**Files touched: composition_root.py, orchestrator.py, context.py, new files**

1. `BehaviorParameters` + `TimingProfile` Pydantic models created, wired in composition root
2. `SessionPlan` Pydantic model created with `random_seed` field
3. Deterministic `random.Random(seed)` injection replacing all direct `random` calls
4. `ExecutionMap` added to `ExecutionContext`
5. `ProviderWatchdog` daemon thread created and started in orchestrator
6. `analysis_log_NNNN.txt` output file with incrementing index (Issue #0)

**Proof Phase 5 is done:** `--seed 42` run produces identical `analysis_log` twice.

### Phase 6: Research Grade
**Goal: ACM Artifacts Functional badge + Reproducibility badge**
**Files: new test files, new docs, Zenodo integration**

1. Mock ATS benchmark suite: 5 HTML files + `run_benchmark.py`
2. Hypothesis property-based tests for Hungarian, ConvexHull, StructuralHash, Dedup
3. `--profile` flag + `tracemalloc` JSON output
4. `INSTALL.md`, `CITATION.cff`, `CHANGELOG.md`, `CONTRIBUTING.md`
5. `docs/ETHICS.md` + deon checklist
6. Zenodo release workflow on Codeberg
7. Memory ceiling test (must stay <1800MB on worst-case config)

**Proof Phase 6 is done:** Full AEC review checklist from Section 25.2 passes.

### Phase 7: Feature Completions
**Goal: User-facing capabilities beyond core**
No dependencies on previous phases except Phase 1 (browser must work).

1. `HumanTypedNavigation` strategy
2. Engine registry YAMLs (google.yaml, bing.yaml, duckduckgo.yaml)
3. ATS site-search query builder + `ATSSerpStrategy`
4. Database wipe/corruption recovery in `run.bat wipe`
5. `pluggy` plugin registration for ATS adapters
6. CAPTCHA solver API hook in `ResolutionPort`
7. Cover letter LLM generation (behind `enable_cover_letter_generation` flag)
8. DuckDuckGo provider
9. "List mode" (discovery + vetting, no applying)

## 29. Configuration & Pydantic Standardization

### 29.1 The Death of Global Settings
The pattern `from auto_apply.domain.config import settings` is forbidden. 
Global state hides dependencies, makes unit testing difficult, and breaks when multiple sessions run concurrently.
- **Values must be injected:** If `ThrottlingFilter` needs the default cooldown delay, it must be passed `default_cooldown: int` in its constructor.
- **Loading is Infrastructure:** Reading from `.env`, `os.environ`, or `.json` files is strictly the job of `CapabilitiesRegistry` and `ProfileRepository` in the Infrastructure/Secondary Adapter layers.

### 29.2 Pydantic Usage Rules
Pydantic v2 `BaseModel` is mandatory for all Domain data structures that cross layer boundaries.
1. **Validation on Assignment:** All models must use `model_config = ConfigDict(validate_assignment=True, frozen=True)`. Mutating a domain model mid-flight is forbidden; create a new instance using `model_copy(update={...})`.
2. **Type Hinting is Law:** Every field must have a strict type hint. Use `pydantic.types` (e.g., `EmailStr`, `HttpUrl`, `PositiveInt`) wherever applicable.
3. **No I/O in Validators:** A `@field_validator` must never check if a file exists on disk (`Path.exists()`). That is an I/O operation. Validators only ensure the string is a structurally valid path. The actual file check happens in the Interaction Adapter when it tries to upload the file.

---

## 30. System Resilience & Reliability Patterns

AA must never crash due to external factors (network drops, website changes, blocked DOMs). The following patterns are mandatory:

### 30.1 Circuit Breakers
Any component communicating with the outside world must implement a circuit breaker.
- **Browser Limits:** The `BrowserHealthMonitor` trips the circuit after `max_failures` (P1-1).
- **Infinite Scroll:** `InfiniteScrollStrategy` must have a hard cap (e.g., `MAX_PAGES = 10`) to prevent getting stuck in infinite dynamic loading loops.

### 30.2 Exponential Backoff & Retries
Network calls and element lookups must never fail on the first attempt if the error is transient.
- Use the `@retry(attempts=3, backoff=1.5)` decorator (from `domain/retry.py`) for all HTTP client requests and LLM API calls.
- StaleElementReferenceExceptions in Selenium/Playwright must automatically trigger a re-lookup of the element up to 3 times before failing the `PlannedAction`.

### 30.3 Idempotency
Executing the same action twice must yield the same result without corrupting state.
- **Database Inserts:** All job insertions must use `INSERT OR IGNORE` or `INSERT OR REPLACE` based on a SHA-256 hash of the normalized URL.
- **Queue Tasks:** If the Orchestrator crashes and re-processes an `APPLY` WorkUnit that was partially completed, the Application Engine must gracefully detect `ALREADY_APPLIED` via perception and mark it complete without throwing an error.

### 30.4 Disk Space Pre-Checks (USB Safety)
Because AA often runs on USB drives with limited capacity, the system must protect itself from disk-full crashes.
- Before writing a checkpoint, logging a heavy payload, or downloading an LLM/SpaCy model, `HardwareInspector` must verify `disk_free_mb > 50`. 
- If disk space is critical, AA must disable logging and block model downloads, degrading gracefully.

---

## 31. The "Agnostic" Trinity

AA is designed to outlive the tools it is currently built upon. We enforce three strict agnosticisms:

### 31.1 Platform-Agnostic (The USB Rule)
AA must run identically from `C:\Users\John\Desktop\` as it does from `E:\` (a USB drive).
- **Rule:** Never use absolute paths for application data. 
- **Rule:** Never write to `%APPDATA%`, `~/.local/share`, or the Windows Registry when `sys.frozen == True`. All data paths MUST be routed relative to `sys.executable`.

### 31.2 Framework-Agnostic (Browser Automation)
AA is immune to the Selenium vs. Playwright wars.
- **Rule:** The `ApplicationEngine` and `DiscoveryEngine` must never know what tool is driving the browser. They only speak to `BrowserInterface`. 
- **Rule:** Any new framework (e.g., Camoufox, Stagehand) requires EXACTLY two files: an Adapter (implementing `BrowserInterface`) and a Provider (implementing `DriverProvider`). Zero changes to core logic.

### 31.3 Provider-Agnostic (AI/LLM)
AA is immune to AI vendor lock-in.
- **Rule:** Workflows must only depend on `TextGenerationPort`. 
- **Rule:** `GPT4AllAdapter` is just one implementation. If a user provides an API key, we use an `OpenAIAdapter`. The interface (`generate(prompt) -> str`) remains identical.

---

## 32. Data Safety & Code Quality Standards

### 32.1 Zero PII Leakage (System Events)
The Research Module must operate with "undoubting confidence" regarding privacy.
- **Rule:** Research data is strictly "System Events". It is cryptographically impossible to reverse-engineer the user.
- **Rule:** PII stripping is done via `DataAnonymizer` using a per-installation cryptographic salt. `Alice` applied to `Google` becomes `Hash(Salt + "Alice")` applied to `Hash(Salt + "Google")`. 

### 32.2 Database Migration System
As AA evolves, the SQLite schema will change. Dropping the database and losing user application history is unacceptable.
- **Rule:** The `DatabaseManager` must use SQLite `user_version` PRAGMA.
- **Rule:** On startup, the manager checks the version. If `current_version < target_version`, it runs sequential, idempotent SQL migration scripts (e.g., `ALTER TABLE job_history ADD COLUMN ...`) before allowing the orchestrator to start.

### 32.3 Pythonic Code Enforcement (SOLID & DRY)
Code that is hard to read is hard to maintain. All PRs must adhere to:
- **Type Hinting:** 100% type hint coverage for function signatures.
- **Ruff/Black:** CI pipelines will reject unformatted code.
- **Single Responsibility (SRP):** If a class parses HTML *and* writes to a database, it must be split.
- **Liskov Substitution (LSP):** Any adapter must be perfectly substitutable for its port. If `BS4PerceptionAdapter` throws an error that `MathPerceptionAdapter` doesn't, LSP is violated.

---

## 33. Updates & Versioning Strategy

Self-updating code is inherently dangerous, triggers antivirus software (breaking the Library Computer constraint), and breaks binary signatures.

**The AutoApply Update Contract:**
1. **Passive Checking:** A daemon thread queries the GitHub Releases API on startup (3-second timeout, fail silent).
2. **Notification Only:** If a newer version exists, the GUI/CLI displays an update notification.
3. **Actionable Instructions:** 
   - If running from Source/Pip: "Update available. Run `pip install --upgrade auto_apply`."
   - If running from PyInstaller USB: "Update available. Please download the latest .zip from GitHub."
4. **No Code Mutations:** AA will *never* attempt to overwrite its own executable or run `git pull` on behalf of the user.


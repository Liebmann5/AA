# Core Abstractions

AutoApply can drive a browser via Selenium, Playwright, or any future
automation library — without changing a single line of business logic. It can
switch from SQLite to PostgreSQL, from `urllib` to `requests`, from a real
browser to a static HTML parser — all by swapping adapters.

This chapter explains the architectural patterns that make this possible:
**ports**, **adapters**, and **dependency injection**.

---

## The Dependency Rule

AA’s code is organised into four concentric layers. The most important rule
in the entire codebase is:

> **Source code dependencies can only point inward.**

Nothing in an inner layer may import anything from an outer layer. The
layers, from innermost to outermost, are:

```
infrastructure/       ← composition root, providers, cascade
    ↓  (depends on)
adapters/             ← browser drivers, HTTP clients, database, GUI, CLI
    ↓
application/          ← orchestrator, engines, workflows, services
    ↓
domain/               ← models, ports, filters, pure domain services
```

- **`domain/`** knows nothing about browsers, databases, or UI frameworks.
  It defines *what* the application needs via abstract interfaces called
  **Ports**.
- **`adapters/`** implements those Ports with concrete technology.
- **`application/`** orchestrates the domain using the Ports — it never
  imports an adapter directly.
- **`infrastructure/`** is the **composition root**: the single place where
  concrete adapters are instantiated and injected into the application.

If you see an import that goes the wrong way — for example, a file in
`domain/` importing from `adapters/` — that is a layering violation and
must be fixed.

---

## BrowserInterface — The Core Contract

The most important Port in AA is `BrowserInterface`. It defines *what* a
browser can do, without saying *how*.

```python
# domain/ports/browser_port.py (simplified)

class BrowserInterface(ABC):
    @abstractmethod
    def get(self, url: str) -> None: ...
    
    @abstractmethod
    def find_element(self, by: str, selector: str) -> ElementInterface | None: ...
    
    @abstractmethod
    def execute_script(self, script: str, *args) -> Any: ...
    
    @abstractmethod
    def current_url(self) -> str: ...
    
    @abstractmethod
    def page_source(self) -> str: ...
    
    # ... and many more: wait_for_element, scroll, click, cookies, etc.
```

Every component that needs a browser — the `DiscoveryEngine`, the
`ApplicationEngine`, the `VettingEngine` — receives a `BrowserInterface`.
They never know whether the real implementation is Selenium or Playwright.
They just call `browser.get(url)`, `browser.find_element(...)`, and the
adapter handles the rest.

`ElementInterface` is the companion contract for individual DOM elements:
`click()`, `send_keys()`, `get_attribute()`, `text`, etc.

### Why this matters

- **Testability:** You can inject a `MockBrowser` that returns canned
  responses. Every engine can be tested without opening a real browser.
- **Replaceability:** To support a new automation library (e.g. `nodriver`),
  you write one new adapter class. Nothing else changes.
- **Graceful degradation:** If no browser is available, the composition root
  injects a `BS4PerceptionAdapter` (which implements `PerceptionPort` via
  static HTML) instead of a full browser adapter. The engines don't know the
  difference.

---

## The Port Pattern

Every external capability that the domain needs is expressed as a **Port** —
an abstract base class or a `typing.Protocol` in `domain/ports/`.

| Port | Purpose | Example adapters |
| ---- | ------- | ---------------- |
| `BrowserInterface` | Drive a web browser | `SeleniumAdapter`, `PlaywrightAdapter` |
| `PerceptionPort` | Read and classify page state | `MathPerceptionAdapter`, `BS4PerceptionAdapter` |
| `InteractionPort` | Click, type, upload files, execute plans | `InteractionExecutor` |
| `ReasoningPort` | Devise an interaction plan from a page snapshot | `FormSolver`, `ClingoFormSolver` |
| `DiscoveryProviderPort` | Search for jobs on a specific platform | `GoogleProvider`, `BingProvider`, `IndeedProvider` |
| `JobRepositoryPort` | Persist and query job application history | `JobRepository` (SQLite) |
| `HTTPClientPort` | Fetch a URL and return its content | `UrllibHTTPClient` |
| `InterruptPolicy` | Decide whether to pause for human approval | `ProfileBasedInterruptPolicy` |
| `HealthMonitor` | Background health checks (browser, network) | `BrowserHealthMonitor`, `NetworkHealthMonitor` |

Ports live in `domain/ports/`. Their names always end with `Port` or
`Interface`. Adapters live in `adapters/` and their names describe the
concrete technology.

---

## Adapters

Adapters are the concrete implementations of ports. They are the only places
where third‑party library imports (Selenium, Playwright, SQLite, `urllib`,
BeautifulSoup, etc.) are allowed.

**Primary adapters** drive the application:
- `adapters/primary/gui/` — the Tkinter GUI
- `adapters/primary/cli/` — the terminal CLI

**Secondary adapters** are driven by the application:
- `adapters/secondary/browser/` — `SeleniumAdapter`, `PlaywrightAdapter`
- `adapters/secondary/perception/` — `MathPerceptionAdapter`, `BS4PerceptionAdapter`
- `adapters/secondary/persistence/` — `DatabaseManager`, `JobRepository`
- `adapters/secondary/discovery/` — `GoogleProvider`, `BingProvider`
- `adapters/secondary/network/` — `UrllibHTTPClient`, `NetworkHealthMonitor`

Every adapter receives its dependencies via its constructor. No adapter ever
reaches into the domain and creates objects itself.

---

## Dependency Injection — How Everything Connects

If every component only talks to ports, how does a real browser ever get
created? This is the job of the **Composition Root**.

The composition root (`infrastructure/composition_root.py`) is the only
file in the codebase that may import from both `adapters/` and `domain/`
simultaneously. It is the wiring diagram made executable:

```python
# infrastructure/composition_root.py (simplified)

def build_orchestrator(registry, driver=None):
    # 1. Create concrete adapters
    db_manager = DatabaseManager()
    job_repo = JobRepository(db_manager)
    
    # 2. Create domain filters, injecting their port dependencies
    throttle_filter = ThrottlingFilter(profile, job_repo)
    spatial_filter = SpatialLocationFilter(profile, geo_db)
    
    # 3. Create the perception adapter — chosen at runtime
    if driver is not None:
        perception_port = MathPerceptionAdapter(driver)
    else:
        perception_port = BS4PerceptionAdapter(UrllibHTTPClient())
    
    # 4. Create the application engine — all dependencies injected
    app_engine = ApplicationEngine(
        perception_port=perception_port,
        interaction_port=InteractionExecutor(driver),
        reasoning_port=FormSolver(profile),
    )
    
    # 5. Assemble the orchestrator
    return AgentOrchestrator(
        profile=profile,
        task_queue=db_manager,
        db=job_repo,
        ...
    )
```

No component calls `new` on its dependencies. Every object is constructed in
one place and passed down. This is **constructor injection**, and it gives
us several powerful properties:

- **The entire object graph is visible in one file.** You can see exactly
  what depends on what by reading `build_orchestrator()`.
- **Testing is trivial.** To test `ApplicationEngine`, you pass mock ports.
  No real browser, no real database, no network.
- **Configuration is centralised.** The composition root decides which
  adapter to use based on runtime conditions (e.g. low‑resource mode,
  available tools, admin policy).

---

## The Pydantic Exception

There is one deliberate exception to the "no framework imports in `domain/`"
rule: **Pydantic** is permitted in `domain/models/` for data validation and
schema generation.

`UserProfile.model_json_schema()` is the single source of truth for the
schema‑driven UI. Banning Pydantic from the domain would force us to
maintain a duplicate schema definition, or move schema generation to the
application layer — which would still need to import domain models anyway.

This exception is bounded: Pydantic is used only for `UserProfile`, `Job`,
`UIElement`, `InteractionPlan`, and a few other data models. Domain services
(`convex_hull.py`, `entropy.py`, `structural_hashing.py`) remain pure
Python with zero external dependencies.

---

## Testing Benefits

The Port/Adapter pattern and constructor injection mean that **any component
can be tested in isolation with a mock**.

```python
def test_throttling_blocks_duplicate():
    # Create a mock repository that says "already applied"
    mock_repo = MagicMock()
    mock_repo.was_applied.return_value = True
    
    # Create the real filter, injecting the mock
    filter = ThrottlingFilter(profile, mock_repo)
    
    # The filter should reject the job
    passed, reason = filter.filter(job)
    assert not passed
    assert "already applied" in reason.lower()
```

No database. No filesystem. No network. The test runs in milliseconds and
proves the filter's logic, not the database driver.

The same pattern works for engines, workflows, health monitors, and GUI
components. The test suite (`tests/`) is full of these examples.

---

## Adding a New Capability

To add a new job board (e.g. LinkedIn), you:

1. Implement `DiscoveryProviderPort` in a new file:
   `adapters/secondary/discovery/providers/linkedin.py`.
2. Register it in `build_orchestrator()`:
   ```python
   from ... import LinkedInProvider
   providers.append(LinkedInProvider(browser, context))
   ```

To add a new browser automation library (e.g. `nodriver`):

1. Implement `BrowserInterface` in a new adapter.
2. Implement `DriverProvider` in `infrastructure/providers/nodriver_provider.py`.
3. Register both in the composition root.

No other code changes. The orchestrator, engines, and workflows never know
the difference.

---

## Summary

AA's architecture is built on three simple ideas:

1. **Define what you need as an abstract Port.**  
2. **Implement it in a concrete Adapter.**  
3. **Wire them together in one place — the Composition Root.**

This gives us framework‑agnostic design, effortless testability, graceful
degradation, and the ability to add new capabilities with a single file and a
single registration line.

---

## Next Steps

- [Browser Cascade](browser_cascade.md) — how the provider registry and
  fallback chain give AA reliable browser selection.
- [Application Engine](application_engine.md) — how the Scan‑Plan‑Act loop
  uses `PerceptionPort`, `ReasoningPort`, and `InteractionPort` to fill out
  any form.
- [ADR‑001: Hexagonal Architecture](../adr/001_hexagonal_architecture.md) —
  the formal record of why this architecture was chosen.
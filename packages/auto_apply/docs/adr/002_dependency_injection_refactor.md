# ADR‑002: Universal Constructor Dependency Injection

**Status:** Accepted  
**Date:** 2025‑10‑03  
**Deciders:** Nick Liebmann  
**Technical Story:** Before the refactor, core components such as `JobRepository`, `ProfileRepository`, and health monitors constructed their own dependencies internally. This hidden coupling made unit testing impossible without a real filesystem or database, obscured the object graph, and prevented graceful degradation when optional dependencies were unavailable.

---

## Context

AutoApply’s hexagonal architecture (see [ADR‑001](001_hexagonal_architecture.md)) demands that the domain and application layers depend only on abstractions, never on concrete implementations. However, several critical components were violating this rule by creating their own collaborators inside their `__init__` methods:

* `JobRepository` instantiates `DatabaseManager()` directly — every repository creates its own database connection.
* `ProfileRepository` is instantiated directly by the GUI and CLI primary adapters, bypassing the application layer.
* `AgentOrchestrator` lazy‑imports and creates `BrowserHealthMonitor` and `NetworkHealthMonitor` inside a private method.

These patterns caused three problems:

1.  **Untestable code** — any test that instantiated `ThrottlingFilter` (which used `JobRepository`) hit the real filesystem. The GUI could not be tested without a real profile database.
2.  **Hidden object graph** — reading `composition_root.py` did not reveal how many database connections existed or which components needed them.
3.  **No graceful degradation** — if `BrowserHealthMonitor` could not be imported (e.g. missing optional dependency), the entire session crashed.

---

## Decision

We adopted a universal rule: **every class must receive its dependencies via its constructor. No class may construct a dependency that it uses.** All construction is centralised in `infrastructure/composition_root.py`.

### Three Critical Refactors

**1. `DatabaseManager` → `JobRepository`**

Before:
```python
class JobRepository:
    def __init__(self) -> None:
        self.db = DatabaseManager()   # hidden coupling
```

After:
```python
class JobRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db                 # injected
```

The composition root now creates one `DatabaseManager` instance and passes it to every component that needs it.

**2. `ProfileRepository` in Primary Adapters**

Before, the GUI and CLI each instantiated `ProfileRepository` directly — a secondary adapter being created inside a primary adapter, bypassing the application layer entirely.

After, a `build_session()` factory in the composition root creates the `ProfileRepository` once and injects it into the GUI and CLI constructors. Neither adapter imports `ProfileRepository` anymore.

**3. Health Monitors in `AgentOrchestrator`**

Before, `AgentOrchestrator._start_health_monitors()` lazy‑imported and instantiated monitors. This hid the dependency graph and crashed on missing optional imports.

After, a `HealthMonitor` Protocol was added to `domain/ports/health_monitor_port.py`. The monitors are constructed in the composition root (with graceful `try/except` for missing modules) and injected into the orchestrator as optional constructor parameters.

---

## Options Considered

### Keep internal construction, use mocking at the module level
**Rejected.** Module‑level mocking (`unittest.mock.patch`) is fragile, depends on import paths, and makes tests slow. It also prevents reasoning about the object graph from code alone.

### Use a service locator / global registry
**Rejected.** A global registry hides dependencies instead of making them explicit. It would also violate the “no domain imports from infrastructure” rule.

### Constructor injection everywhere
**Accepted.** This is the only pattern that makes dependencies explicit, enables isolated testing, and keeps the composition root as the single wiring authority.

---

## Consequences

### What becomes easier

- **Testing:** Any component can be instantiated with mock dependencies. `ThrottlingFilter` can be tested with a mock `JobRepositoryPort` — no database, no filesystem, milliseconds per test.
- **Visibility:** Reading `composition_root.py` reveals the complete object graph. Every dependency is visible in one file.
- **Graceful degradation:** Optional dependencies are handled at construction time. If a monitor cannot be created, it is simply `None` and the orchestrator handles the absence cleanly.

### What becomes harder

- **Wiring overhead:** Every new class requires an additional constructor parameter and a corresponding line in `composition_root.py`. This is mechanical but necessary.
- **Large constructors:** Classes with many dependencies (e.g. `ApplicationEngine`, `ApplicationsWorkflow`) have long constructor signatures. This is a known trade‑off of pure DI and is mitigated by the composition root handling construction exactly once.

---

## The General Pattern

Every DI change in this codebase follows the same three steps:

1. Identify what a class needs from outside itself.
2. Express that need as a Protocol in `domain/ports/` (if it crosses the domain boundary) or as a constructor parameter (if it stays within one layer).
3. Move the construction to `infrastructure/composition_root.py` and pass the result in.

The invariant is: **a class never constructs a dependency that it uses**.

---

## Testing Benefit

The DI refactor enables straightforward unit testing without any real infrastructure:

```python
def test_throttling_blocks_duplicate():
    mock_repo = MagicMock()
    mock_repo.has_applied_to.return_value = True

    filter_ = ThrottlingFilter(profile, mock_repo)
    job = Job(url="https://example.com/job/1", ...)

    assert not filter_.passes(job)
    mock_repo.has_applied_to.assert_called_once_with("https://example.com/job/1")
```

No database. No filesystem. No network.

---

## References

- [ADR‑001: Hexagonal Architecture](001_hexagonal_architecture.md)
- [ADR‑010: Remediation Changelog](010_remediation_changelog.md) — specific violations fixed during the audit sprint
- `infrastructure/composition_root.py` — the central wiring point
- `domain/ports/health_monitor_port.py` — the `HealthMonitor` Protocol
- `application/agent/orchestrator.py` — constructor accepting injected monitors
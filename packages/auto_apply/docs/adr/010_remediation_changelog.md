# ADR‑010: Architecture Audit and Remediation Sprint

**Status:** Accepted
**Date:** 2026‑02‑10
**Deciders:** Nick Liebmann
**Technical Story:** After the major architectural refactors of ADRs 001–009, the codebase needed a systematic review to verify that every layer conformed to the hexagonal dependency rules, that all dependencies were injected, and that no runtime crashes lurked in edge cases. An audit was conducted across all ~250 source files, identifying layering violations, missing injections, duplicate code, and critical runtime bugs. All Priority 1–3 issues were resolved; Priority 4 items were documented and deferred.

---

## Context

The AutoApply codebase had undergone rapid evolution over six months. Several major refactors — hexagonal architecture adoption, universal dependency injection, dual state machines, the HITL system, the BS4 fallback, and the schema‑driven UI — had been implemented across hundreds of files. While the architecture was sound in principle, a systematic audit was needed to verify conformance and catch any regressions.

The audit goals were:

1.  **Verify layering compliance** — ensure no `domain/` file imports from `adapters/`, no `application/` file imports from `infrastructure/`, and no adapter imports across primary/secondary boundaries.
2.  **Verify dependency injection** — ensure every class receives its dependencies via constructor and no class constructs its own collaborators.
3.  **Eliminate duplicate code** — collapse parallel implementations of the same logic (page state classification, state enums) into single sources of truth.
4.  **Fix all runtime crashes** — identify and resolve any bug that would prevent the application from completing a session.

---

## Decision

A comprehensive, file‑by‑file audit was conducted, producing a tiered remediation changelog. Issues were classified by severity:

- **Priority 1** — Runtime crashes that prevented session completion.
- **Priority 2** — Layering violations, duplicate state management, and missing injections that compromised architectural integrity.
- **Priority 3** — Capability gaps that prevented the application from functioning in certain environments.
- **Priority 4** — Desired enhancements that were documented but deferred.

All P1–P3 items were resolved in a single sprint. P4 items were documented for future work.

---

## Priority 1 — Runtime Crash Fixes

These were blocking issues: the application crashed before completing any session.

### SHUTTING_DOWN → STOPPING/STOPPED teardown route
**File:** `application/agent/orchestrator.py`
**Bug:** `transition_to(AgentState.SHUTTING_DOWN)` was called in the teardown path. `SHUTTING_DOWN` did not exist in the `AgentState` enum. The call silently returned `False`, the teardown branch was never taken, and cleanup code was skipped on every session end.
**Fix:** Replaced with the existing `STOPPING → STOPPED` path, already defined in `VALID_TRANSITIONS`.

### Delete duplicate AgentState enum
**File:** `application/agent/states.py` (deleted)
**Bug:** A stale `AgentState` enum with 9 states existed alongside the authoritative 14‑state enum in `state_machine.py`. Whichever was imported last won; the 9‑state version was missing `AWAITING_HUMAN`, `RESOLVING_CAPTCHA`, and `RESOLVING_LOGIC_CONFLICT`.
**Fix:** Deleted the stale file after confirming zero live imports.

### GUI dashboard log method mismatch
**File:** `adapters/primary/gui/ui_handler.py`
**Bug:** `dashboard.log(msg)` was called but the `Dashboard` class exposes `log_message(msg)`, not `log()`. This raised `AttributeError` on every first log emit from the GUI.
**Fix:** Changed `dashboard.log(msg)` to `dashboard.log_message(msg)`.

### Tkinter widget mutations from worker thread
**File:** `adapters/primary/gui/dashboard.py`
**Bug:** `log_message()` mutated `self.log_text` (a Tkinter `Text` widget) directly from worker threads. Tkinter is not thread‑safe; this caused intermittent crashes and corrupted widget state.
**Fix:** Wrapped all widget mutations in `self.after(0, …)` to schedule them on the main thread.

### `PersonalInfo.resume_path` optional
**File:** `domain/models/profile.py`, `adapters/primary/gui/settings_editor.py`
**Bug:** The settings editor set `resume_path = None` when clearing the field. `PersonalInfo.resume_path: Path` was non‑Optional with `validate_assignment=True`. Pydantic raised `ValidationError`.
**Fix:** Changed the model field to `Path | None`.

### `cover_letter_path` → `cover_letter` field name
**File:** `adapters/primary/gui/settings_editor.py`
**Bug:** The settings editor read and wrote `profile.personal_info.cover_letter_path`. The actual model field is `cover_letter`. Reads always returned `None`; writes silently discarded the value.
**Fix:** Changed all references from `cover_letter_path` to `cover_letter`.

### GUI `self.registry` uninitialised
**File:** `adapters/primary/gui/app.py`
**Bug:** `_open_settings()` checked `if self.registry is not None`. `self.registry` was never initialised in `__init__`. If `_open_settings` ran before `_load_and_start`, `AttributeError` crashed the GUI.
**Fix:** Added `self.registry: CapabilitiesRegistry | None = None` to `GUIApp.__init__`.

### CLI dashboard render body
**File:** `adapters/primary/cli/dashboard.py`
**Bug:** The `_render()` method computed statistics, then fell through to `pass`. The dashboard rendered completely blank.
**Fix:** Implemented the render body to print computed statistics to stdout using ANSI clear‑line sequences.

### CLI profile listing body
**File:** `adapters/primary/cli/startup.py`
**Bug:** The profile listing loop body was `pass`. The startup wizard printed a menu header with no entries.
**Fix:** Implemented the loop body to print each profile name with a selection number.

### Deprecated `locale.getdefaultlocale()`
**File:** `adapters/primary/gui/strings.py`
**Bug:** `locale.getdefaultlocale()` is deprecated in Python 3.11 and removed in 3.15. Produced `DeprecationWarning` and would crash on future Python versions.
**Fix:** Replaced with `locale.getlocale()`.

### Five‑dot relative import in evasion session
**File:** `adapters/secondary/evasion/components/session.py`
**Bug:** `from .....core.config import settings` — five leading dots, a five‑level relative import resolving outside the package boundary. Crashed with `ImportError`.
**Fix:** Changed to absolute: `from auto_apply.domain.config import settings`.

---

## Priority 2 — Hexagonal Cleanup and State Collapse

### Split `composition_root` into `registry.py` + `composition_root.py`
**Files:** `infrastructure/registry.py` (new), `infrastructure/composition_root.py` (trimmed)
`CapabilitiesRegistry`, `EnvironmentCapabilities`, `_RUNTIME_DEFAULTS`, and low‑resource thresholds were extracted from `composition_root.py` into `registry.py`. The composition root retains only `build_orchestrator()` and `build_session()`.
**Rationale:** The original file violated single responsibility — "what can this environment do?" vs. "wire up all the objects."

### Inject `DatabaseManager` into `JobRepository`
**Files:** `adapters/secondary/persistence/job_repository.py`, `infrastructure/composition_root.py`
Before: `JobRepository.__init__()` called `DatabaseManager()` internally, creating a new connection per repository.
After: `JobRepository` receives `db: DatabaseManager` via constructor injection. A single connection is created in the composition root and shared.

### Inject `ProfileRepository` into GUI/CLI primary adapters
**Files:** `adapters/primary/gui/app.py`, `adapters/primary/cli/startup.py`, `infrastructure/composition_root.py`
A `build_session()` helper in the composition root creates the `ProfileRepository` once and injects it. Neither the GUI nor the CLI imports `ProfileRepository` directly.

### Inject health monitors into `AgentOrchestrator`
**Files:** `application/agent/orchestrator.py`, `domain/ports/health_monitor_port.py` (new), `infrastructure/composition_root.py`
A `HealthMonitor` Protocol was added. Monitors are constructed in the composition root with graceful `try/except` and injected as optional constructor parameters. Missing optional dependencies no longer crash the session.

### Move `Coordinate` to `domain/models/location.py`
**Files:** `domain/ports/location_port.py`, `domain/models/location.py` (new)
`Coordinate(lat, lng)` was a concrete data model living inside a port definition file. It was moved to `domain/models/location.py`. The port now imports from the models layer.

### Refactor `DOMScanner` cross‑layer imports
**File:** `adapters/secondary/perception/dom_adapter.py`
Removed imports of `application/services/context_manager.py` and `domain/applications/field_classifier.py`. Replaced with an injected `FieldClassifierPort` parameter.

### Extend `ApplicationState` + `VALID_APPLICATION_TRANSITIONS`
**File:** `domain/applications/fsm/states.py`
Added states: `MODAL_OPEN`, `REDIRECT_TO_CAREERS_PAGE`, `REDIRECT_TO_LIST`, `INDEED_TAB_SWITCHED`, `AWAITING_HUMAN`. Terminal states (`SUCCESS`, `CLOSED`, `ALREADY_APPLIED`, `REDIRECT_TO_LIST`, `REDIRECT_TO_CAREERS_PAGE`, `CRITICAL_FAILURE`) have empty outgoing frozensets.

### Add `PerceptionPort.get_current_state()` + implementations
**Files:** `domain/ports/perception_port.py`, `adapters/secondary/perception/math_perception_adapter.py`, `adapters/secondary/perception/bs4_adapter.py`
Added `get_current_state() → ApplicationState` to the `PerceptionPort` contract. Implemented in both adapters using keyword tables and structural heuristics.

### Collapse PRA loop: rewrite `_apply_single`
**File:** `application/use_cases/applications_use_case.py`
Rewrote as a dispatch on `get_current_state()`. Deleted `_detect_success()`, `_detect_already_applied()`, `_detect_redirect_to_list()` — these page‑classification heuristics now live in the perception adapter. Deleted `domain/applications/fsm/universal.py` (duplicate state machine).

### Emit `RedirectToListDetected` event
**Files:** `application/use_cases/applications_use_case.py`, `application/agent/event_bus.py`
When the Application Engine detects `REDIRECT_TO_LIST`, it publishes `RedirectToListDetected` on the EventBus and aborts. The orchestrator decides whether to enqueue a Discovery work unit. Engines never call each other directly.

### Wire `VettingEngine._detect_form_co_location`
**File:** `application/use_cases/vetting_use_case.py`
`_detect_form_co_location()` existed but was never called from `run()`. Wired it into the vetting loop — it short‑circuits vetting when the listing page already contains the application form.

### Delete inline `LANG_*` dicts; wire i18n service
**Files:** `adapters/primary/gui/strings.py`, `application/services/i18n.py`
The inline `LANG_EN` and `LANG_ES` dicts were deleted. All string resolution now routes through `get_text()` from `application/services/i18n.py`, which reads `resources/locales/*.json`.

### Build `application/services/ui_schema.py`
**File:** `application/services/ui_schema.py` (new)
Added `UIField` dataclass and `build_ui_schema(profile_cls, locale)`. Walks `UserProfile.model_json_schema()` to produce a flat list of field descriptors consumed by both the GUI settings editor and CLI wizard. (See [ADR‑007](007_profile_and_schema_driven_ui.md).)

---

## Priority 3 — Capability Expansion

### Add `HTTPClientPort` + `UrllibHTTPClient`
**Files:** `domain/ports/http_client_port.py` (new), `adapters/secondary/network/urllib_http_client.py` (new)
Minimal GET‑only interface with a stdlib implementation. No third‑party dependencies.

### Implement `BS4PerceptionAdapter`
**File:** `adapters/secondary/perception/bs4_adapter.py` (was a one‑line stub; now full implementation)
Full `PerceptionPort` implementation backed by BeautifulSoup. Fetches via `HTTPClientPort`, classifies state via keyword rules + structural analysis, and extracts form elements with a five‑step label resolution chain. (See [ADR‑006](006_bs4_zero_browser_fallback.md).)

### Wire BS4 fallback in composition root
**File:** `infrastructure/composition_root.py`
When `driver is None`, `build_orchestrator()` now creates `BS4PerceptionAdapter(UrllibHTTPClient())` as the perception port. Graceful degradation for zero‑browser environments.

### Add `ATSPort` + `ATSDescriptor`
**File:** `domain/ports/ats_port.py` (new)
Frozen dataclass and Protocol for ATS platform identification. (See [ADR‑004](004_ats_platform_registry.md).)

### Build ATS YAML registry loader
**Files:** `adapters/secondary/discovery/ats_registry.py` (new), `resources/ats/*.yaml` (new)
`ATSRegistry` loads all `*.yaml` files at startup and compiles URL patterns into regex. `match(url)` returns the first matching descriptor. `all_descriptors()` returns the full list for provider site‑filter construction.

### Refactor `GoogleProvider` and `BingProvider` to use `ResilientNavigator`
**Files:** `adapters/secondary/discovery/providers/google.py`, `adapters/secondary/discovery/providers/bing.py`
Both providers were rewritten to use `ResilientNavigator([DirectURLNavigation, HumanSearchNavigation])` instead of calling `safe_navigate()` directly. `GoogleProvider.find_company_career_page()` derives site‑filter domains from the ATS registry.

### Move runtime defaults to YAML
**Files:** `resources/config/runtime_defaults.yaml` (new), `infrastructure/registry.py`
Moved the 21‑key `_RUNTIME_DEFAULTS` dict to YAML. The registry loads it at startup with graceful fallback to inline defaults if `pyyaml` is not installed.

### Add `AgentState.AWAITING_HUMAN` + transitions
**File:** `application/agent/state_machine.py`
Added `AWAITING_HUMAN` state with transitions to/from `RUNNING`, `APPLYING`, `RESOLVING_LOGIC_CONFLICT`, and `STOPPING`. (See [ADR‑005](005_human_in_the_loop.md).)

### Add `InterruptPolicyPort` + implementations
**File:** `domain/ports/interrupt_policy_port.py` (new)
`Checkpoint` enum, `ApplicationContext` frozen dataclass, `InterruptPolicy` Protocol, and three concrete implementations.

### Add HITL approval events + `SessionController` gates
**Files:** `application/agent/event_bus.py`, `application/services/session_controller.py`
`request_approval()` and `provide_approval()` with `threading.Event` per pending approval. GUI and CLI both subscribe to `HUMAN_APPROVAL_REQUESTED`.

### Replace hardcoded settings editor options with `ui_schema`
**File:** `adapters/primary/gui/settings_editor.py`
Hardcoded workplace and employment type checkboxes replaced with schema‑derived loops. Options come from `UIField.options`.

### Replace hardcoded wizard defaults with `ui_schema`
**File:** `adapters/primary/cli/wizard.py`
Full rewrite. `CLIWizard(profile=profile)` accepts an optional profile for defaults. `_schema_label(key, fallback)` resolves prompt labels from `build_ui_schema()`.

---

## Priority 4 — Deferred

These items were identified in the audit but not implemented in this sprint. They are documented for future work.

| Item | Files | Notes |
|------|-------|-------|
| JSON Resume import/export | `application/services/json_resume_io.py` (new) | Two‑way mapping; internal schema remains `UserProfile`. |
| Accessibility wiring | GUI dashboard, captcha adapter | Wire `accessibility_preferences` into GUI palette and audio captcha hints. |
| `BrowserInterface` split | `domain/ports/browser_port.py` | Split 25+ methods into `Navigator`, `Element`, `Cookies` sub‑interfaces for smaller dependency surfaces. |
| Default HITL checkpoint gates | `application/use_cases/applications_use_case.py` | Wire `BEFORE_FORM_SUBMIT` and `ON_SUSPICIOUS_REDIRECT` as the default active gates. |

---

## Options Considered

### Skip the audit; fix issues as they are discovered
**Rejected.** The number and severity of issues that had accumulated across six months of rapid development justified a systematic review. Without it, several crashes (the `SHUTTING_DOWN` bug, the `log()` vs. `log_message()` mismatch, the stale `AgentState` enum) would have persisted into production.

### Defer P2 (architectural) items as well
**Rejected.** Layering violations and duplicate state management are technical debt that compounds. The P2 items were resolved in the same sprint because they touched the same files as P1 items and the cost of deferral (continued architectural drift) outweighed the cost of immediate resolution.

---

## Consequences

### What became easier

- **Session completion:** The application completes a full discovery → vetting → application → teardown cycle without crashing.
- **Architectural integrity:** Every file in the codebase now conforms to the hexagonal layering rules documented in ADR‑001. The composition root is the single wiring authority.
- **Testability:** All components receive their dependencies via constructor injection, enabling isolated unit testing.
- **Graceful degradation:** The BS4 fallback, missing‑monitor handling, and optional dependency guards ensure the application runs on the weakest target hardware.

### What became harder

- **Ongoing discipline:** The audit revealed that layering violations and missing injections can creep in during rapid development. Future code review must include explicit checks for import direction and constructor‑based injection.

---

## Tests Added

| Test file | Coverage |
|-----------|----------|
| `tests/adapters/test_cli_wizard.py` | 19 tests: no‑profile defaults, profile‑derived defaults, user override, schema label resolution, mode/strategy selection, max_results validation. |
| `tests/adapters/test_discovery_providers.py` | 18 tests: `_ats_site_filters` behaviour, navigator wiring, `find_company_career_page` behaviour. |
| `tests/perception/test_bs4_adapter.py` | State classification, form element extraction, label resolution, graceful degradation without BS4. |
| `tests/services/test_ui_schema.py` | Field count, label derivation, options population for multiselect fields. |

---

## References

- [ADR‑001: Hexagonal Architecture](001_hexagonal_architecture.md) — the layering rules enforced by this audit
- [ADR‑002: Dependency Injection](002_dependency_injection_refactor.md) — the injection patterns verified during the audit
- [ADR‑003: PRA Loop and State Machines](003_pra_loop_and_state_machine.md) — the state collapse from dual implementations to single source of truth
- [ADR‑005: Human‑in‑the‑Loop](005_human_in_the_loop.md) — the `AWAITING_HUMAN` state added during this sprint
- [ADR‑006: BS4 Zero‑Browser Fallback](006_bs4_zero_browser_fallback.md) — the BS4 adapter implemented from stub
- [ADR‑007: Schema‑Driven UI](007_profile_and_schema_driven_ui.md) — the `ui_schema.py` module built during this sprint
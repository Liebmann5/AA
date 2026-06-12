# ADR‑003: PRA Loop and Dual State Machines

**Status:** Accepted  
**Date:** 2025‑10‑20  
**Deciders:** Nick Liebmann  
**Technical Story:** The original application engine tracked page state in two separate places — private helper methods in `applications_use_case.py` and a parallel page‑state enum in `universal.py`. When a new terminal state was needed, it had to be added in both locations with slightly different keyword lists. The two implementations drifted silently, making the engine fragile and hard to extend. Additionally, the orchestrator’s operational state was managed by scattered boolean flags (`self.running`, `self.paused`) that lacked formal transition rules and could not express intermediate states like “resolving a CAPTCHA” or “waiting for human approval.”

---

## Context

The Application Engine must classify the current page into a well‑defined state (form step, upload step, review, success, redirect, error, etc.) and then dispatch the correct action. Before the refactor this classification was duplicated:

1. **`application/use_cases/applications_use_case.py`** — private helper methods (`_detect_success`, `_detect_already_applied`, `_detect_redirect_to_list`) scraped the DOM to determine what was happening.
2. **`domain/applications/fsm/universal.py`** — a `UniversalApplicationStrategy` class maintained its own page‑state enum and transition logic, independent of the engine.

Meanwhile, the orchestrator used two boolean flags to manage session state, making it impossible to represent richer operational modes like CAPTCHA resolution or human‑in‑the‑loop pauses without fragile conditional logic.

---

## Decision

We introduced **two formal finite state machines** that operate at different scopes:

### 1. `ApplicationState` — 17‑state page classifier (per‑form)

A single `ApplicationState` enum (in `domain/applications/fsm/states.py`) now defines every possible page state:

```
UNKNOWN, INITIAL_START, LOGIN_WALL, FORM_STEP, UPLOAD_STEP, REVIEW_STEP,
MODAL_OPEN, REDIRECT_TO_CAREERS_PAGE, REDIRECT_TO_LIST, INDEED_TAB_SWITCHED,
SUBMITTING, AWAITING_HUMAN, SUCCESS, ERROR, ALREADY_APPLIED, CLOSED, CRITICAL_FAILURE
```

The classification logic is the responsibility of `PerceptionPort.get_current_state()` — the engine no longer inspects DOM text. A `VALID_APPLICATION_TRANSITIONS` table dictates which states may follow one another. Terminal states have empty outgoing sets, acting as a safety circuit breaker.

### 2. `AgentState` — 14‑state session FSM (orchestrator‑level)

A separate `AgentState` enum (in `application/agent/state_machine.py`) governs the entire agent session:

```
IDLE, INITIALIZING, RUNNING, DISCOVERING, VETTING, APPLYING, PAUSED,
RESOLVING_CAPTCHA, RESOLVING_LOGIC_CONFLICT, AWAITING_HUMAN,
ERROR_RECOVERY, STOPPING, STOPPED, FAILED
```

A `StateMachine` class with a `VALID_TRANSITIONS` frozenset and a thread‑safe `transition_to()` method enforces that the agent never enters an impossible state. Invalid transitions return `False` rather than raising exceptions — the orchestrator logs the attempt and continues in its current state.

### 3. The Perceive‑Read‑Act (PRA) Loop

The Application Engine was rewritten to use a clean PRA loop:

1. **Perceive** — call `perception.get_current_state()` to classify the page.
2. **Read** — validate the transition against `VALID_APPLICATION_TRANSITIONS`.
3. **Act** — dispatch on the current state (`FORM_STEP` → fill fields, `REVIEW_STEP` → submit, `SUCCESS` → return, etc.).

The loop is bounded by a `WorkflowContext.max_steps` (default 25) safety breaker to prevent infinite loops on oscillating pages.

### 4. Cross‑Engine Isolation via Events

When the Application Engine detects a redirect to a listing page (`REDIRECT_TO_LIST`), it does **not** call the Discovery Engine directly. Instead, it publishes a `RedirectToListDetected` event on the EventBus. The orchestrator decides whether to enqueue a Discovery work unit for that URL. Engines never call each other.

---

## Options Considered

### Keep dual classification, add synchronisation tests
**Rejected.** Maintaining two independent implementations of the same logic is inherently fragile. Synchronisation tests would be required indefinitely, and any new developer would need to understand both code paths.

### A single, monolithic state machine covering both page and session state
**Rejected.** Mixing per‑form page states with session‑level operational states would create a combinatorial explosion of states and transitions. The two scopes are orthogonal and are best managed independently.

### Eliminate the FSM entirely, use a linear script with exception‑based control flow
**Rejected.** The original `WorkflowOrchestrator` was a linear script and it was rigid, untestable, and could not recover from unexpected page states. The state machine approach makes the agent’s behaviour predictable and auditable.

---

## Consequences

### What becomes easier

- **Predictability:** Every valid state transition is documented in a single table. Adding a new state requires updating the enum, the transition table, and the perception adapter — nothing else.
- **Safety:** The transition guard prevents impossible jumps (e.g. `SUCCESS` → `FORM_STEP`). The `max_steps` circuit breaker prevents infinite loops.
- **Testability:** The engine dispatches on an enum value; tests can inject a perception port that returns any desired state without a real browser.
- **Extensibility:** Adding a new page state (e.g. `TWO_FACTOR_REQUIRED`) follows a documented five‑step recipe that touches only well‑defined locations.

### What becomes harder

- **State proliferation:** Developers must resist the temptation to add states for every minor variation of a page. The 17 existing states cover the vast majority of real‑world scenarios; additional states should be justified.
- **Transition table maintenance:** The `VALID_APPLICATION_TRANSITIONS` table must be kept accurate. A missing entry will block a valid transition and log a warning rather than crashing, which can mask bugs if not caught in testing.

---

## The Teardown Fix

A pre‑refactor bug called `transition_to(AgentState.SHUTTING_DOWN)` — a state that did not exist in `state_machine.py`. The call silently returned `False` and cleanup code was skipped on every session end. The fix routed teardown through the existing `STOPPING → STOPPED` path, which was already defined in `VALID_TRANSITIONS`. No new states were added.

---

## Adding a New ApplicationState

The documented five‑step process:

1. Add the state to the `ApplicationState` enum in `domain/applications/fsm/states.py`.
2. Add valid transitions to/from it in `VALID_APPLICATION_TRANSITIONS`.
3. Add keyword rules to `_STATE_KEYWORDS` in `MathPerceptionAdapter` and `_TEXT_STATE_RULES` in `BS4PerceptionAdapter`.
4. Add a dispatch branch in `ApplicationEngine.apply()`.
5. Add tests in `tests/perception/` and `tests/use_cases/`.

The `AgentState` FSM, `StateMachine` class, and orchestrator remain untouched — the two state machines are orthogonal.

---

## References

- [ADR‑001: Hexagonal Architecture](001_hexagonal_architecture.md)
- [ADR‑005: Human‑in‑the‑Loop](005_human_in_the_loop.md) — the `AWAITING_HUMAN` state and its transitions
- [Application Engine (Architecture Deep Dive)](../architecture/application_engine.md)
- `domain/applications/fsm/states.py` — `ApplicationState` enum and `VALID_APPLICATION_TRANSITIONS`
- `application/agent/state_machine.py` — `AgentState` enum, `StateMachine` class
- `application/use_cases/applications_use_case.py` — the PRA loop implementation
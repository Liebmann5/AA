# ADR‑005: Human‑in‑the‑Loop Checkpoint Architecture

**Status:** Accepted  
**Date:** 2025‑11‑12  
**Deciders:** Nick Liebmann  
**Technical Story:** Full automation of a legally significant action — submitting a job application on a person’s behalf — demands that the user retain control. AA needed a mechanism to pause at high‑stakes moments, present a clear question, and wait for explicit approval before proceeding, without sacrificing the ability to run fully autonomously when desired. The solution had to work identically in GUI and CLI, degrade gracefully when no user is present, and never block the agent indefinitely.

---

## Context

AutoApply’s Application Engine autonomously navigates to a job application form, fills out every field, and clicks Submit. However, certain steps should not be executed without human review:

- **Before form submission** — the user should have the final say on what is sent.
- **On suspicious redirects** — if the form unexpectedly navigates away, the user should decide whether to continue, skip, or re‑queue the job.
- **On low‑confidence field mappings** — if the solver cannot match a form field to the profile with high confidence, the user should verify the value.

At the same time, some users want fully autonomous operation — a “set it and forget it” mode where AA runs unattended. The design must support both extremes and everything in between.

The solution must satisfy two hard constraints:

1. **Worst‑case user:** The approval prompt must work in a terminal over SSH. No GUI can be assumed.
2. **Timeout safety:** If the user walks away, the agent must not hang indefinitely. A reasonable default (5 minutes) must trigger an automatic fallback.

---

## Decision

We introduced a **Human‑in‑the‑Loop (HITL)** system with three components:

### 1. Pluggable InterruptPolicy

A `Checkpoint` enum defines every point in the pipeline where a pause can be inserted:

```python
class Checkpoint(Enum):
    AFTER_VETTING = auto()            # job approved; about to open form
    BEFORE_FORM_SUBMIT = auto()       # form filled; about to click Submit
    ON_AMBIGUOUS_SUBMISSION = auto()  # post‑submit page unclear
    ON_SUSPICIOUS_REDIRECT = auto()   # unexpected navigation mid‑session
    ON_LOW_CONFIDENCE_FIELD = auto()  # field mapping confidence below threshold
```

The `InterruptPolicy` Protocol (in `domain/ports/interrupt_policy_port.py`) answers one question: “Should the agent pause here?”

Three concrete implementations are provided:

| Policy | Behaviour |
|--------|-----------|
| `ProfileBasedInterruptPolicy` | Reads `app_config.human_review_checkpoints` from the user’s profile. Defaults to `{BEFORE_FORM_SUBMIT, ON_SUSPICIOUS_REDIRECT}`. |
| `NeverInterruptPolicy` | Always returns `False` — fully autonomous. |
| `AlwaysInterruptPolicy` | Always returns `True` — maximum oversight. |

The policy is injected into `ApplicationEngine` at construction time. Adding a new checkpoint requires only a new `Checkpoint` member, a question template, and a guard in the engine’s PRA loop.

### 2. Blocking Approval Gate via SessionController

When a checkpoint fires, the engine calls `SessionController.request_approval()`, passing:

- A human‑readable question (e.g. “About to submit your application to Acme Corp for Software Engineer. Approve, skip, or stop?”).
- A list of valid choices (`["approve", "skip", "stop"]`).
- A checkpoint identifier.

Internally, `request_approval()`:

1. Generates a unique `context_id` (UUID).
2. Creates a `threading.Event` — the gate.
3. Stores the event and a mutable choice holder in a thread‑safe dictionary.
4. Publishes `HUMAN_APPROVAL_REQUESTED` on the EventBus with the context ID, question, and options.
5. Blocks on `event.wait(timeout=300)`.

The GUI or CLI dashboard subscribes to `HUMAN_APPROVAL_REQUESTED` and presents the question:

- **GUI:** A modal dialog appears with buttons for each option. Tkinter’s `grab_set()` ensures the user cannot interact with the main window until they choose. The dialog is scheduled on the main thread via `after(0, …)` to satisfy Tkinter’s thread‑safety requirements.
- **CLI:** The terminal prints a numbered prompt and reads a single line from `stdin`. An `EOFError` guard handles the case where `stdin` is a pipe (worst‑case user scenario), defaulting to “skip.”

When the user chooses, the dashboard calls `SessionController.provide_approval(context_id, choice)`, which:

1. Writes the choice into the mutable holder.
2. Sets the event — unblocking the agent thread.
3. Publishes `HUMAN_APPROVAL_GRANTED` so the orchestrator’s state machine can transition out of `AWAITING_HUMAN` before the agent resumes.

### 3. State Machine Integration

The `AgentState` enum includes an `AWAITING_HUMAN` state. Valid transitions are:

```
RUNNING                  → AWAITING_HUMAN
APPLYING                 → AWAITING_HUMAN
RESOLVING_LOGIC_CONFLICT → AWAITING_HUMAN
AWAITING_HUMAN           → RUNNING        (user approved)
AWAITING_HUMAN           → APPLYING       (user approved mid‑apply)
AWAITING_HUMAN           → STOPPING       (user stopped)
```

The state machine transitions to `AWAITING_HUMAN` **before** the gate opens, so the UI immediately reflects the pause. When `provide_approval()` is called, the machine transitions to `RUNNING` (or `STOPPING` if the user chose “stop”) **before** `gate.set()` unblocks the agent thread — guaranteeing the agent sees the correct state on resume.

---

## Options Considered

### Always pause at every field (no policy, just hardcoded)
**Rejected.** A system that pauses on every form field is not an agent — it’s a glorified copy‑paste tool. The default configuration pauses only at the two highest‑stakes checkpoints, balancing automation with control.

### Use a callback system without blocking the agent thread
**Rejected.** This would require the agent to be async‑aware and would complicate the simple, synchronous Scan‑Plan‑Act loop. Blocking with a `threading.Event` is simple, correct, and works on the lowest‑spec hardware — no asyncio required.

### Require a GUI for approval (no CLI support)
**Rejected.** This violates the worst‑case‑user constraint. AA must work on a headless server accessed via SSH, where `stdin` is the only I/O channel.

---

## Consequences

### What becomes easier

- **User trust:** The user knows that AA will never submit anything without explicit consent (unless they choose fully autonomous mode).
- **Debugging:** The `HUMAN_APPROVAL_REQUESTED` event payload contains the full context, making it trivial to log and audit every decision.
- **Extensibility:** Adding a new checkpoint is a five‑step process: add a `Checkpoint` member, add a question template, add a guard in the engine, update the policy’s default set (if desired), and add a test.
- **Admins:** An `AdminPolicy` can force specific checkpoints to be active via `config_overrides`, ensuring institutional compliance.

### What becomes harder

- **Engine complexity:** The PRA loop now includes HITL evaluation at multiple points, increasing the number of branches. Each checkpoint guard is small and well‑defined, but the overall flow requires careful reading.
- **Threading discipline:** The approval gate involves coordination between the agent thread (which blocks on the gate) and the GUI/CLI thread (which calls `provide_approval()`). Both sides must respect the locking discipline. The `StateMachine` lock is re‑entrant on the same thread in CPython’s GIL, but the distinction is subtle and must be documented.

---

## The ApprovalGate Late‑Binding

A circular dependency exists: `ApplicationEngine` is constructed before `SessionController`, but the approval gate is a method on `SessionController`. To resolve this, the engine stores an `approval_gate` callable that is initially `None`. After construction, `SessionController._wire_approval_gate()` sets the gate on the engine via `engine.set_approval_gate(self.request_approval)`.

This is a documented pragmatic workaround, not an architectural ideal. A future ADR may introduce a `GateRegistry` to eliminate the circular dependency entirely.

---

## References

- [ADR‑003: PRA Loop and State Machines](003_pra_loop_and_state_machine.md) — the `AWAITING_HUMAN` state and its transitions
- `domain/ports/interrupt_policy_port.py` — `Checkpoint`, `ApplicationContext`, `InterruptPolicy`, and concrete policies
- `application/services/session_controller.py` — `request_approval()`, `provide_approval()`, and `_wire_approval_gate()`
- `application/use_cases/applications_use_case.py` — HITL checkpoint guards in the PRA loop
- `adapters/primary/gui/dashboard.py` — GUI approval modal
- `adapters/primary/cli/dashboard.py` — CLI approval prompt
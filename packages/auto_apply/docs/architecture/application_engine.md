---
title: "Application Engine"
status: needs-review
last_verified: 2026-11-26
verified_against: "the step-engine section against application/services/form_engine.py, form_actuator.py, adapters/secondary/perception/pagecomp_form.py, domain/applications/form_localization.py, answer_review.py, external_steps.py, selection_limits.py and runtime_defaults.yaml; the sections after it describe the earlier page loop and were not re-verified"
audience: contributors
---

# Application Engine

The Application Engine is the final and most complex stage of the pipeline.
It takes an approved job, navigates to its application form, and autonomously
fills out every field — standard contact details, custom open‑ended questions,
file uploads, multi‑page wizards, and the final submission — pausing at
configurable checkpoints so the user can review before anything is sent.

The engine is built around a **Scan‑Plan‑Act loop** governed by a
**Finite State Machine**. It uses three injected ports — `PerceptionPort`,
`ReasoningPort`, and `InteractionPort` — to observe the page, decide what
to do, and perform the actions. The engine never touches the browser or DOM
directly. It is completely framework‑agnostic and testable in isolation.

---

## How forms are filled now: the step engine

Since 2026-11 the form is filled by the **application step engine**
(`application/services/form_engine.py`; the decision is
[ADR-023](../adr/023_application_step_engine.md)). The sections after this one
describe the earlier page loop, which stays selectable with
`applications.form_engine: legacy` until it is retired.

`ApplicationsWorkflow` still owns everything around the form: reaching it (the
apply route), challenges and sign-in walls, and the irreversible submit behind
the fail-closed gate. Between those, the engine works the form one step at a
time:

1. **Read** the step with pagecomp, through `FormPagePort`
   (`adapters/secondary/perception/pagecomp_form.py`): the application form,
   its questions, whether each is required (with the evidence), traps, the
   Next/Submit buttons, the declared language and the step position. AA's
   multilingual words are then applied (`form_localization.localize_step`,
   [ADR-025](../adr/025_forms_in_any_language.md)), including any choice
   limit ("pick the best 2"). Every control is read back live, so only what
   is visible on *this* step is worked. A page that is a test (a timer, a code
   editor, or an assessment site) is never worked: it is handed to the person
   or the application stops as `ASSESSMENT`; links to assessments and other
   required steps are recorded, never followed
   ([ADR-026](../adr/026_answer_review_and_external_steps.md)).
2. **Upload first.** The résumé goes in before anything is typed; the engine
   waits until the controls stop changing (a site's résumé parser) and reads
   the step again. Values already present are kept.
3. **Each question in page order:** a short reading pause, an answer from the
   configured sources, one decision by the fill policy
   (`domain/applications/fill_policy.py`), the act through the shared
   interaction tool, and a read-back that proves the value took. Each filled
   answer is marked if the person asked to see it first (trust and timing,
   [ADR-026](../adr/026_answer_review_and_external_steps.md)); with `each`
   timing they are asked at once, with `page` before AA moves on.
4. **Conditional questions.** After a choice that can reveal or withdraw
   questions, a cheap census of visible controls decides whether to read the
   step again.
5. **Ask** for what AA cannot answer — only when asking is allowed — while
   the browser shows the page the questions are on, with the keyboard focus on
   the first one. The person answers in the browser and chooses "done", or, if
   they chose to, answers in AA's own window and AA enters and checks it
   ([ADR-024](../adr/024_accessibility_accommodations.md)).
6. **Advance** with Next only when every question the reader marked required
   holds a value (a sweep catches ones revealed, swapped in or emptied along
   the way), and count it as progress only when the page proves it. A
   rejected step is read for the page's own messages; questions the reader
   could not recognise as required are left to that validation.
7. **Stop before submitting.** The engine never clicks a control that may
   submit: a button that may (pagecomp's `final`, a `submit` role, or submit
   words in any language), or a submit-type Next with no evidence that more
   steps follow, is
   clicked only when the person says "click it" (or chose autonomous
   submission). The workflow shows the submit gate with a summary (counts,
   the labels worth checking and the control it will click, never the
   answers) and clicks the engine's submit control only on "submit". A review
   page with nothing to answer is handled the same way.

### What the person controls

All in the `applications:` block of `runtime_defaults.yaml` (and the layered
settings above it):

| Setting | Default | Effect |
| --- | --- | --- |
| `form_engine` | `steps` | `legacy` runs the earlier page loop instead |
| `assist_mode` | `auto` | When AA may ask in the browser: `auto` (when you asked to review before submitting), `always`, `never` |
| `assist_timeout_s` | `900` | How long AA waits for an in-place answer |
| `review_each_step` | `false` | Pause after every filled step for a check |
| `remember_answers` | `true` | Reuse in-place answers for the rest of the session (memory only; an answer specific to one employer — open-ended, about "here"/"us", naming it — only for that employer) |
| `answer_sources` | session, profile, saved, generated | Where answers come from, in order |
| `generated_answers` | `false` | Let the local text model draft open answers (always flagged for review) |
| `legal_answers` | `profile` | `ask` keeps work-authorisation and sponsorship questions for you |
| `overwrite_prefilled` | `false` | Replace values a site or extension already put in |
| `acknowledge_required` | `true` | Tick a required "I certify / I agree" box (optional boxes are never ticked) |
| `script_fill_fallback` | `true` | Set a value by script, recorded, when typing did not take |
| `min_answer_confidence` | `0.75` | Answers below this are not used |

How AA works with the person — time limits (`1x` to `20x`, or `off`),
answering in AA's window, keyboard focus, terminal output for screen readers
— is the `accessibility:` block
([ADR-024](../adr/024_accessibility_accommodations.md),
[the user guide](../user_guide/accessibility.md)); `assist_timeout_s` is the
standard wait that the time-limit setting scales.

The interrupt policy's checkpoints still apply: `BEFORE_FORM_SUBMIT` (the
gate), `ON_LOW_CONFIDENCE_FIELD` (turns `auto` assistance on), and
`ON_AMBIGUOUS_SUBMISSION` (after submit, when the page does not clearly
confirm, AA asks what you see and records your answer as yours).

### Working alongside other tools

- **Browser extensions and the person.** A value already in a field is kept
  and counted (`prefilled_kept`); a form an autofill extension completed is
  offered for submission like any other.
- **Other answer sources** (a saved-answers store, an LLM, an AI assistant)
  plug in as `AnswerSourcePort` implementations; the policy and read-back
  apply to them unchanged, and they never decide submission.
- **Other readers** (another page-understanding library, an AI browser's
  reading) can implement `FormPagePort`.
- **Research.** One record per step goes to the research observer, and the
  evidence carries counts only: steps, assisted answers, kept values, traps
  left, fill failures, validation problems met, answer provenance and fill
  method.

### Footprint

Trusted input through the interaction tool, human pacing from the same tool,
a reading pause per question, and no page mutation: no injected styles, no
value set by script unless typing failed (and then recorded). One known
exception is tracked as a problem: the reader's change probe leaves a global
the page can see (`window.__pcMut`); moving it to an isolated world is open
work. AA does not
solve CAPTCHAs, never types a password, and never signs in or creates an
account; those steps are handed to the person in the browser window.

## The Scan‑Plan‑Act Loop

The engine’s core is a bounded loop that repeats up to `MAX_STEPS` (default
15) times. Each iteration has three phases:

```
┌──────────────────────────────────────────┐
│               SCAN (Perceive)            │
│  • Classify page state (get_current_state)│
│  • Build DOM snapshot (scan_page)        │
├──────────────────────────────────────────┤
│               PLAN (Reason)              │
│  • Analyse UIModel + UserProfile         │
│  • Generate InteractionPlan              │
│  • Check HITL policy for this step       │
├──────────────────────────────────────────┤
│               ACT (Execute)              │
│  • Execute the InteractionPlan           │
│  • Apply human-like timing               │
│  • Wait for DOM to settle                │
└──────────────────────────────────────────┘
         │
         ▼
   (next iteration)
```

The `MAX_STEPS` safety breaker prevents infinite loops on complex or broken
forms. If the engine reaches the step limit without reaching a terminal
state, it logs a timeout and returns failure.

---

## Page Classification via Finite State Machine

Before scanning for form fields, the engine first asks the perception port
to **classify** the current page. The `PerceptionPort.get_current_state()`
method returns an `ApplicationState` enum value — one of 17 possible states.

### The ApplicationState Enum

```python
class ApplicationState(Enum):
    UNKNOWN = auto()
    INITIAL_START = auto()           # "Apply" / "Easy Apply" button visible
    LOGIN_WALL = auto()              # Forced login required
    FORM_STEP = auto()               # Active inputs present
    UPLOAD_STEP = auto()             # File upload field is primary focus
    REVIEW_STEP = auto()             # "Review your application" screen
    MODAL_OPEN = auto()              # A modal/dialog is blocking the form
    REDIRECT_TO_CAREERS_PAGE = auto()# Landed on a company careers listing
    REDIRECT_TO_LIST = auto()        # Multiple job cards visible
    INDEED_TAB_SWITCHED = auto()    # Indeed: job-list tab active
    SUBMITTING = auto()              # Spinner / loading state
    AWAITING_HUMAN = auto()          # Paused for user approval
    SUCCESS = auto()                 # "Application sent"
    ERROR = auto()                   # Validation errors visible
    ALREADY_APPLIED = auto()         # "You applied on..."
    CLOSED = auto()                  # "No longer accepting applications"
    CRITICAL_FAILURE = auto()        # Unrecoverable technical error
```

Every transition between states is validated against a
`VALID_APPLICATION_TRANSITIONS` table. Terminal states — `SUCCESS`, `CLOSED`,
`ALREADY_APPLIED`, `REDIRECT_TO_LIST`, `REDIRECT_TO_CAREERS_PAGE`, and
`CRITICAL_FAILURE` — have **no outgoing transitions**. The engine detects
these states and immediately returns the appropriate result to the
orchestrator.

### How Classification Works

The perception adapter (Math, BS4, or DOM) implements the classification
logic. It analyses:

- **Visible text** — keyword matching against known success, error, and login
  phrases.
- **DOM structure** — presence of modals (`role="dialog"`), multiple job cards
  (indicating a redirect to a listing page), file upload inputs (indicating an
  upload step).
- **ARIA roles** — `role="alert"` for error messages, `role="progressbar"`
  for loading states.

The engine dispatches on the returned enum value — it does not know how the
classification is performed.

---

## Phase 1: SCAN — Building the Page Snapshot

If the current state is actionable (not terminal), the engine calls
`perception.scan_page()` to produce a `UIModel` — a complete snapshot of
every interactable element on the page.

```python
UIModel(
    url="https://jobs.acme.com/apply/123",
    title="Acme Corp — Application",
    elements=[
        UIElement(id="input-1", element_type=TEXT_INPUT, label="First Name", ...),
        UIElement(id="input-2", element_type=TEXT_INPUT, label="Last Name", ...),
        UIElement(id="input-3", element_type=FILE_UPLOAD, label="Resume/CV", ...),
        UIElement(id="btn-1",   element_type=BUTTON,      label="Submit", ...),
    ]
)
```

Each `UIElement` carries:

- **Semantic data:** the human‑readable label, placeholder text, element type,
  whether it is required, and available options (for selects and radios).
- **Constraints:** a validation pattern (regex), min/max values.
- **Technical reference:** a live DOM element reference (attached privately)
  that the interaction port can use to click, type, or upload.

The `UIModel` is a plain Python object — it contains no live browser
references in its serialisable fields. This means it can be logged, cached,
and reasoned about without holding a browser session open.

---

## Phase 2: PLAN — From Page Snapshot to Action Sequence

The `UIModel` is passed to the `ReasoningPort.devise_plan()` method, which
returns an `InteractionPlan` — an ordered list of `PlannedAction` objects.

### How the Solver Works

The `FormSolver` (the default implementation) uses a **semantic matching**
approach:

1.  **Flatten the user profile** into a dictionary of semantic key → value
    pairs. For example, `"first name"`, `"given name"`, and `"forename"` all
    map to `profile.personal_info.first_name`.
2.  **For each UIElement**, compare its label against every key in the
    flattened profile using `TextMatcher.find_best_match()`.
3.  **If the match score exceeds 0.75**, create a `PlannedAction` with the
    appropriate value and interaction type (TYPE, SELECT_OPTION, UPLOAD_FILE,
    CLICK).
4.  **If no match is found**, the field is skipped for standard filling and
    may be picked up later by the custom‑answer generation step.
5.  **Special‑case handlers** handle checkboxes (consent, terms), radio
    buttons, and file uploads using keyword detection on the label.
6.  **A submit button** is identified by keyword matching on button labels
    (`"submit"`, `"apply"`, `"send"`) and appended as a critical CLICK action.

The solver returns a complete `InteractionPlan`:

```python
InteractionPlan(
    goal_description="Fill Application Form: Acme Corp — Software Engineer",
    actions=[
        PlannedAction(target="input-1", type=TYPE, value="Jane",
                      reasoning="Matched 'First Name' → profile key 'first_name' (0.98)"),
        PlannedAction(target="input-2", type=TYPE, value="Doe",
                      reasoning="Matched 'Last Name' → profile key 'last_name' (0.98)"),
        PlannedAction(target="input-3", type=UPLOAD_FILE, value="/home/jane/resume.pdf",
                      reasoning="Detected Resume upload field."),
        PlannedAction(target="btn-1",   type=CLICK,
                      reasoning="Detected primary submission button."),
    ]
)
```

### Pluggable Reasoning Backends

The `ReasoningPort` abstraction allows different reasoning engines to be
injected:

| Backend | How It Works | Use Case |
| ------- | ------------ | -------- |
| `FormSolver` (default) | Semantic matching via `TextMatcher` | Everyday forms — fast, deterministic, no dependencies. |
| `ClingoFormSolver` | Answer Set Programming via `clingo` | Complex forms with logical constraints — requires `clingo` to be installed. |
| Future: LLM‑based | Prompt an LLM with the full UIModel | Most flexible; requires large model. |

The engine calls `solver.devise_plan(ui_model)` and receives an
`InteractionPlan` regardless of which backend is active.

---

## Phase 3: ACT — Executing the Plan

The `InteractionPlan` is passed to the `InteractionPort.execute_plan()`
method, implemented by `InteractionExecutor`.

### Execution with Human‑like Timing

The executor iterates through each `PlannedAction` and dispatches it to the
appropriate handler:

| Action Type | Handler | Behaviour |
| ----------- | ------- | --------- |
| `TYPE` | `TextInputHandler` | Clears existing text (triggers React events), then types character‑by‑character with parabolic delays. |
| `SELECT_OPTION` | `SelectInputHandler` | For native `<select>`: matches options semantically. For custom comboboxes: clicks to open, types partial keyword, selects best match. |
| `UPLOAD_FILE` | `FileInputHandler` | Validates file exists, locates hidden `<input type="file">`, forces visibility, sends path. |
| `CLICK` | via `PageActionService` | The click ladder: probe, then a trusted pointer click on a planned curved path to a sampled off‑centre point; keyboard, native and (config‑gated, never on submits) JS rungs behind it. |
| `CHECK` (checkbox) | `CheckableInputHandler` | Checks current state, clicks only if needed to reach the desired state. |

Every action is wrapped with **micro‑timing** (parabolic pauses) and
**macro‑timing** (inter‑action delays of 0.3–1.2 seconds). The executor
never calls `element.click()` directly — `InteractionExecutor.click()`
delegates to `PageActionService`, which owns the mouse path, the settle
pause and the seeded RNG.

> **Status (Stage 1).** Clicking and inter‑step pacing route through the
> tool. The two `execution_strategies` classes (`StealthHumanStrategy`,
> `InstantHeadlessStrategy`) are **not** yet constructed by anything —
> `InteractionExecutor.strategy` is assigned and never read. They are
> scheduled to become the tool's two injected timing profiles; until then
> the tool's own config‑driven timing applies and there is no "active
> execution strategy" to select.

**Submission is gated.** The submit click cannot fire unless submission is
explicitly authorised — either the user's `human_review_checkpoints` omits
`BEFORE_FORM_SUBMIT`, or a wired approval gate returned the approval token.
Anything else records `SUBMISSION_GATE_BLOCKED` and does not click. See
[ADR‑012](../adr/012_fail_closed_submission_gate.md).

### Error Recovery

If a non‑critical action fails (e.g. a field is missing or a click is
intercepted), the executor logs the failure and **continues** with the
remaining actions. If a critical action fails (e.g. the submit button cannot
be found), the entire plan is aborted. This prevents AA from submitting a
partially‑filled form.

---

## Human‑in‑the‑Loop Checkpoints

Even with perfect planning, some decisions should not be made without the
user’s consent. AA integrates **Human‑in‑the‑Loop (HITL)** via the
`InterruptPolicy` port.

### How It Works

After the plan is generated — and before it is executed — the engine
evaluates two checkpoints:

1.  **`BEFORE_FORM_SUBMIT`:** If the plan contains a click on a submit button
    (detected by keyword matching on the button’s label), the engine checks
    the interrupt policy. If the policy says to pause, the engine:
    - Publishes `HUMAN_APPROVAL_REQUESTED` on the EventBus.
    - Blocks on a threading gate until the user responds.
    - The GUI or CLI presents a modal/prompt:
      *“About to submit your application to Acme Corp for Software Engineer.
      Approve, skip this job, or stop the session?”*

2.  **`ON_LOW_CONFIDENCE_FIELD`:** If any planned action has a confidence
    score below 0.6, the engine pauses and asks the user to review that
    specific field.

3.  **`ON_SUSPICIOUS_REDIRECT`:** If the page redirects to an unexpected URL
    mid‑application (e.g. a job listing page instead of a form confirmation),
    the engine pauses. The user can choose to treat the redirect as a new
    discovery task, skip the job, or stop the session.

The default policy (`ProfileBasedInterruptPolicy`) pauses at
`BEFORE_FORM_SUBMIT` and `ON_SUSPICIOUS_REDIRECT`. Users can customise this
in their profile (`app_config.human_review_checkpoints`), or disable all
checkpoints for fully autonomous runs.

### Timeout Handling

If the user does not respond within 5 minutes, the engine automatically
skips the job. This prevents a session from hanging indefinitely if the user
walks away.

---

## Handling Open‑Ended Questions

The most difficult part of any form is the **custom question** — “Tell us
about a project you’re proud of,” “Why do you want to work here?” AA answers
these using a three‑tier intelligence system:

### Tier 1: GPT4All (Local LLM)

If the `[ai]` extra is installed and the machine has sufficient RAM, AA sends
a prompt to GPT4All:

```
Given this work experience:
[User's most relevant work description]

Answer this job application question naturally, concisely, in first person
(2-3 sentences max):
"Tell us about your proudest technical achievement."
```

The model generates a custom answer. This is the most human‑like result, but
requires ~6 GB RAM and a 4.7 GB model download.

### Tier 2: SpaCy Similarity

If GPT4All is unavailable, AA uses SpaCy to find the most semantically
relevant paragraph from the user’s work experience and pastes it as the
answer. It’s not generated, but it’s still a real answer written by the
user — just selected algorithmically.

### Tier 3: Career Summary Fallback

If neither GPT4All nor SpaCy is available, AA uses the user’s
`career_summary` as a generic answer. This is the least targeted, but it
works on any hardware with zero extra dependencies.

---

## Multi‑Page Form Navigation

Many enterprise ATS platforms (Workday, Taleo, iCIMS) present applications
as multi‑step wizards. AA handles these automatically:

1.  After filling the current page, AA scans for **Next / Continue** buttons
    using a keyword list (`"next"`, `"continue"`, `"save and continue"`,
    `"proceed"`).
2.  If a next button is found, AA clicks it and waits for the DOM to
    stabilise.
3.  The loop restarts — the page is re‑classified, re‑scanned, and the next
    page’s fields are filled.
4.  If no next button is found, AA assumes the current page is the final
    review step and proceeds to submission.
5.  A `MAX_PAGES` limit (default 10) prevents infinite navigation on
    malformed wizards.

---

## Reaching the Form: the Apply Route

Discovery hands the engine job‑board postings far more often than employer
URLs — in the measured live runs, every vetted job. `_navigate_to_application`
therefore runs a bounded route rather than assuming `job.url` is a form:

1.  If vetting recorded an off‑host apply target in `metadata["apply_url"]`
    (learned while vetting was already reading the posting), navigation
    starts there — the posting is never reloaded.
2.  Otherwise the posting is loaded and its apply controls are searched
    across every actionable element shape (`<a>`, `<button>`,
    `input[type=submit|button]`, `[role=button]`), read by accessible name
    (rendered text, then `value`, `aria-label`, `title`). An off‑host `<a>`
    href is followed **by navigation** — deterministic, and the hop is
    recorded. A target‑less button is **clicked**, after which a new tab is
    followed via the wired `ContextManager`, a JS navigation is honoured,
    and an authentication dialog ends the route.
3.  Every landing page is checked by the two challenge verdicts in
    `domain/services/challenge_assessment.py`: a presented challenge pauses
    in place (a human solve continues the route); a whole‑page login wall
    before any form ends the route.

**Outcomes.** A route that demands an account records `ACCOUNT_REQUIRED`
(an authentication dialog, or a login wall before any form) and fills
nothing. A route that loops or exceeds the hop bound
(`applications.max_apply_hops`, default 3) records `FAILED_NAVIGATION` with
the reason — never a hang. A page with no route at all is attempted as‑is,
preserving the previous behaviour for direct form URLs.

**Evidence.** Every attempt records `posting_host`, `apply_target_host`,
`landed_host`, `apply_route_hops`, and `ats_platform` matched on the
**landed** URL — the hiring‑friction record of how many hops, through whom,
stand between a job seeker and the employer's form.

There are no site‑specific host lists or selectors anywhere in this path;
`tests/architecture/test_apply_route_wiring.py` asserts it structurally.

---

## File Uploads

AA handles resume and cover letter uploads intelligently:

- If the form asks for a **file** (detected by `input[type="file"]` and the
  label text), AA uploads the file at the path specified in the user’s
  profile.
- If the form asks for a **text** cover letter (a `<textarea>` labelled
  “Cover Letter”), AA pastes the text content of the user’s cover letter
  field.
- If the user’s profile has a path to a cover letter file, AA uploads it
  when a file upload field for a cover letter is detected.

---

## Post‑Submission Analysis

After clicking Submit, AA does not simply assume success. It waits for the
confirmation page to load and then:

1.  **Verifies success** — scans for keywords like “application submitted,”
    “thank you for applying.”
2.  **Extracts cooldown periods** — if the confirmation page says “apply again
    in 6 months,” AA parses this and stores it in the company’s history
    record. The `ThrottlingFilter` will use this on future sessions.
3.  **Detects “keep on file” language** — phrases like “we will keep your
    application on file” are treated as a 180‑day cooldown.
4.  **Records the outcome** — the job is marked as `APPLIED` or `FAILED` in
    the persistent database, ensuring it is never double‑applied.

The outcome ladder: a confirmation phrase or confirmation address is
`SUBMITTED`; otherwise, a page that moved off the form's own address (host
and path, compared with the address at the moment of the click) is
`PROBABLY_SUBMITTED`; otherwise `AMBIGUOUS`. The first live run
(2026-11-26) compared against `job.url` instead, which for jobs found
through a search engine is a redirect link: every click read as "probably
submitted". One INFO line records what was seen after the click (hosts and
paths only, the page kind, any confirmation phrase), and one INFO line per
form page records what the engine read (question words, kinds,
requiredness, options, buttons; never a value), so a live run can be judged
from its log (`describe_step`, `tests/workflows/test_submission_verdict.py`).

---

## Graceful Degradation

The Application Engine is designed to work in every tier:

| If … | AA will … |
| ---- | --------- |
| No browser is available | AA refuses to build the session (`BrowserSetupError`) — static mode was removed (ADR‑013); a pretend session is worse than an honest refusal. |
| No `InteractionPort` is available | Classify and plan, but skip execution. Useful for dry‑run analysis. |
| No `ReasoningPort` (rare) | Log an error and abort — the engine requires a planner. |
| GPT4All not installed | Use SpaCy similarity for custom answers (Tier 2). |
| SpaCy not installed | Use career summary for custom answers (Tier 3). |
| File paths in profile are broken | Log a warning and skip the upload field. The engine continues. |
| A form step takes more than 15 iterations | Safety circuit breaker activates; the engine times out gracefully. |

---

## Architecture Integration

The engine is completely decoupled from browser automation, DOM parsing, and
user interface:

```python
# Composition root (simplified)
engine = ApplicationEngine(
    perception_port=MathPerceptionAdapter(driver),   # or BS4, or DOM
    interaction_port=InteractionExecutor(driver, page_action=page_action),
    reasoning_port=FormSolver(profile),
    event_bus=event_bus,
    interrupt_policy=ProfileBasedInterruptPolicy(checkpoints),
)
# approval_gate is wired post-construction by SessionController
```

The engine receives its ports at construction time. The orchestrator calls
`engine.run(job)` and receives a boolean — `True` if the application was
submitted, `False` otherwise. The engine never manages browser lifecycle,
never touches the work queue, and never knows whether it is being run from
a GUI or a terminal.

---

## Summary

The Application Engine transforms a job URL and a user profile into a
submitted application through a rigorous, state‑driven pipeline:

1.  **Classify** the page via the perception port.
2.  **Scan** for interactable elements.
3.  **Plan** a sequence of actions using semantic matching.
4.  **Check** human‑in‑the‑loop policy before critical actions.
5.  **Execute** the plan with human‑like timing.
6.  **Navigate** multi‑page wizards automatically.
7.  **Handle** open‑ended questions using the best available AI tier.
8.  **Submit** and analyse the confirmation for cooldown extraction.

Every step is pluggable, testable, and degradable — the engine works on any
hardware, with any browser, for any user.

---

## Next Steps

- [Core Abstractions](core_abstractions.md) — the `PerceptionPort`,
  `ReasoningPort`, and `InteractionPort` contracts that make the engine
  framework‑agnostic.
- [Vetting Pipeline](vetting_pipeline.md) — what happens before a job
  reaches the Application Engine.
- [ADR‑005: Human‑in‑the‑Loop](../adr/005_human_in_the_loop.md) — the
  design of the interrupt policy and approval gate.
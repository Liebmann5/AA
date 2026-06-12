# Glossary

This page defines the key terms and acronyms used throughout the AutoApply
documentation and source code.  If a term you encounter is missing, please
open an issue on [GitHub](https://github.com/Liebmann5/AA/issues) and we
will add it.

---

## A

### Adapter
A concrete implementation of a **Port**.  Adapters translate between the
abstract domain and the outside world.  A `SeleniumAdapter` implements
`BrowserInterface` by translating its methods into Selenium WebDriver
commands.  Adapters live in `adapters/` and are wired to ports in the
**Composition Root**.

### Admin Policy
A JSON file (`aa_policy.json`) that locks down AA’s behaviour on shared
or institutional machines.  It can restrict allowed browsers, enforce
headless mode, set minimum delays, and disable research collection.  The
policy is read at startup and enforced automatically.

### AgentState
A 14‑state enum (`IDLE`, `RUNNING`, `DISCOVERING`, `APPLYING`, `PAUSED`,
etc.) that governs the entire AA session.  The **State Machine** ensures
only valid transitions are made, preventing impossible program states.

### AOM (Accessibility Object Model)
A semantic representation of a webpage intended for assistive technologies
(screen readers).  AA can query the AOM to find form fields by their
accessible role and name, bypassing fragile CSS selectors.

### Application Engine
The component that fills out and submits a single job application form.
It uses a **Scan‑Plan‑Act** loop and an **ApplicationState** FSM to
navigate multi‑page wizards, fill fields, and handle errors.

### ApplicationState
A 17‑state enum (e.g. `FORM_STEP`, `REVIEW_STEP`, `SUCCESS`, `LOGIN_WALL`)
that classifies the current page of an application form.  The **Application
Engine** dispatches actions based on the current state.

### ATS (Applicant Tracking System)
Software used by employers to manage job applications.  Examples:
Greenhouse, Lever, Workday, Taleo, iCIMS.  AA uses an **ATS Registry**
to identify which platform a job is hosted on and apply platform‑specific
form‑filling strategies.

### ATS Registry
A YAML‑driven registry (`ATSRegistry`) that loads ATS descriptors from
`resources/ats/*.yaml` and matches job URLs to known platforms.

---

## B

### Browser Cascade
The fallback system (`BrowserCascade`) that tries multiple browser
automation tools in priority order until one succeeds.  The cascade
attempts Playwright’s bundled browsers first, then Selenium with OS
browsers, and finally falls back to static HTML if nothing works.

### BrowserInterface
The core **Port** that abstracts a web browser.  Every browser automation
tool (Selenium, Playwright, etc.) is wrapped in an **Adapter** that
implements this interface.

---

## C

### Checkpoint
A point in the application pipeline where AA pauses and asks the user for
approval before proceeding.  Default checkpoints are
`BEFORE_FORM_SUBMIT` and `ON_SUSPICIOUS_REDIRECT`.  Users can customise
which checkpoints are active.

### Composition Root
The single file (`infrastructure/composition_root.py`) where all concrete
**Adapters** are instantiated and injected into the application.  It is
the only place that may import from both `adapters/` and `domain/`.

### Constructor Injection
A form of **Dependency Injection** where all dependencies are passed via
a class’s constructor.  AA uses this pattern exclusively — no class
constructs its own collaborators.

---

## D

### Dependency Injection (DI)
A design pattern where a component receives its dependencies from the
outside rather than creating them internally.  See **Constructor
Injection** and **Composition Root**.

### Discovery Engine
The component that searches for job listings across multiple **Providers**
(Google, Bing, Indeed, company careers pages) and returns deduplicated
`Job` objects.

### Domain
The innermost architectural layer.  Contains pure business logic: models,
ports, vetting filters, and mathematical services.  The domain has no
imports from `adapters/` or `infrastructure/`.

### DriverProvider
A **Protocol** that defines how a specific browser automation tool
(Selenium, Playwright, etc.) is launched and shut down.  Each tool has
its own `Provider` class.

---

## E

### EventBus
A thread‑safe publish‑subscribe message bus.  Components communicate by
publishing **Events**; other components subscribe to the events they care
about.  The bus decouples producers from consumers.

### Event
A named occurrence in the system, defined by the `Event` enum (e.g.
`APPLICATION_SUBMITTED`, `BROWSER_UNHEALTHY`).  Events carry a payload
dictionary with relevant data.

### Evasion Framework
The multi‑layered system that prevents job boards from detecting AA as
a bot.  Layers include fingerprint hardening, behavioural humanisation,
session integrity, and CAPTCHA handling.

### ExecutionContext
A volatile session‑state container that holds the user profile, live
statistics (jobs discovered, applied, failed), and the current work
unit.  Passed to every engine and service that needs session awareness.

---

## F

### FSM (Finite State Machine)
A model of computation where the system is always in exactly one of a
finite set of states, and transitions between states are governed by
explicit rules.  AA uses two FSMs: **AgentState** for the session and
**ApplicationState** for per‑form page classification.

---

## G

### Graceful Degradation
The ability of AA to continue functioning (at reduced capability) when
optional dependencies or hardware resources are unavailable.  Examples:
SpaCy → `difflib` fallback, GPT4All → SpaCy similarity → career summary,
Playwright → Selenium → static HTML.

---

## H

### Hexagonal Architecture
Also called Ports & Adapters.  An architectural pattern where the
business logic (domain) is at the centre, and all external interactions
(browser, database, UI) are handled by interchangeable adapters that
implement abstract ports.  AA is organised into four concentric layers:
domain, application, adapters, infrastructure.

### HITL (Human‑in‑the‑Loop)
The system that pauses AA at critical moments and requires explicit
user approval before proceeding.  See **Checkpoint** and **Interrupt
Policy**.

### Hungarian Algorithm
A combinatorial optimisation algorithm that solves the assignment
problem in O(n³) time.  AA uses it to optimally pair form input
elements with their corresponding label elements based on spatial
proximity and DOM tree distance.

---

## I

### Interrupt Policy
A pluggable policy (`InterruptPolicy`) that decides whether AA should
pause at a given **Checkpoint**.  Concrete implementations:
`ProfileBasedInterruptPolicy` (reads user settings),
`NeverInterruptPolicy` (fully autonomous),
`AlwaysInterruptPolicy` (maximum oversight).

---

## O

### Orchestrator
See **AgentOrchestrator**.  The central controller that manages the
entire session lifecycle: dequeues tasks, dispatches them to engines,
handles errors and retries, and coordinates health monitors.

---

## P

### Port
An abstract interface defined in `domain/ports/` that describes a
capability the domain needs.  Examples: `BrowserInterface`,
`PerceptionPort`, `JobRepositoryPort`.  Ports are implemented by
**Adapters**.

### Provider
A concrete class that implements `DiscoveryProviderPort` and knows
how to search for jobs on a specific platform (e.g. `GoogleProvider`,
`BingProvider`).

### PRA Loop
**Perceive‑Read‑Act loop.**  The core cycle of the **Application
Engine**: classify the page state, validate the transition, dispatch
the correct action.  Bounded by a safety circuit breaker (`max_steps`).

---

## R

### Research Module
The optional, consent‑gated subsystem that records anonymised hiring
market signals.  Data is stored locally in a CSV file and contains no
personally identifiable information.

### ResilientDriver
A decorator that wraps any `BrowserInterface` adapter and adds
automatic popup dismissal, iframe‑traversal search, and health checks.

---

## S

### Scan‑Plan‑Act Loop
See **PRA Loop**.

### State Machine
See **FSM**.

---

## T

### Throttling
The system that enforces rate limits on job applications.  AA records
application history per company and blocks further applications during
a cooldown period (default 180 days).

### Two‑Way Fit
The principle that a job must be a fit for the user AND the user must
be a fit for the job.  The **Vetting Pipeline** enforces this on every
job before it is approved for application.

---

## V

### Vetting Pipeline
The composable filter chain (Throttling, Location, Title, Skills, etc.)
that evaluates each discovered job against the user’s profile.  Jobs
that fail any filter are rejected.

---

## W

### Work Unit
An atomic task in AA’s priority queue.  Each work unit has a type
(`DISCOVER`, `VET`, `APPLY`, `HANDLE_CAPTCHA`), a priority, and a
payload.  The **Orchestrator** dequeues and dispatches them.

### Worst‑Case First
AA’s overriding design principle.  Every feature must work on the
weakest target machine (2 GB RAM, library computer, no admin rights).
Richer tiers (SpaCy, GPT4All) are optional upgrades, not requirements.

---

*If a term is missing, please [open an issue](https://github.com/Liebmann5/AA/issues) so we can add it.*
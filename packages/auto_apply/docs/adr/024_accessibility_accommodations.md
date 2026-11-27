---
title: "ADR-024: Accessibility Accommodations — How AA Works With Every Person"
status: needs-review
last_verified: 2026-11-21
verified_against: "domain/services/person_time.py, domain/applications/form_barriers.py, application/services/session_controller.py (request_approval, stop), application/services/hitl_gate.py, application/services/form_engine.py (answer_in_aa, focus), application/services/accessibility.py, infrastructure/os_accessibility.py, adapters/primary/cli/dashboard.py, adapters/primary/gui/dashboard.py, adapters/primary/gui/settings_editor.py, adapters/primary/cli/profile_wizard.py; tests listed under Verification (local fixtures and unit pins only)"
audience: contributors
---

# ADR-024: Accessibility Accommodations — How AA Works With Every Person

**Status:** Proposed — built and pinned; not yet used by a person who relies on
assistive technology, and not yet proven on live sites `[BUILT]`
**Date:** 2026-11-21
**Deciders:** Nicholas Liebmann
**Related:** [ADR-005](005_human_in_the_loop.md) (the questions AA asks),
[ADR-012](012_fail_closed_submission_gate.md) (unchanged),
[ADR-018](018_layered_settings_and_motion_profile.md) (the settings pattern
reused here), [ADR-023](023_application_step_engine.md) (the engine these
accommodations live in), [ADR-025](025_forms_in_any_language.md) (the
language half of the same work), [ENGINEERING_PHILOSOPHY](../ENGINEERING_PHILOSOPHY.md)

---

## Context

ENGINEERING_PHILOSOPHY makes the worst-situated user the baseline and names
accessibility an architectural concern, not a feature. AA stands between a
person and the application forms of thousands of employers. Two things follow.

1. **AA must itself be usable** by a person who reads with a screen reader,
   magnifies the screen, works from the keyboard or a switch alone, needs more
   time, or is best served by plain language one question at a time.
2. **AA can remove barriers the forms put up.** An employer's custom dropdown
   that a screen reader cannot operate is still a dropdown AA can operate; the
   person only has to say which option they mean.

What AA had before this decision:

* every question to the person waited a fixed time (300 s for the old gates,
  900 s for the engine's) and then moved on without them — a time limit AA
  imposes and the person could not change (WCAG 2.2 SC 2.2.1 Timing
  Adjustable, Level A, requires that they can: turn it off, adjust it over at
  least ten times the default, or extend it);
* the terminal dashboard cleared and redrew itself every second, and drew
  its prompts with box-drawing characters — hostile to a screen reader, which
  re-reads or loses its place in a redrawn terminal;
* a person asked to answer a question "in the browser window" had to find it
  there themselves;
* `application/services/accessibility.py` described a theme, a font scale and
  a screen-reader mode that **nothing read** (it was on the reachability pin's
  list of unreachable modules), and `AccessibilityPreferences` in the profile
  held three fields that nothing read either;
* the research record labelled every application form "AA" (WCAG AA
  conformant) because no check had ever run.

## Decision

### 1. Settings, never reasons — one source

AA stores the accommodations a person chooses, never why. Following the note
in `AccessibilityPreferences` ("rather than save them just ask users if they'd
like to implement any of these accessibility settings"), no field records a
disability, the CLI wizard and the GUI tab ask *how AA should work*, and a pin
(`test_the_answer_sources_never_read_accessibility_settings`) holds that no
answer source can read these settings: using a screen reader must never become
an answer to an application's disability question.

The settings follow ADR-018's input → resolution → resolved pattern:

| Setting (`accessibility.*`) | Default | What it does |
|---|---|---|
| `time_limits` | `1x` | How long AA waits for the person: `1x`, `3x`, `10x`, `20x`, or `off` |
| `answer_in_aa` | `false` | Offer the questions AA cannot answer in AA's own window |
| `focus_asked_field` | `true` | Put the browser's keyboard focus on a question AA asks about |
| `screen_reader_mode` | `false` | Terminal: no redraws, no box drawing, choices read in full |
| `reduced_motion` | `false` | No animation and no redraws |
| `high_contrast`, `font_scale` | `false`, `1.0` | AA's approval window colours and text size |
| `audio_challenge_hint` | `false` | Mention a challenge's audio option when AA hands one over |

Defaults live once, in `runtime_defaults.yaml` (mirrored in the registry's
fallback and parity-pinned). The person's choices live in their profile's
`AccessibilityPreferences`, where `None` means "use the default"; the profile
emits only what the person set and the registry folds it into the one
`accessibility` section. Both the GUI (a new **Accessibility** tab in the
settings editor) and the CLI (an **Accessibility** section in the profile
wizard) write the same fields — GUI and CLI parity, pinned by
`test_the_cli_wizard_writes_accessibility_settings_not_reasons`.

### 2. Time limits the person controls (WCAG 2.2 SC 2.2.1)

`domain/services/person_time.py` scales a wait by the setting, or removes it
(`off`). It is applied in **one** place: `SessionController.request_approval`,
the choke point every question to the person passes through — the submit
gate, CAPTCHA and sign-in hand-offs, the engine's form questions — so no
prompt can be missed. An unknown value is read as the standard limit, never
as "no limit": a typo must not make an unattended session wait for ever.

"Off" must never trap a session, so **stopping the session releases every open
question** (answered "skip", recorded as `AnsweredBy.STOPPED`). Every prompt
says up front how long AA will wait, or that it waits without a limit, in both
the CLI and the GUI (`ApprovalRequest.wait_s`).

AA offers WCAG's "turn off" and "adjust" options. The third option, "extend on
warning", is not built: a blocking prompt with a countdown would need a timer
in both interfaces, and either of the first two options satisfies the success
criterion.

### 3. The gate contract: nothing is ever abandoned

The round-3 review found that the old fallback for a gate without a `timeout`
parameter ran it on a worker thread and abandoned the thread when time ran
out — a prompt reading the terminal would then swallow the person's next
answer. `hitl_gate` now starts no thread at all. A gate must take `timeout`
(None meaning no limit) and keep the promise to return within it; the running
app's gate keeps it with an event the interface thread sets, and stopping sets
it too. A gate that cannot promise is not asked: the answer is "skip" and a
warning names the wiring fault.

### 4. Answering in AA's own window (`answer_in_aa`)

When AA cannot answer a question, the engine can offer it in AA's interface,
which the person can use, instead of the website's form, which they may not:

* a choice question (select, radio group, single checkbox) is asked with the
  form's **own options, exactly as worded**, plus "answer in the browser" and
  "skip";
* a free-text question takes a typed answer, when the gate can take one
  (`kind="text"`; the CLI reads a line, the GUI shows an entry field);
* AA enters the answer through the actuator and **reads it back**; an answer
  that did not take goes to the browser prompt;
* the answer is asked `private=True`: the controller never logs it and records
  only "answered" in the approval evidence;
* uploads, passwords, lists longer than 30 options and anything AA could not
  enter are left to the browser.

### 5. The person lands on the question (`focus_asked_field`)

When AA asks the person to answer in the browser, the actuator scrolls the
first such question into view through the interaction tool (the one place AA
scrolls a page) and gives its control the keyboard focus, so a screen-reader,
magnifier or keyboard user lands on it; the prompt says so. A radio drawn by a
styled label is scrolled to by its label and focused on its input.

### 6. Plain, located questions in the person's language

Every question the engine and the application workflow put to the person is
plain language from the locale bundles (`resources/locales/en.json`,
`es.json`; pinned complete for both): which step it is on ("step 2 of 4"),
which application, which question, whether it is required, and — when the form
is in another language than AA speaks to the person in — that the form is
written in that language and its questions are shown exactly as the form words
them (ADR-025). Approval options are protocol tokens; each interface shows
them through `i18n.option_label` and sends the token back.

### 7. AA's own windows

* **CLI** — in screen-reader or reduced-motion mode the dashboard never clears
  or redraws, prompts carry no box-drawing rules, and every choice is read in
  full ("Choice 1 of 3: Done"). The mode can be switched on for one run with
  `AA_SCREEN_READER=1` before any profile exists, and on Windows AA reads the
  operating system's screen-reader flag (`SPI_GETSCREENREADER`) as a hint —
  only when the person has not chosen either way, because Microsoft documents
  that some readers set it and Narrator does not.
* **GUI approval window** — text sized by `font_scale`, high-contrast colours,
  operable from the keyboard alone (Tab, Enter or Space, Escape to skip; focus
  starts on the first choice or in the answer field), and the typed-answer
  field.
* `application/services/accessibility.py` is now configured once per session
  from the resolved section and is reachable; its module docstring says which
  components read it and which do not yet.

### 8. Questions only the person answers — including accommodation requests

An employer may ask whether an applicant needs an accommodation for the hiring
process (the EEOC's guidance on pre-offer questions). Such questions, and
"reasonable adjustments" in UK usage, join the protected topics (ADR-025's
`protected` class, in every language). The engine now enforces the rule
**centrally** as well as inside each answer source: a protected question takes
an answer only from the person's own declaration (their profile's legal and
self-identification sections, their pronouns, or an answer they gave in this
session) — pinned by `test_an_accommodation_question_is_never_answered_by_a_source`.

### 9. Barriers on the forms, as research evidence

`domain/applications/form_barriers.py` turns what the reader already measured
into a fixed set of counted signals, each keyed by the WCAG 2.2 criterion it
bears on: no page language (3.1.1), unlabelled question (1.3.1/4.1.2),
placeholder-only label (3.3.2), required shown only visually (1.3.1),
personal-data field without an `autocomplete` purpose (1.3.5). They fill the
research pipeline's `wcag_violations` column (empty until now) and the
application evidence's `accessibility_signals`. They are **observations, not a
conformance verdict**: the research record's `wcag_score` now says `FINDINGS`
or `NO_AUTOMATED_FINDINGS` instead of `FAIL`/`AA`, and the research schema
version is 6 (rows at 5 or earlier hold "AA" there, which only meant no check
ran — `domain/constants.py`).

## Consequences

* A person can make every AA time limit ten or twenty times longer, or remove
  it, and can always stop.
* A screen-reader user has a terminal that does not fight their reader and a
  way to answer form questions without operating the employer's widgets.
* The research record can, for the first time, count exclusionary form design
  — always as observations with their method and limits stated.
* The UI port's `ApprovalRequest` grew three optional fields (`kind`,
  `private`, `wait_s`); the port's method set is unchanged.
* Two primary adapters now reach two presentation services (`i18n`,
  `accessibility`); the import ratchet records why
  (`tests/architecture/test_safety_pins.py`).

## Limits and open work

* **Tk and screen readers.** Tk gained screen-reader support only in 9.1
  (released 2026-09-29, TIP 733: `tk accessible`); before that, Tk widgets
  were largely invisible to screen readers. Which Tk a person's Python carries
  varies by platform and installer (the Python 3.12 that ran this work links
  Tk 9.0), and AA's GUI does not use Tk 9.1's accessibility interface yet. The
  CLI in screen-reader mode is the accessible path for a screen-reader user
  today, and the user guide says so.
* **The rest of the GUI** does not read the presentation settings yet (only
  the approval window does); the CLI profile wizard still draws box rules.
* **Two settings name the interface language**: `ApplicationConfig.locale`
  (read) and `AccessibilityPreferences.ui_language` (never read, default
  "en-US"). One must become the single source; recorded on the problem list.
* **Website time limits** (session expiry on an employer's form) are outside
  AA's control and not yet detected.
* **No person who relies on assistive technology has used this yet.** That is
  the proof this ADR waits for.

## Verification

Unit pins: `tests/domain/test_person_time.py`,
`tests/domain/test_form_localization.py` (barriers),
`tests/application/test_session_controller_gates.py`,
`tests/application/test_hitl_gate.py`,
`tests/application/test_form_engine.py` (answer in AA, focus, located prompts,
accommodation questions, unreadable states),
`tests/application/test_accessibility_language_pins.py`,
`tests/application/test_motion_settings.py` (wizard parity),
`tests/infrastructure/test_os_accessibility.py`,
`tests/adapters/test_activity_feed.py` (the CLI prompt). Real browsers:
`tests/integration/test_form_engine_browsers.py::test_round_three_adapter_edges`
(focus lands on the control).

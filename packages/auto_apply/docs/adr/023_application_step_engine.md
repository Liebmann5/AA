---
title: "ADR-023: The Application Step Engine — Read, Decide, Act, Verify, Advance"
status: needs-review
last_verified: 2026-11-21
verified_against: "application/services/form_engine.py, application/services/form_actuator.py, adapters/secondary/perception/pagecomp_form.py, domain/applications/, tests/application/test_form_engine.py, tests/integration/test_form_engine_browsers.py (Playwright and Selenium, local fixtures only)"
audience: contributors
---

# ADR-023: The Application Step Engine — Read, Decide, Act, Verify, Advance

**Status:** Proposed — built and pinned against local fixtures in both browser
adapters, revised after three rounds of independent code review (2026-11-21); not yet
proven on live sites `[BUILT]`
**Date:** 2026-11-21
**Deciders:** Nicholas Liebmann
**Related:** [ADR-003](003_pra_loop_and_state_machine.md) (the form half of its
loop, as now built), [ADR-005](005_human_in_the_loop.md) (checkpoints),
[ADR-012](012_fail_closed_submission_gate.md) (the submit gate, unchanged),
[pagecomp BLUEPRINT](../pagecomp/BLUEPRINT.md) (the reading)

## Context

In the owner's run of 2026-11-03, AA asked "Submit application?" over **zero
filled fields** on four of five links (problem E2E-A1; the prompt has since
been suppressed when nothing is filled, which hid the symptom, not the
cause). The page loop in
`ApplicationsWorkflow` scans with the older perception path, classifies labels
with a matcher, and fills through a semantic filler that was never given the
person's data in a usable shape; uploads went through a file handler the
composition root never built (`file_handler=None`). Every one of those pieces
had pins; none of them had ever filled a live form.

Meanwhile pagecomp (vendored, stdlib-only) already read forms well: form roots,
purpose, label pairing, requiredness with its evidence, traps, groups, the
Next/Back/Submit buttons and the conservative "this may submit" verdict
(CT-INV-004). It had no consumer on the application path.

## Decision

Forms are filled by a **step engine** in the application layer,
`application/services/form_engine.py`, with these properties. A change that
breaks one of them violates this decision.

1. **Reading is pagecomp's, through a port.** `FormPagePort`
   (`domain/ports/form_page_port.py`) returns one `FormStep` at a time (pure
   dataclasses in `domain/applications/form_model.py`) and reads controls back
   live. Its implementation, `adapters/secondary/perception/pagecomp_form.py`,
   resolves each control by its element path, through open shadow roots, with
   an identity check; it works over both browser adapters.
2. **Answers come only from what the person declared**, through
   `AnswerSourcePort` sources in a configured order: the person's answers
   earlier this session (memory only), the profile, their saved templates, and
   — only when turned on — drafts by the local text model, every one flagged
   for review. Protected answers (work authorisation, sponsorship,
   demographics, disability, age, criminal history) come only from the
   person's own declarations — the profile's explicit field or their answer
   in place — whatever the reader classified: `is_protected` checks the
   reader's flag, the canonical type and the question's own words, and every
   source and the acknowledgement rule ask it. Nothing is guessed. An answer
   that is specific to one employer — an open-ended question in any widget,
   a question about "here" or "us", anything naming the employer, long prose
   — is never reused for another.
3. **One pure policy decides each question**
   (`domain/applications/fill_policy.py`): never touch a trap, a hidden or
   disabled control; never type a password (a required one inside the form is
   the person's to type, in place); keep a value already present; tick a
   required acknowledgement that is not protected and leave every optional
   box unticked; fill a confident answer; ask for a required question with no
   answer; leave the rest.
4. **Every act goes through the shared interaction tool and is read back.**
   `form_actuator.py` types, picks options (native select, combobox, radio and
   checkbox groups, visually replaced inputs through their labels), uploads,
   and verifies each value on the page. Trusted input first; a script setter
   only when typing did not take, only when `script_fill_fallback` is on, and
   always recorded as such.
5. **Uploads first**, then a wait until the controls stop changing (the
   reader's settling rule behind `FormPagePort.quiet_detector`, bounded by
   wall clock and a read cap whatever it answers), then a fresh read: résumé
   parsers fill forms.
6. **Nothing required is left behind; progress is proven.** Before Next, a
   sweep makes every question the reader marked required — shown, enabled
   and still empty — unresolved, whatever left it so (revealed by the
   person's own answer, swapped in by a choice, beyond the per-step limit,
   emptied by the page). Which controls are shown is fingerprinted, not
   counted. A step counts as advanced only when the address changed, the form
   went away, or the set of visible questions changed; one that did not move
   is read for the page's own validation messages. A required question the
   reader could not recognise as required is left to the page's validation:
   `READY_TO_SUBMIT` means "every question AA knew to be required holds a
   value", never "the site will accept it".
7. **No submit without consent.** The engine clicks buttons only through
   `ControlActuator.click_button`, which refuses any button that may submit
   (`FormButton.may_submit`: pagecomp's conservative `final`, a `submit`
   role, or submit words in any language such as "Submit and continue",
   "Envoyer" — ADR-025) unless confirmed. A Next that is a submit
   button by type (`<button>` defaults to `type=submit`) is clicked only with
   evidence that more steps follow — the step position (`aria-current="step"`,
   or a "Step N of M" indicator in any language) with N < M, or a separate
   control on the step that says in words that it submits — otherwise it is
   treated as possibly the last button. A question of the form not shown yet
   is **not** evidence (round-3 review: a conditional question can be hidden
   on the last page too). What AA knows about its own click is recorded
   (`StepRecord.click`): a click the tool reports did not happen is never
   counted as progress, whatever the page then does; a click that raised
   mid-way may have happened and is never repeated. Such a control is
   clicked only when the person says "click it" at a `BEFORE_FORM_SUBMIT`
   question, or when they chose autonomous submission (no pre-submit
   review), exactly as the submit gate decides. The final submit is never
   clicked by the engine: it ends `READY_TO_SUBMIT` with the control it
   found (an unclassified last button is offered by its text, never dropped);
   `ApplicationsWorkflow` applies the unchanged fail-closed gate (ADR-012),
   with a summary of what AA did, what to check, and the control it will
   click. A step with no question after an advance is a review page, handled
   the same way. If a form disappears after a Next, the attempt is recorded
   `AMBIGUOUS` — the site may have taken it — never "nothing filled".
8. **The person is asked**, only when asking is allowed (`assist_mode`), for:
   answers AA does not have, a page that rejected a step, a sign-in or
   account step (AA never signs in or creates accounts), a review after each
   step (opt-in), and an unclear result after submit (opt-in,
   `ON_AMBIGUOUS_SUBMISSION`) — in the browser window, with the keyboard focus
   put on the first such question, or in AA's own window when the person
   chose that (ADR-024). Every question goes through `hitl_gate`: asked once
   (the gate's signature is inspected, never probed by a failing call),
   bounded by the gate's own promise to return within its timeout (the
   person's time-limit setting applies; no thread is ever started or
   abandoned — round-3 review), fail closed (no gate, an error, or an answer
   not offered means "skip"). A required question whose state could not be
   read is never treated as handled. A protected question takes an answer
   only from the person's own declaration, enforced in the engine as well as
   in each source.
9. **Evidence carries counts, never values**: steps, assisted answers, kept
   prefilled values, traps left, fill failures, validation problems met, answer
   provenance and fill method. One research record per step. Logs on the
   filling path carry an exception's type and code location, never its
   message.

The previous page loop stays selectable (`applications.form_engine: legacy`)
until it is retired (Track A slice S11).

## Options considered

- **Repair the existing page loop.** Rejected: its perception, matching and
  filling were three separate partial readings of the same page with no
  read-back; fixing each would have rebuilt pagecomp badly, inside the
  workflow.
- **An LLM agent that reads the page and decides every action.** Rejected as
  the default: non-deterministic, unverifiable for research, slow on the
  hardware AA targets, and it invents answers. The design leaves room for one
  as an answer source (`AnswerSourcePort`) or as another `FormPagePort`
  reader, never as the submit authority.
- **The accessibility tree as the reading.** Rejected by standing ruling (no
  AOM perception); pagecomp reads the DOM, including open shadow roots.
- **Setting values by script throughout.** Rejected: untrusted events,
  frameworks revert controlled inputs, and it is the most visible automation
  footprint. Kept only as a recorded fallback.
- **Per-site recipes** (selectors per applicant-tracking system). Rejected:
  the route stays host-agnostic (R-1); sites change and recipes rot.

## Consequences

Easier: one place decides what to do with a question; every action is
verified; the research record knows which step each question was on and how
each answer was made; another reader, answer source or browser can be added
behind a port.

Harder: closed shadow roots are unreachable; frames are opened as pages (one
recorded hop), never filled in place; question vocabulary covers the
languages in ADR-025, unreviewed by native speakers outside English; the
session memory is not saved between sessions (by design for now).

Cost: about 0.4–1.1 s per click and 0.9 s per short field with human timing
off on local fixtures, almost all of it the interaction tool's own waits.

## References

- Code: `application/services/form_engine.py`,
  `application/services/form_actuator.py`,
  `adapters/secondary/perception/pagecomp_form.py`,
  `domain/applications/` (form model, answers, option matching, fill policy),
  `domain/ports/form_page_port.py`, the step-engine path in
  `application/workflows/applications_workflow.py`, its construction in
  `infrastructure/composition_root.py`.
- Settings: the `applications:` block of `runtime_defaults.yaml`.
- Pins: `tests/domain/test_option_matching.py`,
  `tests/domain/test_application_answers.py`,
  `tests/application/test_form_engine.py`,
  `tests/workflows/test_step_engine_path.py`,
  `tests/infrastructure/test_form_engine_wiring.py`,
  `tests/integration/test_form_engine_browsers.py`,
  `tests/pagecomp/test_forms.py::test_lone_checkbox_takes_its_own_label`.

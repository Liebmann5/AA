---
title: "ADR-026: Answer Review, Tests and Required External Steps, Choice Limits"
status: needs-review
last_verified: 2026-11-26
verified_against: "domain/applications/answer_review.py, domain/applications/external_steps.py, domain/applications/selection_limits.py, domain/applications/form_localization.py, application/services/form_engine.py, application/workflows/applications_workflow.py (_authorize_submission), adapters/secondary/perception/pagecomp_form.py, application/services/choice_field.py, application/services/answer_settings.py; tests/domain/test_answer_review.py, test_external_steps.py, test_selection_limits.py, tests/application/test_answer_review_and_external_steps.py, tests/workflows/test_answer_review_gate.py, tests/integration/test_form_engine_browsers.py (Playwright and Selenium, local fixtures only)"
audience: contributors
---

# ADR-026: Answer Review, Tests and Required External Steps, Choice Limits

**Status:** Proposed — built and pinned against local fixtures in two real
browsers; not yet proven on live sites `[BUILT]`
**Date:** 2026-11-26
**Deciders:** Nicholas Liebmann
**Related:** [ADR-005](005_human_in_the_loop.md) (how a question reaches the
person), [ADR-012](012_fail_closed_submission_gate.md) (nothing is sent without
authorisation), [ADR-023](023_application_step_engine.md) (the engine),
[ADR-024](024_accessibility_accommodations.md) (time limits and answering in
AA), [ADR-025](025_forms_in_any_language.md) (the words these rules read)

---

## Context

Four gaps, all found by asking what AA does with a form that is not a plain
list of questions:

1. **Which answers may go out unseen.** AA fills answers from the profile,
   from answers the person saved, and (when allowed) from drafts. Until now
   the only control was the per-step review (`review_each_step`) and the
   pre-submit checkpoint — both about *pages*, neither about *answers*. A
   person who lets AA send applications without asking had no way to say
   "but show me anything you wrote for me", and a person who reviews every
   page had no way to say "my own saved answers are fine".
2. **Tests.** Some application flows contain an assessment: a timed page, a
   code editor, a link to a testing platform with "applications without it
   will not be reviewed". AA must never take a test for a person, and must
   never send an application while believing it complete when the employer
   says it is not.
3. **Required steps elsewhere.** Some forms require a second form on another
   site before they will consider the application.
4. **Choice limits.** "Pick the best 2" over a list of tick boxes. A
   remembered answer with three choices must never be ticked as three.

The person asked for a fifth requirement explicitly: the answer-review
setting must not become coupled to the setting that lets AA send without
asking, or to the machinery that carries questions to the person.

## Decision

### 1. Answers fall into four classes

`answer_review.answer_class` reads only the answer's `source`:

| Class | Sources | Meaning |
| --- | --- | --- |
| `person` | `human` | The person typed or chose it, in place. Never reviewed again. |
| `own` | `profile:…`, `session`, `saved`, `acknowledgement` | The person's own words, used as written. |
| `matched` | `saved:meaning` | A saved answer chosen because its meaning matched a new question (the toolkit's, not yet built). |
| `draft` | `generated…`, and **any source AA does not recognise** | Words AA wrote. Unknown is treated as a draft: fail closed. |

### 2. Trust widens one class at a time; "never" is the default

`applications.answer_trust` (profile: `answer_preferences.trust`):

| Level | Sent without review |
| --- | --- |
| `never` (default) | Plain profile facts only. Saved answers, declared sensitive answers (sponsorship, demographics), matches and drafts are all shown first. |
| `own_words` | Everything in class `own`, including declared answers. |
| `matched` | Also `matched`. |
| `drafts` | Also `draft`. |

At **every** level an answer below `applications.review_below_confidence`
(default 0.8) is reviewed. An unknown setting value reads as `never`.

### 3. Timing is a separate setting

`applications.review_timing`: `each` (ask as each answer is filled), `page`
(one question for a page's answers before AA moves on), `end` (default: one
question before the application is sent). `each` saves the person from
re-reading a page; `page` matches how a person checks a form; `end` asks
least often. If AA has no one to ask (no gate, asking off), `each` and `page`
quietly become `end`: the answers stay pending and the next rule decides.
When the per-step page review (`review_each_step`) is on, it already shows
the page, so `page` timing does not ask a second time.

### 4. Independence, and the one place they meet

`answer_review.py` is a pure function of an answer and two values; a pin
(`tests/domain/test_answer_review.py`) holds that it imports nothing but the
answer model — not the submission setting, not the interrupt policy, not the
gate, not a surface. The engine asks *when* the timing says, through
whatever gate it was given; the gate does not know why it is asked.

The two settings meet in exactly one function,
`ApplicationsWorkflow._authorize_submission`:

| Send without asking? | Anything still needs the person? | Result |
| --- | --- | --- |
| No (pre-submit checkpoint on) | either | One question, as before; pending items are listed in it. Never asked twice. |
| Yes | No | Sent, as before. |
| Yes | Yes, and someone can be asked | One question at checkpoint `ANSWER_REVIEW` listing only what needs the person: send or skip. |
| Yes | Yes, and no one can be asked | **Not sent**; recorded as `SUBMISSION_GATE_BLOCKED` with the reason. |

"Send without asking" therefore never means "send what the person asked to
see". This is the professional pattern for two-key decisions: who may act
and what must be checked are separate policies, combined at the point of
action (as a repository's merge permission and its required reviews are
separate settings, both checked at merge).

### 5. Tests: never taken, structure decides

`external_steps.is_test_step` recognises a test page by structure only: an
element with `role="timer"`, a code editor (CodeMirror, Monaco, Ace), or the
page itself being on an assessment platform (a redirect into the test).
Words alone ("assessment centre") never make a page a test. On a test page
the engine fills nothing. With someone to ask, it hands the page over
(checkpoint `ASSESSMENT`) and continues only once the form is back; with no
one to ask, the application stops as `ASSESSMENT` (evidence outcome
`ASSESSMENT_REQUIRED`, a barrier in the session report).

### 6. Assessments and other required steps: reported, never followed

The page reader returns the visible links in the form's area
(`FormStep.links`). `external_steps.external_steps` reports:

* a link to a known assessment platform (`ASSESSMENT_HOSTS`, a host or any
  subdomain; data, extended as platforms are met), or a link whose words
  name an assessment (`assessment`, any language) → kind `assessment`;
* a link to another site whose words make it a condition of being
  considered (`must_complete`, any language) → kind `external_form`;
* a single required tick box that names an assessment ("I have completed
  the coding test") → an attestation, kind `assessment`.

A bare "required" near a link is **not** a condition (every form says
"Required fields are marked *"), and a required radio or text question
about past assessments is not one either. AA never opens these links. Only
the host goes into research records; the link itself (which can carry a
candidate token) is shown to the person only. A required step counts as
"needs the person" in rule 4.

### 7. Choice limits from the words

`selection_limits.selection_limit` reads a multi-choice question's label and
help text: ranges ("2-3", "2 to 4"), "up to", "at least", "or more",
"exactly", a bare count after a choosing word ("pick the best 2", "your top
3"), and number words, in the languages of ADR-025. "Select all that apply"
removes an implied count but never an explicit bound ("all that apply (up
to 3)" is at most 3). Words that *set* a limit (`choose`, `exactly`) are
safety classes, matched in every language: a wrong match only makes AA ask.
Words that *loosen* one (`at_most`, `at_least`, `or_more`, `all_that_apply`)
are permissive, matched only in the page's languages: a look-alike word from
another language must never let AA tick more. The limit is applied when the
engine reads a step
(`form_localization.localize_step`), not by the page adapter. An answer
outside the limit is never ticked: a required question is asked
(`selection-limit:N chosen, min-max allowed`), an optional one is left.

### 8. Settings, the same in both surfaces

The GUI Settings window has an **Answers** tab; first-run setup has an
Answers section; the CLI profile wizard asks the same three questions and
the CLI profile menu has "Edit a profile's settings". All of them use
`application/services/answer_settings` (choices, words, save rule) and
`application/services/choice_field` (one rule for every multiple-choice
setting: "(none)" first when optional, the number or a unique beginning of a
value accepted in the terminal, anything else refused with the list). The
same rule fixed the name suffix, which was free text the profile refused
("Jr" for "Jr.", or empty) and blocked every save of the About-you tab.
Profile values are stored only when the person changes them, so later
default changes still reach them.

### 9. Evidence

`ApplicationEvidence` records `answer_trust`, `review_timing`,
`answers_needing_review`, `answers_reviewed`, `selection_limited` and
`external_steps` (kind, host, required, evidence — never the link).

## Consequences

* A person can let AA send without asking and still see everything AA wrote
  for them; or review every page and still let their own saved answers
  through. Neither choice changes the other.
* Unattended runs (no one to ask) send nothing that the person asked to see,
  and nothing the employer says is incomplete.
* AA never takes a test, opens an assessment link, or ticks more choices
  than a question allows.

## Limits and open work

* The assessment and must-complete words for languages other than English
  await native-speaker review (as in ADR-025).
* `ASSESSMENT_HOSTS` is a maintained list; an unknown platform is found only
  by its words.
* Test pages are recognised by timers, code editors and assessment hosts. A
  test with none of these (plain multiple choice under a heading, on the
  employer's own site) reads as a form page.
* The `matched` class exists for the text-understanding toolkit, which is
  not yet built; until then no source produces it.
* Drafts (`GeneratedAnswerSource`) do not yet receive the job description
  or record provenance — tracked with the toolkit work.

## Verification

Unit and engine pins: `tests/domain/test_answer_review.py` (the trust matrix,
the confidence floor at every level, fail-closed settings and sources, the
independence pin), `test_external_steps.py`, `test_selection_limits.py`,
`tests/application/test_answer_review_and_external_steps.py` (timings, test
pages, assessment links, limits read by the engine),
`tests/workflows/test_answer_review_gate.py` (rule 4's table). Real-browser
pins in Playwright and Selenium: `test_a_required_coding_test_link_and_a_choice_limit_are_read`,
`test_a_timed_test_page_is_never_answered` (fixtures
`assessment_and_limits.html`, `timed_test.html`). Nineteen deliberate
breakages of these rules were each caught by these tests. None of this is
proof on live sites: that comes from live runs.

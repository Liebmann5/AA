---
title: Checking AA's Answers
status: needs-review
last_verified: 2026-11-26
verified_against: "resources/config/runtime_defaults.yaml (applications.answer_trust, review_timing, review_below_confidence), domain/applications/answer_review.py, domain/models/profile.py (AnswerPreferences), adapters/primary/gui/settings_editor.py (Answers tab), adapters/primary/gui/app.py (first-run setup), adapters/primary/cli/profile_wizard.py, adapters/primary/cli/settings_screen.py"
audience: users
---

# Checking AA's Answers

AutoApply (AA) fills application forms with answers from your profile, from
answers you saved, and — only if you turn it on — from drafts. These
settings decide **which** of those answers you see before an application is
sent, and **when** you see them.

They are separate from the setting that lets AA send applications without
asking you. Turning one on or off never changes the other (see
[ADR-026](../adr/026_answer_review_and_external_steps.md)).

## Where to find them

* **Window:** Settings → **Answers** tab. First-run setup asks the same
  questions.
* **Terminal:** when you create a profile, or from the profile list choose
  **[e] Edit a profile's settings** → **2. Answers**.

## Which answers AA may send without showing you

| Choice | What goes out without your OK |
| --- | --- |
| **None** (recommended, the default) | Only plain facts from your profile, like your name and email. Everything AA wrote or matched, your saved answers, and answers from the sensitive parts of your profile (work authorisation, sponsorship, demographics) are shown to you first. |
| **My own words** | Your profile, your saved answers when they fit word for word, and answers you gave earlier in the same session. |
| **My own words, and saved answers AA matched by meaning** | Also saved answers AA picked because the question meant the same thing. |
| **All of the above, and AI drafts** | Also drafts that pass AA's checks. Drafts are off unless you also tick "Let AA draft answers". |

Whatever you choose, **AA always shows you an answer it is unsure of.**

## When AA shows them to you

* **As AA fills each one** — you look at each answer as it appears.
* **A page at a time** — one question per page, before AA moves on.
* **All at once, before the application is sent** (the default).

If AA has no way to ask you (for example, a run you left unattended), it
waits until the end. If answers still need you and no one can be asked, the
application is **not sent**; the session report says why.

## Tests, assessments and steps on other sites

AA never takes a test for you and never opens a test link.

* On a page with a timer or a code editor, or on a testing site, AA fills
  nothing. If you are there, it asks you to take the test yourself in the
  browser window and choose "done" when the form is back. If you are not,
  it stops that application and records that a test was required.
* When the form links to a test, or says another form must be completed
  first, AA lists it for you before sending and asks whether to send.

## "Pick the best 2"

When a question says how many choices to pick ("pick the best 2", "up to
3", "at least one"), AA never ticks more or fewer. If a remembered answer
does not fit, AA asks you (or leaves an optional question alone).

## Choices in the settings

Every setting with a fixed list of choices is a drop-down in the window and
a numbered list in the terminal. Optional ones start with **(none)**. In the
terminal you can type the number, the choice itself, or its beginning:
`jr` chooses `Jr.`; something that could mean two choices is refused with
the list, never guessed.

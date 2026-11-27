---
title: Accessibility Settings
status: needs-review
last_verified: 2026-11-21
verified_against: "resources/config/runtime_defaults.yaml (accessibility), domain/models/profile.py (AccessibilityPreferences), adapters/primary/gui/settings_editor.py, adapters/primary/cli/profile_wizard.py, adapters/primary/cli/dashboard.py"
audience: users
---

# Accessibility Settings

These settings change how AutoApply (AA) works with you. AA never asks why
you choose them, never stores a reason, and never uses them to answer a job
application.

You can change them in two places, and both save the same settings:

* **Settings window:** open Settings and choose the **Accessibility** tab.
* **Terminal:** the profile setup asks three accessibility questions near the end.

## The settings

**How long AA waits for your answers.** When AA needs you — to approve a
submission, to answer a question it cannot, to solve a verification check — it
waits a limited time, then moves on. You can choose:

* **Standard (1x)**;
* **3x, 10x or 20x** — that many times as long;
* **No time limit (off)** — AA waits until you answer. Stopping the session
  always ends the wait.

Every question tells you how long AA will wait.

**Answer form questions in AA.** When AA cannot answer a question on an
application form, it normally asks you to answer it in the website's form.
With this on, AA shows the question in its own window instead: you pick from
the form's choices, or type your answer, and AA enters it and checks that it
took. This helps when a website's form is hard to use with your tools. You can
still choose "Answer in the browser" for any question.

**Move the keyboard focus to the question.** When AA asks you to answer a
question in the website's form, it scrolls the question into view and puts the
keyboard focus on it, so a screen reader or the keyboard takes you straight
there. On by default.

**Plain, linear text in the terminal.** For screen readers. The terminal stops
redrawing itself, questions have no lines drawn around them, and every choice
is read out in full ("Choice 1 of 3: Done"). To turn it on before you have a
profile, start AA with `AA_SCREEN_READER=1` set:

```powershell
$env:AA_SCREEN_READER = "1"; auto-apply
```

```bash
AA_SCREEN_READER=1 auto-apply
```

On Windows, AA also turns it on when a screen reader tells Windows it is
running — unless you have turned the setting off yourself.

**Reduce motion.** No animation and no redrawing.

**High contrast** and **text size.** For AA's approval window.

**Mention audio challenges.** When AA hands you a verification check, it
reminds you that many have an audio version.

## If you use a screen reader

Use AA in the terminal with plain, linear text on. AA's windows are built with
Tk, which only recently gained screen-reader support, and AA does not use it
yet.

## Forms in other languages

When an application form is in a different language from the one AA speaks to
you in, AA tells you so and shows the form's questions exactly as the form
words them. It never translates a question it answers.

---
title: Running a Job Hunt
status: reviewed
last_verified: 2026-09-19
verified_against: "cli/wizard.py, gui/wizard.py, domain/models/ui_contract.py"
audience: users
---

# Running a Job Hunt

How to configure and run a session on either surface.

---

## Before you start

- Your profile exists and is yours. If you were set up from the bundled
  template, fix it before running anything — AA blocks a session start when two
  or more fields still match the template.
- Your résumé path resolves. Check it in Settings → About you.
- A browser is installed. AA will refuse rather than run without one.
- You have read [STATUS.md](../STATUS.md). No application has ever been
  submitted; expect to be stopped by a CAPTCHA or a login wall.

---

## 1. Choose two things, not one

A session is defined by **two independent axes**. Earlier versions of AA
conflated them into a single "mode", which is why the wizard used to ask a
question nothing read.

### Entry — how jobs arrive

| Entry point | What it does | Good for |
| --- | --- | --- |
| **Search** | Searches Google, Bing and Indeed for your titles and location | Everyday hunting |
| **Direct links** | You paste job URLs; AA goes straight to them | You already know which jobs you want |
| **Company pages** | You paste careers-page URLs; AA mines every posting listed | A shortlist of target employers |
| **Resume** | Continues a previous session from its checkpoint | You stopped partway |

`[PARTIAL]` — in live runs, only Bing has yielded real postings. Google and
Indeed returned zero in the last two runs. This is a known defect, not your
configuration.

### Exit — how far the run goes

| Exit | What happens | Use when |
| --- | --- | --- |
| **Collect only** | Find and store postings. Nothing is checked or applied to | You want a list to review yourself |
| **Collect and check** | Also vet each posting against your profile | You want a filtered list |
| **Collect, check and apply** | Also fill and attempt to submit applications | You are ready to apply |

!!! tip "Collect only is a structural guarantee"

    With collect-only, no application stage exists in the plan, so there is no
    code path to a submission. It is not a setting AA promises to respect — it
    is the absence of the machinery.

    **This is AA's only no-submit guarantee.** There is no `--dry-run` flag.
    Use collect-only for your first run.

---

## 2. Launch

=== "GUI"

    ```bash
    python -m auto_apply
    ```

    A window opens. First time, the setup wizard runs first; after that you land
    on the dashboard and open the session wizard from there.

=== "CLI"

    ```bash
    python -m auto_apply --cli
    ```

    The same questions as text prompts. Press Enter to accept the default shown
    in brackets.

Both surfaces build the **same typed request** and read their labels from one
source, so the two cannot drift apart in what they offer
([ADR-014](../adr/014_typed_ui_port.md)).

---

## 3. Configure the session

The wizard asks:

1. **Entry point** — search, direct links, company pages, or resume.
2. **Exit** — collect / collect and check / collect, check and apply.
3. **Job titles** — comma-separated. Blank uses the titles in your profile.
4. **Location** — city, state or `Remote`. Blank uses your profile default.
5. **Maximum results** — how many postings to process before stopping.
6. **Providers** — which search engines to use. Deselecting one keeps it out of
   the fan-out entirely.

!!! note "Your answers now reach the engine"

    Until 2026-09-15 they did not. The orchestrator replaced its session plan
    while the workflows held the boot plan, so a result cap you typed was never
    applied. Both halves were fixed together; a run today uses the numbers you
    entered.

---

## 4. Watch it run

Both dashboards show the same things:

- **Current state** — what the agent is doing now.
- **Activity stream** — a running log of what happened.
- **Counters** — discovered, vetted, applied, failed.
- **Results** — postings found, with their source and status.

The stream is **polled** by both surfaces — CLI every second, GUI every 500 ms.
Nothing subscribes to the internal event bus, and internal events are projected
onto a small display vocabulary before they reach a screen, so agent-internal
payloads never appear in front of you ([ADR-015](../adr/015_polled_ui_state.md)).

**What you will probably see**, honestly:

- Google and Indeed returning nothing while Bing returns a handful.
- A CAPTCHA or login wall stopping most application attempts.
- Company names occasionally truncated to a single letter in exports (L-8).

None of that is your setup.

---

## 5. Approvals

AA pauses at checkpoints and waits for you:

| Checkpoint | When |
| --- | --- |
| Before submitting a form | Default on |
| On a suspicious redirect | Default on |
| On a low-confidence field | Default on |
| CAPTCHA encountered | Always — AA does not solve CAPTCHAs |

A gate holds for up to 300 seconds, then defaults to **skip**. Skipping loses
one application; guessing could send the wrong thing under your name.

`[PARTIAL]` — the CAPTCHA gate can currently open *after* an attempt has already
been recorded as blocked, in which case solving it cannot rescue that attempt
(L-5).

---

## 6. Autonomy

Autonomy removes the checkpoints. It is available deliberately, and deliberately
hard to reach:

1. Open autonomy settings on either surface.
2. Read both warnings and acknowledge each. **Two acknowledgements are
   required** — the control refuses with fewer, so a surface cannot skip a
   warning screen.
3. The policy is then frozen for the session. Nothing re-reads it mid-run.

Do not enable it until you have watched AA complete the same kind of application
with checkpoints on.

---

## 7. Pause, resume, stop

| Action | Effect |
| --- | --- |
| **Pause** | Finishes the current step, then holds. The browser stays open |
| **Resume** | Continues from the checkpoint |
| **Stop** | Shuts down cleanly, writes the session report, closes the browser |

`[PARTIAL]` — closing the browser window while AA is idle produces a dashboard
showing `PAUSED` while the agent state is `IDLE`, because one transition is
missing from the table (L-4). Use Stop rather than closing the window.

---

## 8. Afterwards

- **Results** — everything discovered, with source and status. Exportable to CSV.
- **Session history** — past sessions, ordered by when the session started
  rather than by file timestamp, so the order survives copying to a USB stick.
- **Session report** — the full record of the run.

!!! danger "Check where an export is going"

    `[PARTIAL]` — the export dialogue currently opens in the repository
    directory and describes plaintext as a convenience. A profile export
    contains your real name, email, phone and profile links. **Choose a
    location outside the working tree, and treat a plaintext export as a
    document you would not leave on a shared computer** (L-10).

Discovered jobs are stored **at discovery**, so a collect-only run keeps what it
found. A collect-only run also does **not** mark URLs as seen, so it will not
shrink a later full search.

---

## Next steps

- [Understanding the output](understanding_output.md)
- [Profiles and privacy](profiles_and_privacy.md)
- [Project status and known defects](../STATUS.md)

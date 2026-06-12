# Running a Job Hunt

Once your profile is set up, you are ready to run an automated job hunt.
This guide explains the different ways to tell AA which jobs to look for,
how to monitor progress, and how to stay in control while the agent works.

---

## Before you start

Make sure you have:

- [Installed AA](../getting_started/installation.md)
- [Created a profile](../getting_started/configuration.md) (the Setup Wizard
  handles this automatically on first launch)

AA uses your existing web browser — you don’t need to install anything extra.

---

## 1. Choosing a mode

When you start a session, you choose **how** AA finds jobs. There are three
options:

| Mode | What it does | Best for |
| ---- | ------------ | -------- |
| **Discovery** | Searches the web (Google, Bing, Indeed) for jobs matching your titles and location. | Everyday job hunting — you give keywords, AA finds listings. |
| **Direct Links** | You paste a list of job application URLs. AA applies to them immediately, skipping search and vetting. | You already know exactly which jobs you want to apply for. |
| **Company Pages** | You paste a list of company careers‑page URLs. AA scrapes every job listed on those pages, then vets and applies. | You have a list of target companies and want to apply to all their open roles. |

All three modes share the same application engine — the only difference is how
the jobs arrive in the queue.

---

## 2. Launching AA

=== "GUI (recommended)"

    ```bash
    python -m auto_apply
    ```

    A window appears. If this is your first time, the Setup Wizard opens first.
    After your profile is loaded, you will see the **Session Configuration**
    wizard.

=== "CLI"

    ```bash
    python -m auto_apply --cli
    ```

    The same configuration questions appear as text prompts. Press Enter at
    each prompt to accept the default shown in brackets.

    !!! tip
        The CLI is ideal for headless servers, SSH sessions, or library
        computers where Tkinter may not be available. All features —
        discovery, vetting, applications, and human‑in‑the‑loop approvals —
        work identically in the terminal.

---

## 3. Session configuration

The **Session Configuration** wizard asks four things:

1. **Mode** — Discovery, Direct Links, or Company Pages (see above).
2. **Job Titles** — comma‑separated list (e.g. `Software Engineer, Backend Developer`).
   If you leave this blank, AA uses the titles saved in your profile.
3. **Location** — city, state, or `Remote`. If left blank, AA uses your profile default.
4. **Max Results** — how many jobs to process before stopping (default 100).

After you click **Start Session** (or press Enter in the CLI), AA begins
immediately.

---

## 4. Live monitoring

While AA runs, you can watch its progress in real time.

=== "GUI Dashboard"

    The dashboard shows:

    - **State** — what AA is doing right now (Searching, Analysing, Applying).
    - **Counters** — discovered, vetted, applied, failed.
    - **Progress bar** — fills as jobs are processed.
    - **Activity feed** — scrollable log of every action.

    Everything updates automatically. No need to refresh.

=== "CLI Dashboard"

    The terminal prints a live table that refreshes every second:

    ```
    ──────────────────────────────────────────
     AutoApply — Live Session Monitor
    ──────────────────────────────────────────
     State:    APPLYING           Duration: 00:04:22
     Found:   42  Vetted:   12  Applied:    8  Failed:    1  (88%)
    ──────────────────────────────────────────
     Task:    [APPLY] https://careers.acme.com/jobs/...
     Queue:   3 pending
    ──────────────────────────────────────────
     Ctrl+C to stop
    ```

    Press `Ctrl+C` to pause and choose whether to stop.

---

## 5. Human‑in‑the‑loop approvals

By default, AA pauses at two critical moments so you can decide what happens
next:

| Checkpoint | What AA asks |
| ---------- | ------------ |
| **Before submitting a form** | "About to apply for *Software Engineer* at *Acme Corp*. Approve, skip this job, or stop the session?" |
| **Suspicious redirect detected** | "The page redirected unexpectedly. Continue as a new discovery task, skip, or stop?" |

When a checkpoint fires:

=== "GUI"

    A small window appears with the question and buttons for each option.
    The agent waits until you choose. If you close the window without
    choosing, the job is skipped.

=== "CLI"

    A numbered menu appears. Type the number of your choice and press Enter.

If you don't respond within 5 minutes, AA automatically skips the job to
keep things moving. You can customise which checkpoints are active (or
disable them entirely for fully autonomous runs) in your profile under
`app_config.human_review_checkpoints`.

---

## 6. Pausing, resuming, and stopping

You can interrupt AA at any time without losing progress.

| Action | GUI | CLI | What happens |
| ------ | --- | --- | ------------ |
| **Pause** | Click the Pause button | Press `Ctrl+C` once | AA finishes the current task (e.g. typing a field), then waits. The browser stays open. |
| **Resume** | Click Resume | *(automatic on next loop)* | AA picks up where it left off. |
| **Stop** | Click Stop | Press `Ctrl+C` twice | AA finishes the current task, saves a checkpoint, and shuts down. You can resume later. |

Checkpoints are saved automatically every 5 completed tasks, so even if the
power goes out, you can resume from near where you left off.

---

## 7. After the session

When all work is done (or you stop early), AA shows a **Session Results**
summary:

```
Jobs Discovered: 42
Jobs Approved:   12
Applications Sent: 8
Applications Failed: 2
Duration: 00:14:32
```

You can choose to **Run Another Session** or close the app.

Every job AA has ever seen is recorded in a local database, so it never
applies to the same URL twice — even across sessions.

---

## Next steps

- [Understanding the Output](understanding_output.md) — learn what all those
  log messages mean and where the data files live.
- [Profiles & Privacy](profiles_and_privacy.md) — encrypt your profile, store
  it on a USB drive, and understand exactly what AA does with your information.
- [Configuration Reference](../getting_started/configuration.md) — all
  environment variables and profile fields explained.
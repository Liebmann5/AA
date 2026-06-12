# Understanding the Output

AA produces a wealth of information while it works — live logs, session
summaries, screenshots of errors, and (if you opt in) anonymised research
data. This guide explains what each piece means, where to find it, and how
to use it to improve your job hunt.

---

## Where everything lives

AA stores all its data in a single directory. You never need to hunt for
files — everything is in one place.

| Platform | Default data directory |
| -------- | ---------------------- |
| Windows  | `%USERPROFILE%\.auto_apply\` |
| macOS    | `~/.auto_apply/` |
| Linux    | `~/.auto_apply/` |
| USB portable | `<drive>:\AutoApply\data\` |

Inside this directory you will find:

```
.auto_apply/
├── profiles/              # Your profile JSON files
├── logs/                  # Session logs (text + optional JSON)
│   └── app.log
├── checkpoints/           # Crash‑recovery snapshots
│   └── checkpoint_<session>.json
├── screenshots/           # Failure screenshots (timestamped PNGs)
├── research_data/         # Anonymised research signals (if opted in)
│   └── hiring_signals.csv
└── applications.db        # SQLite database of all jobs ever seen
```

---

## 1. Live activity feed

While AA runs, the GUI dashboard and CLI terminal both display a stream of
log messages. These messages tell the story of your session in real time.

Example CLI output:

```
INFO  | Discovery starting | query=Software Engineer location=Remote
INFO  | GoogleProvider: Processing query 'Software Engineer' in 'Remote'
INFO  | Discovery complete | found=42
INFO  | Vetting PASS | title=Software Engineer company=Acme Corp
INFO  | Vetting FAIL | title=School Principal company=Education Inc reason=Role Mismatch
INFO  | Buffered application | company=acme corp buffer_size=3
INFO  | Applying batch | company=acme corp count=3
INFO  | ✓ Applied | title=Backend Developer company=Acme Corp
WARN  | ✗ Application failed | title=Frontend Dev company=Widgets LLC
INFO  | Session complete | applied=8 failed=2 duration=00:14:32
```

Key patterns to look for:

| Message | Meaning |
| ------- | ------- |
| `Discovery complete | found=N` | AA found N job listings across all search engines. |
| `Vetting PASS` | This job matches your profile — it will be applied to. |
| `Vetting FAIL | reason=...` | This job was filtered out. The reason tells you which filter blocked it (e.g. title mismatch, company blacklist, too far away). |
| `✓ Applied` | The application form was successfully submitted. |
| `✗ Application failed` | AA could not submit this form. A screenshot was saved. |
| `CAPTCHA detected` | AA hit a bot‑check. It will try to solve it, then pause for manual help if needed. |

!!! tip
    The live feed is also written to `logs/app.log`, so you can review it
    later even if you closed the terminal.

---

## 2. Session reports

At the end of every session, AA displays a one‑page summary. This tells you
how many jobs were processed and what the outcomes were.

```
Jobs Discovered: 42
Jobs Approved:   12
Applications Sent: 8
Applications Failed: 2
Duration: 00:14:32
```

You can also export a more detailed report in JSON or CSV format via the
dashboard's "Export" button or the `--export` CLI flag. The report includes:

- Timestamps for each application
- Company names
- Job titles
- Outcome (success, failed, skipped because already applied)
- Rejection reasons (for vetted‑but‑dropped jobs)
- Fit scores (how well the job matched your profile)

This data is ideal for tracking your application pipeline over time.

---

## 3. Screenshots

When an application fails, AA automatically captures a screenshot of the
page at the moment of failure. Screenshots are saved in the `screenshots/`
directory with descriptive names:

```
failure_application_Acme_Corp_20260501-143000.png
```

These screenshots help you (and developers) understand what went wrong:

- A CAPTCHA that couldn't be solved
- A form with unexpected fields
- A website that changed its layout
- A network error page

If you report a bug on GitHub, attaching the relevant screenshot is the
fastest way to get it fixed.

You can safely delete old screenshots to free up space — they are not needed
for AA to function.

---

## 4. Research data (opt‑in only)

If you enable **Research Collection** in your profile (it is off by default),
AA records anonymised signals about hiring market patterns. No personal
information — not your name, email, job URLs, or company names — is ever
stored in research data.

Research data is written to `research_data/hiring_signals.csv`. The file is
a standard CSV that you can open in Excel, Google Sheets, or any data analysis
tool.

Each row represents a single observation, such as:

- A job posting labelled "Entry Level" that required 5+ years of experience
- A company that disclosed a salary range (a positive signal)
- A form that presented a logic conflict (e.g. a yes/no question where both
  answers are wrong)

The full list of signals and their meanings is documented in the
[Research Module](../research_module/index.md).

!!! important
    Research data stays on your machine. It is never uploaded anywhere
    unless you explicitly choose to export and share it. You can delete
    the file at any time with no impact on AA's core functionality.

---

## 5. Application history database

AA maintains a local SQLite database (`applications.db`) that records every
job URL it has ever seen and whether it was applied to. This database is what
prevents AA from applying to the same job twice, even across different
sessions.

You can inspect the database with any SQLite viewer, but you never need to —
AA manages it automatically. The database is also used by the **Throttling
Filter** to enforce per‑company rate limits.

---

## 6. Crash recovery checkpoints

Every 5 completed tasks, AA saves a checkpoint file to the `checkpoints/`
directory. If AA ever crashes (power loss, computer freeze), it can resume
from the most recent checkpoint, preserving your progress.

Checkpoint files are small (a few KB) and are automatically pruned to keep
only the 3 most recent ones. You never need to manage them manually.

---

## Troubleshooting from the output

| You see … | It means … |
| --------- | ---------- |
| `BROWSER UNHEALTHY` | The browser crashed or stopped responding. AA will try to restart it automatically. |
| `NETWORK UNHEALTHY` | AA lost internet. It will pause and wait for the connection to come back. |
| `All browsers exhausted` | AA couldn't start any browser. Make sure you have Chrome, Firefox, Edge, or Safari installed, or use the portable package which bundles its own browser. |
| `CAPTCHA requires manual solve` | AA encountered a CAPTCHA it couldn't bypass. A browser window should be visible — solve it manually and AA will continue. |
| `max_steps exceeded` | A form took more than 15 pages/steps. AA stopped to prevent an infinite loop. The job will be marked as failed. |

For more solutions, see the [FAQ](../faq.md).
# User Guide

Everything you need to use AutoApply effectively — from your first session to
advanced privacy controls and enterprise deployment.

This guide is written for **non‑technical users**. If you're a developer
looking for architectural details, head to the [Developer Guide](../developer_guide/index.md).

---

## In this section

| Guide | What you'll learn |
| ----- | ----------------- |
| [Running a Job Hunt](running_a_job_hunt.md) | Session modes (discovery, direct links, company pages), GUI vs CLI, how to pause/resume/stop, reading the live dashboard. |
| [Understanding the Output](understanding_output.md) | Logs, session reports, CSV exports, screenshots on failure, and the optional research data file. |
| [Profiles & Privacy](profiles_and_privacy.md) | Creating and editing profiles, encrypting your data with a master password, storing profiles on external drives, what AA collects and how to delete it. |
| [Admin Policy](admin_policy.md) | How IT administrators can lock down AA on shared computers — allowed browsers, headless enforcement, rate limits, research opt‑out. |

---

## Quick answers to common questions

### How do I start my first job hunt?

1. [Install AA](../getting_started/installation.md).
2. Launch it — the Setup Wizard creates your profile automatically.
3. Enter a few job titles and a location, then click **Start Session**.
4. AA searches, filters, and applies. You approve each submission.

See the [Quick Start](../getting_started/quick_start.md) for a 5‑minute walkthrough.

### Can AA apply to jobs without my input?

Yes, but by default it **pauses before every submission** so you can review.
You can disable this in `app_config.human_review_checkpoints` if you want
fully autonomous operation — but we recommend keeping it on.

### Where is my data stored?

All your profiles, application history, and logs live in a folder called
`.auto_apply` in your user home directory. On a USB portable install,
everything stays on the flash drive. Read [Profiles & Privacy](profiles_and_privacy.md)
for details.

### Does AA ever send my data anywhere?

**No.** AA runs entirely on your machine. The optional research module
collects anonymised, aggregate data (never your name, email, or job URLs)
and stores it locally. You must explicitly opt in. Nothing is uploaded
unless you choose to share it.

### What if something goes wrong?

Check the [FAQ](../faq.md) for solutions to common errors (browser version
mismatch, missing pip, Playwright binaries). If you're stuck, open an issue
on [GitHub](https://github.com/Liebmann5/AA/issues).

---

## Feedback

We built AA to serve you. If something is confusing, or if a feature would
make your job hunt easier, please let us know via
[GitHub Issues](https://github.com/Liebmann5/AA/issues) — we read every one.
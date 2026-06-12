# Getting Started

Welcome! This guide helps you choose the right first steps based on who you are
and what you want to accomplish. No matter your background, AA is designed to
work on your machine — even if it's a shared library computer with no admin
rights.

## Who are you?

### 🧑‍💼 I'm a job seeker who wants to automate my applications

You don't need to be technical. Start here:

1. **Install AA** — pick the option that fits your computer:
   - **I have Python and pip** → [Core install](installation.md#core-install-recommended) (~30 MB)
   - **I want smarter matching** → [NLP install](installation.md#nlp-install) (adds SpaCy, ~50 MB)
   - **I want the best AI answers** → [AI install](installation.md#ai-install) (adds GPT4All, ~5 GB)
   - **I'm using a USB stick / library computer** → [Portable install](installation.md#usb-portable-install)
2. **Create your profile** — the Setup Wizard opens automatically on first launch.
   You only need to do this once.
3. **Run your first job hunt** — follow the [Quick Start](quick_start.md) to see
   AA in action in under 5 minutes.

> 💡 **No Python? No admin rights?** Download the pre‑built portable package,
> extract it to a USB drive, and run `AutoApply.exe`. Everything is included.
> Read the [USB portable guide](../deployment/pyinstaller_portable.md).

### 🏫 I'm an IT administrator deploying AA on shared machines

You want to control which browsers are used, enforce rate limits, and ensure
no personal data is left behind. Read:

1. [Admin Policy Guide](../user_guide/admin_policy.md) — how to create and
   deploy `aa_policy.json`.
2. [Enterprise Deployment](../deployment/enterprise_admin_policy.md) — mass
   deployment, Group Policy, MDM, and imaging.
3. [USB Portable Build](../deployment/pyinstaller_portable.md) — build a
   self‑contained package that leaves zero traces on the host.

### 🛠️ I'm a developer who wants to contribute or extend AA

Set up a full development environment:

1. Clone the repo and run `uv sync` — see [Project Setup](../developer_guide/project_setup.md).
2. Read the [Architecture Overview](../developer_guide/architecture_overview.md)
   to understand the hexagonal layers.
3. All design decisions are recorded in the [ADRs](../adr/index.md).

### 🔬 I'm a researcher studying the hiring market

AA can collect anonymised, consent‑gated data about hiring practices. Read:

1. [Research Module Overview](../research_module/index.md) — how it works and
   why your privacy is protected.
2. [Signals Taxonomy](../research_module/signals_taxonomy.md) — exactly what is
   collected and what it means.
3. [Data Format](../research_module/data_format.md) — CSV schema and analysis
   examples.

---

## Quick‑start checklist (for everyone)

- [ ] **Install AA** — [Installation Guide](installation.md)
- [ ] **Create your profile** — the Setup Wizard pops up on first run
- [ ] **Choose your session mode** — [Running a Job Hunt](../user_guide/running_a_job_hunt.md)
- [ ] **Understand the output** — [Understanding the Output](../user_guide/understanding_output.md)
- [ ] **Secure your data** — [Profiles & Privacy](../user_guide/profiles_and_privacy.md)

---

## The AA philosophy in one sentence

> **"Make the tool work perfectly for the person with the weakest computer,
> then let everyone else upgrade from there."**

Every feature in AA has a lightweight fallback. If your machine can't handle
SpaCy, the built‑in text matcher still works. If you don't have a GPU,
GPT4All simply won't load — and AA will still fill out forms. You are never
forced to install anything you don't need.

---

## Next steps

- [Installation Guide](installation.md) — every install method, in detail
- [Quick Start](quick_start.md) — your first automated job hunt
- [Configuration](configuration.md) — deep dive into profiles and settings

If you hit any problems, check the [FAQ](../faq.md) or open an issue on
[GitHub](https://github.com/Liebmann5/AA/issues).
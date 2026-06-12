# Deployment

AutoApply is designed to run anywhere — on a personal laptop, a headless
server, a library computer, or a USB stick. This section covers the three
primary ways to deploy AA, from a single‑command Docker run to a fully
portable, zero‑trace USB build.

Choose the guide that matches your environment and needs.

---

## Deployment Options

| Guide | Best for |
| ----- | -------- |
| [Docker](docker.md) | Running AA in a containerised, headless environment. Ideal for servers, VPS, or scheduled cron jobs. |
| [PyInstaller Portable Build](pyinstaller_portable.md) | Building a standalone `.exe` that runs from a USB drive with **zero installation** and **zero traces** on the host. The recommended way to deploy to library computers, shared machines, or any restricted environment. |
| [Enterprise Admin Policy](enterprise_admin_policy.md) | IT administrators deploying AA across a fleet. Covers mass deployment via Group Policy, MDM, or imaging, and how to pre‑configure `aa_policy.json` for all users. |

---

## Quick Reference

=== "I want to run AA in Docker"

    ```bash
    docker build -t auto-apply:latest .
    docker run --rm -v "$HOME/.auto_apply:/data" auto-apply:latest
    ```
    → Full guide: [Docker](docker.md)

=== "I want to put AA on a USB stick"

    1. Build with PyInstaller using the provided `.spec` file.
    2. Copy the output folder to a USB drive.
    3. Double‑click `AutoApply.exe` — nothing else needed.
    → Full guide: [PyInstaller Portable Build](pyinstaller_portable.md)

=== "I manage a fleet of computers"

    Deploy `aa_policy.json` via Group Policy or MDM to enforce browser
    restrictions, headless mode, rate limits, and data collection policies.
    → Full guide: [Enterprise Admin Policy](enterprise_admin_policy.md)

---

## Which Guide Should I Use?

- **I'm a job seeker using my own computer.** You don't need any of these —
  just [install AA normally](../getting_started/installation.md).

- **I want to run AA on a cloud server or Raspberry Pi.** Use the
  [Docker](docker.md) guide for a headless, always‑on setup.

- **I use library or shared computers.** Use the
  [PyInstaller Portable Build](pyinstaller_portable.md) to run AA from a
  USB drive without installing anything or leaving any data behind.

- **I'm an IT administrator.** Start with
  [Enterprise Admin Policy](enterprise_admin_policy.md) to understand how to
  lock down AA, then use the PyInstaller guide to build a custom package for
  your users.

---

## Deployment Principles

All deployment methods follow the same core rules:

- **No admin rights required.** AA runs as a standard user.
- **All data is portable.** Profiles, databases, and logs can be redirected
  via environment variables or stay on the USB drive.
- **Graceful degradation.** If a preferred browser is unavailable, AA falls
  back through the cascade automatically.
- **Admin policy respected.** Any `aa_policy.json` found in the application
  directory is enforced, regardless of deployment method.

---

## Next Steps

- [Docker](docker.md) — containerised deployment with volume mounts and
  headless configuration.
- [PyInstaller Portable Build](pyinstaller_portable.md) — complete guide to
  building and verifying a portable `.exe`.
- [Enterprise Admin Policy](enterprise_admin_policy.md) — mass deployment
  strategies and policy enforcement.
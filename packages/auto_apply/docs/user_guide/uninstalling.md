---
title: Uninstalling AutoApply
status: reviewed
last_verified: 2026-10-06
verified_against: "application/services/uninstall/engine.py + lifecycle surfaces"
audience: users
---

# Uninstalling AutoApply

Uninstall removes **everything AA created** and touches **nothing that
existed before it**. It is safe to run, safe to interrupt, and safe to run
twice.

## The command

=== "Windows"

    ```powershell
    %USERPROFILE%\.auto_apply\bin\auto-apply.bat --uninstall
    ```

=== "macOS / Linux"

    ```bash
    ~/.auto_apply/bin/auto-apply --uninstall
    ```

In the app: **File → Uninstall…**

Useful flags: `--dry-run` (show the plan, change nothing), `--yes`
(scripted; still keeps research data and honours any retention hold),
`--uninstall-report FILE` (a machine-readable JSON report).

## What happens, in order

1. **Plan.** You see every item with its size, grouped as *"AA created —
   will be removed"*, *"existed before AA — will not be touched"*, and
   *"research data — your choice"*.
2. **Research data.** If research data exists, you choose: **keep
   everything in place** (the default), move it to a folder you choose,
   export a verified copy first, or delete it — deletion requires typing
   `DELETE`. If a [retention hold](../research_module/retention_holds.md)
   is active, deletion is refused and you are told why.
3. **Confirmation.** Type `UNINSTALL` to proceed. Anything else cancels.
4. **Stop.** Every AA process and AA-launched browser is stopped first.
5. **Remove.** Only paths inside AA's roots or recorded in AA's footprint
   ledger are deleted — each one re-checked immediately before deletion.
6. **Report.** What was removed, what was not and why, and this promise:

> AutoApply removed everything it created and left everything that was
> there before. It cannot remove copies made by backup tools (Time Machine,
> OneDrive, File History). It cannot remove OS-level records (shell history,
> search indexes, download quarantine records). It cannot guarantee forensic
> erasure on SSDs; encrypted data is protected by key destruction.

## Per-OS notes

- **Windows:** a running program cannot delete itself. AA launches a small
  detached finisher that removes the program folder after AA closes;
  anything still locked is scheduled for deletion at the next reboot and
  named in the report.
- **macOS / Linux:** the same finisher runs detached; it waits for AA to
  exit before deleting the program folder.
- **USB / portable:** the portable folder *is* the whole install — delete
  it, or run the same `--uninstall` from inside it first to get the
  research-data choice and the report.
- **Interrupted:** run the command again. It resumes and never errors on
  things already gone.

## What uninstall cannot do

It cannot remove copies made by backups, OS-level records, or caches other
programs share (it reports the ones it finds — Selenium, Playwright,
Hugging Face — and never removes them). A source checkout you installed
*from* is reported and left alone.

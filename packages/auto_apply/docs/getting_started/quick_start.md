# Quick Start

Get AutoApply running and complete your first automated job hunt in under five
minutes — no manual configuration required.

## 1. Prerequisites

- AA is [installed](installation.md) and the `auto-apply` command works.
- You have a web browser on your computer (Chrome, Firefox, Edge, or Safari).
  AA will use whatever is available.

## 2. Launch AA

=== "GUI (recommended)"

    ```bash
    python -m auto_apply
    ```

    A window titled **AutoApply** appears.

=== "CLI"

    ```bash
    python -m auto_apply --cli
    ```

## 3. Create your profile (first run only)

The very first time you launch AA, the **Setup Wizard** opens automatically.
It asks for:

- A profile name (e.g. "John-Dev")
- Your resume file (PDF or DOCX)
- Your email address

Everything else can stay at its default — you can fine‑tune later.
After you click **Create Profile & Continue**, AA saves your information
securely and never asks again.

## 4. Start a job hunt session

=== "GUI"

    1. The **Session Configuration** wizard appears after the profile is loaded.
    2. In "Step 1", enter the job titles you are looking for, separated by commas
       (e.g. `Software Engineer, Backend Developer`), and a preferred location
       (e.g. `Remote`).
    3. Click **Next**, then **Start Session 🚀**.

=== "CLI"

    The CLI wizard asks the same questions. Just press Enter to accept the
    defaults. For example:

    ```
    Desired Job Titles (comma-separated) [Software Engineer]: Backend Developer
    Location [Remote]:
    Max Results [100]:
    Select Mode [1]:
    Select Strategy [1]:
    ```

    Press Enter at each prompt to accept the shown default. AA begins immediately.

## 5. Watch it work

AA now:

1. **Discovers jobs** by searching Google, Bing, and Indeed simultaneously.
2. **Filters results** against your profile (title, location, skills).
3. **Applies to approved jobs**, filling out forms automatically.

The GUI shows real‑time counters:

- **Discovered** — how many job listings were found
- **Vetted** — how many passed filtering
- **Applied** — how many applications were submitted
- **Failed** — applications that could not be completed

In CLI mode, the same information is displayed as a live dashboard.

!!! tip
    By default, AA pauses before submitting each application so you can review
    it. Click **Approve** to send it, or **Skip** to move on. This is your
    safety net — nothing is sent without your consent.

## 6. When the session ends

After all jobs are processed, AA shows a **Session Results** summary:

```
Jobs Discovered: 42
Jobs Approved:   12
Applications Sent: 8
Applications Failed: 2
Duration: 00:14:32
```

You can choose to **Run Another Session** or close the app. Every application
and its outcome is saved in your history, so AA never applies to the same job
twice.

## 7. What's next?

- [Customise your profile](configuration.md) — add work history, skills, salary
  expectations, blocked companies, and more.
- [Learn about the output](../user_guide/understanding_output.md) — logs,
  session reports, screenshots, and research data.
- [Set up an admin policy](../user_guide/admin_policy.md) if you are deploying
  AA on shared computers.

## Quick‑start video

*(Coming soon — a 2‑minute screencast of the entire flow.)*
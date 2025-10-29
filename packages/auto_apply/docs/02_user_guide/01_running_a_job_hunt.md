# Running a Job Hunt

You've installed the agent and configured your profile. Now it's time for the exciting part: running your first automated job hunt!

The agent can be run in two modes: with a Graphical User Interface (GUI) or as a Command-Line Interface (CLI) tool.

!!! tip "Which Mode Should I Use?"
    *   **For most users, the GUI is recommended.** It provides a simple window with a progress bar and a real-time log of the agent's actions.
    *   **The CLI is for users who are comfortable working in the terminal.** It provides the same information but as text output.

---

## Step 1: Open Your Terminal

All actions start from your computer's terminal (like PowerShell on Windows, or Terminal on macOS/Linux).

## Step 2: Navigate to the Project Directory

Before you can run the agent, you need to be in the correct folder. Use the `cd` (change directory) command to navigate to the project directory you created during installation.

```bash
cd path/to/AA
```

## Step 3: Launch the Agent

Now, you can launch the agent in your preferred mode.

### Launching the GUI (Recommended)

To start the graphical version of the application, run this command:

```bash
python -m auto_apply
```

A window will appear. It will start with a simple "Welcome" screen. In the future, this will be a full dashboard. To start the process, simply click the "Start Applying to Jobs" button (this functionality is coming soon!).

### Launching the CLI

To start the command-line version, add the `--cli` flag to the command:

```bash
python -m auto_apply --cli
```

The agent will immediately start its work in your terminal. You will see a stream of log messages updating you on its progress, such as:

```
INFO - --- AutoApply Orchestrator Starting ---
INFO - Profile 'default_profile' loaded for Bruce Dickinson.
INFO - Executing adaptive search with 3 registered strategies.
INFO - --- Executing Strategy: Google Direct URL Search ---
...
```

The agent will run through its entire process: discovering jobs, filtering them, and attempting to apply.

---

## What's Next?

As the agent runs, it creates files to keep track of its work. The next guide explains what these files are and how to understand the information you see in the logs.

➡️ **Next: [Understanding the Output](02_understanding_the_output.md)**
```

---
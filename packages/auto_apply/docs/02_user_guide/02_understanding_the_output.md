# Understanding the Output

As the AutoApply Agent runs, it provides real-time feedback and creates several files to store its progress and "memory." This guide explains what you're seeing in the logs and what these important files do.

All of the agent's data is stored securely in a hidden folder in your user home directory called `.auto_apply`.

---

## The Activity Log

Whether you are using the GUI or the CLI, you will see a stream of messages that look like this:

```
INFO - --- AutoApply Orchestrator Starting ---
INFO - Profile 'default_profile' loaded for Bruce Dickinson.
INFO - Executing adaptive search with 3 registered strategies.
INFO - --- Executing Strategy: Google Direct URL Search ---
INFO - Navigating to Google Jobs for query: ...
...
INFO - Filtering complete. 25 actionable jobs remain.
INFO - Beginning application process for 25 jobs.
INFO - Executing application strategy 'GreenhouseStrategy' for 'Junior Developer'...
...
WARNING - SIMULATION MODE: Skipping final form submission on Greenhouse.
...
INFO - --- Session Report ---
INFO -   Jobs Found in Search:      150
INFO -   New Jobs to Process:       25
INFO -   Applications Completed:    10
INFO -   Applications Failed:       2
INFO - --- AutoApply Shutdown Complete ---
```

This log is the story of the agent's work. It tells you which strategies it's using, how many jobs it found, and how many applications it successfully completed. At the end of every run, you will see a **Session Report** that gives you a final summary.

---

## The Agent's "Memory" Files

Inside the `.auto_apply` folder, the agent creates several important JSON files. You can open these with any text editor to see what the agent has learned.

### `job_states.json`

This is the agent's main "to-do list." It keeps track of every single job it has ever found and its current status.

```json
{
  "https://example.com/job/123": {
    "status": "application_completed",
    "title": "Software Engineer",
    "company": "We Hate NewGrads",
    "source": "GoogleDirectURL"
  },
  "https://example.com/job/456": {
    "status": "found",
    "title": "Backend Developer",
    "company": "Data Inc.",
    "source": "BingGUI-Heuristic"
  }
}
```
*   **`"status": "application_completed"`**: Means the agent successfully applied to this job in a previous session.
*   **`"status": "found"`**: Means the agent has found this job but hasn't applied to it yet. It will be on the to-do list for the next run.
*   **`"status": "application_failed"`**: Means the agent tried to apply but ran into an error.

### `applied_jobs.json`

This is a simple list of all the job URLs that the agent has successfully applied to. The `DataFilter` uses this file as its memory to ensure it never applies to the same job twice.

```json
[
  "https://example.com/job/123",
  "https://example.com/job/789"
]
```

### `screenshots/`

If the agent fails to apply for a job, it will automatically save a screenshot of the page at the moment of failure. This is incredibly helpful for debugging! The screenshots are saved in the `screenshots` folder with a descriptive name, like `failure_application_Tech_Corp_20231026-143000.png`.


---
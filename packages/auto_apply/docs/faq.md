# Frequently Asked Questions

This page covers the most common issues users encounter when installing or
running AutoApply. If your question is not answered here, please open an
issue on [GitHub](https://github.com/Liebmann5/AA/issues) or start a
[discussion](https://github.com/Liebmann5/AA/discussions).

---

## Installation & Setup

### Pip is not found / "No module named pip"

**Symptom:** Running `pip install ...` produces `ModuleNotFoundError: No module named 'pip'`.

**Cause:** Your system Python installation has a broken or missing `pip` module.

**Fix:**

1.  Use the built‑in bootstrapping command:
    ```bash
    python -m ensurepip --upgrade
    ```
2.  Then upgrade pip itself:
    ```bash
    python -m pip install --upgrade pip
    ```
3.  If you are using the portable `.exe`, you do not need pip at all — AA is
    self‑contained.

### "No module named 'auto_apply'" after install

**Symptom:** Running `python -m auto_apply` says the module is not found.

**Cause:** The package was not installed in editable mode, or your terminal
is not using the correct Python environment.

**Fix:**

1.  Ensure you are in the correct directory and have activated the virtual
    environment:
    ```bash
    cd AA/packages/auto_apply
    .venv\Scripts\Activate.ps1   # Windows
    source .venv/bin/activate    # macOS/Linux
    ```
2.  Reinstall in editable mode:
    ```bash
    pip install -e .
    ```
3.  If you are using `uv`, run `uv sync` from the repository root.

---

## Browser Issues

### ChromeDriver version mismatch

**Symptom:** `This version of ChromeDriver only supports Chrome version 149. Current browser version is 148`.

**Cause:** The `undetected-chromedriver` or `selenium` package downloaded a
ChromeDriver that does not match your installed Chrome version.

**Fix:**

1.  **Update Chrome** to the latest version.  Chrome auto‑updates, but you
    may need to restart the browser or your computer.
2.  **Alternatively**, AA’s `BrowserCascade` will automatically try Firefox
    next.  You do not need to fix this if Firefox is installed — AA will
    simply use Firefox instead of Chrome.
3.  If you want to pin the driver to match your Chrome version, reinstall
    the driver:
    ```bash
    pip install --force-reinstall undetected-chromedriver
    ```

### Playwright browsers not installed

**Symptom:** `Executable doesn't exist at ...\ms-playwright\chromium-...\chrome.exe`

**Cause:** The Playwright Python package is installed, but the browser
binaries have not been downloaded.  Playwright does not bundle browsers
with the pip install.

**Fix:**

1.  Install the smallest browser (Firefox, ≈ 80 MB):
    ```bash
    playwright install firefox
    ```
2.  Or install all browsers (≈ 300 MB):
    ```bash
    playwright install
    ```
3.  **If you cannot download browsers** (metered connection, no disk space),
    AA will automatically fall back to Selenium and your system‑installed
    browser.  You do not need Playwright for AA to work.

### "No supported browser is installed"

**Symptom:** AA prints `All browsers exhausted` and exits.

**Cause:** AA could not find any working browser.  Neither Playwright’s
bundled binaries nor a system browser (Chrome, Firefox, Edge) is available.

**Fix:**

1.  Install **Google Chrome** or **Mozilla Firefox** from their official
    websites.  AA uses your existing browser — no special configuration
    needed.
2.  On a restricted machine where you cannot install software, use the
    **USB portable build** which bundles its own browser.
3.  If you only need job discovery and vetting (not form submission), you
    can run AA in static mode.  Add `--static` to the launch command; AA
    will use HTTP requests and HTML parsing without a browser.

### AA opens a browser window — can I hide it?

Yes.  Set `run_headless: true` in your profile’s `app_config` section.  The
browser will run invisibly in the background.  On shared computers, an
administrator can force headless mode via `aa_policy.json`.

---

## Runtime & Crashes

### AA stops with an error during a session

**Symptom:** An error message appears in the log and AA pauses or stops.

**Cause:** This could be a transient network error, a website that changed
its layout, or an unexpected form field.

**Fix:**

1.  **Check the screenshot.**  AA automatically saves a screenshot when an
    application fails.  Look in `data/screenshots/` for the most recent PNG.
    This shows exactly what the browser saw at the moment of failure.
2.  **Resume from the checkpoint.**  AA saves progress every 5 completed
    tasks.  If AA crashes, simply restart it — it will offer to resume from
    the last checkpoint.
3.  **If the error repeats**, check the log file at
    `data/logs/app.log` for the full stack trace.  Search for it on
    [GitHub Issues](https://github.com/Liebmann5/AA/issues) — it may already
    be fixed in a newer version.

### AA froze / stopped responding

**Symptom:** The dashboard stops updating and AA seems unresponsive.

**Cause:** The browser process may have crashed, or the internet connection
may have dropped.

**Fix:**

1.  **Wait.**  AA monitors browser and network health.  If the browser
    crashed, AA will try to restart it automatically.  If the network
    dropped, AA will pause and wait for reconnection (up to 5 minutes by
    default).
2.  **If AA does not recover**, press `Ctrl+C` in the terminal (CLI) or
    click the **Stop** button (GUI).  AA will save a checkpoint and exit.
    You can resume later.

### "Human approval required" — what do I do?

AA pauses before submitting each application (by default) and shows a
modal dialog (GUI) or a numbered prompt (CLI).  Choose:

- **Approve** — AA submits the form.
- **Skip** — AA skips this job and moves to the next.
- **Stop** — AA saves progress and shuts down.

If you do not respond within 5 minutes, AA automatically skips the job
and continues.  You can disable these checkpoints in your profile for
fully autonomous operation.

---

## Data & Privacy

### Where is my data stored?

Everything lives in AA’s data directory:

| Platform | Default path |
| -------- | ------------ |
| Windows  | `%USERPROFILE%\.auto_apply\` |
| macOS    | `~/.auto_apply/` |
| Linux    | `~/.auto_apply/` |
| USB portable | `<drive>:\AutoApply\data\` |

Your profile, application history, logs, screenshots, and research data
all live here.  You can change these paths with environment variables —
see the [Configuration Guide](getting_started/configuration.md).

### Does AA send my data anywhere?

**No.**  AA runs entirely on your machine.  It does not phone home, use
analytics, or upload anything to a server.  The optional research module
collects anonymised data and stores it locally — it is never uploaded
unless you manually export and share it.

### How do I delete everything?

1.  Delete the data directory (`~/.auto_apply/` or the `data/` folder on
    your USB drive).
2.  If you installed via pip, uninstall the package:
    ```bash
    pip uninstall auto_apply
    ```
3.  AA leaves no registry entries or files outside its data directory.

---

## Updating & Uninstalling

### How do I update to the latest version?

If you installed via pip:

```bash
pip install --upgrade auto_apply
```

If you are using the portable `.exe`, download the latest `AutoApply-portable.zip`
from the [releases page](https://github.com/Liebmann5/AA/releases) and replace
the files on your USB drive.  Your profile and application history will not
be affected — only the application files are updated.

### Can I run multiple versions of AA?

Yes.  Each version is self‑contained.  However, they share the same data
directory by default, so the application history database will be shared.
To keep them separate, set `AA_DB_PATH` to a different path for each
version.

---

## Still stuck?

1.  Check the [log file](user_guide/understanding_output.md) for details.
2.  Search [existing issues](https://github.com/Liebmann5/AA/issues).
3.  Open a **new issue** with:
    - Your operating system and Python version.
    - What you were doing when the problem occurred.
    - The relevant error message from the log.
    - A screenshot if the problem is visual.
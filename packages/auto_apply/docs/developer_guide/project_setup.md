# Project Setup

Setting up a development environment for AutoApply takes about five minutes.
We use **uv** for dependency management — it’s fast, produces a reproducible
lockfile, and works identically on Windows, macOS, and Linux.

---

## Prerequisites

- **Python 3.10 or newer** — [download from python.org](https://www.python.org/downloads/)
- **Git** — [download from git-scm.com](https://git-scm.com/)
- **uv** — install with `pip install uv` or follow the
  [official instructions](https://docs.astral.sh/uv/getting-started/installation/)

No admin rights are required for any of these steps.

---

## Quick start

```bash
# 1. Clone the repository
git clone https://github.com/Liebmann5/AA.git
cd AA

# 2. Create the virtual environment and install everything
uv sync

# 3. Install Playwright browsers (optional, for live‑browser development)
uv run python -m playwright install firefox

# 4. Verify everything works
uv run python -m auto_apply --check-config
```

That’s it.  `uv sync` reads `pyproject.toml` and `uv.lock`, creates a
virtual environment at `.venv/`, and installs the core package in editable
mode with all development tools (pytest, black, ruff).

---

## What `uv sync` gives you

| Package | Purpose |
| ------- | ------- |
| `auto_apply` (editable) | The application itself, installed from the local source tree.  Changes to `src/` take effect immediately — no re‑install needed. |
| `pytest` + `pytest-mock` | Test runner and mocking utilities. |
| `black` | Opinionated code formatter. |
| `ruff` | Fast Python linter. |

The lockfile (`uv.lock`) pins every transitive dependency to exact versions,
so every developer gets an identical environment.

---

## Installing optional extras

AutoApply’s premium features require additional packages that are not
included in the default install.  You can add them with `uv sync` by
specifying an extra:

| Extra | What it installs | When you need it |
| ----- | ---------------- | ---------------- |
| `nlp` | `spacy` | To develop or test the NLP tier (entity extraction, title similarity, skill matching). |
| `ai` | `gpt4all` | To develop or test the local LLM tier (custom question answering, borderline reasoning). |
| `browser` | `playwright` (added to the core Selenium) | To develop or test Playwright‑specific features. |
| `full` | Everything above | For a complete development environment. |

To add an extra after the initial sync:

```bash
uv sync --extra nlp
uv run python -m spacy download en_core_web_sm   # or en_core_web_lg
```

If you are working on the core engine and don’t need NLP or AI, you can
skip these — the graceful degradation paths ensure the code compiles and
tests pass without them.

---

## Installing Playwright browsers

If you installed the `browser` extra (or `full`), you also need to download
the Playwright browser binaries once:

```bash
# Smallest option (~80 MB)
uv run python -m playwright install firefox

# All Playwright browsers (~300 MB)
uv run python -m playwright install
```

Without this step, the `BrowserCascade` will log a warning and skip
Playwright, falling back to Selenium and your system browsers.  The
application still works — you just won’t have Playwright’s bundled
browsers available during development.

---

## Running AA from source

Since the package is installed in editable mode, you can launch AA
directly:

```bash
uv run python -m auto_apply         # GUI
uv run python -m auto_apply --cli   # CLI
```

Or, equivalently, activate the virtual environment first and omit `uv run`:

=== "Windows"

    ```powershell
    .venv\Scripts\Activate.ps1
    python -m auto_apply
    ```

=== "macOS / Linux"

    ```bash
    source .venv/bin/activate
    python -m auto_apply
    ```

---

## Tooling

All code quality tools are configured in `pyproject.toml`.  Run them before
committing.

### Formatting with Black

```bash
uv run black src/ tests/
```

Black reformats your code to a consistent style.  Configuration is in
`[tool.black]` in `pyproject.toml`:

- Line length: 88
- Target Python version: 3.10

### Linting with Ruff

```bash
uv run ruff check src/ tests/
```

Ruff checks for common errors, style violations, and unused imports.
Configuration is in `[tool.ruff]` and `[tool.ruff.lint]`.  We use a
curated set of rules (`E`, `F`, `W`, `I`, `UP`, `PL`, `T20`) with a few
intentional ignores (see `pyproject.toml` for the rationale behind each
ignore).

### Running tests

```bash
uv run pytest tests/ -x -q
```

See [Running Tests](running_tests.md) for details on test markers,
fixtures, and writing new tests.

---

## IDE configuration

### VS Code (recommended)

Add these settings to `.vscode/settings.json` in the repository root:

```json
{
  "python.defaultInterpreterPath": ".venv/bin/python",
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["tests/"],
  "python.linting.ruffEnabled": true,
  "python.formatting.provider": "black",
  "editor.formatOnSave": true,
  "editor.rulers": [88],
  "[python]": {
    "editor.codeActionsOnSave": {
      "source.organizeImports": "explicit"
    }
  }
}
```

The first line points VS Code to the virtual environment created by `uv sync`.
All other settings are optional but recommended.

### PyCharm

1.  Open the `AA/` directory as a project.
2.  Go to **Settings** → **Project** → **Python Interpreter**.
3.  Choose **Add Interpreter** → **Existing Environment**.
4.  Navigate to `AA/packages/auto_apply/.venv/bin/python` (or
    `.venv\Scripts\python.exe` on Windows).
5.  Configure **Black** as the formatter (Settings → Tools → Black) and
    **pytest** as the test runner (Settings → Tools → Python Integrated
    Tools → Testing → pytest).

---

## Verifying your setup

Run the smoke test.  It builds a minimal orchestrator with no browser
driver and confirms that the entire wiring compiles without errors:

```bash
uv run python -m auto_apply --check-config
```

You should see output similar to:

```
✅ Profile loaded: default_profile
✅ Database accessible
✅ At least one browser available: chrome
✅ Admin policy: none
⚠️  Playwright browsers not installed — Selenium will be used
⚠️  SpaCy model not installed — NLP tier disabled
```

If you see any `ERROR` lines, something is misconfigured.  Check the
[Troubleshooting](#troubleshooting) section below.

---

## Troubleshooting

### `uv sync` fails with a dependency resolution error

Delete the lockfile and regenerate it:

```bash
rm uv.lock
uv sync
```

This can happen if the lockfile was generated on a different operating
system or Python version.  Regenerating it from your current environment
should resolve the conflict.

### `python -m auto_apply` says “No module named auto_apply”

Ensure you installed the package in editable mode.  `uv sync` does this
automatically.  If you set up the environment manually, run:

```bash
uv pip install -e .
```

### Playwright browsers fail to install

On some Linux distributions, Playwright needs additional system libraries:

```bash
uv run python -m playwright install-deps
```

If you don’t have admin rights, you can skip Playwright entirely — AA
will use Selenium with your system browser instead.

### Tests fail with `ModuleNotFoundError` for `auto_apply`

Make sure you are running tests with `uv run pytest tests/` and not a
system‑wide `pytest`.  The `uv run` prefix ensures the test runner uses
the virtual environment where AA is installed.

### `ruff` complains about a line being too long

Our line length is 88 characters.  If a line genuinely cannot be broken
(e.g. a long URL in a docstring), you can add a `# noqa: E501` comment
at the end of the line.  Use this sparingly.

---

## Next steps

- [Running Tests](running_tests.md) — how to run specific test suites
  and write new tests.
- [Architecture Overview](architecture_overview.md) — understand the
  four layers before you start coding.
- [Contribution Workflow](contribution_workflow.md) — how to open a
  pull request that gets merged quickly.
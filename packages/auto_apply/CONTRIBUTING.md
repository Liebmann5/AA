# Contributing to AutoApply

Thank you for your interest in contributing! 🎉
This document is the single setup story for AA. There are no alternate paths to reconcile: one tool, one lockfile, one graph.

---

## 1. Development Environment

### 1.1. Prerequisites

- Python ≥ 3.10 (AA's supported floor — see `packages/auto_apply/pyproject.toml`, `requires-python`).
- Git.
- Nothing else. Everything below is handled by one tool.

### 1.2. Bootstrap

AA's dependency and tooling declarations live in exactly two places:

- `packages/auto_apply/pyproject.toml` — what AA is: runtime dependencies, optional feature extras, entry points. A standard PEP 621 manifest, fully installable by plain `pip`.
- `pyproject.toml` (workspace root) — how AA is developed: the workspace declaration, the `dev` dependency group (PEP 735), shared tool configuration. PEP 735 groups are read by **uv**, not by pip's extras selector.

Contributors and CI therefore use **uv**, which is itself pip-installable:

  ```bash
  pip install uv
  uv sync
  ```

`uv sync`, run from the repository root, creates `.venv`, installs the workspace member (`packages/auto_apply`) in editable mode, installs the `dev` group (pytest, mypy, ruff, hypothesis, mkdocs, …), and honors the committed `uv.lock`. Do not float the lockfile casually; bump it deliberately (`uv lock --upgrade-package <name>`) and commit the result.

Optional feature extras (opt-in, declared in `packages/auto_apply/pyproject.toml`):

  ```bash
  uv sync --extra nlp        # SpaCy — smarter vetting
  uv sync --extra browser    # Playwright — enhanced stealth
  uv sync --extra ai         # GPT4All — local LLM answers
  uv sync --extra semantic   # sentence-transformers — semantic role alignment
  uv sync --extra captcha    # offline audio CAPTCHA solver
  uv sync --extra stealth    # undetected-chromedriver
  uv sync --extra research   # pyarrow + pandas — Parquet export
  uv sync --extra all        # all of the above
  ```

The SpaCy model is downloaded separately, by you, with your knowledge:

  ```bash
  uv run python -m spacy download en_core_web_lg
  ```

### 1.3. Verify the checkout

Run the four gates (exact CI invocations; §8 explains them):

  ```bash
  cd packages/auto_apply
  uv run pytest tests -q -p no:cacheprovider -rs
  uv run ruff check src --select F821 --output-format concise
  uv run mypy --config-file ../../pyproject.toml src/auto_apply
  uv run mypy --config-file ../../pyproject.toml --explicit-package-bases tests
  ```

### 1.4. If you only want to RUN AA

You do not need uv, the workspace, or the dev group.

  ```bash
  pip install auto_apply              # from PyPI (once published), or from a clone:
  pip install packages/auto_apply
  auto-apply                          # console script, or:
  python -m auto_apply                # module entry — both are declared entry points
  ```

The zero-install USB path (PyInstaller + `launch_portable.sh`) is for machines where you cannot install Python at all.

### 1.5. Cleaning up

There is no launcher script anymore. To reset your environment:

  ```bash
  rm -rf .venv packages/auto_apply/.pytest_cache packages/auto_apply/src/auto_apply.egg-info
  ```

On Windows (cmd):

  ```bat
  rmdir /s /q .venv packages\auto_apply\.pytest_cache packages\auto_apply\src\auto_apply.egg-info
  ```

---

## 2. Typical Workflow

1. Start a feature: branch off `dev` → `feature/xyz`
2. Finish feature: merge into `dev`
3. Prepare release: branch off `dev` → `release/vX.Y.Z`
4. Deploy release: merge release into `prod` and tag it
5. Fix bugs: if urgent, use `hotfix` → merge into both `prod` and `dev`

---

## 3. Commit Conventions

Follow this format:

  ```
  <type>(<scope>): <description>

  [optional body]

  [optional footer]
  ```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`

Example:

  ```
  feat(discovery): add provider-order cycling for SERP sources
  ```

---

## 4. Testing

The suite runs with the `dev` group installed by `uv sync` — nothing extra is required.

  ```bash
  cd packages/auto_apply
  uv run pytest tests -q -p no:cacheprovider
  ```

To run a subset:

  ```bash
  uv run pytest tests/workflows -q
  uv run pytest tests -k smoke -q
  ```

The property-based suite (`tests/property_based/`) imports `hypothesis`; it is in the `dev` group, so it collects out of the box.

Test files live under `packages/auto_apply/tests/`.

---

## 5. Pull Requests

- Ensure all four gates pass locally (§1.3) before opening the PR.
- Update documentation when behavior changes.
- Add an entry to `CHANGELOG.md` under the Unreleased section.
- Describe clearly what the PR does and why it is needed.

---

## 6. Reporting Issues

Use GitHub's issue tracker and include:

- Summary of the issue
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python version)

---

## 7. Licensing

All contributions to this repository are made under the MIT License.

---

## 8. Continuous Integration (CI)

AA's four gates run in GitHub Actions on **Linux, Windows and macOS**, on Python **3.10 and 3.12**, on every push and pull request (`.github/workflows/ci.yml`). The gates are:

1. The pytest suite (which includes the boundary-count and architecture pins).
2. `ruff check src --select F821` (used-but-never-defined names).
3. `mypy` over `src/auto_apply` (run WITHOUT `--explicit-package-bases` — the flag that once blinded the gate).
4. `mypy` over `tests/` (run WITH `--explicit-package-bases`, required there to disambiguate duplicate `conftest.py` modules).

### 8.1 Running the gates locally (exact CI equivalents)

Run everything from the **package directory** (`packages/auto_apply`), never the repo root. `uv run` behaves identically on all three operating systems:

  ```bash
  uv run pytest tests -q -p no:cacheprovider -rs
  uv run ruff check src --select F821 --output-format concise
  uv run mypy --config-file ../../pyproject.toml src/auto_apply
  uv run mypy --config-file ../../pyproject.toml --explicit-package-bases tests
  ```

Do not rely on a bare `python` — on developer machines that is often the system interpreter, not the workspace environment, and it has produced missing-module errors that looked like real failures. Use `uv run`, or explicitly use the venv interpreter at `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python` (Linux/macOS).

### 8.2 The `-rs` flag is deliberate

`-rs` prints the per-file skip summary. Roughly ten tests skip when no Chrome driver is available and run when one is. The count is surfaced, never asserted — a silent change in what the suite exercises must be visible in the log, not absorbed.

### 8.3 Resolution is pinned by `uv.lock`

CI runs `uv sync`, which honors the committed `uv.lock`. Third-party stub upgrades inside a version range (e.g. beautifulsoup4 4.14.3 → 4.15.0) have changed gate results on an otherwise identical tree before; the lockfile is what prevents that drift. Bump packages deliberately:

  ```bash
  uv lock --upgrade-package beautifulsoup4
  # run both mypy gates locally, fix what surfaces, then commit the new uv.lock
  ```

Do not edit a version range in `pyproject.toml` and push without running the gates.

### 8.4 When does CI become required (blocking)?

CI is **reporting-only** until it has reported green at least once on all three operating systems. The flip event is explicit: **the first push on which the `gates` job is green on every matrix leg.** At that point, enable branch protection requiring `gates` before merge, and record the date here.

Flip recorded on: ____________

---

Thank you for helping make AutoApply better!

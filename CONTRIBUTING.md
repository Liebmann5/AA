# Contributing to AutoApply

Thank you for your interest in contributing.

This is the single setup and process document for AA. There are no alternate
paths to reconcile: one tool, one lockfile, one dependency graph.

Before anything else, read [STATUS.md](packages/auto_apply/docs/STATUS.md). AA is
pre-alpha; knowing what is actually verified will save you from "fixing"
something that was never wired.

**The most valuable contribution right now is not code.** It is running AA on a
machine that is not the maintainer's — a different OS, less RAM, a locked-down
library computer — and reporting exactly what happened.

---

## 1. Development environment

### 1.1 Prerequisites

- Python ≥ 3.10 (AA's supported floor — `packages/auto_apply/pyproject.toml`,
  `requires-python`).
- Git.
- Nothing else. Everything below is handled by one tool.

### 1.2 Bootstrap

AA's dependency and tooling declarations live in exactly two places:

- `packages/auto_apply/pyproject.toml` — *what AA is*: runtime dependencies,
  optional feature extras, entry points. A standard PEP 621 manifest, fully
  installable by plain `pip`.
- `pyproject.toml` (workspace root) — *how AA is developed*: the workspace
  declaration, the `dev` dependency group (PEP 735), shared tool configuration.
  PEP 735 groups are read by **uv**, not by pip's extras selector.

Contributors and CI therefore use **uv**, which is itself pip-installable:

```bash
pip install uv
uv sync
```

`uv sync`, run from the repository root, creates `.venv`, installs the workspace
member in editable mode, installs the `dev` group (pytest, mypy, ruff,
hypothesis, mkdocs, …), and honours the committed `uv.lock`. Do not float the
lockfile casually; bump it deliberately with `uv lock --upgrade-package <name>`
and commit the result.

Optional feature extras (opt-in, declared in `packages/auto_apply/pyproject.toml`):

```bash
uv sync --extra nlp        # SpaCy — smarter vetting
uv sync --extra browser    # Playwright
uv sync --extra ai         # GPT4All — local LLM answers
uv sync --extra semantic   # sentence-transformers — semantic role alignment
uv sync --extra captcha    # offline audio transcription
uv sync --extra stealth    # undetected-chromedriver
uv sync --extra research   # pyarrow + pandas — Parquet export
uv sync --extra all        # all of the above
```

The SpaCy model is downloaded separately, by you, with your knowledge:

```bash
uv run python -m spacy download en_core_web_lg
```

### 1.3 Verify the checkout

Run the four gates (exact CI invocations; §7 explains them):

```bash
cd packages/auto_apply
uv run pytest tests -q -p no:cacheprovider -rs
uv run ruff check src --select F821 --output-format concise
uv run mypy --config-file ../../pyproject.toml src/auto_apply
uv run mypy --config-file ../../pyproject.toml --explicit-package-bases tests
```

### 1.4 If you only want to run AA

You do not need uv, the workspace, or the dev group. AA is not yet on PyPI, so
install from your clone:

```bash
pip install packages/auto_apply
auto-apply                # console script, or:
python -m auto_apply      # module entry — both are declared
```

The zero-install USB path (PyInstaller + `launch_portable.sh`) is for machines
where you cannot install Python at all.

### 1.5 Cleaning up

There is no launcher script. To reset your environment:

```bash
rm -rf .venv packages/auto_apply/.pytest_cache packages/auto_apply/src/auto_apply.egg-info
```

Windows (cmd):

```bat
rmdir /s /q .venv packages\auto_apply\.pytest_cache packages\auto_apply\src\auto_apply.egg-info
```

---

## 2. Branching and workflow

| Branch | Purpose |
| --- | --- |
| `main` | The only long-lived branch. Always green. |
| `feature/<slug>` | New capability |
| `fix/<slug>` | Bug fix |
| `docs/<slug>` | Documentation only |
| `research/<slug>` | Exploratory work that may never merge |

1. Branch off `main`.
2. Commit in small, reviewable steps.
3. Open a pull request against `main`.
4. Merge with a **merge commit**, not squash — a squash rewrites the base for
   any branch that started from a commit inside the PR, and that has bitten this
   project before.

There is no `dev` or `prod` branch. If you find a document that says there is,
it is stale — please fix it in the same PR.

---

## 3. Commit conventions

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `perf`, `build`, `ci`.

```
feat(discovery): add provider-order cycling for SERP sources
docs(adr): record the static-path retirement as ADR-013
```

---

## 4. Testing, and what a test means here

```bash
cd packages/auto_apply
uv run pytest tests -q -p no:cacheprovider
uv run pytest tests/workflows -q      # a subset
uv run pytest tests -k smoke -q
```

Tests live under `packages/auto_apply/tests/`, mirroring `src/`.

AA's testing discipline is **pins-are-the-spec**: a test does not merely cover
code, it *states a requirement* and must be shown to **fail against the current
code before the fix lands**. A pin that passes the moment you write it has no
teeth and proves nothing.

Label your pins honestly, because the label tells the next reader what the pin
can and cannot catch:

| Label | Meaning |
| --- | --- |
| **teeth** | Demonstrated failing before the fix |
| **differential** | Asserts two implementations agree |
| **coverage** | Exercises a path; asserts little |
| **characterisation** | Records current behaviour, right or wrong |
| **guard** | Structural, prevents a class of regression |

Where proceeding is irreversible (submission), fail closed. Where refusing is
expensive (a click), fail open. State which one you chose and why.

---

## 5. Documentation is part of the change

**A pull request that changes behaviour and not the documentation is
incomplete.** AA's defining defect is capability that was built and never
connected; the documentation equivalent is a document that describes intent as
achievement.

Rules, enforced by `tests/infrastructure/test_docs_gate.py` (see
[ADR-017](packages/auto_apply/docs/adr/017_documentation_gate.md)):

1. Every page under `docs/` carries front matter with `title`, `status`,
   `last_verified` and `audience`.
2. Every significant claim carries a status marker — `[LIVE]`, `[WIRED]`,
   `[PARTIAL]`, `[ORPHAN]`, `[PLANNED]` or `[GOAL]`. **A claim with no marker is
   a defect in the document.**
3. No document may reference a module that lives in `old_retired_files/`.
4. Every relative link must resolve, and every documented install command must
   name an extra that exists.
5. Readiness is asserted in exactly one place:
   [STATUS.md](packages/auto_apply/docs/STATUS.md). Do not restate it elsewhere.
6. Documents are corrected in the **same** change that makes them false.

The full conventions are in
[DOCUMENTATION_STANDARDS.md](packages/auto_apply/docs/DOCUMENTATION_STANDARDS.md).

### When you need an ADR

Write an Architecture Decision Record if your change alters a layer boundary, a
port contract, a data format, a user-visible guarantee, or reverses an earlier
decision. Copy the template from
[the ADR index](packages/auto_apply/docs/adr/index.md) and use the next free
number. Record the options you rejected **and why** — an ADR that lists only the
decision has recorded the least useful half of it.

---

## 6. Nothing is deleted

Orphaned, obsolete, superseded or abandoned files are **retired**, not deleted:

```bash
python retire.py <path> "one-line reason"
```

This moves the file to `packages/auto_apply/docs/old_retired_files/`, stamps its
original path on line 1, and prints a ledger row for that directory's
`README.md`. Build output (`__pycache__`, `.venv`, `*.pyc`) is exempt and is
deleted normally. Personal data is **refused** — the retirement directory is
committed and shipped to everyone who clones AA.

**Before adding any new module, tool or feature, search that directory first.**
Four modules were deleted once as "unimportable dead code"; within hours the pin
that was supposed to prove them dead turned out to be the broken thing. See
[ADR-016](packages/auto_apply/docs/adr/016_retirement_over_deletion.md).

---

## 7. Continuous integration

AA's four gates run in GitHub Actions on **Linux, Windows and macOS**, on Python
**3.10 and 3.12** — six legs — on every push and pull request
(`.github/workflows/ci.yml`):

1. The pytest suite (which contains the boundary, architecture and docs pins).
2. `ruff check src --select F821` (used-but-never-defined names).
3. `mypy` over `src/auto_apply`, **without** `--explicit-package-bases`.
4. `mypy` over `tests/`, **with** `--explicit-package-bases`.

Gates 3 and 4 are deliberately asymmetric. `--explicit-package-bases` once
renamed every module to `src.auto_apply.*` and blinded the `src/` gate for
weeks; it must never be added to gate 3, and never removed from gate 4, where
`tests/` fails on duplicate `conftest` modules without it.
`tests/infrastructure/test_ci_workflow.py` enforces both. Do not tidy it.

### 7.1 The `-rs` flag is deliberate

`-rs` prints the per-file skip summary. Roughly ten tests skip when no Chrome
driver is available and run when one is. The count is surfaced, never asserted —
a silent change in what the suite exercises must be visible in the log.

### 7.2 Resolution is pinned by `uv.lock`

CI runs `uv sync`, honouring the committed lockfile. A third-party stub upgrade
inside a version range has changed gate results on an otherwise identical tree
before. Bump deliberately, run both mypy gates locally, then commit the new lock.

### 7.3 CI is blocking

CI became a required check on 2026-09-05, the first push on which the `gates`
job was green on all six legs.

---

## 8. Pull requests

- All four gates pass locally before you open it.
- Documentation updated in the same PR.
- `CHANGELOG.md` gains an entry under **Unreleased**.
- An ADR if §5 says so.
- The PR description says what changed, why, and **how you verified it**.

"I ran it" is a verification. "It should work" is not.

---

## 9. Reporting issues

Use the [issue templates](https://github.com/Liebmann5/AA/issues/new/choose).
For anything security-related, follow [SECURITY.md](SECURITY.md) instead —
privately, never a public issue.

**Redact before you attach.** AA's logs, screenshots and session reports contain
real personal data, and the PII filter is known to be imperfect.

---

## 10. Licensing

All contributions are made under the MIT Licence. There is no CLA.

---

Thank you for helping make AutoApply better.

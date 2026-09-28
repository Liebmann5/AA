---
title: Installation
status: reviewed
last_verified: 2026-09-19
verified_against: "packages/auto_apply/pyproject.toml extras; CI matrix"
audience: users
---

# Installation

**This is the only installation document.** Earlier copies at `/INSTALL.md` and
`docs/INSTALL.md` have been retired; if you find a third one, it is stale.

---

## Before you start

!!! warning "AutoApply is pre-alpha"

    It has never completed an application submission. Read
    [STATUS.md](../STATUS.md) before you install, so you know what you are
    getting.

## Requirements

| | |
| --- | --- |
| **Python** | 3.10 or newer. CI exercises 3.10 and 3.12 |
| **Browser** | Chrome, Chromium, Firefox or Edge. **Required** — AA refuses to start a session without one ([ADR-013](../adr/013_static_path_retirement.md)) |
| **Operating system** | Windows, macOS or Linux. All three are in CI |
| **Disk** | ~300 MB for a core install. Optional tiers are much larger |
| **Memory** | 4 GB is the design target |
| **Privileges** | None. AA does not need administrator rights |
| **Accounts** | None. No API key, no subscription, no sign-up |

Check your Python:

```bash
python --version
```

If that prints 3.9 or lower, or "command not found", try `python3 --version`.

---

## Method 1 — from a source checkout (recommended today)

**AA is not yet published to PyPI.** `pip install auto_apply` does not work; any
document that tells you otherwise is stale.

```bash
git clone https://github.com/Liebmann5/AA.git
cd AA
pip install uv
uv sync
```

`uv sync` creates `.venv`, installs the package in editable mode, installs the
development group, and honours the committed `uv.lock`.

Run it:

```bash
uv run --package auto_apply python -m auto_apply
```

Verify the checkout:

```bash
cd packages/auto_apply
uv run pytest tests -q -p no:cacheprovider -rs
```

Expect **1384 passed, 2 skipped**, plus roughly ten skips if you have no Chrome
driver installed.

---

## Method 2 — pip, from the checkout

If you do not want uv and only want to run AA:

```bash
git clone https://github.com/Liebmann5/AA.git
cd AA
pip install packages/auto_apply
auto-apply
```

This installs runtime dependencies only. The test suite will not run, because
the development tooling lives in a PEP 735 dependency group that pip's extras
syntax cannot read.

---

## Method 3 — USB portable

For a machine where you cannot install anything.

```bash
cd /media/usb/autoapply
python -m auto_apply --portable
```

Everything AA writes goes to `./data/` next to the working directory — profile,
database, logs, reports, caches.

!!! warning "Containment is not yet proven"

    `[PARTIAL]`. Portable mode runs, but `launch_portable.sh` has known
    containment defects — most importantly it does not set `SE_CACHE_PATH`, so
    Selenium Manager can write a driver into the **host's** cache directory
    while the script's header claims nothing is written outside the drive.

    Treat "leaves no trace" as an intention, not a guarantee, until
    [STATUS.md](../STATUS.md) says otherwise.

A prebuilt PyInstaller executable is `[PLANNED]`. **There is no Releases
download.** Do not follow a document that offers one.

---

## Optional feature tiers

Every extra is opt-in. Nothing below is required for AA to work, and nothing is
downloaded without you asking for it.

| Extra | Install | Adds | Size |
| --- | --- | --- | --- |
| `nlp` | `uv sync --extra nlp` | SpaCy entity extraction, semantic title matching | small; model separate |
| `semantic` | `uv sync --extra semantic` | sentence-transformers role alignment | ~400 MB |
| `browser` | `uv sync --extra browser` | Playwright | ~300 MB plus browsers |
| `ai` | `uv sync --extra ai` | GPT4All, a local LLM for open-ended answers | model 4–8 GB on first use |
| `stealth` | `uv sync --extra stealth` | undetected-chromedriver | small |
| `captcha` | `uv sync --extra captcha` | offline audio transcription | ~100 MB |
| `research` | `uv sync --extra research` | Parquet export (pyarrow, pandas) | ~150 MB |
| `all` | `uv sync --extra all` | Everything above | large |

Installing with pip instead of uv:

```bash
pip install "packages/auto_apply[nlp]"
```

### The SpaCy model is a separate, deliberate download

```bash
uv run python -m spacy download en_core_web_lg
```

It is not downloaded automatically. AA does not put anything on your device
without asking — that is a hard principle, not a default.

!!! note "The model changes your results"

    Installing the model measurably changes vetting behaviour: with it, several
    job-title filters become more permissive. Runs with and without it are not
    directly comparable. If you are collecting research data, record which
    configuration you used.

### Playwright browsers

```bash
uv run python -m playwright install firefox
```

---

## Verify your installation

```bash
python -m auto_apply --check-config
```

This prints what AA detected — Python version, available browsers, optional
dependencies, data directory — and exits without starting a session. **Paste
this output into any bug report.**

---

## First run

```bash
python -m auto_apply          # GUI
python -m auto_apply --cli    # terminal
```

The first launch opens the setup wizard. Continue with
[Quick Start](quick_start.md).

---

## Uninstalling

```bash
# uv checkout
rm -rf .venv

# pip install
pip uninstall auto_apply
```

Your data lives in AA's data directory, which is **not** removed by either
command. In portable mode it is the `data/` folder next to where you ran AA;
otherwise `--check-config` prints the path. Delete it yourself when you want the
data gone — AA will not delete your profile on your behalf.

---

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `pip install auto_apply` — package not found | AA is not on PyPI yet. Use Method 1 |
| `No module named tkinter` | Debian and Ubuntu split it out: `sudo apt install python3-tk`. Or use `--cli`, which needs no GUI toolkit |
| Session refuses to start, "no browser" | AA requires a browser. Install Chrome, Chromium, Firefox or Edge |
| `import hypothesis` fails during tests | You installed with pip rather than `uv sync`. Dev tooling is a PEP 735 group |
| Browser launches then exits immediately | Headless environment with no display. Set headless mode in your profile |
| Works on one machine, not another | Run `--check-config` on both and compare. Usually a missing browser or a different Python |

More in the [FAQ](../faq.md).

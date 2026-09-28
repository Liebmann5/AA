# `auto_apply`

The AutoApply package. Documentation, contribution guidance and project status
live at the repository root and in `docs/`.

| | |
| --- | --- |
| **What it is** | Deterministic, local, zero-shot comprehension of unfamiliar web interfaces, applied to job applications |
| **State** | Pre-alpha. **No release, and no application has ever been submitted.** See [`docs/STATUS.md`](docs/STATUS.md) |
| **Licence** | MIT |
| **Python** | 3.10+ (3.10 and 3.12 in CI) |
| **Requires** | A browser — Chrome, Chromium, Firefox or Edge |

## Install and run

```bash
# from the repository root
pip install uv
uv sync
uv run --package auto_apply python -m auto_apply
```

Full instructions: [`docs/getting_started/installation.md`](docs/getting_started/installation.md).

## The four gates

Run from this directory:

```bash
uv run pytest tests -q -p no:cacheprovider -rs
uv run ruff check src --select F821 --output-format concise
uv run mypy --config-file ../../pyproject.toml src/auto_apply
uv run mypy --config-file ../../pyproject.toml --explicit-package-bases tests
```

## Layout

```
src/auto_apply/
├── domain/          pure models, ports and algorithms — no framework imports
├── application/     workflows, services, the agent orchestrator
├── adapters/
│   ├── primary/     the driving side: GUI, CLI
│   └── secondary/   the driven side: browser, discovery, persistence, research
├── infrastructure/  composition root, browser cascade, capabilities registry
└── resources/       YAML configuration, ATS descriptors, i18n, profile template

tests/               mirrors src/, plus architecture and infrastructure pins
docs/                the MkDocs site
```

Dependencies pointing strictly inward; the composition root is the only place
that knows both sides of a port.

## Documentation

```bash
uv run mkdocs serve
```

| | |
| --- | --- |
| What works today | [`docs/STATUS.md`](docs/STATUS.md) |
| Why it is built this way | [`docs/adr/index.md`](docs/adr/index.md) |
| Detailed design | [`docs/AA_ARCHITECTURE_BIBLE.md`](docs/AA_ARCHITECTURE_BIBLE.md) |
| Intent and priorities | [`docs/ENGINEERING_PHILOSOPHY.md`](docs/ENGINEERING_PHILOSOPHY.md) |
| Contributing | [Repository root `CONTRIBUTING.md`](https://github.com/Liebmann5/AA/blob/main/CONTRIBUTING.md) |

# Developer Guide

Welcome! This guide is for anyone who wants to understand, extend, or
contribute to AutoApply. Whether you are fixing a bug, adding a new job
board, or just curious about the architecture, you will find what you need
here.

AA is built on a **hexagonal (ports & adapters) architecture** with strict
dependency rules. If you are new to the codebase, we recommend reading the
[Architecture Overview](architecture_overview.md) first — it will save you
hours of head‑scratching.

---

## In this section

| Guide | What you'll learn |
| ----- | ----------------- |
| [Contribution Workflow](contribution_workflow.md) | Git branching strategy, commit conventions, pull request process, code review expectations. |
| [Project Setup](project_setup.md) | Cloning the repo, setting up `uv`, installing dev dependencies, configuring your IDE, and running the smoke test. |
| [Running Tests](running_tests.md) | How to run the test suite, what the different markers mean, and how to write new tests with the provided fixtures. |
| [Architecture Overview](architecture_overview.md) | The hexagonal layer map, the dependency rule, the composition root, and the key design decisions that shape the codebase. |
| [Adding an ATS Platform](adding_an_ats_platform.md) | A step‑by‑step recipe for adding a new Applicant Tracking System to the registry — a single YAML file is all you need. |

---

## Quick Start for Developers

```bash
# Clone and enter the repo
git clone https://github.com/Liebmann5/AA.git
cd AA

# Install uv if you don't have it
pip install uv

# Create the environment and install everything
uv sync

# Run the smoke test to verify everything works
uv run python -m auto_apply --check-config
```

That's it. `uv sync` creates a virtual environment, installs the core
package in editable mode, and pins every dependency with the lockfile.
You are ready to start coding.

---

## Where to go from here

- **To make your first contribution**, read the
  [Contribution Workflow](contribution_workflow.md) and
  [Project Setup](project_setup.md).

- **To understand the codebase**, start with the
  [Architecture Overview](architecture_overview.md) — it explains the
  four layers and how they fit together.

- **To add support for a new job board or ATS**, jump straight to
  [Adding an ATS Platform](adding_an_ats_platform.md).

- **To explore why we made certain decisions**, browse the
  [Architecture Decision Records](../adr/index.md).

---

## Documentation

The full documentation site (the one you are reading) is built with
[MkDocs Material](https://squidfunk.github.io/mkdocs-material/).
To preview it locally while you edit:

```bash
uv run mkdocs serve
```

Open http://127.0.0.1:8000 in your browser. Pages rebuild automatically
when you save a file.

---

## Getting Help

- **Bugs and feature requests:** [GitHub Issues](https://github.com/Liebmann5/AA/issues)
- **Discussions:** [GitHub Discussions](https://github.com/Liebmann5/AA/discussions)
- **Architecture questions:** The [ADRs](../adr/index.md) are the
  authoritative record of every major design decision.

If you are stuck on something that isn't covered here, open an issue or
start a discussion — we want to make contributing to AA as smooth as
possible.
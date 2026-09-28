---
title: API Reference
status: reviewed
last_verified: 2026-09-27
verified_against: "mkdocs build --strict; griffe static load of each rendered module"
audience: contributors
---

# API Reference

Generated from docstrings by [mkdocstrings](https://mkdocstrings.github.io/).
Build the site to render it:

```bash
cd packages/auto_apply
uv run mkdocs serve
```

!!! note "Ports are documented by hand, and that is deliberate"

    AA's stable surface is its **ports**, not its classes — an adapter may be
    replaced, a port is a contract. You would therefore expect them here.

    They are not, for a measured reason. `src/auto_apply/domain/ports/` is an
    **implicit namespace package**: it has no `__init__.py`, as do 25 other
    directories in `src/`, including `adapters/`, `adapters/primary/`,
    `adapters/secondary/` and `domain/services/`. Python imports them fine
    under PEP 420, and the module-reachability pin explicitly accounts for
    them, so this is a property of the tree rather than a defect in it.

    But `griffe`, the static analyser behind mkdocstrings, reads source without
    importing it. It will not descend from a regular package (`auto_apply.domain`,
    which has an `__init__.py`) into a subdirectory that lacks one, so every
    `auto_apply.domain.ports.*` module is invisible to it. Measured: `griffe.load`
    raises `KeyError: 'ports'` for all 35 of them, while loading `ports` as a
    top-level package from that directory finds all 35.

    Rather than add `__init__.py` to one of twenty-six namespace directories
    purely to satisfy a documentation tool — inconsistency bought with a source
    change, in service of a doc build — the port catalogue is **written by
    hand** and kept honest by the documentation gate:

    **→ [Port Catalogue](../reference/ports.md)** — all 35 ports, what each
    abstracts, and how many modules actually use it.

    That page carries something generated docs cannot: a measured importer
    count per port, which is how an orphaned port becomes visible.

## Domain models

The data structures that cross AA's boundaries.

::: auto_apply.domain.models.ui_contract
    options:
      show_root_heading: true
      members_order: source

::: auto_apply.domain.models.work_unit
    options:
      show_root_heading: true

::: auto_apply.domain.models.capability_profile
    options:
      show_root_heading: true

::: auto_apply.domain.models.policy
    options:
      show_root_heading: true

::: auto_apply.domain.models.job
    options:
      show_root_heading: true

::: auto_apply.domain.models.profile
    options:
      show_root_heading: true

---

This page renders the models a contributor most often needs, not every module
in the tree. Adding one is a four-line block; do it when a model becomes one
people need.

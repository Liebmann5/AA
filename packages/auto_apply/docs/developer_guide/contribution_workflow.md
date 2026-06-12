# Contribution Workflow

We are excited that you want to contribute to AutoApply. This document
describes the process for getting your changes reviewed and merged. It
covers our branching model, commit conventions, pull request checklist,
and code review expectations.

If you are looking for setup instructions, start with the
[Project Setup](project_setup.md) guide.

---

## Overview

```
1. Fork & clone        → 2. Create a feature branch
       ↓
3. Write code + tests  → 4. Open a pull request
       ↓
5. Code review         → 6. Merge & deploy
```

All contributions go through pull requests on GitHub. We use a **trunk‑based
development** model with short‑lived feature branches targeting the `dev`
branch. The `main` branch always reflects the latest stable release.

---

## 1. Fork and clone

1.  Fork the [main repository](https://github.com/Liebmann5/AA) to your
    GitHub account.
2.  Clone your fork locally:
    ```bash
    git clone https://github.com/YOUR_USERNAME/AA.git
    cd AA
    ```
3.  Add the upstream remote so you can keep your fork in sync:
    ```bash
    git remote add upstream https://github.com/Liebmann5/AA.git
    ```

---

## 2. Create a branch

Always create a new branch for your work. Branch off `dev` for features and
fixes; branch off `main` for critical hotfixes.

| Branch type | Naming convention | Example |
| ----------- | ----------------- | ------- |
| Feature / enhancement | `feature/<description>` | `feature/workday-multi-step-support` |
| Bug fix | `fix/<description>` | `fix/indeed-scraping-attribute-error` |
| Documentation | `docs/<description>` | `docs/adr-011-new-adr` |
| Hotfix (production) | `hotfix/<description>` | `hotfix/chrome-149-compat` |

```bash
git checkout dev
git pull upstream dev
git checkout -b feature/my-awesome-change
```

---

## 3. Commit conventions

We use **Conventional Commits** to keep the history readable and to enable
automated changelog generation in the future.

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

### Types

| Type | When to use |
| ---- | ----------- |
| `feat` | A new feature (e.g. a new discovery provider) |
| `fix` | A bug fix |
| `docs` | Documentation only changes |
| `test` | Adding or updating tests |
| `refactor` | Code restructuring that does not change behaviour |
| `chore` | Tooling, dependencies, build scripts |

### Examples

```
feat(discovery): add LinkedIn Easy Apply provider
fix(vetting): handle None max_commute_miles in SpatialLocationFilter
docs(adr): publish ADR-011 on portable build strategy
test(orchestrator): add integration test for checkpoint recovery
refactor(domain): extract FieldClassifier synonyms to constructor injection
chore: upgrade ruff to 0.15.10
```

Keep the first line under 72 characters. If you need more space, leave a
blank line and then write a longer description. Reference related issues
in the footer:

```
fix(applications): prevent crash on missing InteractionPort

The InterruptionHandler constructor required an InteractionPort but was
sometimes instantiated with only a BrowserInterface. This makes the
interactor parameter optional and falls back to element.click().

Closes #142
```

---

## 4. Before opening a pull request

Run these checks locally. The CI pipeline will run them automatically, but
catching issues early saves everyone time.

- [ ] **Tests pass:** `uv run pytest tests/ -x -q`
- [ ] **Linting passes:** `uv run ruff check .`
- [ ] **Formatting is correct:** `uv run black --check .`
- [ ] **New code has tests:** if you added a feature or fixed a bug, add
  tests that prove it works.
- [ ] **Documentation is updated:** if your change affects user‑facing
  behaviour, update the relevant docs in `docs/`.
- [ ] **Commit history is clean:** squash trivial fix‑up commits before
  opening the PR.

---

## 5. Open a pull request

1.  Push your branch to your fork:
    ```bash
    git push origin feature/my-awesome-change
    ```
2.  Go to the [main repository](https://github.com/Liebmann5/AA) and click
    **New pull request**.
3.  Set the **base branch** to `dev` (or `main` for hotfixes).
4.  Fill in the PR template with:
    - A clear title (will become the merge commit message).
    - A description of what you changed and why.
    - A link to any related issues.
    - A checklist confirming you have run tests, linting, and updated docs.

A maintainer will be assigned automatically. CI will run the full test
suite on your changes.

---

## 6. Code review

Every pull request is reviewed by at least one maintainer. Reviews focus
on:

### Architecture & design
- Does the change respect the hexagonal layering (no `domain/` importing
  from `adapters/`)?
- Are new dependencies injected via constructors rather than created
  internally?
- If a new port or adapter is introduced, is it wired correctly in the
  composition root?

### Correctness & safety
- Does it handle edge cases (empty lists, `None` values, missing optional
  dependencies)?
- Does it degrade gracefully on low‑resource hardware?
- Are there any race conditions or thread‑safety concerns?

### Test coverage
- Do new features have corresponding tests?
- Do the tests use mocks for external dependencies (no real browser or
  network I/O in unit tests)?
- Do existing tests still pass?

### Documentation & readability
- Are docstrings present for new public functions and classes?
- Is the relevant user‑facing documentation updated?
- Is the code clear to a first‑time reader?

### Style & consistency
- Does it pass `ruff` and `black` without exceptions?
- Are imports absolute (`from auto_apply.domain.ports import ...`)?
- Are naming conventions consistent with the rest of the codebase?

Review comments are suggestions, not personal criticism. If you disagree,
explain your reasoning — we want to find the best solution together.

---

## 7. After review

- Respond to feedback by pushing new commits to your branch. The PR updates
  automatically.
- Once all comments are resolved and CI is green, a maintainer will squash‑
  merge your PR into `dev`.
- After merge, delete your feature branch. Your changes will be included in
  the next release.

---

## Reporting bugs without a fix

If you find a bug but cannot fix it yourself, open an issue with:

- A clear title.
- Steps to reproduce.
- What you expected to happen.
- What actually happened (include any error messages or screenshots).
- Your operating system and Python version.

---

## Suggesting features

Feature requests are welcome. Open an issue and describe:

- The problem you are trying to solve.
- Your proposed solution.
- Any alternatives you have considered.

If the feature is large, a maintainer may ask you to write a brief design
document before starting implementation.

---

## Community standards

By contributing, you agree to abide by our [Code of Conduct](../CODE_OF_CONDUCT.md).
We are committed to building a respectful, inclusive community.

---

## Questions?

If anything in this guide is unclear, open a
[GitHub Discussion](https://github.com/Liebmann5/AA/discussions) — we will
update the documentation to make it clearer for the next person.
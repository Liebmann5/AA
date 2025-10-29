# Contributing to AutoApply

Thank you for your interest in contributing! 🎉
This document provides guidelines and procedures for submitting changes and maintaining high-quality contributions.

---

## 1. Development Environment

### 1.1. Setup
   ```bash
git clone https://github.com/Liebmann5/AA.git
cd AA/packages/auto_apply
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

### 1.2. Code Style

Use the following commands before committing:
   ```bash
black .
ruff check .
pytests.

---

## 2. Typical Workflow
1. Start a feature: Branch off dev → feature/xyz
2. Finish feature: Merge into dev
3. Prepare release: Branch off dev → feature/vX.Y.Z
4. Deploy release: Merge release into prod and tag it
5. Fix bugs: If urgent, use hotfix → merge into both prod and dev

---

## 3. Commit Conventions

Follow this format:
   ```bash
<type>(<scope>): <description>

[optional body]

[optional footer]


Types: feat, fix, docs, test, refactor, chore

Example:
   ```bash
feat(scraping): add adaptive search result prioritization

---

## 4. Testing

To ensure coverage:
   ```bash
pytest --maxfail=1 --disable-warnings -q

Test files are located under:
   ```bash
packages/auto_apply/tests/

---

## 5. Pull Requests

 - Ensure code passes linting and all tests.
 - Update documentation if behavior changes.
 - Add an entry to CHANGELOG.md under the Unreleased section.
 - Describe clearly what the PR does and why it is needed.

---

## 6. Reporting Issues

Use GitHub’s issue tracker and include:

 - Summary of the issue
 - Steps to reproduce
 - Expected vs actual behavior
 - Environment details (OS, Python version)

---

## 7. Licensing

All contributions to this repository will be made under the MIT License.

 - 

---

Thank you for helping make AutoApply better!
---
title: "ADR-016: Retirement Replaces Deletion"
status: reviewed
last_verified: 2026-09-19
verified_against: "retire.py, docs/old_retired_files/README.md"
audience: contributors
---

# ADR-016: Retirement Replaces Deletion

**Status:** Accepted
**Date:** 2026-08-30 (policy) · 2026-09-19 (recorded)
**Deciders:** Nicholas Liebmann

## Context

On 2026-08-30 four modules were deleted as unimportable dead code:
`telemetry.py`, `heuristic_adapter.py`, `location_extractor.py`,
`fingerprint_js.py`. Within hours the reachability pin that had "proved" them
dead turned out to be the broken thing, and three of the four were recovered
from git history.

Reading them after recovery showed how wrong the verdict had been. `telemetry.py`
was a complete, working Bayesian confidence tracker with Laplace smoothing;
`PageActionService` had been designed to consult it and never did.
`heuristic_adapter.py` was the **only** caller the humanised scroll functions
ever had — deleting it orphaned three more functions with no route back.

The general lesson: **a file that looks worthless is usually a file whose
context has been lost**, and deletion destroys exactly the context needed to
judge it. In a codebase whose defining defect is capability built and never
connected, "nothing imports this" is the *symptom* of the defect, not evidence
that the code is worthless.

## Decision

**Nothing authored in this project is deleted.**

1. Orphaned, obsolete, superseded or abandoned files are **retired** via
   `python retire.py <path> "reason"`, which moves them to
   `packages/auto_apply/docs/old_retired_files/`, preserving the original path
   as a stamp on line 1 and preserving git history through `git mv`.
2. Every retirement gets a **ledger row** recording what the file was, how
   complete it was, and a disposition tag: `AS-IS`, `AFTER-REWIRE`, `IDEA-ONLY`,
   or `SUPERSEDED-BY`.
3. **Before adding any new code, feature, tool or module, check that directory
   first.** This is a required step, not a courtesy — building a second copy of
   something already sitting there is the project's own defect with extra steps.
4. Build output is exempt: `__pycache__`, `.venv`, `*.pyc`, caches and logs are
   deleted normally, and `retire.py` refuses them.
5. **Personal data is refused.** The retirement directory is committed and
   shipped to everyone who clones AA, so screenshots, logs, `dev_data/`,
   résumés, `.env` files and credentials never enter it. `retire.py` refuses
   these by path, suffix and name, but the real check is reading the file first.
6. `retire.py --recall` reverses a retirement and restores the original path.

## Options considered

**A. Delete, and rely on git history.**
Rejected on evidence. Git preserves the bytes and destroys the *index*. Nobody
searches a reflog for a module they do not know exists, which is why three of
the four deleted modules were only recovered because the deletion happened to be
noticed within hours.

**B. A `deprecated/` directory inside `src/`.**
Rejected. Anything under `src/` is importable, gets linted, gets type-checked and
shows up in reachability counts. Retired code must be *out* of the build while
staying *in* the repository.

**C. A separate archive repository.**
Rejected. It splits the clone, and the rule "check before you build" only works
if checking is one directory away.

**D. Retirement with an indexed ledger.** — **Chosen.**

## Consequences

**What becomes true**

- Recovery is a `--recall` away, and the ledger says whether recovery is worth it
  before anyone reads the code.
- Dispositions carry forward. `heuristic_adapter.py` is tagged `AFTER-REWIRE`
  with the reason attached, so the next person does not re-derive it.
- Retiring becomes cheap enough to be honest with. Files that would have been
  left rotting in `src/` out of loss-aversion get moved out of the build.

**What is given up**

- The repository grows and never shrinks. Accepted: text is cheap, and lost
  context has already cost this project more than disk ever will.
- The ledger needs maintaining. A stale ledger is a worse index than no
  directory, so the row is written in the same change as the move.

## References

- `retire.py`
- `packages/auto_apply/docs/old_retired_files/README.md` — the ledger
- [ADR-013](013_static_path_retirement.md) — the largest retirement so far

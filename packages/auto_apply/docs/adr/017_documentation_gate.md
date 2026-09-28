---
title: "ADR-017: Documentation Is Enforced by a Gate, Not by a Checklist"
status: reviewed
last_verified: 2026-09-19
verified_against: "tests/infrastructure/test_docs_gate.py"
audience: contributors
---

# ADR-017: Documentation Is Enforced by a Gate, Not by a Checklist

**Status:** Accepted
**Date:** 2026-09-19
**Deciders:** Nicholas Liebmann

## Context

A documentation audit on 2026-09-19 measured the state of 65 Markdown files
against the code. Findings, each proven by inspection rather than impression:

| Finding | Measure |
| --- | --- |
| Pages with a status marker on any claim | **0 of 65** |
| Pages recording when they were last checked | **3 of 65** |
| Documented package extras that do not exist | 2 sites, both naming an extra called "full" |
| Broken relative links | 11 |
| Documents referencing retired modules as live | 8 |
| Docs pages unreachable from the site navigation | 20 of 55 |
| CI steps documented that are not run | 2 of 5 |
| Real CI gates that are undocumented | 2 of 4 |
| Chat-transcript residue committed into a page | 1 |
| Duplicate document pairs disagreeing with each other | 3 |
| Sections sharing the number "24" in the Architecture Bible | 2 |

None of this was written wrong. **All of it drifted**, because the code changed
and the document did not.

The decisive observation is about remedies rather than defects. Three separate
documentation programmes had been written before this one — a 19-document
specification suite, a rewritten architecture bible, and a release checklist.
**None of them was ever committed to the repository.** Writing better documents
had a measured zero percent landing rate. The bottleneck was never quality.

Meanwhile the project already possessed the answer. `test_install_commands_exist.py`
reads `CONTRIBUTING.md` and both READMEs and fails when a documented install
command names an extra that does not exist — a documentation defect caught by
the test suite. It works. It scans exactly three files, which is why
`docs/index.md` was free to advertise a non-existent extra indefinitely.

## Decision

**Documentation is subject to a gate, on the same terms as code.**

`tests/infrastructure/test_docs_gate.py` runs inside gate 1 and asserts:

1. Every page under `docs/` carries front matter with `title`, `status`,
   `last_verified` (a valid ISO date) and `audience`.
2. Every relative link in every Markdown file resolves.
3. No document references a module that lives in `old_retired_files/`.
4. Every package extra named in an install command is declared in
   `packages/auto_apply/pyproject.toml` — the existing check, widened to the
   whole tree.
5. Every ADR in the index exists, and every ADR file appears in the index.
6. Every page under `docs/` is reachable from the MkDocs navigation.
7. `CITATION.cff` and `pyproject.toml` agree on the version.
8. No page contains conversational residue.
9. Readiness vocabulary appears only in `STATUS.md`.

Supporting conventions, defined in
[DOCUMENTATION_STANDARDS.md](../DOCUMENTATION_STANDARDS.md): status markers on
every significant claim; one source of truth per subject; documents corrected in
the change that makes them false; prefer a pin to a paragraph.

## Options considered

**A. A documentation review checklist in the PR template.**
Rejected. The PR template already asked for documentation updates. All twelve
findings above accumulated underneath it. A checklist measures intention at the
moment of least information.

**B. A separate documentation CI job.**
Rejected. A job that can be marked non-blocking will be, and a second workflow
is a second thing to keep honest. Inside gate 1 it is simply part of the suite.

**C. A link checker from the ecosystem (`lychee`, `mkdocs-linkcheck`).**
Rejected as the primary mechanism, and worth revisiting as a supplement. They
check links and nothing else — not retired-module references, not the extras
contract, not front matter, not the single-source-of-truth rule. Six of nine
checks have no off-the-shelf equivalent because they encode *this* project's
defect history.

**D. A pin in the suite.** — **Chosen.** It matches how every other invariant in
AA is held, it fails on the developer's machine before CI, and it makes a
documentation defect a red suite rather than an opinion.

## Consequences

**What becomes true**

- A stale document becomes a **failing test**, with an author and a commit.
- The nine checks are cheap: pure file reads, no network, no build.
- Documentation joins the pins-are-the-spec discipline that governs the rest of
  the codebase.

**What becomes harder**

- Renaming or adding a page requires updating `mkdocs.yml`. That is the point:
  20 of 55 pages were unreachable precisely because nothing forced it.
- Front matter must be maintained. It is four lines, and `status: needs-review`
  is always an honest answer.

**What this gate explicitly cannot do**

It cannot tell whether a true-looking sentence is true. It checks structural
currency and internal consistency. Only a human reading the code can check
correctness — which is what `last_verified` records, and why that field is
required.

## References

- `tests/infrastructure/test_docs_gate.py`
- `tests/infrastructure/test_install_commands_exist.py` — the precedent
- [DOCUMENTATION_STANDARDS.md](../DOCUMENTATION_STANDARDS.md)

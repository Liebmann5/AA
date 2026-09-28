---
title: Documentation Standards
status: reviewed
last_verified: 2026-09-19
verified_against: "tests/infrastructure/test_docs_gate.py"
audience: contributors
---

# Documentation Standards

This document defines how AA's documentation is written, what it may claim, and
what is enforced automatically. It applies to every file under `docs/` and to
the repository-root documents.

Documentation here is treated as **part of the system**, not as commentary on
it. The rules below exist because each one has a defect behind it.

---

## 1. Why these rules exist

AA's defining defect class is *capability that was built and never connected*.
The documentation version is the same defect: **a document that describes intent
as achievement.**

Measured examples from this repository before 2026-09-19:

- Six subsystems were marked "Stable" on the docs home page, including a
  form-filling engine that had never completed a submission and a browser
  cascade whose final fallback had been removed.
- An ADR described a subsystem whose three implementation files had been retired.
- The continuous-integration section named five steps, of which two were not run
  at all and two more were run with different flags; two of four real gates were
  undocumented.
- Two documented install commands named a package extra that does not exist.
- The docs home page ended with a chat-transcript sign-off, committed
  verbatim.

None of those were caused by carelessness at the moment of writing. All of them
were caused by **the code changing and the document not**. So the rules target
that, and a gate enforces the ones that can be enforced.

---

## 2. Status markers

Every significant claim carries one. **A claim with no marker is a defect in the
document.**

| Marker | Meaning | Test for using it |
| --- | --- | --- |
| `[LIVE]` | On a real execution path, exercised by a live run | Can you name the run? |
| `[WIRED]` | Connected and tested; not proven in a live run | Does a test exercise it end to end? |
| `[PARTIAL]` | Works within a stated boundary | Have you stated the boundary? |
| `[ORPHAN]` | Built; has no consumer | Can you show the one-line proof — no caller, not constructed? |
| `[PLANNED]` | Decided, not built | Is the decision recorded in an ADR? |
| `[GOAL]` | Intended direction, no committed design | Are you sure it is not `[PLANNED]`? |

An `[ORPHAN]` claim must carry its **one-line proof of death** next to it. A
module is not dead because it looks unused.

---

## 3. Provenance front matter

Every page under `docs/` begins with:

```yaml
---
title: Running a Job Hunt
status: reviewed          # reviewed | needs-review | superseded
last_verified: 2026-09-19
verified_against: "suite 1384 passed / 2 skipped"
audience: users           # users | contributors | researchers | operators | everyone
---
```

`last_verified` is the honest answer to "when did a human last check this
against the code?" — not the last time the file was touched. **A claim's age is
part of its content.** A page whose `last_verified` is old is not wrong; it is
*unverified*, which is different and more useful to know.

`status: needs-review` is a legitimate state. Marking a page honestly is always
better than silently implying it is current.

---

## 4. Single source of truth

| Subject | Lives in | Nowhere else |
| --- | --- | --- |
| Readiness, gate counts, known defects | `docs/STATUS.md` | Do not restate |
| Install commands and extras | `docs/getting_started/installation.md` | Others link to it |
| Contributor setup and process | `/CONTRIBUTING.md` | |
| Decisions and their rejected alternatives | `docs/adr/` | |
| Intent and priority ordering | `docs/ENGINEERING_PHILOSOPHY.md` | |
| Detailed design | `docs/AA_ARCHITECTURE_BIBLE.md` | |
| Release history | `/CHANGELOG.md` | |

Readiness was once asserted in four places that disagreed. One place, linked
from everywhere, is the fix.

---

## 5. Documents are corrected in the change that makes them false

Not in a follow-up issue, not in a documentation sprint. **The same pull
request.** A stale document is a defect with a known author and a known commit,
and it is cheapest to fix at that moment.

Corollary: if you cannot update the document, your change is not finished.

---

## 6. Prefer a pin to a paragraph

If a property can be asserted by a test, assert it by a test and let the
document point at the test. A paragraph claiming "the application engine never
clicks an element directly" is worth less than a pin that fails when it does —
and that exact sentence sat in this repository as an aspiration for weeks before
becoming true by accident.

Where a document states a guarantee, name its enforcement. Where there is no
enforcement, say so. "Enforced by review, not yet by a pin" is an honest and
useful sentence.

---

## 7. The information architecture

AA follows the four-mode documentation split. A page that tries to be two of
these serves neither.

| Mode | Directory | Serves | Written as |
| --- | --- | --- | --- |
| **Tutorial** | `getting_started/` | A newcomer, learning | A guaranteed path to one success |
| **How-to** | `user_guide/`, `developer_guide/`, `deployment/` | Someone with a goal | Steps to a specific outcome |
| **Reference** | `reference/`, `api_reference/`, `research_module/` | Someone looking something up | Complete, dry, structured |
| **Explanation** | `architecture/`, `adr/`, `ENGINEERING_PHILOSOPHY.md` | Someone who wants to understand | Argument, alternatives, consequences |

The failure mode to watch for: an explanation growing steps, or a how-to growing
an argument. Split it.

---

## 8. Depth, and where it belongs

More words is not more depth. Depth is measured by the **question count test**:
read the page as the person who must act on it, and count the questions you
would still have to ask. Depth is the inverse of that count.

The axis most often missing is **derivation** — pages state conclusions without
showing the options weighed or why the rejected option was rejected. A table is
an answer; the derivation is what makes the answer checkable.

Depth by page type:

| Page type | Deep on | Shallow on |
| --- | --- | --- |
| ADR | Derivation, counter-argument, consequences | Step-by-step detail |
| Architecture | Grounding, failure modes | Procedure |
| How-to | Resolution, actionability | Argument — none at all |
| Reference | Coverage, grounding | Argument |
| Tutorial | Actionability | Everything else |

Depth is **wrong** when the evidence does not exist yet, the decision is
genuinely deferred, the reader is executing rather than deciding, the detail
constrains implementation rather than behaviour, or you are restating something
said elsewhere. Restating is the most common form of false depth.

---

## 9. Failure modes are documented, including hangs

Anything that crosses a process boundary — a browser, the network, the file
system, a subprocess — documents what it does on failure, and that includes
**hanging**. "Returns or raises" is an incomplete contract; AA has shipped a
terminal hang that both halves of that sentence would have missed.

---

## 10. Writing style

- Plain sentences. No marketing adjectives. If a capability is impressive, the
  measurement will show it.
- **No emoji in body text.** They survive badly in terminals, screen readers and
  cp1252 consoles, and this project's own logging has already been broken once
  by a non-ASCII glyph on a Windows console.
- Second person for instructions ("run", "open"), not "we".
- Every command is complete and copy-pasteable, with its working directory
  stated. A fragment the reader must assemble is not an instruction.
- British or American spelling — either, consistently within a page.
- Code fences carry a language.
- Tables for enumerable facts; prose for arguments.
- Never leave conversational or chat-transcript text in a document. It has
  happened; the gate now checks for it.

---

## 11. Accessibility

AA targets WCAG 2.1 AA, and its users include people on screen readers and
low-quality displays.

- Every image has alternative text.
- Links say where they go. Never "click here".
- Headings are hierarchical, never skipped for visual effect.
- Do not use colour alone to convey a status; use the marker word too.
- Tables have header rows; no merged or layout-only tables.

---

## 12. What the gate enforces

`tests/infrastructure/test_docs_gate.py` runs inside gate 1 and asserts:

1. Every page under `docs/` has front matter with `title`, `status`,
   `last_verified` (a valid ISO date) and `audience`.
2. Every relative link in every Markdown file resolves to a real path.
3. No document references a module that now lives in `old_retired_files/`.
4. Every package extra named in an install command is declared in
   `packages/auto_apply/pyproject.toml`.
5. Every ADR listed in the ADR index exists, and every ADR file is listed.
6. Every page under `docs/` is reachable from the MkDocs navigation.
7. `CITATION.cff` and `pyproject.toml` agree on the version.
8. No document contains conversational residue.
9. Readiness vocabulary (the "Stable"-style status table) appears only in
   `STATUS.md`.

**What the gate cannot catch:** whether a true-looking sentence is actually
true. It checks that documents are internally consistent and structurally
current. Only a human reading the code can check whether a claim is correct, and
that is what `last_verified` records.

Two further limits, stated rather than left to be discovered:

- **Link fragments are not validated.** Check 2 resolves the file a link points
  at and ignores any `#anchor` after it, so a link to a heading that does not
  exist still passes. This is deliberate. The table of contents in
  `AA_ARCHITECTURE_BIBLE.md` uses GitHub's double-hyphen slug for headings
  containing an em-dash, while python-markdown collapses it to a single hyphen;
  that file is read on GitHub and on this site, and correcting it for one breaks
  the other. MkDocs reports anchor mismatches at INFO, which is why
  `validation.anchors` is left at its default — the reason is written into
  `mkdocs.yml` so nobody raises it and then "fixes" the links into a broken
  state.
- **Status markers are not machine-checked.** Section 2 is a rule the gate does
  not enforce, because deciding which sentences are "significant claims" is a
  judgement no regular expression should be trusted with. It is enforced at
  review, and the list in `CONTRIBUTING.md` says so explicitly.

See [ADR-017](adr/017_documentation_gate.md) for why this is a gate rather than
a checklist.

---

## 13. Reviewing a documentation change

Name the **axis**, not the document. "Thin on derivation" is actionable in one
turn; "go deeper" produces length instead of depth.

Useful review questions:

- Does this sentence rule anything out? If not, delete it.
- What would make this document wrong?
- Where is the proof for that claim?
- What happens when this fails? Including: what happens when it hangs?

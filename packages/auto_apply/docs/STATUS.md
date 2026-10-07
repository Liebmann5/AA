---
title: Project Status
status: reviewed
last_verified: 2026-09-19
verified_against: "suite 1384 passed / 2 skipped; CI green on 6 legs"
audience: everyone
---

# Project Status

**This page is the single source of truth for AutoApply's readiness.** Readiness
is asserted here and nowhere else. If another document contradicts this one,
this one is right and the other is a defect — please
[report it](https://github.com/Liebmann5/AA/issues/new?template=documentation.yml).

**Last verified:** 2026-09-19 · **Commit:** `main` after PR #7 (`c415338`)

---

## One-line answer

AA is **pre-alpha**. It discovers and vets real job postings, fills forms, runs
from a USB stick, and has **never successfully submitted an application**.

---

## The headline measurement

Most recent full live run:

| Outcome | Count |
| --- | --- |
| Application attempts | 18 |
| **Submissions** | **0** |
| Recorded as stopped by CAPTCHA | 13 |
| Recorded as stopped by a login wall | 5 |

**Correction (2026-09-10): the two "stopped by" numbers are not trustworthy.**
They came from a substring search over the page source — any page containing
the text `recaptcha` anywhere, including inside an HTML comment, was recorded
as a CAPTCHA. Hand triage of 20 pages that verdict flagged found 12 were
ordinary rendered job postings (every LinkedIn page sampled was a false
positive) and only 8 were real challenges. A later run recorded three vetted
postings as CAPTCHA_BLOCKED seconds after vetting had read real job text from
those same URLs. The "login wall" count was never triaged at all. The
challenge verdict has since been rebuilt on page structure — challenge
markup, form count, rendered content — with the page title deliberately
ignored, and the pause now happens in place, on the challenging page.

The conclusion previously drawn here — that "the binding constraint today is
*access*, not comprehension" — is **withdrawn**. The honest summary is: AA
has submitted 0 of 18 attempts, the reasons recorded for most of those
failures are unreliable, and re-measuring with the corrected verdict is the
next milestone. The 0 stands; the 13 and the 5 do not.

---

## Status vocabulary

Used on every significant claim in every AA document. **A claim with no marker is
a defect in that document.**

| Marker | Meaning |
| --- | --- |
| `[LIVE]` | On a real execution path, exercised by a live run |
| `[WIRED]` | Connected and tested, not yet proven in a live run |
| `[PARTIAL]` | Works in some conditions; the boundary is stated |
| `[ORPHAN]` | Built, has no consumer. Exists in the tree and runs nothing |
| `[PLANNED]` | Decided, not built |
| `[GOAL]` | Intended direction; no design has been committed |

---

## Subsystem readiness

### Core

| Subsystem | Status | Evidence / boundary |
| --- | --- | --- |
| Hexagonal layering | `[LIVE]` | Boundary count asserted at an exact figure by an architecture pin |
| Composition root / dependency injection | `[LIVE]` | Whole object graph built in one file |
| Priority-queue orchestrator | `[LIVE]` | Single event loop; priority bands per ADR-011 |
| SQLite persistence (WAL) | `[LIVE]` | 14 tables |
| Seeded reproducibility | `[LIVE]` | Per-namespace RNG streams; required-namespace set pinned |
| Event bus | `[PARTIAL]` | Publishes broadly; subscriber inventory is pinned with an explicit exemption ceiling |

### Discovery

| Subsystem | Status | Evidence / boundary |
| --- | --- | --- |
| Bing provider | `[LIVE]` | The only provider that has yielded real postings in a live run |
| Google provider | `[PARTIAL]` | Yielded 0 postings in the last two runs — opaque redirect architecture |
| Indeed provider | `[PARTIAL]` | Yielded 0 postings in the last two runs |
| SERP extraction behind a port | `[LIVE]` | DOM miner retained as a committed fallback |
| URL resolution (7-stage, vendor-free) | `[LIVE]` | detect → climb → identity → static → relocate → activate → classify |
| Discovery output persistence | `[LIVE]` | Stored at discovery; survives a run that skips vetting |
| Company career-page mining | `[PARTIAL]` | Reachable for pasted careers URLs only |
| Pagination ("next page") | `[ORPHAN]` | Handlers exist, nothing constructs them |

### Vetting

| Subsystem | Status | Evidence / boundary |
| --- | --- | --- |
| Filter chain (title, location, skills, salary, throttling) | `[LIVE]` | |
| SpaCy semantic matching | `[LIVE]` optional | Behaviour changes measurably with and without the model — results are not comparable across the two |
| Local LLM for borderline decisions | `[WIRED]` optional | GPT4All; unproven at scale |

### Applications

| Subsystem | Status | Evidence / boundary |
| --- | --- | --- |
| Form field detection (mathematical DOM) | `[LIVE]` | Hungarian label-input pairing, structural hashing, honeypot detection |
| Form filling | `[WIRED]` | Fills correctly in tests and partial live runs; never carried through to a submission |
| Fail-closed submission gate | `[LIVE]` | Refuses rather than submitting unproven work (ADR-012) |
| **End-to-end submission** | **`[GOAL]`** | **0 of 18 attempts.** The single most important unmet milestone |
| Human-in-the-loop checkpoints | `[LIVE]` | CAPTCHA round trip verified live: gate opened, choice honoured, session resumed |
| Multi-page applications | `[WIRED]` | Advance logic exists; not proven past a real gate |

### Interfaces

| Subsystem | Status | Evidence / boundary |
| --- | --- | --- |
| Typed UI contract (`SessionRequest`) | `[LIVE]` | Both surfaces emit it (ADR-014) |
| CLI | `[LIVE]` | All four entry points, selectable exit axis |
| GUI (Tkinter) | `[LIVE]` | Parity with the CLI on entry points and labels |
| Activity stream | `[LIVE]` | Both dashboards poll the port (ADR-015) |
| Session history and results | `[LIVE]` | |
| Profile export / import | `[LIVE]` | Refuses overwrite without a flag; refuses path traversal |
| Autonomy control | `[LIVE]` | Two acknowledgements required; policy frozen at composition |
| `UIPort` has a typed consumer | `[PLANNED]` | Both surfaces still import `SessionController` directly |

### Portability and deployment

| Subsystem | Status | Evidence / boundary |
| --- | --- | --- |
| Windows / macOS / Linux | `[LIVE]` | Six CI legs green |
| USB portable mode | `[PARTIAL]` | Runs; `launch_portable.sh` has known containment defects, including not setting `SE_CACHE_PATH` |
| PyInstaller one-file build | `[PLANNED]` | Documented, not produced |
| Docker (test image) | `[WIRED]` | Test harness only, not a deployment target |
| Admin policy (`aa_policy.json`) | `[LIVE]` | |
| **Zero-browser operation** | **removed** | A live browser is required; AA refuses a session rather than faking one (ADR-013) |

### Research

| Subsystem | Status | Evidence / boundary |
| --- | --- | --- |
| Signal detectors | `[LIVE]` | 29 detectors |
| Consent gate, versioned | `[LIVE]` | Off by default |
| PII anonymisation (salted SHA-256) | `[LIVE]` | Sentinel pin; see the known scope gap below |
| NDJSON / CSV / JSON-LD export | `[LIVE]` | |
| Whole-journey research key | `[PLANNED]` | Today's records are application-scoped; discovery and vetting losses are not yet joined |
| Post-submission outcome tracking | `[PLANNED]` | Deferred, **not cancelled**; the join key must never be dropped |

---

## Quality gates

| Gate | State |
| --- | --- |
| Test suite | **1384 passed, 2 skipped** |
| `ruff check src --select F821` | Clean |
| `mypy src/auto_apply` | Clean across 264 files |
| `mypy --explicit-package-bases tests` | Clean |
| CI matrix | Green on `{ubuntu, windows, macos}` × `{3.10, 3.12}` |
| CI blocking since | 2026-09-05 |
| Documentation gate | Added 2026-09-19 (ADR-017) |

---

## Known defects

Highest first. These are the reasons AA is not alpha.

| ID | Defect | Impact |
| --- | --- | --- |
| L-6 | A test leaks a browser process; the shell does not return until a window is closed by hand | **The suite cannot run fully unattended** |
| L-8 | Company names truncate to one character in exports (10 of 14 rows in one run) | Research output is degraded; recoverable from the URL |
| L-9 | The exported `source` column always reads `history` | Which engine found a job is lost — the column you most want, given that only Bing yields |
| L-10 | The export dialogue defaults into the repository and describes plaintext as a convenience | A profile with real identity data was written to `packages/` |
| L-7 | Discovery yield is Bing-only | Two of three providers return nothing |
| ~~L-5~~ | **Fixed 2026-09-10 (item 12A):** the challenge pause now happens in place, on the challenging page, before any outcome is recorded; a solve continues the same attempt | Remaining: prove it on a live run |
| L-4 | `IDLE → ERROR_RECOVERY` is missing from the transition table | The dashboard shows `PAUSED` while the agent state is `IDLE` |
| L-1 | Settings cannot save a profile with an empty optional `Literal` field | Blocks editing for some profiles |
| L-2 | Two write paths disagree about résumé path portability | Onboarding breaks `--portable` for the users who need it |
| L-3 | The onboarding résumé picker starts blank and warns nobody at finish | Silent misconfiguration |
| F-9 | The PII sentinel pin does not cover the surface formatters | A formatter interpolating a profile field would slip through |
| F-10 | Authorisation evidence is in-memory only | The POLICY stamp exists during a run and not after it |

---

## What would change this page

| Milestone | Effect |
| --- | --- |
| One verified end-to-end submission | Applications move from `[GOAL]` to `[LIVE]`; the biggest blocker clears |
| L-6 fixed | The suite runs unattended; the release path opens |
| A second provider yields postings | Discovery stops being single-source |
| Five people who are not the maintainer run AA on their own machines | The definition of released is met |
| One full session on a 4 GB machine from a USB stick | The worst-case claim becomes measured rather than designed |

---

## How to check this page yourself

```bash
cd packages/auto_apply
uv run pytest tests -q -p no:cacheprovider -rs
uv run ruff check src --select F821 --output-format concise
uv run mypy --config-file ../../pyproject.toml src/auto_apply
uv run mypy --config-file ../../pyproject.toml --explicit-package-bases tests
```

If the numbers above no longer match, this page is stale. Updating it is part of
the change that made it stale, not a separate task.

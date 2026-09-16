# AA_MASTER_TODO — additions, updated 2026-09-16

Paste into `AA_MASTER_TODO.md`. Every row carries its proof. Status markers follow the existing
convention: **[VERIFIED]** = proven by execution, **[READ]** = asserted from source only.

**Suite at close of the frontend arc: 1384 passed, 2 skipped.**
CI gates: `ruff --select F821` clean on `src` and `tests`; `mypy src` clean across 264 files.

> **Fence convention:** code blocks indented two spaces.

---

# CLOSED

## BATCH 0 — the first-run identity defect · CLOSED 2026-09-15

Manifests `d4b8774e`, `4eae83b9`.

| # | Item | Status |
|---|---|---|
| B0-1 | GUI onboarding no longer loads `default_profile`; builds from scratch, collects all 11 required fields via `build_ui_schema` | **[VERIFIED]** live run created `Ant_B` with no template values |
| B0-2 | `validate_profile` gains a whole-profile template-contamination check; blocks at ≥2 matches, warns at 1 | **[VERIFIED]** |
| B0-3 | Settings gains an "About you" tab — the first screen where a GUI user can correct their own name, email, phone or address | **[VERIFIED]** |
| B0-4 | `default_profile.json` repaired: invalid `\` escapes (line 17) + a trailing comma (line 94) | **[VERIFIED]** parses |
| B0-5 | Settings Save button restored (pack order) + About-you tab scrolls | **[VERIFIED]** live |

**Ruling:** profiles already on disk carrying template identity are *accepted at load, rejected at
session start*, with a repair path in the GUI — failing toward blocking the irreversible action
(submission under a wrong name) over the reversible one (starting the tool).

**Why the threshold is ≥2:** the template's education entry is "Queen Mary University of London". A
real graduate typing their own school would be locked out by a 1-match rule. A user who actually
copied the template trips on ten fields at once.

## CHAIN A / U2 — the typed contract · CLOSED 2026-09-15

Manifests `9336e8b5`, `1627aff9`. Suite 1246.

| # | Item | Status |
|---|---|---|
| A-1 | `domain/models/ui_contract.py` — frozen, validated DTOs; `SessionRequest` carries the entry and exit axes as separate fields | **[VERIFIED]** |
| A-2 | `domain/ports/ui_port.py` — driving Protocol, satisfied structurally by `SessionController`, no wrapper | **[VERIFIED]** |
| A-3 | Legacy `initialize_session(dict)` becomes a translating shim; `direct_links` no longer raises | **[VERIFIED]** |
| A-4 | Two URL seeders collapsed into one parameterised by `execution_mode`; the priority 1-vs-3 split preserved and derived | **[VERIFIED]** |
| A-5 | `get_stats` no longer reaches through `orchestrator._session_report` | **[VERIFIED]** AST pin |
| A-6 | Event exemption inventory shrank by 8 | **[VERIFIED]** |

**Rulings:** the port returns a null-object snapshot rather than `None` when no session is running,
so adapters never branch. The legacy shim **translates** the CLI's five keys rather than rejecting
them, so the silently-discarded answers were honoured one stage early.

**Correction on record:** `vet` maps to `VET_AND_APPLY`, not `VET_ONLY`. Legacy `vet` applied to
whatever passed vetting; `VET_ONLY` would have silently narrowed a mode. Claude supplied the wrong
row from an enum name; Kimi traced the legacy docstring and caught it.

## CHAIN B / U3 — both surfaces on the contract · CLOSED 2026-09-15

Suite 1271.

| # | Item | Status |
|---|---|---|
| B-1 | `CLIWizard.run()` returns a `SessionRequest`; `startup.py` passes it through. **The typed answers now reach the queue** — this closes the original defect | **[VERIFIED]** live |
| B-2 | The exit axis is selectable: collect links / collect and check / collect, check and apply | **[VERIFIED]** live |
| B-3 | `providers` added to `SessionRequest`; engine choice reaches the discovery fan-out | **[VERIFIED]** live — `providers=('google','bing')`, Indeed absent because deselected |
| B-4 | GUI wizard reaches parity: all four entry points, same labels from one source | **[VERIFIED]** |
| B-5 | `strategy` prompt deleted — the wizard asked a question nothing read | **[VERIFIED]**; two places in the codebase already said so in writing |

**Found while tracing `providers` to a real consumer:** `orchestrator.session_plan = new_plan`
replaced the plan object while `DiscoveryWorkflow` and `ApplicationsWorkflow` held their own
reference to the **boot** plan from `composition_root`. **No request-scoped value had ever reached
the workflows** — the result cap a user typed had never once been applied. A plan-level pin passed
while the scraper read a stale plan. Fixed in the same change.

## CHAIN C — output, history and custody · CLOSED 2026-09-15

Suite 1312.

| # | Item | Status |
|---|---|---|
| C-1 | Discovered jobs persist **at discovery**, not at vetting — `add_job` previously had exactly one caller (`vetting_workflow.py:363`), so any mode skipping vetting found jobs and discarded them | **[VERIFIED]** |
| C-2 | Anti-poisoning: a collect-only run does not mark URLs as seen and shrink a later full search | **[VERIFIED]** teeth pin |
| C-3 | Sessions that drain their queue are recorded as completed — history was previously a biased sample of abandonments only | **[VERIFIED]** |
| C-4 | `export_profile` on the port and both surfaces, symmetric with `import_profile`; refuses overwrite without an explicit flag, refuses path traversal, does not mutate encryption state | **[VERIFIED]** 4 pins |
| C-5 | Results and session history surfaced and exportable on both surfaces | **[VERIFIED]** live |
| C-6 | `list_reports` sorts by the session's own `started_at`, not file mtime | **[VERIFIED]** 3 cases |

**Why the sort key mattered beyond the failing test:** mtime is a property of the *file*. Copy a
reports directory to a USB stick and every timestamp becomes the copy time, so the history order
collapses — wrong on principle for a tool whose story is "take your data with you", not merely
flaky on Windows.

## CHAIN D — the activity stream · CLOSED 2026-09-15

Suite 1335.

| # | Item | Status |
|---|---|---|
| D-1 | 47 internal events project to a small `ActivityKind`; the raw `Event` no longer crosses the port | **[VERIFIED]** |
| D-2 | Both dashboards render the stream; `Dashboard.log_message` finally has a caller | **[VERIFIED]** |
| D-3 | **Both surfaces poll the port; neither subscribes to the bus.** Both already ran refresh loops (CLI 1.0 s, GUI 500 ms), so this removed the last two push paths rather than adding polling | **[VERIFIED]** pin asserts `.subscribe(` in neither dashboard |
| D-4 | `UIMessageHandler` retired to `docs/old_retired_files/`; its reachability exemption removed | **[VERIFIED]** |

**Ruling:** the gate is polled like everything else. A subscription imports `domain.events` and
reaches `orchestrator.event_bus` — exactly the coupling the port removes, and it would have to be
unwound at U4. Polling costs ≤1 s of notice on a gate that holds for up to 300 s.

## CHAIN E — safety pins and autonomy · CLOSED 2026-09-16

Manifest `e4389e49`. Suite 1384.

| # | Item | Status |
|---|---|---|
| E-1 | `test_safety_pins.py`: PII sentinel (teeth) + two ratchets | **[VERIFIED]** all three mutation-tested |
| E-2 | Autonomy is a real control on both surfaces, through the port | **[VERIFIED]** |
| E-3 | `set_autonomy` refuses with fewer than two acknowledgements — a surface cannot skip a warning screen | **[VERIFIED]** |
| E-4 | `AnsweredBy.POLICY` is stamped. It had been declared (`:188`), documented (`:181`) and written by **nothing** | **[VERIFIED]** |
| E-5 | The interrupt policy is frozen at composition; `set_autonomy` writes the profile but never touches a built policy | **[VERIFIED]** AST guards |

**Ruling — immutability at composition.** Two of the three candidate failure modes (a malicious
mid-run profile edit, a config reload) are *already* structurally unreachable; nothing re-reads the
profile. The one that isn't is a future coding error, and the guarantee was **true only by accident
and unpinned**. The sharpest catch: `set_autonomy` writes the profile, and if it also rebuilt a
live policy the guarantee would become false *by design* — so the control never rebuilds, and AST
guards pin it.

**Simplification:** `applications_workflow.py` needed no edit for the POLICY stamp. With autonomy
on the gate is never consulted, so `autonomy() AND outcome in (SUBMITTED, PROBABLY_SUBMITTED)`
proves policy authorisation with no new payload field to trust.

## STAGE U5 / "CHAIN F" — CANCELLED 2026-09-16

Planned as a deletion. Both targets turned out load-bearing:

- **The four "backward-compatible" keys** in `session_report.get_stats()` are now typed fields on
  `SessionSnapshot` and `SessionSummary` (`ui_contract.py:370, :413, :431`) and are read by
  `checkpoint_manager.py:452`. Deleting them breaks the checkpoint manager. The comment was the
  stale thing, not the keys — corrected in place.
- **The dict shim** has no production caller (`cli/startup.py` and `gui/app.py` both pass a
  `SessionRequest`) but **eight pins exercise it on purpose**, including the guard that legacy
  `{"mode": "discovery", "input": "X"}` still queues what it queued before the port existed. Those
  pins are the evidence Chain A did not break the ~1,200 tests that predated it.

Recorded in `AA_ARCHITECTURE_BIBLE.md` §24.3 so nobody reads the old plan and removes them.

---

# OPEN

## P0 — blocks CI

| # | Item | Evidence |
|---|---|---|
| **L-6** | **A test leaks a browser process.** `pytest tests -q` reports ~110 s but the shell does not return until the window is closed by hand — a live child process holds the pipe. Reproduced on four separate runs. **The suite cannot run unattended, so CI cannot run it.** Likely the same root cause as the orchestrator teardown: `Orchestrator thread did not exit within 10s` with urllib3 retrying `/session/<id>` against a dead driver. One defect, two symptoms. Candidates: `tests/integration/test_form_filling.py`, `tests/integration/test_multipage_live_run.py` — both carry the class-scoped-fixture deprecation warning | 4 runs + live log |

## P1 — frontend residue

| # | Item | Evidence |
|---|---|---|
| F-6 | **`UIPort` is 17 methods and session-shaped.** Identity and custody parity cannot be pinned until it widens — census §7's rows stay unpinned | `ui_port.py` |
| F-7 | **`UIPort` has no consumer.** WIRE-LATER exemptions in `KNOWN_UNWIRED_PORTS` *and* `KNOWN_UNREACHABLE`, both ceilings raised (22→23, 50→51). Removal trigger recorded: delete when `gui/app.py` and `cli/startup.py` type against `UIPort` at U4 | **[VERIFIED]** |
| F-8 | **A circular assertion.** `test_dict_and_private_shim_agree_on_execution_mode_for_every_label` computes `expected` from `_LEGACY_ENTRY_TO_EXECUTION_MODE` — the table the shim consumes. Door drift fails; a wrong table row passes. Mutation-tested both ways. **Fix, specified:** in `test_legacy_dict_shim_still_queues_what_it_queued`, assert the seeded `WorkUnit`'s `context_data["execution_mode"]` against string **literals**, and assert `SessionExecutionMode("vet_and_apply").includes_application is True` — pinning the semantic independently of the map | **[VERIFIED]** by mutation |
| F-9 | **The PII sentinel pin is scoped too narrowly.** `test_no_pii_in_the_activity_stream` walks attribute chains only in `session_controller.py`. The surface formatters — `gui/app.py::format_results_lines`, `format_history_lines`, `cli/dashboard.py` — are not covered, so a formatter interpolating a profile field slips through. **Fix:** extend the chain-walk to an allowlist of formatter modules | Kimi review Q3b |
| F-10 | **`approval_evidence()` is in-memory only.** The POLICY stamps this arc added live on the controller; the on-disk session JSON does not carry them. A research-durability gap — the label exists during the run and not after it | Kimi review Q3c |
| F-11 | **U4 — retype both surfaces against `UIPort`.** Drives the reach ratchet to empty (12 imports across 6 files, four importing `SessionController` directly), clears F-7's two exemptions, and makes a real parity pin possible | `test_safety_pins.py` |
| F-12 | **The reach ratchet has a known blind spot**, by design: it only flags imports outside `auto_apply.domain.*` and `auto_apply.adapters.primary.*`, so an adapter importing a domain module that has quietly grown UI-shaped methods passes silently | Kimi review Q2 |
| F-13 | **Five print sites remain outside the primary adapters** (four in `session_controller`, one in `composition_root`). The four are the Profile Check advisory — it goes to stdout, so **a GUI user never sees it**. `main.py`'s 39 are exempt by design | `test_safety_pins.py` |

## P1 — defects found by live runs

| # | Item | Evidence |
|---|---|---|
| L-1 | **Settings cannot save a profile with an empty optional Literal.** `suffix` is a `Literal[...]`; the About-you tab renders it as free text and an empty box submits `""`. Two halves, one fix: an empty optional must become `None`, and the tab must pick its widget from the schema's `options` rather than from the value's Python type. `build_ui_schema` already emits `options` and the Search tab consumes them via `_field_options` | live run, `literal_error` |
| L-2 | **Two write paths for `resume_path` disagree about portability.** Onboarding stores the raw absolute path; the settings editor stores `make_portable_path(...)`. A profile created in onboarding breaks `--portable` for exactly the users who need it | `gui/app.py` vs `settings_editor.py` |
| L-3 | **The onboarding resume picker starts blank and readonly**, populating only if the user clicks Browse, with no warning at finish if they didn't | live run |
| L-4 | **`IDLE → ERROR_RECOVERY` is not in the transition table.** Closing the browser while idle blocks the transition three times as a WARNING; the orchestrator pauses its loop anyway, so the dashboard reads `PAUSED` while `AgentState` is `IDLE` | live log ×3 |
| L-5 | **The HITL gate opens after the application is already dead** — 53 s after `outcome=CAPTCHA_BLOCKED` was recorded. Solving the challenge cannot rescue it; the gate can only observe that one died. **Belongs to the gate-crossing arc** | live log timestamps |
| L-7 | **Discovery yield is Bing-only.** Google 0 and 0 ("opaque redirect architecture"), Indeed 0 and 0, Bing 6 and 3 | live log |
| **L-8** | **Company names truncate to one character.** 10 of 14 in one export: `H` for Harris Oakmark, `S` for Specialist Staffing Group, `P` for Publicis Groupe, `C` for Cloudbeds, `F` for FIS. ZipRecruiter survives; LinkedIn and Glassdoor do not. The full name sits in the URL (`...-at-harris-oakmark-...`), so it is recoverable | exported CSV |
| **L-9** | **The exported `source` column always reads `history`.** All 14 rows. `get_recent_jobs` rehydrates with a hardcoded `source="history"`, so which engine found a job is discarded on the read path — and given L-7 that is the column you most want | exported CSV |
| **L-10** | **The export dialog defaults into the repository and calls plaintext a convenience.** It opened at the repo root and wrote a profile carrying real name, email, phone and LinkedIn/GitHub URLs to `packages/`, confirming with *"plaintext JSON — readable on any machine, no password needed"* as though that were a feature. `.gitignore` matched nothing. **The dialog should default outside the working tree and that message should read as a warning** | live run |

**L-8 and L-9 were invisible for the project's entire life** and surfaced within minutes of results
having a screen. Worth remembering when weighing whether a surface is "just UI".

## P2 — CAPTCHA detector arc (independent of the frontend)

| # | Item |
|---|---|
| D-1 | The block detector fires on a **substring** match (`cf-turnstile`) with `weighted=false agree=no forms=0 iframes=0`. A live run showed three consecutive `CAPTCHA detected` outcomes on pages that had already loaded job content. Verify how many are real blocks versus page furniture before changing the rule |
| D-2 | `detector_samples` hit its 20-file cap during a 6-minute run — "further disagreements are logged but not dumped". The cap fills faster than the evidence is reviewed |
| D-3 | Triage the existing samples before writing any new rule. A substring-matching detector is the wrong *kind* of fix; the disagreement data says which kind is right |

## P3 — future, not now

| # | Item |
|---|---|
| N-1 | **Post-submission outcome tracking** (responses, interviews). Deferred, *not cut* — likely post-TTK. Three things must stay true: the `attempt_id` + `page_index` join key must never be dropped, `applied_jobs` must stay durable, and the session summary must remain a **projection over stored records**, never a computed-and-discarded snapshot |
| N-2 | **Secure document store.** The library/shared-computer case needs AA to store, access and hand back user files safely — not just hold a path to a file on someone else's disk. Larger than `resume_path`; scope it when the resume work comes up |
| N-3 | **File preview before save, user-toggleable.** When a user picks a file, show it so they can confirm it is the right one. Default-on or default-off is itself a decision; the toggle is the requirement |
| N-4 | **The alpha usability protocol** (`AA_ALPHA_USABILITY_PROTOCOL.md`). Its precondition is met — `DISCOVER_ONLY` is selectable and structurally cannot submit, which is the only no-submit guarantee AA has since there is no `--dry-run` anywhere. Still outstanding: the ethics route (no IRB without an affiliation; approval cannot be granted retroactively), and a pilot on one throwaway participant before the five |

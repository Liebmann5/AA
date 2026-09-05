# `old_retired_files/` — the retirement directory

**Established 2026-08-30. This directory replaces deletion.**

## The rule

**Nothing in this project is deleted.** Code that is orphaned, obsolete, superseded, abandoned, or
merely embarrassing is **retired** — moved here with its original path recorded on line 1 and its
story recorded in the ledger below. The reason is evidence, not sentiment: four modules were removed
on 2026-08-30 as "unimportable dead code", and within hours the pin that was supposed to prove them
dead turned out to be the thing that was broken. A file that looks worthless is usually a file whose
context has been lost, and context is exactly what this directory preserves.

**Before writing any new code, feature, tool, or module, you must check this directory first.** Not
as a courtesy — as a required step, the same way you would check whether a function already exists
before writing it. This project's defining defect is capability that was built and never connected;
building a second copy of something already sitting here is the same defect with extra steps. The
ledger below is the index. Search it before you search your memory.

## Personal data never comes in here

**This directory is part of the repository. Everything in it is committed, pushed to Codeberg, and
shipped to every person who clones AA.** That makes it the wrong place for anything that is not
source, and a dangerous place for anything about a person.

**Never retire:**

- `dev_data/` in any form — the profile database, `aa_data.db`, session rows, the work queue.
- Screenshots. AA writes them on navigation failure and they routinely contain a real name, address,
  email, employment history and whatever else was on the form at the moment it failed.
- Logs — `app.log` and its rotations. The PII filter is known to be imperfect (its unanchored pattern
  destroys roughly one task ID in six and its own substitution re-matches), so a log is not safe
  merely because it was filtered.
- `.env`, API keys, cookies, browser profile directories, session storage.
- Résumés, cover letters, or any document a user supplied.
- Test fixtures captured from a live run against a real account.

**Before retiring any file, read it.** A module is source and belongs here; a module with a real
postcode in a hardcoded test constant does not. If a file mixes the two, retire the code and strip
the data first — the ledger row records that you did, and what you removed.

`retire.py` refuses paths under `dev_data/`, `.env`, `.venv`, `__pycache__` and `.kimi_out/`
outright, and `kimicli.py` will not let the model write into `dev_data/` or into this directory at
all. Those are backstops, not the check. **The check is you reading the file.**

**Why this matters more here than elsewhere.** AA's stated custody model assumes the worst case: a
library or careers-centre computer, a user who cannot see the property that makes their situation
dangerous. A retired file is *more* exposed than a live one, not less — it is out of sight, nobody
runs it, nobody reviews it again, and it stays in the repository and in git history forever. Data
that leaks through this directory leaks quietly and permanently.

**If personal data does reach here,** removing the file in a later commit does not remove it from
history. Say so plainly in the ledger, and treat it as a disclosure incident: history rewrite plus
rotation of anything credential-shaped. Not deleting is a policy about *work*; it was never a policy
about *someone else's data*.

---

**Out of scope:** build artefacts and environment directories — `__pycache__/`, `.venv/`, `.pytest_cache/`,
`*.pyc`, `.kimi_out/`, log rotations, coverage output, anything regenerable by running a command.
Those are deleted normally. The rule protects *authored work*, not machine output.

**What this buys, beyond safety.** Retiring is cheap and reversible, so nothing has to be argued
about before it is moved. That is what makes it acceptable to mark a large batch of orphans at once:
the cost of being wrong drops from "lost work" to "one `git mv` back". A decision that is cheap to
reverse can be made quickly and honestly; a decision that destroys something cannot.

---

## How to retire a file

From the repository root:

```powershell
python retire.py packages/auto_apply/src/auto_apply/domain/services/entropy.py "0 importers; math chain with occlusion + honeypot_detection; keep for rewiring"
```

The script does three things and nothing else:

1. `git mv` (falls back to a plain move outside git) into
   `packages/auto_apply/docs/old_retired_files/<the file's original relative path>`.
   The directory structure is preserved, so two files named `base.py` never collide and the origin
   is obvious from the path alone.
2. **Shifts the file's contents down one line** and writes the original repository-relative path
   into the new line 1, as a comment in that file's own comment syntax
   (`#` for `.py`/`.yaml`/`.toml`/`.ps1`/`.sh`, `//` for `.js`/`.ts`, `<!-- -->` for `.md`/`.html`).
   Formats with no comment syntax — `.json` and `.bat` in particular — are moved unchanged and
   recorded in the ledger only. `run.bat` below is the live example: its origin exists only in the
   ledger row and in the directory layout, so **do not flatten this directory**.
3. Prints the ledger row for you to paste below.

**Recalling a file** is `git mv` in the other direction, then delete line 1. Move the ledger row from
RETIRED to RECALLED and say what changed your mind — a recall is the most useful entry in this file,
because it is direct evidence about how good this project's "this is dead" judgements actually are.

---

## RETIRED — currently in this directory

| Retired | File | Original path | Why retired | What it was / how far it got | Reusable? |
|---|---|---|---|---|---|
| 2026-09-05 | `run.bat` | `packages/auto_apply/run.bat` | PKG-1: ~400 lines across the pair duplicating uv + `pyproject.toml`; its pip extras selector named a group that never existed, so the documented test path installed nothing and aborted at collection on `import hypothesis` | 237 lines — complete, working Windows launcher: detects Python, creates `.venv`, installs the package, offers an **interactive extras menu** (`ai` / `nlp` / `full` plus a consented spaCy model download), and dispatches subcommands. Broken in exactly one place, fatally: `pip install -e "<dir>[dev]"` selected an extra that was never declared — dev tooling lives in the workspace-root PEP 735 `[dependency-groups] dev`, which pip's extras syntax cannot read — so `run.bat test` installed nothing and then aborted on `import hypothesis`. Same failure that broke the Docker test image, and the same instruction survived in `CONTRIBUTING.md §1.1`. **The piece worth recovering is the interactive extras menu**: it is the only place AA ever asked before installing anything, which is hard principle 2 in working form. Rebuild it as a small Python prompt in the CLI, not as a shell script. | SUPERSEDED-BY `uv` + `pyproject.toml` |
| 2026-09-05 | `run.sh` | `packages/auto_apply/run.sh` | PKG-1: POSIX twin of `run.bat`, same duplication and the same broken `[dev]` selector | 93 lines — complete POSIX launcher: venv creation, editable install with the same non-existent `[dev]` extras selector, subcommand dispatch. No interactive extras menu — that lived only in the Windows twin. Nothing here is worth recovering that `uv sync` does not already do from one declaration on all three operating systems; it is recorded because the *pair* is the evidence for why launcher logic belongs in `pyproject.toml`. `launch_portable.sh` deliberately SURVIVED this retirement — it is deployment config, not package management, and `selenium_provider.py:464-521` reads the env vars it exports. | SUPERSEDED-BY `uv` + `pyproject.toml` |
| 2026-09-02 | `telemetry.py` | `packages/auto_apply/src/auto_apply/application/services/telemetry.py` | recovered from git; broken import 'APP_DATA_DIR' from domain.config | 127 lines — complete, working Bayesian confidence tracker. Subscribes to `FORM_FIELD_FILLED/FAILED` and APPLICATION_SUBMITTED/FAILED, keeps per-domain per-strategy success/fail counts with Laplace smoothing, exposes `get_confidence_score(url, key)`. `PageActionService` was meant to consult it before trusting a cached selector and never did. Only the one import is broken. | AFTER-REWIRE |
| 2026-09-02 | `heuristic_adapter.py` | `packages/auto_apply/src/auto_apply/adapters/secondary/perception/heuristic_adapter.py` | recovered from git; broken import 'settings' from domain.config; sole caller of the humanised scrollers | 166 lines — complete ARIA-role container finder. Scans for role=tree/feed/list, falls back to generic tags, scores candidates by valid-child count, traverses iframes via `ContextManager`. Its `_trigger_lazy_load` is the ONLY caller behavior.`human_like_page_scan` ever had — recovering it restores the route back for the humanised scrollers (AD-10, Appendix B #11). | AFTER-REWIRE |
| 2026-09-02 | `location_extractor.py` | `packages/auto_apply/src/auto_apply/application/services/location/location_extractor.py` | recovered from git; requires flashtext, not installed | 49 lines — complete thin wrapper over FlashText's Aho-Corasick automaton for O(N) city/state extraction from job descriptions. Works as written once the dependency is added. | AS-IS |
| 2026-09-02 | `fingerprint_js.py` | `packages/auto_apply/src/auto_apply/adapters/secondary/evasion/fingerprint_js.py` | recovered from git; imports ..core.config which does not exist | 22 lines — stub. Two patches only: navigator.webdriver spoof and hardwareConcurrency. The import target never existed at that path. Superseded in scope by `fingerprint_chrome.py` / `fingerprint_firefox.py`, which are themselves unwired. | IDEA-ONLY |

---

## RECALLED — came back out

| Retired | Recalled | File | What changed the verdict |
|---|---|---|---|
| *(none yet)* | | | |

---

## PRE-POLICY LOSSES — deleted before this directory existed

These four were removed on 2026-08-30, before the no-delete rule. **They are recoverable from git
history and should be recovered into this directory** rather than left as a gap — they are the exact
case that motivated the policy.

| File | Original path | Why it was deleted | Standing |
|---|---|---|---|
| `fingerprint_js.py` | `src/auto_apply/adapters/secondary/evasion/fingerprint_js.py` | raised on real import; unreachable from every entry point | Evasion work is deferred, not cancelled. Recover. |
| `telemetry.py` | `src/auto_apply/application/services/telemetry.py` | `from auto_apply.domain.config import APP_DATA_DIR` — a name that does not exist | The import was broken; the *idea* was not. Recover. |
| `heuristic_adapter.py` | `src/auto_apply/adapters/secondary/perception/heuristic_adapter.py` | same broken-import shape | **Highest recovery value.** It was the only constructor of the three humanised scroll functions, which are now orphaned with no route back (Appendix B #11). Recover. |
| `location_extractor.py` | `src/auto_apply/application/services/location/location_extractor.py` | same shape | Location work is live (`haversine.py` is itself orphaned). Recover. |

To recover one:

```powershell
git log --diff-filter=D --name-only --oneline -- "*telemetry.py"
git checkout <the commit before the deletion>^ -- packages/auto_apply/src/auto_apply/application/services/telemetry.py
python retire.py packages/auto_apply/src/auto_apply/application/services/telemetry.py "recovered from git; retired under the 2026-08-30 policy rather than deleted"
```

---

## Ledger conventions

- **One row per file, per direction.** A file that is retired, recalled, and retired again gets three
  rows. The history is the point.
- **"Why retired" is a proof, not an opinion.** `0 importers, confirmed by grep` — not `looked unused`.
- **"What it was / how far it got"** is the field that earns this directory its keep. Two sentences:
  what the thing does, and how complete it is. *"Full 4-strategy pagination cascade, working, never
  reachable because `max_pages_per_query=1` makes `range(1,1)` empty"* saves someone a week.
  *"Old pagination code"* saves nobody anything.
- **"Reusable?"** — one of `AS-IS` · `AFTER-REWIRE` · `IDEA-ONLY` · `SUPERSEDED-BY <name>`.
- **If you stripped data before retiring, say so** in the "Why retired" cell: `data stripped: 2
  hardcoded postcodes` . A reader must never wonder whether the file they are looking at is the
  whole file.
- Update this file **in the same change that moves the file.** A ledger updated later is a ledger
  that is wrong in between, which is how the project's docs got into the state they are in.

## Disposition tags used elsewhere

The architecture pins' exemption dicts (`KNOWN_UNWIRED_PORTS`, `KNOWN_UNREACHABLE`) tag every entry
with a disposition. Since 2026-08-30 the vocabulary is:

`WIRE-LATER` · `RETIRE-CANDIDATE` · `PLANNED` · `TEST-ONLY`

There is no `DELETE-CANDIDATE`. An entry tagged `RETIRE-CANDIDATE` leaves `src/` by arriving here.

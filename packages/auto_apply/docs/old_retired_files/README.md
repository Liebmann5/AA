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
| 2026-10-06 | `classifier.py` | `packages/auto_apply/src/auto_apply/adapters/secondary/dom/classifier.py` | PageClassifier superseded by the one page verdict (domain/services/page_assessment.py); its only constructor, `serp_strategy._page_block_type`, now asks `assess_page` | 143 lines — complete, working page classifier that ran JavaScript in the live page through the browser. Order: challenge (via `DefaultDetectionStrategy`), a **title-only** 404 check, JSON-LD JobPosting (returned as SERP), login page, a **title-only** success check ("thank you", "application submitted"), application form. Built fresh on every call; one live WebDriver round trip per probe. Its challenge answer disagreed with `challenge_assessment` on the same page. The title-based 404 check was carried into the verdict as labelled debt. | SUPERSEDED-BY `packages/auto_apply/src/auto_apply/domain/services/page_assessment.py` |
| 2026-10-06 | `page_classification_port.py` | `packages/auto_apply/src/auto_apply/domain/ports/page_classification_port.py` | port of the retired PageClassifier; the verdict is a pure function and needs no port | 24 lines — the `PageClassifierPort` protocol (`classify() -> PageType`). Never wired: `test_port_wiring.py` carried it as a WIRE-LATER exemption because `GenericSERPStrategy` built the concrete class instead. Recall only if a live-probe verdict is ever needed; the pure snapshot verdict was ruled sufficient. | SUPERSEDED-BY `packages/auto_apply/src/auto_apply/domain/services/page_assessment.py` |
| 2026-10-06 | `detection.py` | `packages/auto_apply/src/auto_apply/adapters/secondary/evasion/detection.py` | weighted-substring detection superseded by the structural verdict in page_assessment | 306 lines — `DefaultDetectionStrategy` scored title words, page text, URL substrings and selectors against `detection_config.json` (live threshold 60); `CloudflareDetectionStrategy` had no consumer; a module-level `is_challenge_present(browser)` fed `EvasionManager`. Matched English keywords in titles and raw text, and the URL substrings `blocked` / `denied`, which misfire on ordinary URLs. **Salvaged before retiring:** the `/verify/` URL marker and the `cf-spinner` class, lifted into `challenge_assessment.py`. | SUPERSEDED-BY `domain/services/challenge_assessment.py` + `packages/auto_apply/src/auto_apply/domain/services/page_assessment.py` |
| 2026-10-06 | `detection_config.json` | `packages/auto_apply/src/auto_apply/adapters/secondary/evasion/detection_config.json` | config for the retired detection strategies; sole reader was detection.py | 70 lines — keyword, selector and weight tables for `DefaultDetectionStrategy`. Carried two disagreeing thresholds: a live `threshold: 60` and an unread `confidence_weights` / `confidence_threshold: 70` block whose own comment said 70 was the intended value. Moved unchanged (JSON has no comment syntax); its origin is recorded here only. | SUPERSEDED-BY `packages/auto_apply/src/auto_apply/domain/services/page_assessment.py` |
| 2026-10-06 | `manager.py` | `packages/auto_apply/src/auto_apply/adapters/secondary/evasion/manager.py` | EvasionManager superseded; both discovery gates ask assess_page directly | 70 lines — `EvasionManager.check_page_safety()` wrapped `detection.is_challenge_present`, with a 5-second retry sleep whose recheck result was discarded. Constructed only for Indeed. Its `on_captcha_detected` default (`"skip"`) disagreed with `AppSettings` (`"stop"`), so one setting had two defaults. When it reported a block, Indeed returned no jobs **without recording a blocked observation**, so research undercounted Indeed blocks; the verdict path now records one. | SUPERSEDED-BY `packages/auto_apply/src/auto_apply/domain/services/page_assessment.py` |
| 2026-10-06 | `auditor.py` | `packages/auto_apply/src/auto_apply/adapters/secondary/evasion/auditor.py` | 0 importers in src (only the reachability pin named it); vendor probe salvaged as verdict signals; the ip-api call not salvaged | 195 lines — an unwired evasion audit display: gathered a `BrowserStateSnapshot` (fingerprint, JS environment, DOM metrics, Chromium-only console logs) and printed a report. Called `http://ip-api.com/json` — sending the user's IP to a third party, over plain HTTP — which conflicts with AA's no-unnecessary-network rule. **Salvaged:** its anti-bot vendor probe (Cloudflare, Akamai, DataDome, PerimeterX page globals), now `vendor:*` annotation signals on the verdict, never persisted (remembering vendors per site is a ruled future feature). | IDEA-ONLY |
| 2026-10-06 | `browser_state.py` | `packages/auto_apply/src/auto_apply/domain/browser_state.py` | snapshot models used only by the retired evasion auditor; 0 importers after it left | 110 lines — six pydantic models (`EvasionProfile`, `NetworkProfile`, `BrowserFingerprint`, `DOMMetrics`, `JSEnvironment`, `BrowserStateSnapshot`) describing what a page can observe about the browser. Complete as data shapes; nothing but `auditor.py` ever filled them. Worth recalling if AA ever records what pages can observe for research. | AS-IS |
| 2026-10-06 | `test_classifier_probe.py` | `packages/auto_apply/tests/application/test_classifier_probe.py` | PageClassifier retired; its pins moved to test_serp_block_gate.py and test_page_assessment.py | 262 lines, 10 tests (one parametrized) — pinned the classifier's probe order and the removal of its slow mine-probe (measured at ~40 s per SERP). The mine-count pin was ported to `test_serp_block_gate.py`; the classification cases are covered by `test_page_assessment.py` over the same page shapes. | SUPERSEDED-BY `tests/workflows/test_page_assessment.py` |
| 2026-10-06 | `__init__.py` | `packages/auto_apply/src/auto_apply/adapters/secondary/dom/__init__.py` | empty package after classifier.py was retired; the reachability pin flagged it as an orphan | 1 line — the package docstring "DOM-inspecting adapters (page classification)". Retired with the package's only module. Recall alongside `classifier.py`. | SUPERSEDED-BY `packages/auto_apply/src/auto_apply/domain/services/page_assessment.py` |
| 2026-10-01 | `process.py` | `packages/auto_apply/src/auto_apply/adapters/secondary/os/process.py` | never wired, and could not work as built; superseded by an explicit idempotent AgentOrchestrator.shutdown() reachable from every exit, plus a weak atexit net (item 1, the browser leak) | 122 lines. A JSON registry of child PIDs, with create-time checks against PID reuse, and a cleanup_all() reaper. register() ran on every Selenium launch, but Selenium 4.48 exposes no browser PID, so it recorded the chromedriver/geckodriver PID instead. cleanup_all() had zero callers; called by hand (measured 2026-10-01) it killed chromedriver while all 9 Chrome processes and the profile lock survived, and the next launch was still refused. One registry per USER_DATA_DIR with no owner field, so two AA processes would reap each other's drivers; entries were never pruned. | SUPERSEDED-BY `AgentOrchestrator.shutdown()` in `packages/auto_apply/src/auto_apply/application/agent/orchestrator.py` |
| 2026-09-28 | `parquet_exporter.py` | `packages/auto_apply/src/auto_apply/adapters/secondary/research/parquet_exporter.py` | superseded by research_exporter.py (item 4b): bundle export with total ordering, the provenance public key, and no failure path that yields a plausible empty file | 170 lines. Three near-identical `export_*` methods over three of the six research tables; `job_lifecycles`, `application_outcomes` and `research_provenance` had no export path at all, so the Ed25519 public key every signature verifies against could not leave the database. `ORDER BY` was on day-granular date columns, so two exports of one database could differ. `_query` swallowed every exception into `[]` and `_write_csv` wrote an empty file for zero rows, making a locked database indistinguishable from an empty corpus. Had no tests. | SUPERSEDED-BY `packages/auto_apply/src/auto_apply/adapters/secondary/research/research_exporter.py` |
| 2026-09-27 | `INSTALL.md` | `INSTALL.md` | one of three disagreeing install documents; superseded by the single canonical guide | 206 lines. 209 lines - a complete install guide. Ordered source-first and pip-second, and documented `pip install auto_apply` from PyPI, where AA has never been published. Its USB and troubleshooting material was folded into the canonical guide. | SUPERSEDED-BY `packages/auto_apply/docs/getting_started/installation.md` |
| 2026-09-27 | `INSTALL.md` | `packages/auto_apply/docs/INSTALL.md` | second of three disagreeing install documents; superseded by the single canonical guide | 232 lines. 234 lines - a near-duplicate of the root INSTALL.md with the two methods in the opposite order, so the two disagreed about which path was recommended. Also documented a PyPI install that does not exist. | SUPERSEDED-BY `packages/auto_apply/docs/getting_started/installation.md` |
| 2026-09-27 | `CONTRIBUTING.md` | `packages/auto_apply/CONTRIBUTING.md` | moved to the repository root, where GitHub's community profile looks for it | 217 lines. 220 lines. Sections 1 and 8 were accurate and detailed - the uv bootstrap, the four gates and the asymmetric mypy flags - and were carried into the root copy unchanged. Section 2 described `dev`, `prod` and `release/` branches that do not exist; the root copy documents the real `main`-only model. | SUPERSEDED-BY `/CONTRIBUTING.md` |
| 2026-09-27 | `CODE_OF_CONDUCT.md` | `packages/auto_apply/CODE_OF_CONDUCT.md` | moved to the repository root, where GitHub's community profile looks for it | 32 lines. 34 lines - a short Contributor Covenant reference without the enforcement ladder, the reporting contact or the scope section. The root copy is the full Covenant 2.1 plus a clause specific to this project's users. | SUPERSEDED-BY `/CODE_OF_CONDUCT.md` |
| 2026-09-27 | `CHANGELOG.md` | `packages/auto_apply/CHANGELOG.md` | claimed a public release that never happened; superseded by the honest root changelog | 31 lines. 33 lines. Recorded `[0.1.0] - 2025-10-20 Initial public release` for a project with zero external users and no tag, credited the retired run.sh/run.bat launchers, listed offline CAPTCHA solving as shipped, and said AA uses Setuptools. Kept as evidence of how far a changelog can drift from its repository. | SUPERSEDED-BY `/CHANGELOG.md` |
| 2026-09-27 | `enterprise_admin_policy.md` | `packages/auto_apply/docs/deployment/enterprise_admin_policy.md` | near-duplicate of user_guide/admin_policy.md; two pages documenting one policy file | 345 lines. 347 lines. Heading-for-heading the same document as user_guide/admin_policy.md with different capitalisation, covering the same nine policy fields. Readers could not tell which was authoritative. The user_guide copy survives and is linked from the deployment index. | SUPERSEDED-BY `packages/auto_apply/docs/user_guide/admin_policy.md` |
| 2026-09-09 | `bs4_adapter.py` | `packages/auto_apply/src/auto_apply/adapters/secondary/perception/bs4_adapter.py` | orphaned by the STATIC_ASSISTED deletion (P6, 2026-09-09); 0 importers, confirmed by the reachability pin failing on it | 438 lines - complete static-HTML PerceptionPort implementation over BeautifulSoup: navigate, scan_page, get_current_state, extract_full_dom_tree. Working; it was constructed by the composition root's driver-None branch and never reached a discovery provider, because no provider exists that runs without a browser. | AS-IS |
| 2026-09-09 | `urllib_http_client.py` | `packages/auto_apply/src/auto_apply/adapters/secondary/network/urllib_http_client.py` | sole consumer was bs4_adapter, retired in the same change; 0 importers | 94 lines - complete stdlib-only HTTPClientPort implementation over urllib.request. No third-party dependency, which is why it existed: it was the zero-install fetch path for the static mode that was never built. | AS-IS |
| 2026-09-09 | `http_client_port.py` | `packages/auto_apply/src/auto_apply/domain/ports/http_client_port.py` | the port for urllib_http_client; no implementation and no consumer remain after this change | 62 lines - the HTTPClientPort protocol. Retired with its only implementation so the port inventory does not carry a promise nothing keeps. Recall it first if static fetch is ever spiked. | AS-IS |
| 2026-09-09 | `test_bs4_adapter.py` | `packages/auto_apply/tests/adapters/test_bs4_adapter.py` | tests a retired module; would fail on import once bs4_adapter leaves src/ | 346 lines, 37 tests - full unit coverage of the adapter with the HTTPClientPort mocked, so no network I/O. Recall alongside the adapter. | AS-IS |
| 2026-09-09 | `test_urllib_http_client.py` | `packages/auto_apply/tests/adapters/test_urllib_http_client.py` | tests a retired module; would fail on import once urllib_http_client leaves src/ | 122 lines, 8 tests - patches urllib.request so no network I/O. Recall alongside the client. | AS-IS |
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

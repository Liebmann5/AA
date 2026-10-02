# Changelog

All notable changes to AutoApply are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project intends to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
from its first tag onward.

> **There has been no release.** No version of AutoApply has ever been tagged or
> published. `0.1.0` in `pyproject.toml` is a development placeholder, not a
> shipped artefact. A previous version of this file claimed an
> "Initial public release" on 2025-10-20; that release never happened and the
> claim has been withdrawn.
>
> **Definition of released:** a tagged, installable artefact that five people
> who are not the maintainer have run on their own machines, plus an honest
> account of what it does and does not do.

---

## [Unreleased]

### Added

- **Replay (`--replay`).** Re-runs text extraction and every per-posting
  research detector over a folder of kept page copies, with no browser,
  network, research database, research key or clock, and writes
  `replay.jsonl` and `manifest.json`. The same corpus and AA version give the
  same bytes on any operating system and Python version; CI proves it on all
  six legs against a committed synthetic corpus. The manifest names the AA
  version, the extraction method, the detector roster, every corpus file
  with its digest, and what a replay cannot reproduce. Vetting, the research
  aggregator and replay now build a posting's observation with the same code,
  so a replay cannot drift from a live run. Page copies now also keep the
  listing's title, location and platform, which a replay needs to find the
  jurisdiction.

- **Typed UI contract.** `SessionRequest` and a `UIPort` driving protocol; both
  the GUI and the CLI now emit the same typed request instead of an untyped
  dict. ([ADR-014](packages/auto_apply/docs/adr/014_typed_ui_port.md))
- **Selectable session exit axis** — collect links / collect and check /
  collect, check and apply — and all four entry points exposed on both surfaces.
- **Discovery output persistence.** Discovered jobs are now stored at discovery
  rather than at vetting, so a run that skips vetting no longer discards
  everything it found.
- **Session history and profile export/import** on both surfaces, with overwrite
  and path-traversal refusals.
- **Activity stream.** 47 internal events project onto a small `ActivityKind`
  set rendered by both dashboards; the raw event no longer crosses the port.
  ([ADR-015](packages/auto_apply/docs/adr/015_polled_ui_state.md))
- **Autonomy control** with two required acknowledgements, an immutable
  interrupt policy frozen at composition, and AST guards proving it is never
  rebuilt mid-session.
- **Safety pins** — a PII sentinel plus two ratchets, all three mutation-tested.
- **Continuous integration.** Four gates on `{ubuntu, windows, macos}` ×
  `{3.10, 3.12}`; blocking since 2026-09-05.
- **Documentation gate** — the fifth gate, run inside the pytest suite.
  ([ADR-017](packages/auto_apply/docs/adr/017_documentation_gate.md))
- **Repository health files**: `SECURITY.md`, `SUPPORT.md`, `GOVERNANCE.md`,
  `DISCLAIMER.md`, issue and pull-request templates.
- **Labelling tool (`--label`).** A blind, resumable way to record ground
  truth: say what each saved block-detector page really was, and log the
  applications you make by hand for the paired audit. Answers are saved as
  append-only JSON Lines; saved pages open only as copies that run no code and
  load nothing; insights show every rate with its denominator and a 95%
  interval. New studies are data, not code. See the Labelling user guide.
- **Research accounting per session.** The end-of-session summary on both
  surfaces, and the saved session report's new `research` section, say what
  research collection recorded, what it could NOT record (by the step that
  failed, counted in records) and what it recorded in a weaker form — such as
  a signal written without its provenance signature. Every site that loses or
  weakens research data now counts it; before, most were a log line only.
- **Page copies (research, a separate opt-in).** When the person turns them
  on — only possible while research participation is on — AA keeps a cleaned
  copy of each job posting page it reads, on this device only, as a standard
  WARC file. Cleaning happens before anything is written: the person's own
  name, email, phone and street address, every form value and hidden field,
  scripts, frames and token tags are removed; the page as first read is never
  saved. Search result pages are never copied. Research rows gain a
  `page_copy_id` — a fingerprint (a salted commitment, so it cannot be matched
  against public pages to reveal which postings someone read) that proves a
  row came from a kept copy. Copies are written by a background writer, so
  they never slow a session. They are deleted after 90 days
  (`page_copy_keep_days`), oldest first past 200 MB (`page_copy_max_mb`), when
  page copies are turned off (unless the person chooses to keep them) and on
  any withdrawal from research. Export contains no page copies. The consent
  text says copies are not encrypted and should stay off on a shared
  computer.
- **`--research-summary`** prints what the discovery research tables hold —
  pages, cards, candidates, and destinations grouped by hiring platform — with
  every share shown against its denominator. Read-only; starts no session.
- **Research consent screens on both surfaces.** Research participation is now
  reachable by the people it belongs to: **File → Research…** in the app (from
  first launch, before any profile exists; the Settings dialog also has a
  **Research…** button) and **`python -m auto_apply --research`** on the
  command line. Both show the current state in plain words — off, withdrawn,
  changed-since-you-agreed, agreed-but-not-collecting (and why), or on — show
  the same consent text from the single canonical copy, and offer the same
  actions: agree, decline, withdraw with or without deleting what was
  collected (export is offered first; deletion requires typing DELETE in the
  terminal and has no default button in the app), export, and turn page copies
  on or off with a keep-or-delete choice. A blank answer, Escape, or closing
  the window never grants and never deletes.
- **Withdrawal now really stops collection.** The stop channel is
  process-wide: withdrawing through any consent instance stops the running
  research observer, and the result can no longer report "stopped" while
  collection continues. Previously a second consent instance — exactly what a
  screen obtains mid-session — withdrew on paper while the aggregator kept
  writing and recreated the purged database and signing key.
- **Research export from the app and the CLI screen**, through the same
  verifiable bundle as `--export-research`.

### Changed

- **Discovery is pipelined, not batched.** Priority bands order the queue so one
  search flows discover → vet → apply before the next search begins.
  ([ADR-011](packages/auto_apply/docs/adr/011_discovery_pipeline_priority.md))
- **Submission is fail-closed.** AA refuses to submit when it cannot prove the
  form was filled correctly.
  ([ADR-012](packages/auto_apply/docs/adr/012_fail_closed_submission_gate.md))
- **`pyproject.toml` is the single source of dependency truth.** The `run.sh`
  and `run.bat` launchers were retired; they duplicated uv and selected an
  extras group that never existed.
- **Documentation reorganised** to a standard MkDocs layout with a reference
  section, provenance front matter on every page, and status markers on every
  significant claim.
- **Canonical repository is GitHub**; Codeberg is a mirror. `CITATION.cff`,
  `pyproject.toml` and the documentation now agree.
- **Research consent text 2.3.** The dialog now says that destination hosts
  are stored as shown and can name an employer (`acme.myworkdayjobs.com`),
  that a web address inside a link text is cut to its host, and that a results
  page repeating your search words in a title or link text is stored as shown.
  Anyone who agreed to an earlier version is asked again before collection
  resumes.
- **Research consent text 2.4.** The dialog says page copies exist as a
  second, separate choice that stays off unless turned on, and the withdraw
  dialog says kept page copies are deleted either way. The page-copies choice
  has its own text, versioned separately (1.0). Anyone who agreed to 2.3 is
  asked again before collection resumes.

### Fixed

- **First-run identity defect.** GUI onboarding no longer seeds a new user with
  the template profile's identity; a whole-profile contamination check blocks a
  session start at two or more template matches.
- **Request-scoped values never reached the workflows.** The orchestrator
  replaced its session plan while the workflows held a reference to the boot
  plan, so a result cap typed by a user had never once been applied.
- **Résumé attachment.** A stored path was resolved against the process working
  directory, missed, and was swallowed by a bare `except` — the fail-closed gate
  was submitting applications with no résumé attached.
- **Cover-letter mangling.** Two independent paths ran cover-letter text through
  `pathlib`, collapsing `//` and breaking every URL in it.
- **Cross-OS document paths.** Relative document values stored with Windows
  separators could not resolve on Linux or macOS.
- **Terminal CAPTCHA hang.** `CAPTCHA_REQUIRES_MANUAL_SOLVE` was published into
  an empty bus and followed by `pause()` with nothing subscribed and nothing
  calling `resume()`.
- **Type gate floor.** An unused import forced mypy to run at 3.12 while
  `requires-python` declared 3.10; restoring the floor immediately caught a
  3.11-only API that raises on the supported minimum.
- **Wrong pay-transparency jurisdictions and metros.** The location matchers
  matched substrings, so "Chicago, IL" was California, "Canada" was California
  and "Memphis, TN" was Hawaii; ST-01 then reported violations of laws that do
  not cover the posting. On a 107-location table, 33 jurisdictions (22 of them
  a law where none applies) and 25 metros were wrong. They now read whole
  tokens, check a town against its stated state, and can return every
  jurisdiction the law file defines (Rhode Island was unreachable).
- **Search words reached the research record through link text.** A results
  page that renders a URL inside its link (a visible URL, or a breadcrumb
  such as `www.indeed.com › q-<search words>-jobs`) had that text stored
  verbatim, and advertising evidence quoted whole URL path segments. Both now
  keep the host only, and the evidence names the advertising word it matched.
- **Session history ordering** now sorts by the session's own `started_at`
  rather than file mtime, which collapses when a reports directory is copied to
  a USB stick.

### Removed

- **The zero-browser static path.** `BS4PerceptionAdapter`, `UrllibHTTPClient`
  and `HTTPClientPort` are retired and `STATIC_ASSISTED` is gone. AA now refuses
  to start a session when the browser cascade exhausts, rather than promising a
  mode with no implementation behind it. The capability is deferred, not
  cancelled. ([ADR-013](packages/auto_apply/docs/adr/013_static_path_retirement.md))
- **`run.sh` / `run.bat`** launchers — retired, superseded by `uv`.
- Retired files are never deleted; see
  `packages/auto_apply/docs/old_retired_files/README.md` for the ledger.

### Known gaps

Tracked in [STATUS.md](packages/auto_apply/docs/STATUS.md). The headline ones:
no application has ever been submitted; discovery yields postings from Bing
only; a test leaks a browser process so the suite cannot run fully unattended;
company names truncate to a single character in exports.

---

<!-- Release links go here once a tag exists.
[Unreleased]: https://github.com/Liebmann5/AA/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Liebmann5/AA/releases/tag/v0.1.0
-->

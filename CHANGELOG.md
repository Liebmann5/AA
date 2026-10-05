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

- **The challenge verdict and the apply route (item 12).** Whether a page is
  a human-verification challenge or a login wall is now decided by one
  structural predicate (`domain/services/challenge_assessment.py`) — never by
  substrings in the page source, the title or the URL. A presented challenge
  pauses the session in place, on the challenging page, before any outcome is
  recorded; a human solve continues the same application attempt. AA now
  routes from a job-board posting to the employer's form: vetting learns
  off-host apply targets into `metadata["apply_url"]`, and applications
  follows a bounded, recorded route (off-host links navigated, target-less
  buttons clicked, new tabs followed via the now-wired ContextManager). New
  outcome `ACCOUNT_REQUIRED` for account-gated apply flows. Every attempt
  records posting/apply-target/landed hosts, hop count, the landed page's
  ATS, and the signals behind any challenge verdict.
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
- **Salary extraction from posting text.** One pure domain function reads
  US-dollar pay — ranges and single figures, hourly, weekly, biweekly,
  semi-monthly, monthly and annual, "$100k" forms, "up to" / "starting
  at" — and vetting, replay and
  the research aggregator all share it, so a live run and a replay see the
  same salary. Figures are stored as annual USD equivalents (hourly ×2,080
  = 40 h × 52 weeks, a stated assumption) with the as-stated span saved
  beside them (`salary_observations.source_text`). Non-USD, ambiguous or
  conflicting figures are recorded as not found, never guessed; so is pay
  per day, per shift or per pay period, which has no single annual
  equivalent. A figure counts as pay only with a pay word, a range word or
  an hourly rate beside it, so a bare "$75,000" with no label is a
  deliberate miss: precision first. Pinned against 95 labelled strings plus
  a 40-string held-out table with precision and recall floors; scored
  separately on a 45-string set written independently of the rules, which
  found the biweekly misreading fixed here.
- **Research key provisioning.** Agreeing to research now creates a private
  research salt on the device (`research_salt.txt`, owner-only where the OS
  allows) — no environment variable, so a real user can actually contribute.
  `AA_RESEARCH_SALT` still overrides it (and changes every employer identity
  the installation mints). Withdrawing with deletion removes the salt with
  the signing key, rotating employer-name identities too.
- **Signed research exports.** Every export bundle now carries
  `bundle_signature.json` — an Ed25519 signature over the bundle digest and
  the index, made with the installation key — and a signed run identity in
  `index.json` (AA version, a SHA-256 of the installed code, Python, OS;
  never a fabricated commit). The signature file states plainly what it
  proves (bytes unaltered since export) and what it does not (unmodified
  code, contributor identity).
- **`--verify-research`.** Verifies a bundle offline with only its own
  files: every file hash, the bundle digest, the bundle signature and every
  signed row, printing what it checked and what it did not. Exit 0/1/2.
- **Research public-key fingerprint on both research screens**, so a
  contributor has something to publish that recipients can match a bundle
  against.
- **Release attestation.** Published releases now carry Sigstore
  build-provenance attestations, minted by the new release workflow on
  GitHub's runners, over exactly two subject sets: the replay outputs
  (`replay.jsonl`, `manifest.json` — after a byte-equality check against the
  committed expected digest) and the built sdist and wheel. A version-gate
  job refuses to publish when the tag, `pyproject.toml` and `CITATION.cff`
  disagree, and every attesting job waits on it. The workflow runs only on
  published releases, with empty top-level permissions and least-privilege
  per-job grants, so the signing identity is unreachable from pull-request
  code. The one-person runbook is `docs/developer_guide/releasing.md`.

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
- **Research consent text 2.5.** The dialog now says AutoApply creates the
  private research key on the device when you agree (no AA_RESEARCH_SALT
  setting to find), and the withdraw dialog says deletion also removes the
  private research key that anonymised employer names. Anyone who agreed to
  2.4 is asked again before collection resumes.
- **ST-02's evidence text** no longer cites Colorado's standard on rows from
  other jurisdictions; it names the generic good-faith range standard.

### Fixed

- **The CAPTCHA verdict was wrong on most of the pages it flagged.** A
  substring search recorded any page containing the text `recaptcha` —
  including inside an HTML comment — as a CAPTCHA: 12 of 20 hand-triaged
  pages were false positives, and the "access, not comprehension"
  conclusion in STATUS.md has been withdrawn. The verdict is now
  structural: on the 20 measured pages it scores 20 of 20 (12 postings
  clear, 7 interstitials gated, 1 embedded widget), including the
  interstitial population whose ~5k characters of boilerplate defeated the
  first text-length threshold.
- **The login-wall check fired on a posting titled "Registered Nurse"** —
  first via a title substring, then via "/register" as a URL substring.
  Titles are never read and URL markers match whole path segments only.
- **The Apply search was skipped on every job-board posting** (they all
  contain a `<form>`), and it could only see `<button>` elements — offsite
  apply links, submit inputs and `[role=button]` were invisible. Apply,
  Next and Submit now share one control source read by accessible name
  (text, then `value`, `aria-label`, `title`).
- **An off-host apply link lost to any on-page form with 3+ inputs**, so
  the one measured off-host route was filled in place (an alert form on
  the posting). The posting's own apply link now outranks form detection.
- **A hidden sign-in modal in a page's markup counted as an account
  requirement.** The verdict now asks the browser whether a
  password-bearing dialog is actually visible after the apply click, and
  only falls back to markup when the browser cannot answer.
- **ContextManager was never passed to the application engine** — an apply
  click that opened a new tab stranded AA on the posting. It is now built
  and injected by the composition root, with a wiring pin.
- **Item 5's labelling suite** broke when the temporary detector-sample
  producer was deleted; the dump format now has one writer living beside
  its reader, so the two cannot drift.
- **Research salt storage moved out of the domain, and both research
  secrets are created atomically.** Salt file I/O now lives beside the
  provenance key in the security adapter; the domain resolves through one
  injected reader wired by the composition root, and an unwired manager
  cannot create files. The salt and the key are created with
  `O_CREAT | O_EXCL` and owner-only permissions from the first byte — no
  write-then-chmod window, no silent last-writer-wins race — and the test
  suite can no longer mint real research secrets into the data folder: a
  conftest guard fails the run if the real files change.
- **Exporting research no longer mints a private key.** A bundle is signed
  only when a key already exists; otherwise `index.json` declares the
  bundle unsigned, the verifier reports that state instead of failing it,
  and nothing but the bundle is written.
- **Release workflow build attestation.** `uv build` in a workspace member
  writes to the workspace root's `dist/`; the build now uses
  `--out-dir dist` so the attested and uploaded paths exist. The release
  runbook routes the version bump and the DOI commit through pull requests
  and verifies the replay digest by regenerating it rather than
  downloading it.

- **ST-01 recorded violations on postings that disclosed pay.** Nothing in
  AA read salaries, so every posting in a pay-transparency jurisdiction —
  including ones showing their range — was recorded as a legal violation.
  ST-01 now fires only when no US-dollar pay figure was found, respects each
  law's effective date against the posting's own capture date, and claims
  only what AA can know: severity `violation` only where the law covers
  every employer (AA never knows employer size), `concern` otherwise, and a
  single figure where a range is required is a separate `flag`. Rhode Island
  no longer fires — its law requires disclosure only on request. Research
  schema version is now 3; old and new rows are told apart by the
  `schema_version` column.
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
- **Export bundles differed by operating system.** `index.json` and
  `verification.json` were written in text mode, so the same database
  produced a different bundle digest on Windows than on Linux. Every bundle
  file is now written as exact bytes, with an AST ratchet against text-mode
  writes of bundle files.
- **The provenance key was world-readable** on shared machines (written
  with the default umask). New and existing keys are restricted to their
  owner where the OS allows.
- **Dead signing code.** `ProvenanceSigner.sign_payload` had no caller;
  removed. Bundle signing goes through `sign_hex`, like row signing.
- **`CITATION.cff` was invalid CFF 1.2.0.** Empty `doi:` and `orcid:` strings
  fail the DOI/ORCID patterns (a Zenodo deposit would have failed or been
  wrong), and `date-released: "2026-09-19"` named a release that does not
  exist. All three are removed; the DOI returns as the Zenodo concept DOI
  after the first deposit, per the runbook. A docs-gate pin now fails on any
  empty pattern-bearing field.

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

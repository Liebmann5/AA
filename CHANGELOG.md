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

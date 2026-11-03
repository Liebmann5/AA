---
title: "Page Comprehension Toolkit: Evidence and Research"
status: needs-review
last_verified: 2026-11-02
verified_against: "7701de8 + S1 reply files (pass 3)"
audience: contributors
---

# Evidence, trace and research

Philosophy: research-grade data is *intentionally designed evidence*, not raw logs.
The comprehension toolkit is where AA decides what a page is, so it is where the
evidence must be designed: **observation, inference, decision, action and result
are separate records.** Today the logs record counts, not URLs or reasons (LR-6,
defect 9): a run cannot be audited.

## 1. One trace, shared

The toolkit's trace **is** ADR-022's per-page record and the Workbench's input. It
keeps the join key `attempt_id + page_index` (AA_TODO_ADDITIONS N-1: never drop it).
JSON Lines, append-only, UTF-8, written in binary mode like the footprint ledger
(`footprint_ledger.py`), schema-versioned (`trace_schema: 1`) per
`research_module/data_format.md` practice. `[PLANNED]`

| Event | Fields (essence) | Why |
| --- | --- | --- |
| `run.start` | session, seed, profile, parameter-set hash, tool versions, memory-snapshot hash, calibration record, env facts, library version | replay and provenance |
| `step` | trigger (navigate, click, redirect, new tab, script), source page, destination, verdict kind, timings, epoch | ADR-022 navigation trail |
| `observation` | observation hash, access adapter, capabilities used, **footprint class**, truncations, node count, bytes, duration | cost and honesty about what was cut |
| `tool.run` | tool id/version, strategy, input hash, output hash, work units, duration, outcome (`ok`/`abstain`/`timeout`) | auditability |
| `finding` | kind, node ids, confidence, margin, evidence list, epoch | explainability |
| `memory` | hit/miss/verify-fail, entry key, expectation result | memory is never silent |
| `defence` | kind, vendor, signals, confidence | research on barriers |
| `human` | pause reason, understanding shown, resume diff class, edits (section 4) | HITL research |
| `param` | set loaded, parent, diff, evidence (n, statistic, p) | tuning audit |

## 2. Recording levels and what each costs

| Level | Content | Needs | Cost (derived `[GOAL]`) |
| --- | --- | --- | --- |
| L0 | counters: tool, outcome, duration, work units | nothing | about 100 B/run; negligible CPU |
| L1 | + hashes, parameter and tool versions, strategy, finding summaries (kinds, confidence, counts), ranked-run **features** (numbers, no text) | nothing; local only | about 1 KB/run, about 25 KB/page, under 0.1 ms/page |
| L2 | + the observation itself: the cleaned page copy (existing redaction: user details, scripts, form values and hidden fields removed) or a compressed `Doc` dump, and finding node ids | the existing page-copy consent; local only | tens to low hundreds of KB per page (unmeasured), written by the background writer so a copy never slows a pass |
| L3 | research export: hosts, verdict kinds, aggregate features, **copy fingerprints (commitments)**; never full URLs carrying search words, never values | research consent (ADR-020 decision 9 rule) | counts only |

USB and low-storage users keep L0-L1 and turn L2 off (item 8): the tool still works;
only local counterfactual tuning and exact replay are unavailable to them.
Default per CT-Q-017: L0, L1 on; L2 opt-in; L3 consent-gated.

## 3. Replay determinism

A result is a pure function of `(observation, parameter set, tool versions, seed, memory
snapshot, work-unit budget)`; the live web is not deterministic, so **the observation
is the thing that is recorded.** With L2, replay reruns the tools and must reproduce
the recorded output hashes byte for byte (the existing replay already does this for
detectors, `[LIVE]`). With only L1, a run is *verifiable* (hashes match a re-observation
that happens to be identical) but not *re-computable*. Environment (Python, OS) is
recorded beside the artifact and outside its digests, as `replay_service.py` already
does. The live-versus-recorded distinction is stated in every export.

## 4. Human edits and the pause/resume protocol (item 18)

Checkpoints: `BEFORE_FORM_SUBMIT`, `ON_SUSPICIOUS_REDIRECT`, the in-place CAPTCHA pause
and the autonomy setting (ADR-005, ADR-012). At **every** pause the toolkit exposes a
`PauseContext` (CT-DS-012): observation id and epoch, page family and verdict, the
region and field findings with confidence, the **intended action list** with each
action's preconditions, the submit prediction, and the reasons for any `UNKNOWN`.
On resume (CT-ALG-024): epoch increments; enumerate windows; re-observe; `DocDiff`
against the pre-pause document; classify; re-derive the plan. **Never act on stale
understanding** (CT-INV-003).

Recording human edits: each field whose value or state changed while paused yields a
`human.edit` event: control key, edit kind (fixed AA's fill, filled AA's blank,
unrelated), time. Values are **not** stored in the research trace. With the user's
"learn my phrasing" choice, values are kept **locally** in the user's profile store as
phrasing examples (this is the owner's idea, recorded as a capability); otherwise they
are hashed. Fields the human changed become *human-owned* and are never overwritten.

| Edge case | Failure mode if mishandled | Handling |
| --- | --- | --- |
| Human edited fields | AA overwrites their answer | human-owned lock; precondition check |
| Human submitted the form themselves | AA submits again (duplicate application) | verdict `SUCCESS_PAGE`/`ALREADY_APPLIED` found on re-observe; plan dropped |
| Human navigated elsewhere in the tab | AA acts on a different page | URL/origin compare; `NAVIGATED`; re-derive or stop |
| Human closed the tab/window AA held | driver error, orphan state | window enumeration; `WINDOW_LOST`; recover to a remaining window or stop |
| Human opened extra tabs | AA attaches to the wrong one | window set diff; attach by opener chain and URL, else ask |
| Human solved the challenge | AA still reports blocked, or acts on token that expires | verdict re-run; challenge tokens age, so re-check before acting |
| Session expired during a long pause | AA fills a login page | verdict `LOGIN_REQUIRED`; hand back |
| Page auto-refreshed / SPA re-rendered | stale node handles | epoch rule; handles never cross an epoch |
| Zoom or viewport changed | all geometry stale | geometry re-read; relative thresholds |
| Browser/driver died | session error loops | typed `ACCESS_LOST`; stop, record |
| Dialog (alert/beforeunload) open on resume | every command fails | dialog check first; handle by policy |
| Machine slept; clock jump | timeouts misfire | work-unit budgets; re-observe |
| Pause timed out (policy) | undefined | treated as a refusal: `USER_SKIPPED` vs fault stay distinct (ADR-012) |

## 5. Privacy

No PII in L0-L1 by construction: the trace carries ids, hashes, numbers and enumerated
kinds. The existing PII sentinel pin is extended to the trace writer (F-9 closes the
same gap for formatters). URLs are stored as host plus path-shape locally; full URLs
only locally and only if the user's session record already holds them; never in L3.
`approval_evidence()` is in memory only today (F-10); the trace is where it becomes
durable.

## 6. Research questions served

| Question | Trace data |
| --- | --- |
| How often do employer pages block or throttle automation, and which vendors? | `defence` events with vendor and signals |
| How complex are ATS forms (steps, fields, required ratios, conventions)? | `finding` kinds from Forms/Required; `form_observations` |
| Which required-marking conventions occur and how often is requiredness invisible until submit? | Required signals and error-mapping outcomes |
| What fraction of forms and widgets are inaccessible (unlabelled controls, keyboard traps)? | Pairing `UNLABELED`, Widgets findings |
| Hidden-field and honeypot prevalence | Visibility/honeypot findings |
| How do page structures change over time (template drift)? | skeleton hashes by domain and date; memory verify-fail rate |
| How accurate is the comprehension itself? | gold labels vs findings (09) |
| Where do users have to intervene, and why? | `human` events |

## 7. Meeting AA's research-grade and publishability criteria

| Criterion | How the toolkit meets it | Status |
| --- | --- | --- |
| FAIR4RS (Bible 25.1): findable, accessible, interoperable, reusable, reproducible, sustained | standalone library with its own version and changelog, stdlib only, exportable trace schema, seeded determinism | `[PLANNED]` |
| ACM artifacts functional: smoke test without a browser; mock ATS benchmark | every tool runs on fixtures; the five benchmark forms become `Doc` fixtures | `[PARTIAL]` |
| ACM artifacts reusable: plug-in tools, pinned image, `--seed`, `--profile` | tool registry, `Dockerfile.test`, seed in `run.start`, per-tool timings | `[PLANNED]` |
| Tier 1 property tests (Bible 25.4) | sibling-run tolerance (Lemma 2), pairing optimality, `diff(a,a)=∅`, collapse monotonicity | `[PLANNED]` |
| Tier 3 reproducibility (seeded twice, identical traces; memory ceiling; performance regression) | CT-NFR-003, 005, 018 | `[PLANNED]` |
| Tier 4 validity (ablation: math engine on versus off on the mock ATS benchmark) | the evaluation in 09 runs ablations per tool | `[PLANNED]` |

## 8. Environment tags on every observation (pass 2)

Every trace event that carries an observation also carries its environment:
`owner` for AA's runs on the user's machine, `cloud` for a data-centre session,
or another named host. Research exports keep the tag. An error rate or a ledger
tick computed from one environment is reported for that environment only. Pass 2
showed why: from a data centre, 4 of 5 search engines refused the client, and
controls the owner saw on Notion pages were withheld from it.

## 9. The pass-2 evidence set

Pass 2 kept its live observations outside AA, in the owner's evidence archive,
directory `evidence/`:

| Path | Contents |
| --- | --- |
| `link_check.md` | every link of the owner's list, opened once: final URL, redirect chain, status, outcome, `robots.txt` |
| `specimens/<family>/<id>/` | `meta.yaml` (URL, time, environment, browser and version, how reached, status, `robots.txt` note, family, source, ledger rows, what it shows, what makes it hard), `dom.html.gz` (rendered DOM), `screenshot.jpg`, `a11y.yaml.gz` (ARIA snapshot), `summary.json` (computed measures) |
| `specimens/_robots/` | each host's `robots.txt` as fetched |
| `coverage.md` | ledger row → specimen IDs and distinct sources; gaps and what was tried |
| `analysis/` | offline probes of AA's code and their outputs: the verdict replay, the extraction-script probe, the worst-case probe, the Hungarian non-termination probe |
| `tools/` | the capture scripts, the seeded picker and the registry, so the set can be re-collected |

**Rules of use.** A specimen is third-party page content captured once for
design evidence. It may become a unit-test input that guards code (CT-Q-027),
cleaned of anything personal. It is never proof of AA's behaviour, and it is
never published as a page copy (CT-Q-018: fingerprints only). The set holds
123 specimens from 45 sources, each under 2 MB, 33 MB in total. Pages behind a
login were not saved beyond the wall itself.

**Research use already made of it.** Replaying AA's own page verdict over the
specimens is the first research-grade measurement of AA's perception on the open
web. It is versioned (commit `1bf7935`), deterministic (a pure function over
stored inputs), comparable (per family and source) and honest about environment
(`cloud`). Its results are in [10](10_gap_analysis_and_build_plan.md) s5.

## 10. The per-page record as built in slice S1 (trace schema 1)

Slice S1 builds the discovery part of the trace as the start of ADR-022's
per-page record, not a parallel log: `domain/models/page_record.py`.

| Type | Fields | Level |
| --- | --- | --- |
| `PageRecord` | `pass_kind` (`harvest`, `finalize`), `pass_index`, `page_index`, `observation`, `detection`, `record_level`, `identity_level`, `identity_attributes` (a count), `analyze_ms`, `decisions` | L0 view: counters and timings; L1 view: everything |
| `ObservationFacts` | node count, payload bytes, script, build and stitch times, `text_capped`, `text_budget_hit`, `depth_cut` → `truncations()` | L0 |
| `ListingDetectionFacts` | candidates, `chrome_excluded`, ranked `group_sizes` | L1 |
| `CardDecision` | card index, `stage` (`found`, `fate`, `opened`), `reason` (enumerated), `fate` (`kept`, `dropped`, `deferred`), resolution state, candidate and rejection counts, `title_source`, `title_truncated`, `url_ref` | L1 |

Every card a pass sees has one `found` and exactly one `fate` decision; every
click in the finalize pass is one `opened` decision. Reasons are enumerated
(`title_and_link`, `no_title`, `multi_route`, `no_eligible_link`, `no_link`,
`invalid_job`, `already_resolved`, `no_identity`, `click_budget`,
`opaque_stop`, `no_activator`, `opened_*`). The record holds **no page text by
construction**: no titles, URLs, hosts, attribute names or values; a pin
checks it. A destination is referred to by `url_ref`, the first 16 hex digits
of SHA-256 of its canonical URL. `url_ref` is an unkeyed commitment, so it is
**local only** (a guessable URL could be recovered by hashing candidates); it
is never exported to research, where the keyed identities of
`research_identity` apply.

**Where it goes today.** One JSON line per pass to the session log at DEBUG
under logger `auto_apply.trace` (`page record <source> {…}`), the L1 view.
LR-6 is met by DEBUG lines from the extractor's logger, one per URL found,
kept or dropped, with the fate, reason, outcome, score, `url_ref` and the URL
itself (local session log only, never the console). The append-only JSON
Lines trace file of section 1 (`trace_schema: 1`, binary-mode writer) is the
next step (slice S0's writer, [10](10_gap_analysis_and_build_plan.md) s3); the
record type does not change when it moves there.

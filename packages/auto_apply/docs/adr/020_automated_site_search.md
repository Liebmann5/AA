---
title: "ADR-020: Automated Site-Restricted Search — Planning, Pacing, Preview and Refusal"
status: needs-review
last_verified: 2026-10-29
verified_against: "domain/services/search_planner.py, application/services/host_pacing.py, application/services/search_preview.py, application/workflows/discovery_workflow.py, application/services/auditing/degradation_detector.py, infrastructure/registry.py"
audience: contributors
---

# ADR-020: Automated Site-Restricted Search — Planning, Pacing, Preview and Refusal

**Status:** Accepted
**Date:** 2026-10-29
**Deciders:** Nicholas Liebmann
**Supersedes / Superseded by:** none

## Context

[ADR-019](019_search_surface_catalog_and_query_builder.md) built the
search-surface catalog and the query builder: what a surface accepts,
composed once, for searches a person runs by hand. The obvious next step was
to let *automation* use the same knowledge — aim discovery at specific hiring
platforms with `site:`-restricted queries. That step carries risks the
hand-built search never faces:

- Automation acts with **nobody reading a verification label** mid-run.
- Every host AA queries becomes part of the research record's sampling
  frame, so an unverified target is not merely a wasted query, it is
  contamination.
- A `site:`-restricted search concentrates a session's traffic onto a few
  ATS hosts — the pattern that gets a client throttled or challenged.
- A restriction that silently degrades — an engine that cannot carry it, a
  result that is not a posting of the platform searched — would produce jobs
  AA claims came from a platform they did not come from.

A second, older measurement pressed from the other side: the wizards asked
users to choose things and then showed them nothing of what would happen —
the same "shape checked, binding not" defect class
[ADR-014](014_typed_ui_port.md) removed from session configuration.

## Decision

**1. Planning is a pure function, composed once.** `SearchPlanner`
(`domain/services/search_planner.py`) is deterministic — no clock, no I/O,
no randomness — and every query it emits is built by the catalog's composer.
Nothing in the planning path formats a `site:` clause by hand. Engines
rotate innermost and platforms outermost, so no engine host receives two
consecutive queries while another enabled target exists. The default
strategy is one query per platform per engine per (title, location); the
strategy is pluggable, and a strategy that cannot be composed yet degrades
to per-platform with a warning, never to silence.

**2. The automation floor is stricter than the builder's.** Only platforms
whose restriction is `measured` or `vendor`-documented may be planned
(`AUTOMATION_STATUSES`). The builder shows unverified platforms with a label
because a person can judge a label; automation cannot, so unverified
platforms are never planned, and the checklist in
[verifying_platform_search.md](../developer_guide/verifying_platform_search.md)
is the only way a platform earns admission.

**3. Engines get a query they can carry, or no query.** Refusal-both extends
to automation: an engine whose catalog form cannot carry a site restriction
receives nothing — never a degraded version of the query. Concretely:
Google's site-restricted searches use the **web** form
(`site_template: web`), because the jobs vertical's cards carry no
followable per-card URL (measured 2026-10-07, recorded in
`google.surface.yaml`); Indeed declares no site form and is never sent one.

**4. The session budget is session-wide and never reallocates.**
`max_queries_per_session` caps the whole session, owned by the one component
that spans discovery tasks (the workflow); engine rotation carries across
task boundaries. The plan is a pure function of its inputs and reads no
yield, no history and no clock — so it cannot shift budget mid-session,
which is what keeps a seeded run and a replay comparable.

**5. One pacer owns every contact.** `HostPacer`
(`application/services/host_pacing.py`) spaces consecutive contacts to any
single host — search engines during discovery, ATS hosts during vetting and
applying — by a floor with seeded jitter, from
`discovery.between_provider_pause_min/max` (1.0–2.0 s by default).
Reservations are taken under a lock so interleaving cannot violate the
floor. robots.txt is deliberately not consulted on the interactive path:
interactive browsing is not bulk crawling, and a robots fetch would itself
be a request.

**6. A challenged engine is benched, not retried.** An engine that answers
with a CAPTCHA or a login wall receives no further requests for the rest of
the session — the check happens *before* navigation — while the other
engines continue; the end-of-session report names it. The silent-degradation
guard benches on a harvest collapse only when yield *and* page size collapse
together against the provider's own recorded baseline, and site-restricted
harvests keep their own baseline scope, so a sparse `site:` harvest can
never bench an engine's generic searches.

**7. Off-shape hits are refused loudly, never laundered.** A result that is
not a posting of the platform searched is dropped and counted — or routed to
company-page mining when that is enabled — and terminal pages
(success/confirm/closed) are never followed.

**8. Provenance is stored with the job.** Every discovered job carries the
provider, the exact query, the target platform, the engine form, the route,
and the page and rank, persisted in `job_history.metadata_json`; the results
CSV shows all of it except the route.

**9. The sampling frame is research data; the query text is not.** Behind
consent, `search_plan_frames` records which engines and platforms were
searched and how many queries each received — names and counts, never the
words searched for. Research schema 5, consent text 2.7.

**10. The user sees the plan before it runs, from the same computation.**
`SessionRequest.platforms` is a tri-state (unset = inherit, empty =
explicitly generic, names = targeted). Precedence: admin lock
(`AdminPolicy.search_platforms`, a field-level lock in the
[ADR-018](018_layered_settings_and_motion_profile.md) pattern, applied after
`config_overrides` so the named lock wins) → this session's choice → profile
default (`ApplicationConfig.search_platforms`) → YAML. The plan preview is
computed from the session plan after the request and any lock are applied,
by the same planner the workflow uses — one shared computation
(`plan_updates_for_request`), so the preview cannot drift from the run. It
is offline by construction, appears as a "Preview plan…" button (GUI) and an
automatic confirm step (CLI), and `--print-plan` prints it without starting
anything. Both surfaces read one vocabulary
(`QueryBuilderService.automation_platform_vocabulary()`) and render the
outcome through one formatter (`format_discovery_outcome_lines`). `UIPort`
grows to 28 methods with `preview_search_plan`.

**Feeds: accepted, not built.** Public ATS posting feeds are accepted in
design as a future discovery provider (`requires_live_browser = False`),
never a replacement for the browser path. The accepted shape: a feed
response is captured as a WARC `resource` record of the raw bytes; replay
re-runs the feed parser and the detectors over it, never the DOM extractor;
a feed whose content type or shape fails the parser contract yields zero
items and a recorded observation, never a guessed harvest; a per-endpoint
shape hash gives a first-seen baseline; because the request carries the
user's terms, no query text reaches research; and it is built after the
user-facing surfaces, not before them. No code exists for this, and none of the
documents outside this ADR claim otherwise.

## Options considered

**Hand-formatted `site:` clauses in the provider files.** Rejected — the
"knowledge scattered across provider files" defect ADR-004 recorded for ATS
platforms and ADR-019 removed for hand-built searches, recreated one layer
down.

**The builder's evidence floor for automation.** Rejected — a label is a
control only when someone reads it; mid-run nobody does, and every host
queried enters the research sampling frame.

**Reallocating budget by yield** (queries flow to whichever engine is
producing). Rejected — the plan would stop being a pure function of its
inputs, and a seeded run and its replay would no longer be comparable. The
plan is fixed at planning time; the bench, not reallocation, is the answer
to a bad engine.

**Aborting the session when an engine challenges.** Rejected — one
challenged host says nothing about the others; benching isolates the signal
and the session continues degraded but honest.

**Retrying a challenged engine.** Rejected — a challenge is the host's
answer; repeating the question is the pattern rate-limiters exist to punish,
on the worst-case user's metered connection.

**Per-call-site pacing.** Rejected — pacing literals scatter across
providers, are unmeasurable in one place, and cannot cover the ATS hosts
that vetting and applying contact. One owner, one config pair, one seeded
jitter stream.

**Consulting robots.txt before each contact.** Rejected for the interactive
path — a robots fetch is itself a request, and the throttler/robots
machinery remains available for a future bulk-fetch path where the question
applies.

**Showing the plan only on request.** Rejected for the CLI — the wizard
already asks the questions; showing what they mean costs one screen and
catches a wrong plan before it costs a session. The GUI keeps it a button
because a modal between every field and Start would punish exploration.

## Consequences

- Easier: targeting a platform is one wizard answer; verifying a platform is
  one checklist; the plan is inspectable before anything runs and the
  outcome is reported after; a challenged engine costs one benching, not a
  session.
- Harder: a new platform is inadmissible to automation until a human
  measures it — deliberately. The planner, the pacer and the preview are
  three more deterministic components whose behaviour must be pinned rather
  than assumed.
- **Nothing in this ADR has been proven on a live run.** Every behaviour
  here is unit-pinned; the first live session with targeting engaged is its
  test. [STATUS.md](../STATUS.md) carries the same sentence.
- The feeds design is recorded so a future implementer does not re-litigate
  it; it has no code.

## References

- `domain/services/search_planner.py`, `domain/services/query_composer.py`
- `application/services/host_pacing.py`, `application/services/search_preview.py`
- `application/workflows/discovery_workflow.py`
- `application/services/auditing/degradation_detector.py`
- `infrastructure/registry.py` (the search-platform fold and the admin lock)
- `resources/search_surfaces/google.surface.yaml` (`site_template: web` and its measurement)
- [ADR-004](004_ats_platform_registry.md), [ADR-014](014_typed_ui_port.md), [ADR-018](018_layered_settings_and_motion_profile.md), [ADR-019](019_search_surface_catalog_and_query_builder.md)
- [verifying_platform_search.md](../developer_guide/verifying_platform_search.md)

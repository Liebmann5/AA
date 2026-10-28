---
title: "ADR-019: The Search-Surface Catalog and the Query Builder"
status: needs-review
last_verified: 2026-10-28
verified_against: "domain/models/search_surface.py, domain/services/query_composer.py, application/services/query_builder.py, adapters/secondary/discovery/search_surface_registry.py"
audience: contributors
---

# ADR-019: The Search-Surface Catalog and the Query Builder

**Status:** Accepted
**Date:** 2026-10-28
**Deciders:** Nicholas Liebmann

## Context

AA composes search queries in two places that must never disagree: the
automated discovery engines (which send URLs no user sees) and the
user-facing query builder (which composes a search a person runs themselves).
Before the catalog, each engine strategy hardcoded its own URL construction —
the exact "knowledge scattered across provider files" defect [ADR-004](004_ats_platform_registry.md)
recorded for ATS platforms. And the builder, once it existed, faced a sharper
version of the same question: what is a site *allowed* to claim it supports?

## Decision

**One catalog, two read paths, one composer.**

1. **The search-surface catalog is the single source of truth for what a
   surface accepts** — typed operators, address-bar parameters, URL
   construction — as typed, validated YAML under `resources/search_surfaces/`.
   Every operator and option records a *verification status*
   (`vendor` / `measured` / `third_party` / `unverified`), a source, and for
   `measured` a date. An unverified capability is recorded so its absence from
   the offered set is deliberate; it is never offered and never composed.

2. **Platforms come from the ATS descriptors**, not a second list —
   `resources/ats/*.yaml` carries the tenancy, the `site:` restriction and its
   own evidence status. Platform identity is single-sourced the way
   [ADR-004](004_ats_platform_registry.md) intended.

3. **Automation reads the bundled catalog only** (`load_surface_bundled`). A
   user override in the data directory can extend the surfaces a person
   searches by hand, but it can never change the URLs AA's automation sends.
   The byte-identity pin (`tests/adapters/test_engine_url_byte_identity.py`)
   holds this.

4. **Refusal-both, and a location ruling.** Anything a surface cannot express
   is refused or noted, never silently dropped. A *restriction* whose loss
   changes what the search *is* (a `site:` limit, an `any_of` the surface
   cannot carry) is refused — no bar text, no link, because a link without it
   would be a different search. A *hint* whose loss only broadens the same
   search — a location on a surface with no location field — is **noted**,
   with the remedy named, because refusing it would strand a worst-case user
   inside an error they cannot act on. This distinction is decided once, in
   the domain (`query_composer._compose_url`), for every surface.

5. **The port shape: one vocabulary, two objects.** The builder's nine
   methods live on `UIPort`, satisfied by `SessionController` in-session.
   Because the builder is useful *before* any session exists — when no
   controller does — the pre-session `QueryBuilderService` exposes the
   identical method names, and the GUI reads whichever object is present
   (controller mid-session, service otherwise) without branching on which.
   Drift is pinned, not trusted: a test asserts the service, the port and the
   controller share the same names, and that the CLI and GUI produce the same
   `QueryResult` for the same input. A tenth method, `resolve_query_target`,
   folds a platform or company target into the request being remembered, so a
   query kept on either surface replays identically.

## Options considered

**Keep the engine strategies' hardcoded URL builders.** Rejected — two sources
of query truth is the defect the catalog exists to remove, and the byte-identity
pin proves the move changed nothing automation sends.

**A wrapper port-implementation for the pre-session builder.** Rejected — a
second class that only forwards to the service is the wrapper ADR-014
explicitly avoided; the service speaking the port's names gives one vocabulary
with no wrapper.

**Refuse on a dropped location, like a dropped site: limit.** Rejected — a
location is a hint, not a restriction; a locationless engine search is the
same search, broadened. The user sees a note and the remedy, not a dead end.

## Consequences

- Easier: a new surface is one YAML file; a new platform is one descriptor;
  verification status is data, and upgrading it is a hand-measurement, not a
  code change. Both surfaces can never drift into two vocabularies.
- Harder: a new port method means touching the port, the controller, the
  service, both surfaces and two pin sets — deliberately, since a divergent
  surface is the defect class this removes.
- **Research option, deferred — not closed.** Whether people find AA's
  automated search or the hand-built searches more useful is a research
  question (the paired-audit arm could compare outcomes). It is recorded here
  as a deferral: it would need its own versioned consent through the existing
  research-consent mechanism, and nothing in the builder writes toward a
  research store.

## References

- `domain/models/search_surface.py`, `domain/services/query_composer.py`
- `application/services/query_builder.py`
- `adapters/secondary/discovery/search_surface_registry.py`
- `tests/adapters/test_engine_url_byte_identity.py`
- [ADR-004](004_ats_platform_registry.md), [ADR-014](014_typed_ui_port.md)
- [ui_port_layer.md](../architecture/ui_port_layer.md)

# ADR‑009: Consent‑Gated, Zero‑PII Research Module

**Status:** Accepted (updated 2026-07-01)
**Date:** 2026-01-15
**Deciders:** Nick Liebmann
**Technical Story:** AutoApply is uniquely positioned to observe the hiring market from the candidate’s perspective at scale. Most academic research on hiring uses employer‑side data (ATS vendor analytics, HR surveys). AA produces the first large‑scale candidate‑side dataset. However, collecting any data about a user’s job hunt carries ethical and privacy risks. The research module had to be designed so that it is impossible to extract personally identifiable information from its output, even with full access to the raw data files.

*Updated 2026-07-01 to reflect the wiring of ResearchSignalAggregator and the deprecation of the old ResearchCollector.*

---

## Context

AutoApply, in the course of its normal operation, encounters systematic patterns in the hiring market:

- Job postings labelled “Entry Level” that require years of experience.
- ATS platforms that reject applications within minutes.
- Forms that present logical contradictions.
- Companies that disclose salary ranges versus those that do not.

These observations have genuine public‑interest value. Aggregated across many users, they could inform policy discussions, empower job seekers, and hold employers accountable. However, collecting this data requires navigating a fundamental tension: we want rich, structured observations, but we must never record anything that could identify an individual user or their specific job applications.

---

## Decision

We implemented a **consent‑gated, passive, zero‑PII research data collector** — the `ResearchCollector` in version 1, superseded by `ResearchSignalAggregator` in version 2.1. The new collector is built on 29 signal detectors and writes to a SQLite database, not CSV. It is governed by five non‑negotiable design principles encoded in its implementation.

### Wiring (Updated 2026-07-01)

As of the architecture audit, the old `ResearchCollector` (CSV, 13‑column schema) has been removed from the composition root. The new `ResearchSignalAggregator` is wired directly into `build_orchestrator()` after a dual‑gate consent check:

1. The outer gate: `CapabilitiesRegistry.is_research_enabled()` (the user’s config opt‑in).
2. The inner gate: `ResearchConsentManager.is_active()` (SQLite‑backed consent record, versioned).

If both gates pass, a `ResearchSignalAggregator` is instantiated, started as a daemon thread, and injected into every workflow via the `ResearchObserverPort`. If either gate fails — or if any exception occurs during initialization — a `NullResearchObserver` is substituted silently, and the session runs normally with zero research overhead.

The workflows now call `observe_job_posting()`, `observe_form()`, and `observe_application_outcome()` at appropriate points, each wrapped in `try/except` to ensure a failure in the research pipeline never interrupts the core job‑hunting flow.

---

## Consequences

### What becomes easier

- **Real research data.** The 29‑detector pipeline now actually runs. Signals are accumulated in a SQLite database, ready for analysis.
- **Consent enforcement.** The dual‑gate mechanism ensures data is collected only with explicit, versioned consent. Withdrawing consent immediately stops collection.
- **Graceful degradation.** NullResearchObserver ensures the research module consumes zero resources when disabled.

### What becomes harder

- **Maintaining two consent systems** (the config flag and the SQLite record) until the old system is fully removed (planned for the next ADR).

---

## References

- [ADR‑001: Hexagonal Architecture](001_hexagonal_architecture.md) — the EventBus and port/adapter pattern that enables passive observation
- [ADR‑005: Human‑in‑the‑Loop](005_human_in_the_loop.md) — the consent model is similar: opt‑in, overrideable by admin policy
- `application/services/research/collector.py` — the old `ResearchCollector` (deprecated)
- `adapters/secondary/research/signal_aggregator.py` — the new `ResearchSignalAggregator`
- `domain/ports/research_port.py` — the `ResearchObserverPort` contract
- [Research Module Documentation](../research_module/index.md)
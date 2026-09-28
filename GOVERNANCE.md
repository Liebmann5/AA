# Governance

This document describes how decisions are made in AutoApply. It is deliberately
short and deliberately honest: AA is a single-maintainer project, and a
governance document that implies a committee would be a lie in the first
paragraph.

## Current model: benevolent dictator, one maintainer

| Role | Who | What they decide |
| --- | --- | --- |
| Maintainer | Nicholas Liebmann ([@Liebmann5](https://github.com/Liebmann5)) | Everything: scope, architecture, releases, merges |
| Contributor | Anyone who opens a PR | Nothing formally; influence through argument and evidence |

There is no steering committee, no vote, and no appeal. This is a fact about the
project's size, not a statement about the value of contribution.

## Risk this creates, stated plainly

Single-maintainer capacity is recorded as the project's highest-exposure risk.
If the maintainer stops, AA stops. The mitigations in place are: an MIT licence
that permits anyone to fork and continue, documentation aimed at somebody who is
not the maintainer, and a test suite that encodes intent rather than just
behaviour.

## How decisions are made

**Small changes** — bug fixes, documentation, tests, tooling — are decided in the
pull request. If the gates pass and the change is right, it merges.

**Architectural changes** require an **Architecture Decision Record**. An ADR is
not paperwork after the fact: it is where the options considered and the reason
the rejected option was rejected get written down. If a decision changes a layer
boundary, a port contract, a data format, or a user-visible guarantee, it needs
an ADR. See [the ADR index](packages/auto_apply/docs/adr/index.md).

**Scope changes** are the maintainer's alone, because AA's scope is tied to a
research thesis rather than to feature demand.

## Standing exclusions

Some things are decided and will not be reopened without new evidence. They are
excluded on principle, not on effort:

- **CAPTCHA solving.** AA detects and records; it does not defeat.
- **Credential storage by default.** A vault may exist as a seam; it does not
  ship enabled.
- **Generating claims about a user.** Selection and emphasis, yes. Invention, no.
- **Hosted or multi-tenant operation.** Thirty users behind one library IP looks
  thirty times more automated than any human, so the hosted shape is worse at its
  own job — independent of the privacy argument.
- **A required cloud AI or API key.** The whole thesis is that this is
  unnecessary.
- **Concurrency on the deterministic path.** Reproducibility outranks throughput.
- **A general framework before one domain works.**

Proposing one of these is not unwelcome; it just needs to argue against the
recorded reason rather than around it.

## The priority ordering

When two good properties conflict, AA resolves the conflict lexicographically.
Higher tier wins, and the loss is recorded at the decision site.

| Tier | Name | Contains |
| --- | --- | --- |
| T0 | Identity | Worst-case user; free; private; harmless to the host |
| T1 | Research-grade | Deterministic, auditable, provenanced, verified, consented |
| T2 | Architectural longevity | Agnostic, layered, decoupled, modular, portable, configurable, extensible **at named points only** |
| T3 | Human accessibility | Readable, testable, documented, CI, versioned |
| T4 | Performance | Efficient, optimised, lean, responsive |
| T5 | Scale | Scalable, generic, reusable, concurrent, asynchronous |

A change that claims to serve every tier is probably wrong. The full derivation
is in [ENGINEERING_PHILOSOPHY.md](packages/auto_apply/docs/ENGINEERING_PHILOSOPHY.md)
and the [Architecture Bible](packages/auto_apply/docs/AA_ARCHITECTURE_BIBLE.md).

## Becoming a maintainer

There is no maintainer besides the author, and no process for adding one, because
no one has yet sustained contribution long enough for the question to be real.
If you want that to change: land several non-trivial changes, review other
people's, and ask. The process will be written when it is needed, not before.

## Nothing is deleted

Orphaned, obsolete, superseded or abandoned files are **retired**, not deleted —
moved to `packages/auto_apply/docs/old_retired_files/` with their origin stamped
on line 1 and their story recorded in the ledger. Before adding any new code or
tool, check that directory first. See
[ADR-016](packages/auto_apply/docs/adr/016_retirement_over_deletion.md).

## Licence and provenance

AA is MIT licensed. Contributions are accepted under the same licence; there is
no CLA. AA is citable software — see [CITATION.cff](CITATION.cff).

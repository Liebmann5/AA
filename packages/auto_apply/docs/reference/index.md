---
title: Reference
status: reviewed
last_verified: 2026-09-19
verified_against: "src/auto_apply tree, 35 port modules, 260 src modules"
audience: everyone
---

# Reference

Look-up material: complete, structured, and deliberately free of argument. If
you want to know *why* something is shaped the way it is, read
[Architecture](../architecture/index.md) or an [ADR](../adr/index.md) instead.

| Page | Contents |
| --- | --- |
| [Profile schema](profile_schema.md) | Every field in a user profile, with types and defaults |
| [Ports](ports.md) | The port catalogue — what each one abstracts, and how many modules use it |
| [Command line](cli.md) | Flags, environment variables, and what is parsed before import |
| [Glossary](glossary.md) | Terms used precisely throughout AA |

Configuration values are documented as a task in
[Configuration](../getting_started/configuration.md) rather than duplicated
here — one subject, one page.

Machine-generated API documentation lives in
[API Reference](../api_reference/index.md).

## Counts as of 2026-09-19

Measured, not estimated. If these disagree with the tree, the tree is right and
this page is stale.

| Thing | Count |
| --- | --- |
| Source modules | 260 |
| Source lines | 61,251 |
| Port modules | 35 |
| Test modules | 146 |
| Tests passing | 1,384 (2 skipped) |
| SQLite tables | 14 |
| Architecture decision records | 17 |
| Signal detectors | 29 |
| Discovery providers | 3 (Google, Bing, Indeed) |

## Where the authoritative answer lives

| Question | Authority |
| --- | --- |
| Does this work yet? | [STATUS.md](../STATUS.md) |
| How do I install it? | [Installation](../getting_started/installation.md) |
| Why was it built this way? | [ADR index](../adr/index.md) |
| What is AA trying to be? | [ENGINEERING_PHILOSOPHY.md](../ENGINEERING_PHILOSOPHY.md) |
| How does the detailed design work? | [AA_ARCHITECTURE_BIBLE.md](../AA_ARCHITECTURE_BIBLE.md) |
| What changed? | [CHANGELOG](https://github.com/Liebmann5/AA/blob/main/CHANGELOG.md) |

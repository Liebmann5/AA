---
title: Command-Line Reference
status: reviewed
last_verified: 2026-09-19
verified_against: "src/auto_apply/main.py argument parser"
audience: everyone
---

# Command-Line Reference

Two entry points are declared and behave identically:

```bash
python -m auto_apply      # module entry
auto-apply                # console script, available after install
```

## Flags

| Flag | Argument | Effect |
| --- | --- | --- |
| `--cli` | — | Run the terminal interface instead of the GUI |
| `--debug` | — | Verbose debug logging |
| `--check-config` | — | Print an environment and capability summary, then exit |
| `--profile` | `NAME_OR_PATH` | Use a named profile or a profile file for this run |
| `--portable` | — | Store all data in `./data/` relative to the working directory |
| `--seed` | `N` | Deterministic mode. Identical configuration produces identical execution traces |
| `--export-research` | — | Export collected research signals and exit, without running a session |
| `--export-format` | `csv` \| `ndjson` \| `parquet` | Output format for `--export-research`. Default `csv` |
| `--research-summary` | — | Print what the discovery research tables hold, then exit. Read-only; starts no session |
| `--label` | — | Label saved pages and log the applications you make by hand. See [Labelling](../user_guide/labelling.md) |
| `--encrypt-profile` | — | Encrypt the current plaintext profile into a `.vault` file behind a master password |

## Flags parsed before anything else

`--portable` and `--seed` are read by a **pre-parser** that runs before any
`auto_apply` module is imported.

This is not tidiness. `domain/config.py` computes the data directories at import
time, so `AA_DATA_DIR` must be set before that import happens or portable mode
silently writes to the wrong place. The seed has the same constraint: it must be
in the environment before any component reads it.

Both flags are also declared on the main parser so they appear in `--help`.

## Determinism

```bash
python -m auto_apply --cli --seed 42
```

`--seed N` derives an independent, reproducible random stream per namespace via
`SHA-256(seed:namespace)`. Runs with the same seed and the same configuration
produce the same execution trace, which is what makes AA's research output
reproducible.

Without `--seed`, AA uses an unseeded generator. **That is the correct default
for real use** — a fixed seed makes your behaviour predictable to the sites you
visit.

## Portable mode

```bash
cd /media/usb/autoapply
python -m auto_apply --portable
```

Everything AA writes — profiles, database, logs, reports, caches — goes to
`./data/` next to the working directory. Equivalent to setting `AA_DATA_DIR`
yourself.

`[PARTIAL]` — portable mode runs, and `launch_portable.sh` has known containment
defects, including not setting `SE_CACHE_PATH`, which lets Selenium Manager
write a driver to the host's cache. See [STATUS.md](../STATUS.md) before relying
on "no traces on the host".

## Exporting research data

```bash
python -m auto_apply --export-research --export-format ndjson
```

Exits without running a session. `parquet` requires the `research` extra.
Exports only what you consented to collect; if you never opted in, the export is
empty. Format details are in
[research_module/data_format.md](../research_module/data_format.md).

## Encrypting a profile

```bash
python -m auto_apply --encrypt-profile
```

Prompts for a master password and writes a `.vault` file. **The plaintext
`.json` is deleted after a successful encryption.** There is no recovery path if
you forget the password — that is a property of the encryption, not an oversight.

## Environment variables

| Variable | Effect |
| --- | --- |
| `AA_DATA_DIR` | Root for all data AA writes. `--portable` sets it to `./data` |
| `AA_RANDOM_SEED` | Equivalent to `--seed` |
| `PYTHONIOENCODING` | CI sets `utf-8`. AA reconfigures the console itself, so this is belt and braces |

## Exit behaviour

AA is a long-running interactive agent rather than a batch tool, and **does not
yet publish a stable exit-code contract**. `--check-config`,
`--export-research`, `--research-summary`, `--label` and `--encrypt-profile`
exit after their work; the others run until you stop the session.

`[PLANNED]` — a documented exit-code table. Do not script against exit codes
until it exists.

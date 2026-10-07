---
title: Retention Holds and Uninstall
status: reviewed
last_verified: 2026-10-06
verified_against: "application/services/uninstall/engine.py; research_consent.py"
audience: researchers
---

# Retention Holds and Uninstall

AA is not the investigator. Your IRB-approved protocol governs your data,
and it outlives the tool: 45 CFR 46.115(b) requires records relating to
conducted research to be retained **at least 3 years** after the research is
completed, and many institutions require 6–7. AA's job is to never make
your protocol unmeetable.

## The hold

A retention hold is a small JSON file in AA's data directory:

```
<data dir>/research_retention.json
```

```json
{
  "hold_until": "2029-06-30",
  "note": "IRB protocol 2026-114, 3-year retention after completion",
  "set_on": "2026-10-13"
}
```

`hold_until` is an ISO date **or** the string `"until-released"`. Create or
edit the file with any text editor — deliberately, so a researcher can set
it without AA running. An unparseable date reads as **active**: a garbled
hold fails toward preservation, never toward destruction. Both lifecycle
surfaces (CLI `--uninstall`, GUI **File → Uninstall…**) show the hold and
its note in the plan.

## What uninstall does with research data

| Choice | Without a hold | With an active hold |
| --- | --- | --- |
| **Keep in place** (default) | Data stays; nothing is mutated | Data stays; withdrawal is recorded without destroying anything (page copies included), and a notice is written into the data |
| **Move** (`--research-keep DIR`) | The whole research home moves to your folder | Not offered by the surfaces |
| **Export** (`--research-export DIR`) | A verified bundle is written first; originals go with the data home | Available — a copy destroys nothing |
| **Delete** (`--research-delete`) | Secure purge via the consent-withdrawal path (secure-delete, key rotation) | **Refused** — no flag overrides the hold; export is offered instead |

Two things are always true: collection is **stopped first** (a live
aggregator once recreated a purged database and minted a new key — that
path is now a pinned test), and page copies follow their own consent text
(deleted on withdrawal) **unless a hold is active**, in which case they are
preserved too.

## Documenting the withdrawal (OHRP 2010 guidance)

When uninstall retains or exports research data, AA writes
`aa_withdrawal_notice.json` into the retained/exported data:

```json
{
  "type": "research-withdrawal-notice",
  "date": "2026-10-13",
  "decided_by": "subject",
  "scope": "all research components",
  "method": "uninstall (kept)",
  "identifying_information": "none"
}
```

It records who decided and the scope — never anything identifying, and never
into a place the uninstall then claims is gone. The machine-readable
`--uninstall-report` records the same decision.

## What the consent text says

Since consent version 2.6, the dialog every participant sees states that
uninstalling AA withdraws participation, that research records are kept by
default, that deletion happens only by explicit choice, and that a
retention hold prevents destruction while active. The canonical text lives
in `domain/services/research_consent_text.py` and is quoted verbatim in
[RESEARCH_CONSENT_DIALOG.md](../RESEARCH_CONSENT_DIALOG.md).

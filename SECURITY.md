# Security Policy

AutoApply runs on other people's computers, handles a user's real identity
documents, and drives a browser against third-party websites. Security is
treated as an architectural concern, not a late review step.

## Supported versions

AA has **no tagged release**. The only supported version is the current
`main` branch. When `v0.1.0` is tagged this table will be filled in.

| Version | Supported |
| --- | --- |
| `main` | Yes |
| Everything else | No — no release exists yet |

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Report privately through either channel:

1. **GitHub Security Advisories** (preferred) —
   <https://github.com/Liebmann5/AA/security/advisories/new>
2. **Email** — liebmann.nicholas1@gmail.com with `[AA SECURITY]` in the subject.

Please include:

- What the vulnerability allows an attacker to do.
- The steps to reproduce it, with the smallest input that triggers it.
- The commit hash, operating system and Python version you tested on.
- Whether you have disclosed it anywhere else.

**Please do not include real personal data in a report.** AA writes screenshots
and logs that routinely contain a real name, address and employment history. If
a reproduction needs one of those artefacts, say so and we will arrange a
private channel rather than attaching it to a ticket.

## What to expect

AA is maintained by one person. These are honest targets, not a corporate SLA:

| Stage | Target |
| --- | --- |
| Acknowledgement | 3 working days |
| Initial assessment | 10 working days |
| Fix or documented mitigation | 90 days for high severity |

You will be credited in the advisory and the changelog unless you ask not to
be. AA has no bug-bounty budget.

## Scope

**In scope**

- Anything that writes outside AA's own data directory without consent.
- Anything that exfiltrates profile data, documents or credentials.
- Anything that leaves traces on a shared or library machine after teardown.
- Personal data appearing in logs, exports, screenshots or research output.
- Failures of the consent gate or the PII anonymisation path.
- Dependency vulnerabilities reachable from AA's own code paths.
- Anything that submits an application without the user's authorisation.

**Out of scope**

- Websites detecting and blocking AA. That is expected behaviour, and AA
  records it as data rather than defeating it.
- CAPTCHA challenges not being solved. AA does not solve CAPTCHAs by design.
- Vulnerabilities requiring an attacker who already has full control of the
  user's machine.
- Issues in a fork, or in a dependency with no reachable path from AA.

## Security properties AA claims

Each of these is a claim you may test and disprove. Where a pin enforces the
property, the pin is named; a claim with no pin is a claim awaiting one.

| Property | Enforcement |
| --- | --- |
| No credential is stored by default | No credential vault ships; `NullVault` is the only implementation |
| Research output contains no raw personal data | Salted SHA-256 anonymisation; `tests/architecture/test_safety_pins.py` |
| Personal data does not reach the activity stream | PII sentinel pin, `test_no_pii_in_the_activity_stream` (known scope gap: surface formatters are not yet covered) |
| Nothing is installed or updated on the user's device without consent | Hard Principle 2, `ENGINEERING_PHILOSOPHY.md`; enforced by review, not yet by a pin |
| Submission never happens without authorisation | Fail-closed gate, [ADR-012](packages/auto_apply/docs/adr/012_fail_closed_submission_gate.md) |
| Autonomy cannot be enabled without two acknowledgements | `set_autonomy` refuses with fewer than two; AST guards |

Known gaps are listed in [STATUS.md](packages/auto_apply/docs/STATUS.md) rather
than hidden here.

## Hardening guidance for shared machines

If you are deploying AA in a library, school or career centre, read
[user_guide/admin_policy.md](packages/auto_apply/docs/user_guide/admin_policy.md).
An `aa_policy.json` can lock browsers, force headless operation, impose delay
floors and disable research collection device-wide.

---
title: "Research Consent Dialog — Exact UI Text (v2.3)"
status: needs-review
last_verified: 2026-09-27
verified_against: "bulk provenance stamp 2026-09-27; content not individually re-verified against code"
audience: researchers
---

# Research Consent Dialog — Exact UI Text (v2.3)

This document is the AUTHORITATIVE SOURCE for the consent dialog text shown
to users when they enable research data collection in Settings → Research.

The canonical strings live in code —
`src/auto_apply/domain/services/research_consent_text.py` — so the GUI and
CLI load them instead of carrying copies. The GUI/CLI must render this text
VERBATIM (or link to it) — do not paraphrase. A pin
(`tests/research/test_research_consent.py`) fails if this document and the
code module drift apart, and a second pin fails if any table in the research
schema is not disclosed in the text below. Edit the code module FIRST.

`CURRENT_CONSENT_VERSION` in `domain/constants.py` MUST match
the version number in this document's title. If you edit this text in any
way that changes what data is collected or how, increment
`CURRENT_CONSENT_VERSION` — this triggers re-consent for existing users
(see `ResearchConsentManager.needs_reconsent()`).

---

## Dialog Title

> Help Improve the Job Market — Optional Research Participation

## Dialog Body

> AutoApply can optionally analyze the job postings and application forms
> it processes during your sessions to detect patterns of hiring system
> dysfunction — things like ghost job postings, salary transparency law
> violations, discriminatory language, and unrealistic job requirements.
>
> This is completely optional and OFF by default.
>
> What gets collected if you opt in:
>
> - Anonymized excerpts (max 200 characters) of job description text that
>   triggered a detection pattern
> - The employer's name, converted to an anonymous code that cannot be
>   reversed back to the employer's name
> - Job posting metadata: posting date, platform, location, salary range
>   (if disclosed), and job category
> - How long postings stay visible and how often they are reposted, per
>   platform (no posting URLs)
> - Application form structure: number of fields, whether certain
>   questions are present (e.g. "What is your current salary?"),
>   accessibility compliance
> - Whether your applications receive any acknowledgment within 30 days
> - Which search providers and result-page hosts your sessions visited,
>   what those result pages looked like (job titles shown, whether a page
>   was a block or CAPTCHA page), and the link texts and destination hosts
>   behind result links. Your search query and full web addresses (URLs)
>   are NOT recorded; a web address shown inside a link text is cut down
>   to its host. Job titles, link texts and destination hosts are stored
>   as shown and may include employer names (a host such as
>   acme.myworkdayjobs.com names its employer). A results page that
>   repeats your search words in a title or link text (a listing called
>   "20 Python jobs in Sacramento") is stored as shown too.
> - Which detectors ran on each posting and how each concluded, so rates
>   in published research have a trustworthy denominator
> - A public verification key that lets recipients confirm exported rows
>   came from an unmodified AutoApply (the private key never leaves your
>   data folder)
>
> What is NEVER collected:
>
> - Your name, email, phone number, or any personal identifying information
> - Your resume content or cover letters
> - Your answers to application questions
> - Login credentials (never stored or logged, with or without research)
> - Full job description text (only short excerpts proving a detected pattern)
> - Your search queries or full web addresses (URLs)
>
> How your data is used:
>
> Anonymized data may be aggregated with data from other AutoApply users
> and published in academic research about hiring market dysfunction —
> for example, studies on ghost job prevalence, pay transparency law
> compliance, or discriminatory hiring patterns. Published results report
> only aggregate statistics (e.g. "23% of postings in Sector X showed signs
> of being ghost jobs") — never information that could identify you. Rows
> that name an employer at all store the name only as an irreversible
> anonymous code; job titles, link texts and destination hosts are
> recorded as displayed (see above).
>
> Your rights:
>
> - You can withdraw consent at any time in Settings → Research
> - Withdrawing consent immediately stops new data collection
> - You can request deletion of all data collected so far — deletion is
>   immediate and permanent, and covers every research table as well as the
>   private key that signed your rows
> - You can export a copy of everything collected from your sessions before
>   deleting it
>
> Note: research collection also needs a private research key on this
> device (the AA_RESEARCH_SALT setting). If it is missing, research stays
> off and AutoApply works normally — your choice is remembered and takes
> effect once the key is present.
>
> Full details: see docs/ETHICS.md in the AutoApply repository.

## Buttons

> I Agree — Enable Research Participation
> Not Now

## Re-Consent Prompt (shown when `needs_reconsent()` is True)

> AutoApply's Research Practices Have Been Updated
>
> You previously opted into research data collection (version
> {old_version}). The data collection practices have changed since then —
> please review the updated terms before research collection resumes.
>
> "View Changes" links to the CHANGELOG.md entry for the new version,
> which describes in plain language what changed.

## Withdrawal Confirmation

> Withdraw Research Participation?
>
> This will stop all future research data collection immediately.
>
> [ ] Also delete all data collected so far (recommended)
>
> If checked, ALL research data linked to your sessions — every anonymized
> signal, salary, form, discovery and detector record — is deleted
> immediately and permanently, together with the private key that signed
> your rows, so nothing you contribute later can be linked back to what was
> deleted. Files you previously exported yourself are not touched; delete
> those separately if you want them gone. Your consent record itself is
> kept, so AutoApply remembers that you withdrew.
>
> This cannot be undone.

## Data Export Confirmation

> **Export Your Research Contribution**
>
> This will create a folder containing all anonymized data collected from
> your AutoApply sessions — one file per research table, an index, and the
> public verification key. It is saved under `reports/` in AutoApply's data
> folder.
>
> Format: [ CSV ▾ ]  (options: CSV, NDJSON, Parquet)
>
> [ Export ]   [ Cancel ]

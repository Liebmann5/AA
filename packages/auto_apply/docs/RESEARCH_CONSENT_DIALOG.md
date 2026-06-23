# Research Consent Dialog — Exact UI Text (v2.1)

This document is the AUTHORITATIVE SOURCE for the consent dialog text shown
to users when they enable research data collection in Settings → Research.

The GUI/CLI must render this text VERBATIM (or link to it) — do not
paraphrase. `CURRENT_CONSENT_VERSION` in `domain/constants.py` MUST match
the version number in this document's title. If you edit this text in any
way that changes what data is collected or how, increment
`CURRENT_CONSENT_VERSION` — this triggers re-consent for existing users
(see `ResearchConsentManager.needs_reconsent()`).

---

## Dialog Title

> **Help Improve the Job Market — Optional Research Participation**

## Dialog Body

> AutoApply can optionally analyze the job postings and application forms
> it processes during your sessions to detect patterns of hiring system
> dysfunction — things like ghost job postings, salary transparency law
> violations, discriminatory language, and unrealistic job requirements.
>
> **This is completely optional and OFF by default.**
>
> ### What gets collected if you opt in:
>
> - Anonymized excerpts (max 200 characters) of job description text that
>   triggered a detection pattern
> - The employer's name, converted to an anonymous code that cannot be
>   reversed back to the employer's name
> - Job posting metadata: posting date, platform, location, salary range
>   (if disclosed), and job category
> - Application form structure: number of fields, whether certain
>   questions are present (e.g. "What is your current salary?"),
>   accessibility compliance
> - Whether your applications receive any acknowledgment within 30 days
>
> ### What is NEVER collected:
>
> - Your name, email, phone number, or any personal identifying information
> - Your resume content or cover letters
> - Your answers to application questions
> - Login credentials (never stored or logged, with or without research)
> - Full job description text (only short excerpts proving a detected pattern)
>
> ### How your data is used:
>
> Anonymized data may be aggregated with data from other AutoApply users
> and published in academic research about hiring market dysfunction —
> for example, studies on ghost job prevalence, pay transparency law
> compliance, or discriminatory hiring patterns. Published results report
> only aggregate statistics (e.g. "23% of postings in Sector X showed signs
> of being ghost jobs") — never information that could identify you or any
> specific employer by name.
>
> ### Your rights:
>
> - You can withdraw consent at any time in Settings → Research
> - Withdrawing consent immediately stops new data collection
> - You can request deletion of all data collected so far — this happens
>   within 24 hours and is permanent
> - You can export a copy of everything collected from your sessions before
>   deleting it
>
> Full details: see `docs/ETHICS.md` in the AutoApply repository.

## Buttons

> [ I Agree — Enable Research Participation ]   [ Not Now ]

## Re-Consent Prompt (shown when `needs_reconsent()` is True)

> **AutoApply's Research Practices Have Been Updated**
>
> You previously opted into research data collection (version
> `{old_version}`). The data collection practices have changed since then —
> please review the updated terms before research collection resumes.
>
> [ View Changes ]   [ I Agree — Continue Participation ]   [ Withdraw Consent ]

"View Changes" should link to the CHANGELOG.md entry corresponding to the
version bump, which must describe in plain language what changed.

## Withdrawal Confirmation

> **Withdraw Research Participation?**
>
> This will stop all future research data collection immediately.
>
> [ ] Also delete all data collected so far (recommended)
>
> If checked, all anonymized signals, salary observations, and form
> observations linked to your sessions will be permanently deleted within
> 24 hours. This cannot be undone.
>
> [ Withdraw ]   [ Cancel ]

## Data Export Confirmation

> **Export Your Research Contribution**
>
> This will create a file containing all anonymized data collected from
> your AutoApply sessions. The file will be saved to your Downloads folder.
>
> Format: [ CSV ▾ ]  (options: CSV, JSON, Parquet)
>
> [ Export ]   [ Cancel ]

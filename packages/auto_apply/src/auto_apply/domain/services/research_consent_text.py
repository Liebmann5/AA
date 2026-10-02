"""The canonical research-consent dialog text — the ONE copy.

The GUI and CLI render these strings; they never carry their own copies.
docs/RESEARCH_CONSENT_DIALOG.md quotes them verbatim and a pin
(tests/research/test_research_consent.py) fails if the document and this
module drift apart, so the document's "AUTHORITATIVE SOURCE" claim is
enforced rather than asserted. Edit HERE first, then update the doc's quoted
sections; bump CURRENT_CONSENT_VERSION (domain/constants.py) and the doc's
title together whenever the text changes what is collected or how.

The "What gets collected" list is pinned against the research schema itself:
every table in signal_aggregator._SCHEMA_SQL maps to a phrase that must
appear in DIALOG_BODY (same pin file), so a new table cannot ship
undisclosed the way the discovery and detector tables did (M5).
"""

from __future__ import annotations

from auto_apply.domain.constants import CURRENT_CONSENT_VERSION
from auto_apply.domain.ports.research_consent_port import ResearchConsentDialog

__all__ = [
    "DIALOG_TITLE",
    "DIALOG_BODY",
    "AGREE_LABEL",
    "DECLINE_LABEL",
    "RECONSENT_TITLE",
    "RECONSENT_BODY_TEMPLATE",
    "WITHDRAW_TITLE",
    "WITHDRAW_BODY",
    "consent_dialog",
]

DIALOG_TITLE = "Help Improve the Job Market — Optional Research Participation"

DIALOG_BODY = """AutoApply can optionally analyze the job postings and application forms
it processes during your sessions to detect patterns of hiring system
dysfunction — things like ghost job postings, salary transparency law
violations, discriminatory language, and unrealistic job requirements.

This is completely optional and OFF by default.

What gets collected if you opt in:

- Anonymized excerpts (max 200 characters) of job description text that
  triggered a detection pattern
- The employer's name, converted to an anonymous code that cannot be
  reversed back to the employer's name
- Job posting metadata: posting date, platform, location, salary range
  (if disclosed), and job category
- How long postings stay visible and how often they are reposted, per
  platform (no posting URLs)
- Application form structure: number of fields, whether certain
  questions are present (e.g. "What is your current salary?"),
  accessibility compliance
- Whether your applications receive any acknowledgment within 30 days
- Which search providers and result-page hosts your sessions visited,
  what those result pages looked like (job titles shown, whether a page
  was a block or CAPTCHA page), and the link texts and destination hosts
  behind result links. Your search query and full web addresses (URLs)
  are NOT recorded; a web address shown inside a link text is cut down
  to its host. Job titles, link texts and destination hosts are stored
  as shown and may include employer names (a host such as
  acme.myworkdayjobs.com names its employer). A results page that
  repeats your search words in a title or link text (a listing called
  "20 Python jobs in Sacramento") is stored as shown too.
- Which detectors ran on each posting and how each concluded, so rates
  in published research have a trustworthy denominator
- A public verification key that lets recipients confirm exported rows
  came from an unmodified AutoApply (the private key never leaves your
  data folder)

What is NEVER collected:

- Your name, email, phone number, or any personal identifying information
- Your resume content or cover letters
- Your answers to application questions
- Login credentials (never stored or logged, with or without research)
- Full job description text (only short excerpts proving a detected pattern)
- Your search queries or full web addresses (URLs)

How your data is used:

Anonymized data may be aggregated with data from other AutoApply users
and published in academic research about hiring market dysfunction —
for example, studies on ghost job prevalence, pay transparency law
compliance, or discriminatory hiring patterns. Published results report
only aggregate statistics (e.g. "23% of postings in Sector X showed signs
of being ghost jobs") — never information that could identify you. Rows
that name an employer at all store the name only as an irreversible
anonymous code; job titles, link texts and destination hosts are
recorded as displayed (see above).

Your rights:

- You can withdraw consent at any time in Settings → Research
- Withdrawing consent immediately stops new data collection
- You can request deletion of all data collected so far — deletion is
  immediate and permanent, and covers every research table as well as the
  private key that signed your rows
- You can export a copy of everything collected from your sessions before
  deleting it

Note: research collection also needs a private research key on this
device (the AA_RESEARCH_SALT setting). If it is missing, research stays
off and AutoApply works normally — your choice is remembered and takes
effect once the key is present.

Full details: see docs/ETHICS.md in the AutoApply repository."""

AGREE_LABEL = "I Agree — Enable Research Participation"
DECLINE_LABEL = "Not Now"

RECONSENT_TITLE = "AutoApply's Research Practices Have Been Updated"

RECONSENT_BODY_TEMPLATE = """You previously opted into research data collection (version
{old_version}). The data collection practices have changed since then —
please review the updated terms before research collection resumes.

"View Changes" links to the CHANGELOG.md entry for the new version,
which describes in plain language what changed."""

WITHDRAW_TITLE = "Withdraw Research Participation?"

WITHDRAW_BODY = """This will stop all future research data collection immediately.

[ ] Also delete all data collected so far (recommended)

If checked, ALL research data linked to your sessions — every anonymized
signal, salary, form, discovery and detector record — is deleted
immediately and permanently, together with the private key that signed
your rows, so nothing you contribute later can be linked back to what was
deleted. Files you previously exported yourself are not touched; delete
those separately if you want them gone. Your consent record itself is
kept, so AutoApply remembers that you withdrew.

This cannot be undone."""


def consent_dialog() -> ResearchConsentDialog:
    """The dialog every surface renders before grant(), versioned.

    The version is CURRENT_CONSENT_VERSION — the same value grant() records
    — so "which text did this user agree to" is answered by construction.
    """
    return ResearchConsentDialog(
        version=CURRENT_CONSENT_VERSION,
        title=DIALOG_TITLE,
        body=DIALOG_BODY,
        agree_label=AGREE_LABEL,
        decline_label=DECLINE_LABEL,
        reconsent_title=RECONSENT_TITLE,
        reconsent_body_template=RECONSENT_BODY_TEMPLATE,
        withdraw_title=WITHDRAW_TITLE,
        withdraw_body=WITHDRAW_BODY,
    )

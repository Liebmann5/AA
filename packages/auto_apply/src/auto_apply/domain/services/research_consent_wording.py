"""Plain words for the research-consent states — one copy, both surfaces.

NOT consent text: nothing here is versioned, and nothing here is pinned to
docs/RESEARCH_CONSENT_DIALOG.md (that pin covers the dialog strings in
research_consent_text.py only). This module is the single home for the
words a screen uses to describe the CURRENT state — off, withdrawn, needs
re-consent, inactive with a reason, active — and the page-copies state, so
the GUI research window and the CLI research screen can never disagree
about what a state means or what the user can do next (S4). A totality pin
in tests/adapters/test_cli_research_screen.py fails if a state or reason
exists without words, and the parity pin asserts both surfaces read their
words from here.

The research public-key fingerprint line (public_key_line) lives here too:
not a state, but a sentence both surfaces must word identically.

Window chrome (button captions, menu labels) is deliberately NOT here and
NOT translated either way: the consent text itself is never translated —
a translated dialog would be a different text the user agreed to and would
need its own version — and the states describe that same text, so they
stay in the one language the consent record can mean.
"""

from __future__ import annotations

from auto_apply.domain.ports.research_consent_port import (
    PageCopiesState,
    ResearchConsentReason,
    ResearchConsentState,
    ResearchConsentStatus,
)

__all__ = [
    "status_headline",
    "status_detail",
    "page_copies_line",
    "public_key_line",
    "view_changes_note",
]

_HEADLINES: dict[ResearchConsentState, str] = {
    ResearchConsentState.OFF: "Research participation is off.",
    ResearchConsentState.WITHDRAWN: "You withdrew from research participation.",
    ResearchConsentState.NEEDS_RECONSENT: (
        "AutoApply's research practices have changed since you agreed."
    ),
    ResearchConsentState.INACTIVE: (
        "You agreed to research participation, but nothing is being collected."
    ),
    ResearchConsentState.ACTIVE: "Research participation is on.",
}

_DETAILS: dict[ResearchConsentState, str] = {
    ResearchConsentState.OFF: (
        "Nothing about your sessions is recorded for research. You can read "
        "the consent text and agree to turn it on; AutoApply works the same "
        "either way."
    ),
    ResearchConsentState.WITHDRAWN: (
        "Nothing new is collected. You can join again whenever you like; "
        "AutoApply works the same either way."
    ),
    ResearchConsentState.NEEDS_RECONSENT: (
        "Nothing is collected until you read the updated text and agree "
        "again. AutoApply works normally in the meantime."
    ),
    ResearchConsentState.ACTIVE: (
        "Anonymized research data is recorded as described in the consent "
        "text. You can withdraw, export, or delete it at any time."
    ),
}

# INACTIVE renders from its reason, not the state — S4's "you agreed, and
# nothing is being collected" case, which is where EVERY grant lands until
# salt provisioning (item 10) exists. It must say what (if anything) the
# user can do.
_REASON_DETAILS: dict[ResearchConsentReason, str] = {
    ResearchConsentReason.NO_SALT: (
        "The private research key AutoApply keeps on this device is missing "
        "and could not be created. Your choice is remembered and takes "
        "effect once the key exists — AutoApply retries creating it each "
        "time a session starts, and works normally either way."
    ),
    ResearchConsentReason.ADMIN_PROHIBITED: (
        "An administrator policy on this device disables research "
        "collection. AutoApply works normally; the choice is locked by "
        "your device administrator."
    ),
    ResearchConsentReason.NOT_OFFERED: (
        "This AutoApply installation does not offer research collection. "
        "AutoApply works normally without it."
    ),
}

# INACTIVE with a reason this module does not know cannot happen through
# status() today — but the port promises status() never raises and is safe
# to poll, so the wording must never raise either. An honest generic line,
# not a KeyError.
_INACTIVE_UNKNOWN_REASON: str = (
    "Research collection is not running right now, for a reason this "
    "version of AutoApply does not have words for. AutoApply works "
    "normally; your consent record is unchanged."
)

_ACTIVE_COLLECTING: str = (
    "Anonymized research data is being recorded in the running session, as "
    "described in the consent text. You can withdraw, export, or delete it "
    "at any time."
)


def status_headline(status: ResearchConsentStatus) -> str:
    """The one-sentence headline for the current state. Never empty."""
    return _HEADLINES[status.state]


#: Shown instead of an invitation to agree when research is not offered on
#: this device (admin policy or installation): the opt-in is locked.
_LOCKED: str = (
    "Research participation is turned off on this device — by an "
    "administrator policy or by how AutoApply was installed — so it cannot "
    "be turned on here. AutoApply works normally without it."
)


def status_detail(status: ResearchConsentStatus) -> str:
    """What the state means and what the user can do next. Never empty."""
    if not status.offered and status.state in (
        ResearchConsentState.OFF,
        ResearchConsentState.WITHDRAWN,
        ResearchConsentState.NEEDS_RECONSENT,
    ):
        return _LOCKED
    if status.state is ResearchConsentState.INACTIVE:
        return _REASON_DETAILS.get(status.reason, _INACTIVE_UNKNOWN_REASON)
    if status.state is ResearchConsentState.ACTIVE and status.collecting_now:
        return _ACTIVE_COLLECTING
    return _DETAILS[status.state]


def page_copies_line(status: ResearchConsentStatus) -> str:
    """One line for the page-copies state, including "on but not copying"."""
    if status.page_copies is PageCopiesState.OFF:
        return "Page copies are off."
    if status.page_copies is PageCopiesState.NEEDS_RECONSENT:
        return (
            "The page-copies terms have changed; agree to the new text to "
            "keep cleaned copies of job pages."
        )
    if status.state is ResearchConsentState.ACTIVE and status.collecting_now:
        return "Page copies are on — cleaned copies of job pages are kept on this device."
    return (
        "Page copies are on, but none are being kept right now — keeping "
        "starts when research collection does."
    )


def public_key_line(fingerprint: str | None) -> str:
    """The one line both surfaces show about the research public key (F5):
    the fingerprint a contributor publishes with shared research, so a
    recipient can match it against the key inside an export bundle. None —
    no key yet — is normal before the first recorded row or export, and
    says so."""
    if fingerprint is None:
        return (
            "Research public key: none yet — AutoApply creates it the first "
            "time research data is recorded."
        )
    return (
        f"Research public key fingerprint: {fingerprint} — publish this "
        "with any research you share, so recipients can match it against "
        "the key inside your export."
    )


def view_changes_note() -> str:
    """What the surfaces show where the re-consent template says "View
    Changes": neither surface can hyperlink the CHANGELOG entry, so both
    say where the changes are recorded and then show the full current text
    (FORK 4 — the substance of the link, without a consent-version bump)."""
    return (
        "What changed is recorded in CHANGELOG.md (in the AutoApply folder) "
        "under the new consent version; the full current text is shown below."
    )

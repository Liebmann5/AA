"""The driving port for research consent — the one answer to "is research on?".

Why this port exists
--------------------
Three places used to answer "is research on?" independently: a config flag no
user could reach (``enable_research_collection``), a consent record no
production code could write (``grant_consent`` had no caller), and the admin
prohibition. That is the predicate-enumeration defect: three answers, nothing
checking them against each other, and the user's click connected to none of
them (M1/M2, measured 2026-10-01).

This port is the single interface both user surfaces (GUI settings, CLI)
call — before any session exists and during one. It is deliberately SEPARATE
from UIPort: UIPort is session-bound (constructed around a live orchestrator),
while consent must work on first run, before any profile or orchestrator
exists. It is satisfied structurally by the application layer
(``ResearchConsentManager``), following the UIPort/ProfileRepositoryPort
precedent of a port declared once in domain/ports and satisfied without a
wrapper class.

Semantics (ruled 2026-10-01, FORKs 1-4):
    * The consent RECORD is the only user-level store. Granting writes it;
      withdrawing writes it. Nothing else records the user's decision.
    * Collection requires ALL of: consent granted and current, research
      offered on this device, no admin prohibition, a research salt present.
      ``should_collect()`` is that conjunction and the only collection
      decision; composition_root calls it and nothing else.
    * A GRANT takes effect at the next session build (the session's
      composition is frozen). A WITHDRAWAL takes effect immediately — the
      dialog promises "withdrawing consent immediately stops new data
      collection", and a rights promise outranks the frozen-composition rule.
    * Consent never blocks AA from starting. A grant with no salt leaves
      research clearly OFF (status reports INACTIVE / NO_SALT) and the
      session builds normally. Rows are never written without a private salt
      because no aggregator exists to write them.
    * Page copies (item 6) are a second, specific consent on the SAME port:
      their own versioned dialog, their own grant and withdraw, and their
      own state on ResearchConsentStatus. They require current research
      consent (the record, not collection) and never imply it.
    * Registration of the session's observer is process-wide
      (application/services/research_consent.py): a withdraw() through ANY
      instance of this port stops the running observer of this process, so a
      surface can never report a stop that did not happen (the S2
      measurement, 2026-10-02).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from auto_apply.domain.constants import CURRENT_PAGE_COPIES_VERSION
from auto_apply.domain.models.consent import ConsentRecord


class ResearchConsentState(str, Enum):
    """The user-facing state of research consent.

    OFF             — no consent was ever granted.
    WITHDRAWN       — consent was granted, then withdrawn.
    NEEDS_RECONSENT — consent exists but for an older consent version; the
                      dialog must be shown again before collection resumes.
    INACTIVE        — consent is granted and current, but collection cannot
                      run; ``ResearchConsentStatus.reason`` says why.
    ACTIVE          — consent is granted and current and nothing blocks
                      collection (it starts at the next session build).
    """

    OFF = "off"
    WITHDRAWN = "withdrawn"
    NEEDS_RECONSENT = "needs_reconsent"
    INACTIVE = "inactive"
    ACTIVE = "active"


class ResearchConsentReason(str, Enum):
    """Why an INACTIVE grant cannot collect. NONE for every other state."""

    NONE = "none"
    NO_SALT = "no_salt"
    ADMIN_PROHIBITED = "admin_prohibited"
    NOT_OFFERED = "not_offered"


class PageCopiesState(str, Enum):
    """The state of the page-copies consent (item 6) on ResearchConsentStatus.

    OFF             — page copies were never granted, or were turned off.
    ON              — granted under the current page-copies text. Whether any
                      copy is actually being kept right now is NOT a state
                      here: it is ON combined with the research state and
                      collecting_now, which the surfaces render.
    NEEDS_RECONSENT — granted, but for an older page-copies version; the
                      page-copies text must be shown again before copies
                      resume.
    """

    OFF = "off"
    ON = "on"
    NEEDS_RECONSENT = "needs_reconsent"


@dataclass(frozen=True)
class ResearchConsentStatus:
    """Everything a surface needs to render without reaching into internals.

    Attributes:
        state: The headline state (drives which screen is shown).
        reason: Why an INACTIVE state cannot collect; NONE otherwise.
        offered: Whether research is offered on this device at all. False
            means an admin policy or deployment turned it off — surfaces
            should lock or hide the opt-in, per docs/research_module.
        collecting_now: True only while a live research observer is running
            under this service instance. A pre-session instance always
            reports False; a granted mid-session instance reports False until
            the next build, which is the honest answer.
        consent_version: The version the user most recently agreed to.
        current_version: The version the current dialog carries
            (CURRENT_CONSENT_VERSION).
        page_copies: The state of the second, specific page-copies consent.
        page_copies_version: The page-copies text version the user most
            recently agreed to.
        current_page_copies_version: The version the current page-copies
            dialog carries (CURRENT_PAGE_COPIES_VERSION).
    """

    state: ResearchConsentState
    reason: ResearchConsentReason
    offered: bool
    collecting_now: bool
    consent_version: str | None
    current_version: str
    page_copies: PageCopiesState = PageCopiesState.OFF
    page_copies_version: str | None = None
    current_page_copies_version: str = CURRENT_PAGE_COPIES_VERSION


@dataclass(frozen=True)
class ResearchConsentDialog:
    """The exact text a surface must render before calling grant().

    The strings are the single canonical copy, owned by
    ``domain/services/research_consent_text.py``; a pin requires every line
    of them to appear verbatim in docs/RESEARCH_CONSENT_DIALOG.md, so what the user
    reads and what the code records can never drift apart. ``version`` is how
    the text the user agreed to is identified — it is what grant() records.

    Attributes:
        reconsent_body_template: The re-consent prompt, carrying a literal
            ``{old_version}`` placeholder the surface formats.
    """

    version: str
    title: str
    body: str
    agree_label: str
    decline_label: str
    reconsent_title: str
    reconsent_body_template: str
    withdraw_title: str
    withdraw_body: str


@dataclass(frozen=True)
class PageCopiesDialog:
    """The exact text a surface must render before calling grant_page_copies().

    Mirrors ResearchConsentDialog for the second, specific consent: the
    strings come from the one canonical module
    (``domain/services/research_consent_text.py``), are quoted verbatim in
    docs/RESEARCH_CONSENT_DIALOG.md under the same pin, and ``version`` is
    what grant_page_copies() records — so what the user saw and what was
    recorded cannot diverge.
    """

    version: str
    title: str
    body: str
    agree_label: str
    decline_label: str


@dataclass(frozen=True)
class WithdrawalResult:
    """The outcome of withdraw(), for the surface's confirmation screen.

    collection_stopped is True only when no enabled observer exists in this
    process after the stop attempt — it can never report a stop that did
    not happen (the S2 measurement, 2026-10-02).
    """

    purged: int
    collection_stopped: bool
    status: ResearchConsentStatus


@runtime_checkable
class ResearchConsentPort(Protocol):
    """The complete consent surface: status, the dialog text, grant, withdraw,
    and the page-copies consent.

    Satisfied structurally by ResearchConsentManager (application layer).
    Both user surfaces (the CLI research screen and the GUI research
    window) call exactly these operations:

        * pre-session (first run, settings): build the service via
          composition_root.build_research_consent() (no registry needed);
        * during a session: controller.research_consent is the instance the
          session's observer registered with. Registration is also
          process-wide, so a withdraw() through ANY instance stops the
          running observer of this process — see the module docstring.
    """

    def status(self) -> ResearchConsentStatus:
        """The current consent state. Never raises; safe to poll."""
        ...

    def consent_dialog(self) -> ResearchConsentDialog:
        """The exact text to render before calling grant()."""
        ...

    def grant(self) -> ResearchConsentStatus:
        """Record consent to the CURRENT version and return the new status.

        The surface MUST have rendered consent_dialog() first — the version
        recorded is the version that dialog carries, so what the user saw
        and what was recorded cannot diverge. No acknowledgement tokens
        (unlike set_autonomy): the dialog itself is the acknowledgement, and
        a grant is reversible at any time via withdraw(purge_data=True).
        Collection starts at the next session build.
        """
        ...

    def withdraw(self, purge_data: bool = True) -> WithdrawalResult:
        """Stop collection NOW, record the withdrawal, optionally purge.

        A running observer is stopped before the record is written; with no
        session running, the stop is a no-op and only the record (and the
        data, when purge_data is True) changes.
        """
        ...

    # ── Page copies (item 6): the second, specific consent ──────────────────

    def page_copies_dialog(self) -> PageCopiesDialog:
        """The exact text a surface must render before grant_page_copies()."""
        ...

    def grant_page_copies(self) -> ConsentRecord:
        """Record agreement to keep cleaned page copies on this device.

        Requires current research consent (the record, not collection):
        raises ValueError otherwise. Copies start only when research
        collection does — granting during INACTIVE/NO_SALT is allowed and
        remembered, mirroring the research grant itself.
        """
        ...

    def withdraw_page_copies(self, delete: bool = True) -> int:
        """Stop keeping page copies NOW; by default delete every kept copy.

        Research participation is unaffected. Returns how many copies were
        deleted (0 when delete is False).
        """
        ...

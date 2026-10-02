"""
ResearchConsentManager — the consent gate for all research data collection.

ARCHITECTURE: Application-layer service. Depends only on RepositoryPort
(domain port) for persistence — never touches SQLite directly. The
composition root injects a concrete repository adapter.

Default state: research is OFF. No data is collected, no detectors run,
no SignalAggregator is even constructed, until the user explicitly grants
consent through grant_consent(). This is the worst-case-user-safe default
and the FAIR4RS / deon-compliant default (see docs/ETHICS.md).

Consent versioning: CURRENT_CONSENT_VERSION (domain/constants.py) is bumped
whenever data collection practices change. If a user previously consented
to v2.0 and the app now requires v2.1, is_consent_current() returns False
and the UI must re-prompt before research resumes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, runtime_checkable

from auto_apply.domain.constants import (
    CURRENT_CONSENT_VERSION,
    CURRENT_PAGE_COPIES_VERSION,
)
from auto_apply.domain.models.consent import ConsentRecord
from auto_apply.domain.ports.consent_repository_port import ConsentRepositoryPort
from auto_apply.domain.ports.research_consent_port import (
    ResearchConsentDialog,
    ResearchConsentReason,
    ResearchConsentState,
    ResearchConsentStatus,
    WithdrawalResult,
)
from auto_apply.domain.services import research_consent_text
from auto_apply.domain.services.research_identity import (
    salt_available as _research_salt_available,
)

logger = logging.getLogger(__name__)


class InMemoryConsentRepository:
    """In-memory ConsentRepositoryPort for testing.

    NOT for production use — production must persist to disk so consent
    survives restarts. See SqliteConsentRepository in the adapters layer
    for the real implementation.
    """

    def __init__(self) -> None:
        self._record = ConsentRecord()
        self._purge_count = 0

    def load_consent(self) -> ConsentRecord:
        return self._record

    def save_consent(self, record: ConsentRecord) -> None:
        self._record = record

    def purge_research_data(self) -> int:
        count = self._purge_count
        self._purge_count = 0
        return count

    def purge_page_copies(self) -> int:
        return 0

    def _set_purge_count(self, n: int) -> None:
        """Test helper — not part of the port contract."""
        self._purge_count = n


class ResearchConsentManager:
    """Application service governing research data collection consent.

    This is the ONE answer to "is research on?" (ruled 2026-10-01, FORK 1/2).
    It satisfies domain.ports.research_consent_port.ResearchConsentPort
    structurally; both user surfaces call it, and composition_root builds it
    via build_research_consent() and consults should_collect() — nothing else
    decides whether an aggregator is constructed.

    Usage in composition_root.py:
        consent_service = build_research_consent(registry)
        if consent_service.should_collect():
            observer = ResearchSignalAggregator(db_path, consent_service.consent_version)
            observer.start()
            consent_service.register_observer(observer)
        else:
            observer = NullResearchObserver()

    Args:
        repository: Persistence adapter for consent records.
        is_offered: Whether research is offered on this device/build — the
            ``enable_research_collection`` flag AFTER policy enforcement.
        admin_prohibited: Whether an admin policy forbids research here. Kept
            separate from is_offered so status() can say "disabled by your
            device administrator" rather than merely "unavailable".
        salt_available: Zero-arg callable answering "is a research salt
            configured?". Defaults to domain.research_identity.salt_available,
            which reads the process environment (fixed for a session).
    """

    def __init__(
        self,
        repository: ConsentRepositoryPort,
        *,
        is_offered: bool = True,
        admin_prohibited: bool = False,
        salt_available: Callable[[], bool] | None = None,
    ) -> None:
        self._repository = repository
        self._is_offered = is_offered
        self._admin_prohibited = admin_prohibited
        self._salt_available = salt_available or _research_salt_available
        self._active_observer: Any = None

    def is_active(self) -> bool:
        """Return True when the CONSENT RECORD is granted and current.

        Requires BOTH: consent was granted, AND the consent version matches
        CURRENT_CONSENT_VERSION (re-consent required after policy changes).

        This answers exactly one question — has the user granted current,
        unwithdrawn consent? It does NOT answer whether research collection
        runs: that is should_collect(), which additionally requires research
        to be offered, no admin prohibition, and an available salt. (An
        earlier revision of this docstring claimed is_active() was the
        collection decision; it never was — the config flag it ignored was
        the gate no user could open. See AA_MASTER_TODO predicate row 18.)

        Returns:
            True if the consent record is granted and current.
        """
        record = self._repository.load_consent()
        if not record.granted:
            return False
        if record.withdrawn_at is not None:
            return False
        if record.consent_version != CURRENT_CONSENT_VERSION:
            logger.info(
                "ResearchConsent | Consent version mismatch (have=%s, current=%s) "
                "— re-consent required",
                record.consent_version, CURRENT_CONSENT_VERSION,
            )
            return False
        return True

    def needs_reconsent(self) -> bool:
        """Return True if the user previously consented but the policy has changed.

        Used by the UI to show a "research practices have been updated,
        please review" prompt rather than the full first-time dialog.

        Returns:
            True if a previous consent exists but is for an old version.
        """
        record = self._repository.load_consent()
        return (
            record.granted
            and record.withdrawn_at is None
            and record.consent_version != CURRENT_CONSENT_VERSION
        )

    # ── The collection decision (FORK 1) ─────────────────────────────────────

    def _consent_state(
        self, record: ConsentRecord
    ) -> tuple[ResearchConsentState, ResearchConsentReason]:
        """The one (state, reason) computation behind status() and
        should_collect() — both presentations read this, never their own."""
        if record.withdrawn_at is not None:
            return ResearchConsentState.WITHDRAWN, ResearchConsentReason.NONE
        if not record.granted:
            return ResearchConsentState.OFF, ResearchConsentReason.NONE
        if record.consent_version != CURRENT_CONSENT_VERSION:
            return ResearchConsentState.NEEDS_RECONSENT, ResearchConsentReason.NONE
        if self._admin_prohibited:
            return ResearchConsentState.INACTIVE, ResearchConsentReason.ADMIN_PROHIBITED
        if not self._is_offered:
            return ResearchConsentState.INACTIVE, ResearchConsentReason.NOT_OFFERED
        if not self._salt_available():
            return ResearchConsentState.INACTIVE, ResearchConsentReason.NO_SALT
        return ResearchConsentState.ACTIVE, ResearchConsentReason.NONE

    def should_collect(self) -> bool:
        """The ONE collection decision: consent granted and current, research
        offered, no admin prohibition, and a salt available.

        composition_root calls this and nothing else to decide whether a
        ResearchSignalAggregator is constructed. When it is False, research
        is clearly off and AA builds and runs normally (FORK 4): rows are
        never written without a salt because no aggregator exists.
        """
        state, _reason = self._consent_state(self._repository.load_consent())
        return state is ResearchConsentState.ACTIVE

    # ── The consent interface (FORK 2 — satisfies ResearchConsentPort) ───────

    def status(self) -> ResearchConsentStatus:
        """Everything a surface needs to render, without internals access."""
        record = self._repository.load_consent()
        state, reason = self._consent_state(record)
        return ResearchConsentStatus(
            state=state,
            reason=reason,
            offered=self._is_offered and not self._admin_prohibited,
            collecting_now=self.collecting,
            consent_version=record.consent_version,
            current_version=CURRENT_CONSENT_VERSION,
        )

    def consent_dialog(self) -> ResearchConsentDialog:
        """The exact text a surface must render before calling grant().

        Single canonical copy: domain/services/research_consent_text.py;
        every line of it must appear verbatim in docs/RESEARCH_CONSENT_DIALOG.md, so
        what the user reads and what grant() records cannot drift apart.
        """
        return research_consent_text.consent_dialog()

    def grant(self) -> ResearchConsentStatus:
        """Record consent to the CURRENT version and return the new status.

        The surface MUST have rendered consent_dialog() first — the version
        recorded is the version that dialog carries. No acknowledgement
        tokens (unlike set_autonomy): the dialog itself is the
        acknowledgement, and a grant is reversible at any time via
        withdraw(purge_data=True). Collection starts at the next session
        build, never mid-session (the session's composition is frozen).
        """
        self.grant_consent()
        return self.status()

    def withdraw(self, purge_data: bool = True) -> WithdrawalResult:
        """Stop collection NOW, record the withdrawal, optionally purge.

        Unlike a grant, a withdrawal takes effect immediately — the dialog
        promises "withdrawing consent immediately stops new data collection",
        and a rights promise outranks the frozen-session rule (FORK 3).
        """
        self.stop_collection()
        purged = self.withdraw_consent(purge_data=purge_data)
        return WithdrawalResult(
            purged=purged,
            collection_stopped=not self.collecting,
            status=self.status(),
        )

    # ── The stop channel (FORK 3) ────────────────────────────────────────────

    def register_observer(self, observer: Any) -> None:
        """Register the session's live research observer for later stopping.

        Called by composition_root right after the aggregator starts. This
        registration is what lets a mid-session withdrawal — and session
        shutdown — reach the running observer at all (M4: previously nothing
        held it). Only ever called with the real aggregator, never the Null
        observer. The reference is strong on purpose: the manager lives as
        long as the controller that owns the session.
        """
        self._active_observer = observer

    @property
    def collecting(self) -> bool:
        """True while a registered observer is live (enabled)."""
        observer = self._active_observer
        return bool(observer is not None and getattr(observer, "is_enabled", False))

    def stop_collection(self) -> bool:
        """Stop the registered observer, if any. Idempotent.

        The observer's stop() flushes its queue through the tested drain —
        items collected under consent are written, not lost — and marks it
        disabled, so later observe_* calls become no-ops instead of feeding
        a queue no thread will ever drain. A failure to stop is logged and
        NOT raised: a withdrawal must not fail because the flush hiccuped.

        Returns:
            True if an observer was registered (and stop was attempted).
        """
        observer = self._active_observer
        self._active_observer = None
        if observer is None:
            return False
        try:
            observer.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ResearchConsentManager | observer stop failed: %s", exc
            )
        return True

    @property
    def consent_version(self) -> str | None:
        """The consent version the user most recently agreed to, or None."""
        return self._repository.load_consent().consent_version

    def grant_consent(self) -> ConsentRecord:
        """Record that the user has agreed to CURRENT_CONSENT_VERSION.

        Returns:
            The newly created ConsentRecord.
        """
        record = ConsentRecord(
            granted=True,
            consent_version=CURRENT_CONSENT_VERSION,
            granted_at=datetime.now(timezone.utc),
            withdrawn_at=None,
        )
        self._repository.save_consent(record)
        logger.info("ResearchConsent | Consent granted (version=%s)", CURRENT_CONSENT_VERSION)
        return record

    # ── Page copies (item 6): a second, specific consent ─────────────────────

    def page_copies_dialog(self) -> tuple[str, str]:
        """(title, body) a surface must show before grant_page_copies()."""
        return (
            research_consent_text.PAGE_COPIES_TITLE,
            research_consent_text.PAGE_COPIES_BODY,
        )

    def page_copies_on(self) -> bool:
        """Whether the person agreed to the CURRENT page-copies text and
        their research consent is current. Says nothing about whether
        research actually runs; should_copy_pages() decides that."""
        record = self._repository.load_consent()
        return (
            self.is_active()
            and record.page_copies
            and record.page_copies_version == CURRENT_PAGE_COPIES_VERSION
        )

    def should_copy_pages(self) -> bool:
        """The ONE page-copy decision: research collection runs AND the
        person agreed to page copies under the current text. Read on every
        copy (not cached for the session), so turning copies off takes
        effect at the very next page."""
        return self.should_collect() and self.page_copies_on()

    def grant_page_copies(self) -> ConsentRecord:
        """Record agreement to keep cleaned page copies on this device.

        Page copies extend research participation and are meaningless
        without it, so a person who has not given current research consent
        cannot grant them: that raises rather than recording a decision the
        surface never showed the research text for.
        """
        if not self.is_active():
            raise ValueError(
                "page copies need current research consent first; show "
                "consent_dialog() and grant() before page_copies_dialog()"
            )
        previous = self._repository.load_consent()
        record = ConsentRecord(
            granted=previous.granted,
            consent_version=previous.consent_version,
            granted_at=previous.granted_at,
            withdrawn_at=previous.withdrawn_at,
            page_copies=True,
            page_copies_version=CURRENT_PAGE_COPIES_VERSION,
            page_copies_at=datetime.now(timezone.utc),
        )
        self._repository.save_consent(record)
        logger.info(
            "ResearchConsent | page copies granted (version=%s)",
            CURRENT_PAGE_COPIES_VERSION,
        )
        return record

    def withdraw_page_copies(self, delete: bool = True) -> int:
        """Stop keeping page copies NOW; by default delete every kept copy.

        Research participation is unaffected. Returns how many copies were
        deleted (0 when ``delete`` is False).
        """
        previous = self._repository.load_consent()
        self._repository.save_consent(
            ConsentRecord(
                granted=previous.granted,
                consent_version=previous.consent_version,
                granted_at=previous.granted_at,
                withdrawn_at=previous.withdrawn_at,
            )
        )
        logger.info("ResearchConsent | page copies withdrawn")
        return self._repository.purge_page_copies() if delete else 0

    def withdraw_consent(self, purge_data: bool = True) -> int:
        """Withdraw consent and optionally purge all collected research data.

        Args:
            purge_data: If True (default), delete all research data
                attributable to this user — immediately, per the data
                retention policy in docs/ETHICS.md. The purge itself is
                synchronous.

        Order (FORK 3): stop the running observer FIRST (no new writes; its
        queued items are flushed by stop()'s tested drain), then persist the
        withdrawn record, then purge if asked. With purge_data=True the final
        flushed batch is written and immediately deleted — bounded waste (one
        batch), chosen over a second code path; with purge_data=False the
        flush is exactly what the user is owed, since everything collected
        under consent is kept. If the daemon is wedged and stop's join times
        out, the purge still proceeds: the repository's row-deletion fallback
        exists for exactly a locked/held database.

        Kept page copies are deleted in both cases (purge_research_data
        includes them; without it they are deleted on their own).

        Returns:
            Number of records purged (0 if purge_data=False).
        """
        self.stop_collection()
        previous = self._repository.load_consent()
        record = ConsentRecord(
            granted=False,
            consent_version=previous.consent_version,
            granted_at=previous.granted_at,
            withdrawn_at=datetime.now(timezone.utc),
        )
        self._repository.save_consent(record)
        logger.info("ResearchConsent | Consent withdrawn")

        if purge_data:
            count = self._repository.purge_research_data()
            logger.info("ResearchConsent | Purged %d research records", count)
            return count
        # Page copies (item 6) go either way: they exist only to check
        # research rows against their pages while the person participates,
        # and the withdraw text promises they are deleted.
        self._repository.purge_page_copies()
        return 0
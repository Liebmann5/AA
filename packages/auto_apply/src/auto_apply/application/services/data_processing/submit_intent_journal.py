"""The submission journal: at most one AA-initiated submission per job key.

Phase 0 (P0-3). AA_ENGINE_MATH.md §2 is normative; this module is its I/O.

**Frame.** Each record is ``u32be(len(payload)) ‖ payload ‖ sha256(payload)``,
payload being the record's compact UTF-8 JSON (``SubmitIntentRecord``).
Appends are ``write → flush → os.fsync``; an ARMED frame is then read back
from the file and verified before ``arm`` returns, and no dispatch may
follow an ARMED record that was not read back (spec §2 step 1).

**Reading.**

* A torn last frame — a short header, a frame that runs past the end of the
  file, or a bad checksum on the final frame — is an incomplete write. It is
  treated as absent: its bytes are copied to a ``.torn-<n>`` file beside the
  journal (nothing is deleted) and the journal is cut back to the last valid
  frame, so the next append leaves the journal readable. No dispatch can have
  followed it: ``arm`` does not return until its frame is read back.
  A bad frame followed only by zero bytes to the end of the file is a torn
  tail too: FAT32 and exFAT (and ext4 without data journalling) can record a
  file's new size before its data, so after a power cut or a pulled stick the
  unwritten part reads back as zeros (exFAT's valid-data length does exactly
  this). No record has length zero, so zeros can only be an unfinished write.
* A bad frame *before* the last means the medium is corrupt. The journal
  then refuses to arm for the rest of the session and says so in plain
  words; startup is never blocked.

**Blocking (spec R4, and A3′(b) "block on any surviving record").** A new
attempt for a job key or URL is refused while the journal holds an attempt
for the same key or URL whose latest record is ARMED, DISPATCHING, ACKED or
UNKNOWN, or DONE with a blocking outcome. Only NOT_SENT, or DONE with a
non-blocking outcome, lets the job be tried again. The check reads an
in-memory index kept current by every append under the profile lock — so
it costs a dict lookup, however long the journal grows.

**Recovery.** ``reconcile`` runs once at startup, before any attempt, under
the profile lock. For every unresolved attempt it makes the blocking state
durable in the database first, then appends DONE:

* R1/R2: last record ARMED or DISPATCHING → append UNKNOWN, write UNKNOWN to
  the database, append DONE.
* R3: ACKED → write its outcome, append DONE.
* UNKNOWN → write UNKNOWN, append DONE.

The database writer never weakens a blocking row, and a crash part-way is
repaired by running it again (idempotent): records are only ever appended.

No answer value and no page text is ever written here: job keys, URLs,
outcome names, timestamps.
"""

from __future__ import annotations

import hashlib
import logging
import os
import struct
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from auto_apply.application.services.profile_lock import ProfileLock
from auto_apply.domain.models.application_evidence import (
    BLOCKING_OUTCOMES,
    OUTCOME_VOCABULARY,
)
from auto_apply.domain.models.submission_attempt import (
    RECORD_VERSION,
    AttemptState,
    SubmitIntentRecord,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ArmRefused",
    "AttemptView",
    "IntentJournalError",
    "SubmitIntentJournal",
]

_HEADER = struct.Struct(">I")
_DIGEST_LEN = 32
#: A record is a few hundred bytes; anything far larger is a garbled length.
_MAX_PAYLOAD = 1 << 20

#: Refusal reasons ``arm`` reports (stable names: the workflow and the
#: evidence carry them; the person-facing text is built from them).
JOURNAL_CORRUPT = "journal-corrupt"
JOURNAL_UNAVAILABLE = "journal-unavailable"
PROFILE_LOCKED = "profile-locked"
SYNCED_FOLDER = "synced-folder"
UNRESOLVED_ATTEMPT = "unresolved-attempt"
WRITE_FAILED = "journal-write-failed"


class IntentJournalError(Exception):
    """The journal could not be written or read back."""


class ArmRefused(Exception):
    """Arming was refused; nothing may be dispatched. ``reason`` is one of
    the module's refusal names."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass
class AttemptView:
    """The journal's current view of one attempt."""

    attempt_id: str
    job_key: str
    legacy_url: str
    state: AttemptState
    outcome: str
    armed_seq: int

    @property
    def resolved(self) -> bool:
        return self.state in (AttemptState.NOT_SENT, AttemptState.DONE)

    @property
    def blocks(self) -> bool:
        """Does this attempt block a new one for its key and URL?"""
        if self.state is AttemptState.NOT_SENT:
            return False
        if self.state is AttemptState.DONE:
            return self.outcome in BLOCKING_OUTCOMES or self.outcome not in _KNOWN_OUTCOMES
        return True


#: Outcome names the vocabulary knows; a DONE record naming anything else
#: blocks (fail closed).
_KNOWN_OUTCOMES = frozenset(OUTCOME_VOCABULARY)


def _frame(payload: bytes) -> bytes:
    return _HEADER.pack(len(payload)) + payload + hashlib.sha256(payload).digest()


def _zeros_from(data: bytes, start: int) -> bool:
    """Is every byte from ``start`` to the end of the file zero?"""
    return not data[start:].strip(b"\x00")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


#: Writes one attempt's outcome durably to the database. Signature:
#: ``(job_url, job_key, outcome, attempt_id) -> None``; raises on failure.
OutcomeWriter = Callable[[str, str, str, str], None]


class SubmitIntentJournal:
    """One profile's append-only submission journal."""

    def __init__(
        self,
        path: Path,
        profile: str,
        lock: ProfileLock,
        *,
        synced_root: str | None = None,
        clock: Callable[[], str] = _now,
    ) -> None:
        self._path = Path(path)
        self._profile = str(profile)
        self._lock = lock
        self._synced_root = synced_root
        self._clock = clock
        self._mutex = threading.Lock()
        self._attempts: dict[str, AttemptView] = {}
        self._by_key: dict[str, set[str]] = {}
        self._by_url: dict[str, set[str]] = {}
        self._seq = 0
        self._good_size = 0
        self._loaded = False
        self._corrupt: str | None = None
        self._unusable: str | None = None
        self._torn_note: str | None = None

    # ------------------------------------------------------------------ state
    @property
    def path(self) -> Path:
        return self._path

    @property
    def corrupt(self) -> str | None:
        """Why the journal is unreadable (corruption before the tail), or None."""
        self._ensure_loaded()
        return self._corrupt

    @property
    def synced_root(self) -> str | None:
        return self._synced_root

    @property
    def torn_note(self) -> str | None:
        """Set when a torn last record was found and set aside at load."""
        self._ensure_loaded()
        return self._torn_note

    def unresolved(self) -> list[AttemptView]:
        self._ensure_loaded()
        with self._mutex:
            return [a for a in self._attempts.values() if not a.resolved]

    def blocks(self, job_key: str, legacy_url: str) -> bool:
        """Does the journal hold an attempt that blocks this job?"""
        self._ensure_loaded()
        with self._mutex:
            return self._blocks_locked(job_key, legacy_url)

    def _blocks_locked(self, job_key: str, legacy_url: str) -> bool:
        ids = set(self._by_key.get(job_key, ())) if job_key else set()
        if legacy_url:
            ids |= self._by_url.get(legacy_url, set())
        return any(self._attempts[i].blocks for i in ids)

    # ------------------------------------------------------------------ read
    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._mutex:
            if self._loaded:
                return
            self._load_locked()
            self._loaded = True

    def _load_locked(self) -> None:
        try:
            data = self._path.read_bytes()
        except FileNotFoundError:
            return
        except OSError as exc:
            self._unusable = f"the journal could not be read ({type(exc).__name__})"
            return
        offset = 0
        size = len(data)
        while offset < size:
            if size - offset < _HEADER.size:
                self._set_aside_torn(data, offset, "a short header")
                return
            (length,) = _HEADER.unpack_from(data, offset)
            end = offset + _HEADER.size + length + _DIGEST_LEN
            if end > size:
                # A frame that runs past the end of the file is an incomplete
                # write (a garbled length that overruns reads the same way).
                self._set_aside_torn(data, offset, "a frame past the end of the file")
                return
            if length == 0 or length > _MAX_PAYLOAD:
                if _zeros_from(data, offset):
                    self._set_aside_torn(data, offset, "a zero-filled tail")
                    return
                self._corrupt = f"a bad record length at byte {offset}"
                return
            payload = data[offset + _HEADER.size: offset + _HEADER.size + length]
            digest = data[end - _DIGEST_LEN: end]
            if hashlib.sha256(payload).digest() != digest:
                if end == size or _zeros_from(data, end):
                    self._set_aside_torn(data, offset, "a bad checksum on the last record")
                    return
                self._corrupt = f"a bad checksum at byte {offset}"
                return
            try:
                record = SubmitIntentRecord.from_payload(payload)
            except (ValueError, KeyError, TypeError) as exc:
                self._corrupt = f"an unreadable record at byte {offset} ({type(exc).__name__})"
                return
            self._index_locked(record)
            offset = end
            self._good_size = offset

    def _set_aside_torn(self, data: bytes, offset: int, why: str) -> None:
        """Copy the torn tail aside, then cut the journal back to the last
        valid frame so later appends keep it readable."""
        tail = data[offset:]
        n = 1
        while True:
            aside = self._path.with_name(f"{self._path.name}.torn-{n}")
            if not aside.exists():
                break
            n += 1
        try:
            aside.write_bytes(tail)
            with open(self._path, "r+b") as fh:
                fh.truncate(offset)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            self._unusable = (f"a torn last record could not be set aside "
                              f"({type(exc).__name__})")
            return
        self._good_size = offset
        self._torn_note = f"{why}; its bytes were kept in {aside.name}"
        logger.warning("submit journal: a torn last record was set aside (%s)", why)

    def _index_locked(self, record: SubmitIntentRecord) -> None:
        self._seq = max(self._seq, record.seq)
        view = self._attempts.get(record.attempt_id)
        if view is None:
            view = AttemptView(record.attempt_id, record.job_key, record.legacy_url,
                               record.state, record.outcome, record.seq)
            self._attempts[record.attempt_id] = view
            if record.job_key:
                self._by_key.setdefault(record.job_key, set()).add(record.attempt_id)
            if record.legacy_url:
                self._by_url.setdefault(record.legacy_url, set()).add(record.attempt_id)
        else:
            view.state = record.state
            if record.outcome:
                view.outcome = record.outcome

    # ------------------------------------------------------------------ write
    def _append_locked(self, record: SubmitIntentRecord, *, read_back: bool) -> None:
        if self._unusable:
            raise IntentJournalError(self._unusable)
        frame = _frame(record.to_payload())
        created = not self._path.exists()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "ab") as fh:
                start = fh.tell()
                if start != self._good_size:
                    # Something other than this object wrote the file: refuse.
                    raise IntentJournalError("the journal changed under AA")
                fh.write(frame)
                fh.flush()
                os.fsync(fh.fileno())
        except (OSError, IntentJournalError) as exc:
            self._cut_back_locked()
            raise IntentJournalError(f"append failed ({type(exc).__name__})") from exc
        if created:
            self._fsync_dir()
        if read_back:
            try:
                with open(self._path, "rb") as fh:
                    fh.seek(self._good_size)
                    got = fh.read(len(frame))
            except OSError as exc:
                self._cut_back_locked()
                raise IntentJournalError(f"read-back failed ({type(exc).__name__})") from exc
            if got != frame:
                self._cut_back_locked()
                raise IntentJournalError("read-back did not match the record")
        self._good_size += len(frame)
        self._index_locked(record)

    def _cut_back_locked(self) -> None:
        """Undo a partial append so the journal ends on a valid frame."""
        try:
            with open(self._path, "r+b") as fh:
                fh.truncate(self._good_size)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            self._unusable = f"a failed write could not be undone ({type(exc).__name__})"

    def _fsync_dir(self) -> None:
        """Make the new file's directory entry durable (POSIX). Windows cannot
        open a directory for flushing; there the entry's durability rests on
        the file system (NTFS journals metadata; FAT does not — a stick that
        loses it is the F1 case of AA_ENGINE_MATH.md §2)."""
        if not hasattr(os, "O_DIRECTORY"):
            return
        try:
            fd = os.open(str(self._path.parent), os.O_RDONLY | os.O_DIRECTORY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    def _record(self, attempt_id: str, job_key: str, legacy_url: str,
                state: AttemptState, outcome: str = "") -> SubmitIntentRecord:
        self._seq += 1
        return SubmitIntentRecord(
            v=RECORD_VERSION, seq=self._seq, ts=self._clock(), profile=self._profile,
            attempt_id=attempt_id, job_key=job_key, legacy_url=legacy_url,
            state=state, outcome=outcome,
        )

    # ------------------------------------------------------------------ API
    def arm(self, job_key: str, legacy_url: str) -> str:
        """Record a new attempt; returns its id only after the ARMED frame is
        durable and read back. Raises :class:`ArmRefused` otherwise."""
        self._ensure_loaded()
        if self._corrupt:
            raise ArmRefused(JOURNAL_CORRUPT, self._corrupt)
        if self._unusable:
            raise ArmRefused(JOURNAL_UNAVAILABLE, self._unusable)
        if self._synced_root:
            raise ArmRefused(SYNCED_FOLDER, self._synced_root)
        if not self._lock.acquire():
            raise ArmRefused(PROFILE_LOCKED, str(self._lock.path))
        with self._mutex:
            if self._blocks_locked(job_key, legacy_url):
                raise ArmRefused(UNRESOLVED_ATTEMPT)
            attempt_id = uuid.uuid4().hex
            record = self._record(attempt_id, job_key, legacy_url, AttemptState.ARMED)
            try:
                self._append_locked(record, read_back=True)
            except IntentJournalError as exc:
                self._seq -= 1
                raise ArmRefused(WRITE_FAILED, str(exc)) from exc
            return attempt_id

    def mark(self, attempt_id: str, state: AttemptState, outcome: str = "") -> None:
        """Append a later record for an armed attempt (raises on failure)."""
        if state is AttemptState.ARMED:
            raise ValueError("an attempt is armed only once, by arm()")
        with self._mutex:
            view = self._attempts.get(attempt_id)
            if view is None:
                raise IntentJournalError("no such attempt")
            record = self._record(attempt_id, view.job_key, view.legacy_url, state, outcome)
            try:
                self._append_locked(record, read_back=False)
            except IntentJournalError:
                self._seq -= 1
                raise

    def reconcile(self, write_outcome: OutcomeWriter) -> list[AttemptView]:
        """Make every unresolved attempt's blocking state durable in the
        database, then resolve it (spec R1–R3). Returns the attempts it
        settled. Requires the profile lock; raises ArmRefused when another
        process holds it, IntentJournalError when the journal is unusable."""
        self._ensure_loaded()
        if self._corrupt:
            raise IntentJournalError(f"the journal is damaged: {self._corrupt}")
        if self._unusable:
            raise IntentJournalError(self._unusable)
        if not self._lock.acquire():
            raise ArmRefused(PROFILE_LOCKED, str(self._lock.path))
        settled: list[AttemptView] = []
        for view in self.unresolved():
            if view.state is AttemptState.ACKED and view.outcome in BLOCKING_OUTCOMES:
                outcome = view.outcome
            else:
                # ARMED/DISPATCHING (dispatch may have happened), UNKNOWN, or
                # an ACKED record whose outcome is not a recognised blocking
                # one: all settle as UNKNOWN — the safe direction.
                if view.state in (AttemptState.ARMED, AttemptState.DISPATCHING):
                    self.mark(view.attempt_id, AttemptState.UNKNOWN, "UNKNOWN")
                outcome = "UNKNOWN"
            write_outcome(view.legacy_url, view.job_key, outcome, view.attempt_id)
            self.mark(view.attempt_id, AttemptState.DONE, outcome)
            settled.append(view)
        return settled

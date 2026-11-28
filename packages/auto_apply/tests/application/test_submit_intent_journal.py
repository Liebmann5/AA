"""The submission journal (Phase 0, P0-3; AA_ENGINE_MATH.md §2).

TEETH: every pin here fails without the journal — the module did not exist —
and each names the behaviour that, reverted, makes it fail.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from auto_apply.application.services.data_processing import submit_intent_journal as sij
from auto_apply.application.services.data_processing.submit_intent_journal import (
    JOURNAL_CORRUPT,
    PROFILE_LOCKED,
    SYNCED_FOLDER,
    UNRESOLVED_ATTEMPT,
    WRITE_FAILED,
    ArmRefused,
    SubmitIntentJournal,
)
from auto_apply.application.services.profile_lock import ProfileLock
from auto_apply.domain.models.submission_attempt import AttemptState

KEY = "boards.example.io|/jobs/1"
URL = "https://boards.example.io/jobs/1"


def _journal(tmp_path: Path, name: str = "p", *, lock: ProfileLock | None = None,
             synced: str | None = None) -> SubmitIntentJournal:
    return SubmitIntentJournal(tmp_path / f"{name}.journal", name,
                               lock or ProfileLock(tmp_path / f"{name}.lock"),
                               synced_root=synced)


class _Writer:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        self.fail = fail

    def __call__(self, url: str, key: str, outcome: str, attempt_id: str) -> None:
        if self.fail:
            raise RuntimeError("database unavailable")
        self.calls.append((url, key, outcome, attempt_id))


# ── arming ──────────────────────────────────────────────────────────────────


def test_arm_writes_a_verified_armed_record_and_blocks_the_job(tmp_path: Path) -> None:
    j = _journal(tmp_path)
    attempt = j.arm(KEY, URL)
    assert attempt
    fresh = _journal(tmp_path, lock=ProfileLock(tmp_path / "other.lock"))
    assert fresh.blocks(KEY, "") and fresh.blocks("", URL), "durable, and read back from disk"
    assert [a.state for a in fresh.unresolved()] == [AttemptState.ARMED]


def test_a_second_attempt_in_the_same_session_is_refused(tmp_path: Path) -> None:
    """Spec R4 within a session: the database write failed after a dispatch
    (so D has no row) — the journal alone blocks the job."""
    j = _journal(tmp_path)
    attempt = j.arm(KEY, URL)
    j.mark(attempt, AttemptState.UNKNOWN, "UNKNOWN")  # no DONE: D never got its row
    with pytest.raises(ArmRefused) as refused:
        j.arm(KEY, "https://other.example/redirect?to=1")
    assert refused.value.reason == UNRESOLVED_ATTEMPT


def test_a_done_blocking_outcome_still_blocks_on_any_surviving_record(tmp_path: Path) -> None:
    """A3'(b): the D row can be lost on a stick that drops writes; the
    journal's DONE(UNKNOWN) record alone keeps the job blocked."""
    j = _journal(tmp_path)
    attempt = j.arm(KEY, URL)
    j.mark(attempt, AttemptState.UNKNOWN, "UNKNOWN")
    j.mark(attempt, AttemptState.DONE, "UNKNOWN")
    assert j.blocks(KEY, URL)


def test_not_sent_resolves_the_attempt_and_the_job_stays_retriable(tmp_path: Path) -> None:
    j = _journal(tmp_path)
    attempt = j.arm(KEY, URL)
    j.mark(attempt, AttemptState.NOT_SENT, "ERROR")
    assert not j.blocks(KEY, URL)
    assert j.arm(KEY, URL), "nothing reached the site: a later attempt is legitimate"


def test_a_write_failure_refuses_to_arm_and_leaves_the_journal_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j = _journal(tmp_path)
    first = j.arm(KEY, URL)
    j.mark(first, AttemptState.NOT_SENT, "ERROR")
    monkeypatch.setattr(sij.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("eio")))
    with pytest.raises(ArmRefused) as refused:
        j.arm(KEY, URL)
    assert refused.value.reason == WRITE_FAILED
    monkeypatch.undo()
    reread = _journal(tmp_path, lock=ProfileLock(tmp_path / "x.lock"))
    assert reread.corrupt is None and not reread.blocks(KEY, URL)


# ── torn and corrupt records ────────────────────────────────────────────────


def test_a_torn_last_record_is_set_aside_and_later_appends_stay_readable(tmp_path: Path) -> None:
    """TEETH: without the cut-back, the next ARMED record lands after the
    torn bytes and every later read reports corruption — automation would
    stop for good after an ordinary power cut."""
    j = _journal(tmp_path)
    done = j.arm(KEY, URL)
    j.mark(done, AttemptState.NOT_SENT, "ERROR")
    path = tmp_path / "p.journal"
    with open(path, "ab") as fh:
        fh.write(struct.pack(">I", 500) + b'{"half":')   # a write cut off mid-frame
    j2 = _journal(tmp_path, lock=ProfileLock(tmp_path / "p2.lock"))
    assert j2.torn_note and j2.corrupt is None
    second = j2.arm("other|/2", "https://other/2")
    j3 = _journal(tmp_path, lock=ProfileLock(tmp_path / "p3.lock"))
    assert j3.corrupt is None and j3.torn_note is None
    assert [a.attempt_id for a in j3.unresolved()] == [second]
    assert list(tmp_path.glob("p.journal.torn-*")), "the torn bytes are kept, not deleted"


def test_a_zero_filled_tail_is_torn_not_corrupt(tmp_path: Path) -> None:
    """TEETH: without the zero check, a length of zero reads as corruption and
    the profile can never submit again. FAT32/exFAT record a file's new size
    before its data, so a pulled stick leaves exactly this tail."""
    j = _journal(tmp_path)
    done = j.arm(KEY, URL)
    j.mark(done, AttemptState.NOT_SENT, "ERROR")
    path = tmp_path / "p.journal"
    with open(path, "ab") as fh:
        fh.write(b"\x00" * 4096)
    j2 = _journal(tmp_path, lock=ProfileLock(tmp_path / "p2.lock"))
    assert j2.corrupt is None and j2.torn_note and "zero" in j2.torn_note
    j2.arm("other|/2", "https://other/2")
    j3 = _journal(tmp_path, lock=ProfileLock(tmp_path / "p3.lock"))
    assert j3.corrupt is None and j3.torn_note is None


def test_a_last_record_zeroed_part_way_is_torn_not_corrupt(tmp_path: Path) -> None:
    """TEETH: without the zero check after a bad checksum, a last frame whose
    data stopped half-way (the rest zeros, past the frame's end too) reads as
    corruption."""
    j = _journal(tmp_path)
    first = j.arm(KEY, URL)
    path = tmp_path / "p.journal"
    frame = path.read_bytes()                        # exactly one frame
    j.mark(first, AttemptState.NOT_SENT, "ERROR")
    half = len(frame) // 2
    with open(path, "ab") as fh:
        fh.write(frame[:half] + b"\x00" * (len(frame) - half) + b"\x00" * 512)
    j2 = _journal(tmp_path, lock=ProfileLock(tmp_path / "p2.lock"))
    assert j2.corrupt is None and j2.torn_note
    assert j2.unresolved() == []                     # the two real records survived


def test_zeros_followed_by_a_record_are_still_corruption(tmp_path: Path) -> None:
    """The zero rule covers only a tail: valid data after the zeros means the
    medium lost bytes in the middle, which stays a refusal."""
    j = _journal(tmp_path)
    a = j.arm(KEY, URL)
    j.mark(a, AttemptState.NOT_SENT, "ERROR")
    path = tmp_path / "p.journal"
    data = path.read_bytes()
    path.write_bytes(b"\x00" * 64 + data)
    j2 = _journal(tmp_path, lock=ProfileLock(tmp_path / "p2.lock"))
    assert j2.corrupt
    with pytest.raises(ArmRefused) as refused:
        j2.arm("other|/2", "https://other/2")
    assert refused.value.reason == JOURNAL_CORRUPT


def test_a_bad_record_before_the_last_stops_submitting(tmp_path: Path) -> None:
    j = _journal(tmp_path)
    a = j.arm(KEY, URL)
    j.mark(a, AttemptState.NOT_SENT, "ERROR")
    path = tmp_path / "p.journal"
    data = bytearray(path.read_bytes())
    data[10] ^= 0xFF                                     # inside the FIRST frame's payload
    path.write_bytes(bytes(data))
    j2 = _journal(tmp_path, lock=ProfileLock(tmp_path / "p2.lock"))
    assert j2.corrupt
    with pytest.raises(ArmRefused) as refused:
        j2.arm("other|/2", "https://other/2")
    assert refused.value.reason == JOURNAL_CORRUPT


# ── recovery (R1–R3) ────────────────────────────────────────────────────────


def test_recovery_settles_an_armed_attempt_as_unknown_before_resolving_it(
    tmp_path: Path,
) -> None:
    j = _journal(tmp_path)
    attempt = j.arm(KEY, URL)                            # then the power went
    restarted = _journal(tmp_path, lock=ProfileLock(tmp_path / "r.lock"))
    writer = _Writer()
    settled = restarted.reconcile(writer)
    assert [s.attempt_id for s in settled] == [attempt]
    assert writer.calls == [(URL, KEY, "UNKNOWN", attempt)]
    assert restarted.unresolved() == []
    assert restarted.blocks(KEY, URL), "UNKNOWN blocks re-application"


def test_recovery_keeps_an_acked_outcome(tmp_path: Path) -> None:
    j = _journal(tmp_path)
    attempt = j.arm(KEY, URL)
    j.mark(attempt, AttemptState.ACKED, "SUBMITTED")     # crash before the D write
    writer = _Writer()
    _journal(tmp_path, lock=ProfileLock(tmp_path / "r.lock")).reconcile(writer)
    assert writer.calls == [(URL, KEY, "SUBMITTED", attempt)]


def test_recovery_is_idempotent(tmp_path: Path) -> None:
    j = _journal(tmp_path)
    j.arm(KEY, URL)
    writer = _Writer()
    _journal(tmp_path, lock=ProfileLock(tmp_path / "r1.lock")).reconcile(writer)
    _journal(tmp_path, lock=ProfileLock(tmp_path / "r2.lock")).reconcile(writer)
    assert len(writer.calls) == 1, "a second run finds nothing left to settle"


def test_recovery_leaves_the_attempt_blocking_when_the_database_write_fails(
    tmp_path: Path,
) -> None:
    j = _journal(tmp_path)
    j.arm(KEY, URL)
    restarted = _journal(tmp_path, lock=ProfileLock(tmp_path / "r.lock"))
    with pytest.raises(RuntimeError):
        restarted.reconcile(_Writer(fail=True))
    assert restarted.blocks(KEY, URL), "never resolved until the blocking row is durable"
    assert [a.state for a in restarted.unresolved()] == [AttemptState.UNKNOWN]


def test_recovery_into_the_real_database_blocks_the_job(tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    import auto_apply.adapters.secondary.persistence.database as db_module

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "aa.db")
    db_module.DatabaseManager._instance = None
    try:
        db = db_module.DatabaseManager()
        j = _journal(tmp_path)
        j.arm(KEY, URL)
        _journal(tmp_path, lock=ProfileLock(tmp_path / "r.lock")).reconcile(
            db.record_attempt_outcome)
        assert db.has_applied_previously(URL) is True
        assert db.has_applied_previously("https://elsewhere/x", job_key=KEY) is True
    finally:
        db_module.DatabaseManager._instance = None


# ── the lock and the synced folder ──────────────────────────────────────────


def test_two_holders_of_one_profile_never_both_arm(tmp_path: Path) -> None:
    """Two independent acquisitions of the same lock file — the second is
    refused (flock per open file description; msvcrt.locking per handle)."""
    a = _journal(tmp_path, "shared", lock=ProfileLock(tmp_path / "shared.lock"))
    b = _journal(tmp_path, "shared", lock=ProfileLock(tmp_path / "shared.lock"))
    a.arm(KEY, URL)
    with pytest.raises(ArmRefused) as refused:
        b.arm("other|/2", "https://other/2")
    assert refused.value.reason == PROFILE_LOCKED


def test_the_lock_dies_with_its_holder(tmp_path: Path) -> None:
    first = ProfileLock(tmp_path / "x.lock")
    assert first.acquire()
    first.release()   # what the OS does when the process ends
    assert ProfileLock(tmp_path / "x.lock").acquire()


def test_a_synced_folder_refuses_to_arm(tmp_path: Path) -> None:
    j = _journal(tmp_path, synced="OneDrive: C:\\Users\\x\\OneDrive")
    with pytest.raises(ArmRefused) as refused:
        j.arm(KEY, URL)
    assert refused.value.reason == SYNCED_FOLDER


def test_nothing_in_the_journal_is_a_value(tmp_path: Path) -> None:
    j = _journal(tmp_path)
    a = j.arm(KEY, URL)
    j.mark(a, AttemptState.ACKED, "SUBMITTED")
    raw = (tmp_path / "p.journal").read_bytes()
    for field in (b"attempt_id", b"job_key", b"legacy_url", b"state", b"outcome"):
        assert field in raw
    assert os.path.getsize(tmp_path / "p.journal") < 2000

"""The submission attempt: its states and its journal record (Phase 0, P0-3).

AA_ENGINE_MATH.md §2 is the specification. Each application run that reaches
a control which may send the application is ONE attempt. Its states, in the
order the journal records them:

* ``ARMED`` — recorded, flushed and read back before any dispatch.
* ``DISPATCHING`` — diagnostic only; never read by safety logic.
* ``ACKED`` — positive page evidence that the site took it.
* ``UNKNOWN`` — AA cannot tell whether the site received it.
* ``NOT_SENT`` — every click of the attempt was refused before anything could
  dispatch; nothing reached the site. Resolves the attempt as non-blocking.
* ``DONE`` — the outcome is durable in the database.

Resolution: an attempt is *resolved* once its last record is ``NOT_SENT`` or
``DONE``. Until then it blocks a new attempt for the same job key or URL
(spec R4: "J holds an unresolved attempt for k").

Pure: no I/O, no clock, no registry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

__all__ = [
    "RECORD_VERSION",
    "AttemptState",
    "SubmitIntentRecord",
]

#: Journal record format version. Readers accept this version only.
RECORD_VERSION = 2


class AttemptState(str, Enum):
    """The durable states of one submission attempt."""

    ARMED = "ARMED"
    DISPATCHING = "DISPATCHING"
    ACKED = "ACKED"
    UNKNOWN = "UNKNOWN"
    NOT_SENT = "NOT_SENT"
    DONE = "DONE"


@dataclass(frozen=True)
class SubmitIntentRecord:
    """One journal record. Carries keys, a URL and an outcome name only —
    never an answer value, never page text."""

    v: int
    seq: int
    ts: str
    profile: str
    attempt_id: str
    job_key: str
    legacy_url: str
    state: AttemptState
    #: The evidence outcome this record settles on (ACKED/UNKNOWN/NOT_SENT/DONE),
    #: empty for ARMED/DISPATCHING. A name from the outcome vocabulary only.
    outcome: str = ""

    def to_payload(self) -> bytes:
        """Compact UTF-8 JSON, keys sorted: the bytes the frame checksums."""
        data: dict[str, Any] = {
            "v": self.v,
            "seq": self.seq,
            "ts": self.ts,
            "profile": self.profile,
            "attempt_id": self.attempt_id,
            "job_key": self.job_key,
            "legacy_url": self.legacy_url,
            "state": self.state.value,
            "outcome": self.outcome,
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8")

    @classmethod
    def from_payload(cls, payload: bytes) -> SubmitIntentRecord:
        """Parse a payload; raises ValueError on anything malformed."""
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("record is not an object")
        if data.get("v") != RECORD_VERSION:
            raise ValueError(f"unsupported record version {data.get('v')!r}")
        return cls(
            v=int(data["v"]),
            seq=int(data["seq"]),
            ts=str(data["ts"]),
            profile=str(data["profile"]),
            attempt_id=str(data["attempt_id"]),
            job_key=str(data["job_key"]),
            legacy_url=str(data["legacy_url"]),
            state=AttemptState(str(data["state"])),
            outcome=str(data.get("outcome", "")),
        )

    @property
    def resolves(self) -> bool:
        """Does this record resolve its attempt?"""
        return self.state in (AttemptState.NOT_SENT, AttemptState.DONE)

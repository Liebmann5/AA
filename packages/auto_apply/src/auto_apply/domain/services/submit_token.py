"""The one-use submit token (Phase 0, P0-4).

AA_ENGINE_MATH.md §3 and §3a. A token is minted only after a click that may
send the application has been authorised — by the person at the gate, or by
their autonomous-submission setting — and only for an attempt the journal has
armed. It binds:

* the **values** the person approved: the §3 digest (``digest_canonical``)
  of every answer the run wrote, plus what the final step's controls hold at
  the moment of approval;
* the **target**: the control's identity (tag, type, name, id, value) and the
  form it would submit (``formaction``/``formmethod``/``formtarget``, the
  form's action and method), checked again by the click ladder immediately
  after it resolves the element and before any rung can fire (§3a, decision
  7: trusted clicks, re-verified inside the ladder);
* the step fingerprint and the **authorisation source** (``person`` or
  ``policy``).

It is consumed exactly once, before dispatch: a second consume raises.

Pure: no I/O, no clock, no registry. Values are never logged; the digest is
the only thing derived from them.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from typing import Any

from auto_apply.domain.services.comparators import canonical_value, digest_canonical

__all__ = [
    "AUTH_PERSON",
    "AUTH_POLICY",
    "ControlIdentity",
    "SubmitAuthorization",
    "TokenAlreadyUsed",
    "TokenBook",
    "values_changed",
]

AUTH_PERSON = "person"
AUTH_POLICY = "policy"


class TokenAlreadyUsed(Exception):
    """A token was presented a second time."""


@dataclass(frozen=True)
class ControlIdentity:
    """What a submit control is, read from the page. Compared field by field
    by the click ladder; the box and visibility are the probe's job."""

    tag: str = ""
    type: str = ""
    name: str = ""
    id: str = ""
    value: str = ""
    formaction: str = ""
    formmethod: str = ""
    formtarget: str = ""
    form_action: str = ""
    form_method: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> ControlIdentity:
        """From the ``identity`` member of the probe's result (missing → empty)."""
        src = data if isinstance(data, Mapping) else {}
        return cls(**{f.name: str(src.get(f.name) or "")[:300] for f in fields(cls)})

    def mismatch(self, other: ControlIdentity) -> str:
        """The first field that differs, or "" when the two are the same control."""
        for f in fields(self):
            if getattr(self, f.name) != getattr(other, f.name):
                return f.name
        return ""

    @property
    def readable(self) -> bool:
        """Was anything read at all? An empty identity binds nothing."""
        return bool(self.tag)


@dataclass(frozen=True)
class SubmitAuthorization:
    """One authorised dispatch of one attempt."""

    nonce: str
    attempt_id: str
    values_digest: str
    control: ControlIdentity
    step_fingerprint: str
    auth_source: str


def values_changed(
    approved: Iterable[tuple[str, str, Any]], now: Iterable[tuple[str, str, Any]]
) -> tuple[str, ...]:
    """Keys whose value differs between approval and now (§3 equivalence:
    canonical forms when both have one, else the raw text). A key present at
    approval and absent now counts as changed."""
    later: dict[str, tuple[str, Any]] = {k: (kind, v) for k, kind, v in now}
    changed: list[str] = []
    for key, kind, value in approved:
        if key not in later:
            changed.append(key)
            continue
        kind_now, value_now = later[key]
        a = canonical_value(kind, value)
        b = canonical_value(kind_now, value_now)
        if a is not None and b is not None:
            if a != b or kind != kind_now:
                changed.append(key)
        elif str(value or "") != str(value_now or ""):
            changed.append(key)
    return tuple(changed)


class TokenBook:
    """Mints tokens and enforces one use each (one book per workflow)."""

    def __init__(self) -> None:
        self._used: set[str] = set()

    @staticmethod
    def mint(
        *,
        attempt_id: str,
        values: Iterable[tuple[str, str, Any]],
        control: ControlIdentity,
        step_fingerprint: str,
        auth_source: str,
    ) -> SubmitAuthorization:
        """Raises ValueError on malformed values (a duplicate key, an unknown
        kind): a token that cannot bind its values is never minted."""
        if not attempt_id:
            raise ValueError("a token needs an armed attempt")
        if auth_source not in (AUTH_PERSON, AUTH_POLICY):
            raise ValueError("unknown authorisation source")
        return SubmitAuthorization(
            nonce=uuid.uuid4().hex,
            attempt_id=attempt_id,
            values_digest=digest_canonical(values),
            control=control,
            step_fingerprint=str(step_fingerprint or ""),
            auth_source=auth_source,
        )

    def consume(self, token: SubmitAuthorization) -> SubmitAuthorization:
        """Use the token once; a second use raises :class:`TokenAlreadyUsed`."""
        if token.nonce in self._used:
            raise TokenAlreadyUsed(token.nonce)
        self._used.add(token.nonce)
        return token

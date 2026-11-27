"""Result values every tool returns (05 section 2, CT-DS-005).

A tool never raises on malformed input. It returns one of:

* ``Ok(value, confidence, evidence, margin)``: it found something;
* ``Abstain(reason, evidence, candidates)``: it cannot decide, and says why;
* ``Timeout(partial, units_used, reason)``: it ran out of work units.

``Stale`` is not a tool result. The analyzer hands it to a consumer that asks
about a finding taken at an older epoch than the page it now acts on
(CT-INV-003).

All values are frozen and hold only tuples, frozensets, strings and numbers,
so equal inputs give equal, hashable, fingerprintable outputs (CT-NFR-003).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Any, Generic, TypeVar, Union

T = TypeVar("T")


@dataclass(frozen=True)
class Evidence:
    """One reason behind a finding.

    ``signal`` is a short enumerated name (``"label-for"``, ``"asterisk"``),
    ``detail`` a human-readable line that never carries page text by default,
    ``weight`` the contribution to a score when the tool scores, and
    ``nodes`` the node indexes in the ``Doc`` the evidence points at.
    """

    signal: str
    detail: str = ""
    weight: float | None = None
    nodes: tuple[int, ...] = ()


@dataclass(frozen=True)
class Ok(Generic[T]):
    value: T
    confidence: float = 1.0
    evidence: tuple[Evidence, ...] = ()
    margin: float | None = None

    @property
    def ok(self) -> bool:
        return True


@dataclass(frozen=True)
class Abstain:
    reason: str
    evidence: tuple[Evidence, ...] = ()
    candidates: tuple[Any, ...] = ()

    @property
    def ok(self) -> bool:
        return False


@dataclass(frozen=True)
class Timeout(Generic[T]):
    partial: T | None
    units_used: int
    reason: str = "work-unit budget exhausted"

    @property
    def ok(self) -> bool:
        return False


@dataclass(frozen=True)
class Stale:
    """A finding from an older page state (CT-INV-003). Never act on it."""

    finding_epoch: int
    current_epoch: int

    @property
    def ok(self) -> bool:
        return False


Result = Union[Ok[Any], Abstain, Timeout[Any]]


def _canon(obj: Any) -> Any:
    """A JSON-ready canonical form: sets sorted, dataclasses by field order."""
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        # repr is shortest round-trip, platform-independent since Python 3.1.
        return {"f": repr(obj)}
    if isinstance(obj, Enum):
        return {"e": f"{type(obj).__name__}.{obj.name}"}
    if is_dataclass(obj) and not isinstance(obj, type):
        return {
            "d": type(obj).__name__,
            "v": [[f.name, _canon(getattr(obj, f.name))] for f in fields(obj)],
        }
    if isinstance(obj, (list, tuple)):
        return [_canon(x) for x in obj]
    if isinstance(obj, (set, frozenset)):
        items = [_canon(x) for x in obj]
        return {"s": sorted(items, key=lambda x: json.dumps(x, sort_keys=True))}
    if isinstance(obj, dict):
        return {"m": sorted(([_canon(k), _canon(v)] for k, v in obj.items()),
                            key=lambda kv: json.dumps(kv[0], sort_keys=True))}
    # Unknown objects are fingerprinted by type only: they must not leak
    # memory addresses (repr) into a determinism hash.
    return {"o": type(obj).__name__}


def fingerprint(obj: Any) -> str:
    """Stable SHA-256 hex digest of a result or value (trace output hash)."""
    data = json.dumps(_canon(obj), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()

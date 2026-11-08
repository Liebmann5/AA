"""Versioned, hashed tool parameters (CT-DS-007, CT-NFR-019).

Every number a tool decides with lives here, declared by the tool as a
``ParamSpec`` with bounds. A ``ParameterSet`` is immutable: a change makes a
new set with a new hash, so a trace always names the exact parameters a
result came from, and a rollback is "use the previous hash".

Safety parameters (the honeypot cost ratio, the "unknown counts as will
submit" rule) are marked ``safety=True`` and cannot be changed by tuning;
only an explicit owner override can change them, and the override is
recorded in the set's provenance.

Bible rule 2 (no default overriding ``runtime_defaults.yaml``): when AA
embeds this library it passes the YAML's values in through
``ParameterSet.from_mapping``; the defaults below are the library's own
documented values for standalone use and are reported as such.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParamSpec:
    name: str
    default: float | int | str | bool
    lo: float | None = None
    hi: float | None = None
    safety: bool = False
    doc: str = ""

    def check(self, value: Any) -> None:
        if isinstance(self.default, bool):
            if not isinstance(value, bool):
                raise ValueError(f"{self.name}: expected bool, got {value!r}")
            return
        if isinstance(self.default, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{self.name}: expected number, got {value!r}")
            if self.lo is not None and value < self.lo:
                raise ValueError(f"{self.name}={value} below {self.lo}")
            if self.hi is not None and value > self.hi:
                raise ValueError(f"{self.name}={value} above {self.hi}")
            return
        if not isinstance(value, str):
            raise ValueError(f"{self.name}: expected str, got {value!r}")


@dataclass(frozen=True)
class ParameterSet:
    """Parameters per tool id. ``values[tool][name] -> value``."""

    values: Mapping[str, Mapping[str, Any]]
    provenance: tuple[str, ...] = ("library defaults",)
    _hash: str = field(default="", compare=False, repr=False)

    def __post_init__(self) -> None:
        frozen = {t: dict(sorted(p.items())) for t, p in sorted(self.values.items())}
        object.__setattr__(self, "values", frozen)
        blob = json.dumps(frozen, sort_keys=True, separators=(",", ":"))
        object.__setattr__(self, "_hash", hashlib.sha256(blob.encode()).hexdigest()[:16])

    @property
    def hash(self) -> str:
        return self._hash

    def for_tool(self, tool_id: str) -> Mapping[str, Any]:
        return self.values.get(tool_id, {})

    def tool_hash(self, tool_ids: Iterable[str]) -> str:
        """Hash of the parameters of the given tools only (cache keys)."""
        part = {t: self.values.get(t, {}) for t in sorted(set(tool_ids))}
        blob = json.dumps(part, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    @classmethod
    def from_specs(cls, specs: Mapping[str, Iterable[ParamSpec]]) -> "ParameterSet":
        return cls({tool: {p.name: p.default for p in ps} for tool, ps in specs.items()})

    def with_overrides(
        self,
        specs: Mapping[str, Iterable[ParamSpec]],
        overrides: Mapping[str, Mapping[str, Any]],
        *,
        reason: str,
        owner_safety_override: bool = False,
    ) -> "ParameterSet":
        """A new set with ``overrides`` applied, bounds-checked and recorded."""
        new = {t: dict(p) for t, p in self.values.items()}
        for tool, changes in overrides.items():
            declared = {p.name: p for p in specs.get(tool, ())}
            for name, value in changes.items():
                spec = declared.get(name)
                if spec is None:
                    raise KeyError(f"{tool}.{name} is not a declared parameter")
                if spec.safety and not owner_safety_override:
                    raise PermissionError(
                        f"{tool}.{name} is a safety parameter; tuning may not change it"
                    )
                spec.check(value)
                new.setdefault(tool, {})[name] = value
        return ParameterSet(new, self.provenance + (reason,))

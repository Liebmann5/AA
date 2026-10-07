"""Data shapes for the uninstall engine — plain dataclasses, JSON-able."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

GROUP_AA = "aa"
GROUP_PREEXISTING = "preexisting"
GROUP_RESEARCH = "research"
GROUP_INSTALL = "install"

PROMISE_TEXT = (
    "AutoApply removed everything it created and left everything that was "
    "there before. It cannot remove copies made by backup tools (Time "
    "Machine, OneDrive, File History). It cannot remove OS-level records "
    "(shell history, search indexes, download quarantine records). It cannot "
    "guarantee forensic erasure on SSDs; encrypted data is protected by key "
    "destruction."
)


@dataclass(frozen=True)
class RetentionHold:
    """A research retention hold (45 CFR 46.115(b) protocols outlive the tool).

    hold_until: ISO date, or "until-released". An unparseable value reads as
    ACTIVE — a garbled hold must fail toward preservation, never toward
    destruction.
    """

    hold_until: str
    note: str = ""

    def active(self, today: str) -> bool:
        """today: ISO date string, injected for determinism."""
        if not self.hold_until:
            return False
        if self.hold_until == "until-released":
            return True
        return self.hold_until >= today


@dataclass
class PlanItem:
    """One thing the uninstaller found, classified."""

    path: Path
    group: str  # GROUP_AA | GROUP_PREEXISTING | GROUP_RESEARCH | GROUP_INSTALL
    size_bytes: int
    origin: str = "aa"
    note: str = ""


@dataclass
class UninstallPlan:
    """Everything execute() will act on, produced by build_plan()."""

    run_mode: str
    data_root: Path
    install_root: Path | None
    items: list[PlanItem]
    research_items: list[PlanItem]
    running_pids: list[int]
    hold: RetentionHold | None
    discovery_mode: bool
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResearchDecision:
    """What to do with research data. None = keep in place (never destroy,
    never guess a location)."""

    action: str | None = None  # None | "keep" | "export" | "delete" | "keep-in-place"
    dest: Path | None = None
    fmt: str = "csv"


@dataclass(frozen=True)
class UninstallDecision:
    confirm: bool
    research: ResearchDecision = ResearchDecision()


@dataclass
class Leftover:
    path: str
    reason: str


@dataclass
class UninstallReport:
    """The honest account: removed, kept (with why), failed, leftovers."""

    run_mode: str
    dry_run: bool
    removed: list[str] = field(default_factory=list)
    kept: list[Leftover] = field(default_factory=list)
    failed: list[Leftover] = field(default_factory=list)
    stopped_pids: list[int] = field(default_factory=list)
    scheduled_for_reboot: list[str] = field(default_factory=list)
    research_action: str = "none"
    research_detail: str = ""
    withdrawals_documented_at: str = ""
    leftovers: list[Leftover] = field(default_factory=list)
    promise: str = PROMISE_TEXT

    @property
    def clean(self) -> bool:
        """True when nothing failed and nothing unexpected remains."""
        return not self.failed and not self.leftovers

    def to_json_bytes(self) -> bytes:
        """The machine-readable report, UTF-8, trailing newline (byte discipline)."""

        def _default(obj: object) -> str:
            if isinstance(obj, Path):
                return str(obj)
            raise TypeError(type(obj).__name__)

        return (
            json.dumps(asdict(self), indent=2, sort_keys=True, default=_default) + "\n"
        ).encode("utf-8")

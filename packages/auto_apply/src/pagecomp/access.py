"""Access contracts (05 sections 4, 5 and 14; CT-T-001, CT-DS-010).

Pure: this module defines what an access adapter must deliver and the
pure steps every adapter shares (budget mapping, frame grafting, read
staleness). The browser is reached only by adapters outside the library
(AA's ``pagecomp_access``), which implement ``AccessPort``.

The contract of ``AccessPort.observe``:

* it returns an ``ObservationOutcome`` and never raises, whatever the page does;
* every loop, wait and recursion in the adapter is bounded by the
  ``ObservationRequest`` budgets; a budget that fires is a ``Truncation`` or
  a read flag on the observation, never silence;
* ``timed_out`` is the typed timeout result: the observation is whatever was
  read before the deadline (possibly an empty document), flagged ``partial``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pagecomp.doc import (
    FRAME_CAP,
    FRAME_CROSS_ORIGIN_UNREAD,
    FRAME_DETACHED,
    FRAME_NAVIGATED,
    FRAME_STATES,
    DocLimits,
)
from pagecomp.observation import (
    AX_TREE,
    CLOSED_SHADOW_UNSEEN,
    CROSS_ORIGIN_UNSEEN,
    FLAG_NAVIGATED,
    FLAG_SPA_NAVIGATED,
    FLAG_STALE,
    IFRAME_TRAVERSAL,
    SHADOW_PIERCING,
    SNAPSHOT_HTML,
    SNAPSHOT_LAYOUT,
    PageObservation,
)

# Capabilities of 05 section 5 not already named in ``observation``.
ISOLATED_WORLD = "ISOLATED_WORLD"
TRUSTED_INPUT = "TRUSTED_INPUT"
WINDOW_EVENTS = "WINDOW_EVENTS"
NETWORK_EVENTS = "NETWORK_EVENTS"
FILE_CHOOSER = "FILE_CHOOSER"
DOWNLOAD_EVENTS = "DOWNLOAD_EVENTS"
REGION_QUERY = "REGION_QUERY"
#: How the read was made (exactly one per observation).
VIA_CDP = "VIA_CDP"
VIA_SCRIPT_WALK = "VIA_SCRIPT_WALK"
VIA_REPLAY = "VIA_REPLAY"

KNOWN_CAPABILITIES = frozenset({
    SNAPSHOT_HTML, SNAPSHOT_LAYOUT, AX_TREE, SHADOW_PIERCING, IFRAME_TRAVERSAL,
    ISOLATED_WORLD, TRUSTED_INPUT, WINDOW_EVENTS, NETWORK_EVENTS, FILE_CHOOSER,
    DOWNLOAD_EVENTS, REGION_QUERY, VIA_CDP, VIA_SCRIPT_WALK, VIA_REPLAY,
})
KNOWN_GAPS = frozenset({CLOSED_SHADOW_UNSEEN, CROSS_ORIGIN_UNSEEN})


@dataclass(frozen=True)
class CapabilitySet:
    """CT-DS-010: what an adapter provided, and what it knows it missed.

    ``provided`` and ``gaps`` are disjoint. Unknown names are rejected so a
    typo cannot silently claim a capability.
    """

    provided: frozenset[str] = frozenset()
    gaps: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        unknown = (self.provided - KNOWN_CAPABILITIES) | (self.gaps - KNOWN_GAPS)
        if unknown:
            raise ValueError(f"unknown capability names: {sorted(unknown)}")
        if self.provided & self.gaps:
            raise ValueError("a capability cannot be both provided and a gap")

    def has(self, name: str) -> bool:
        return name in self.provided

    def with_gap(self, name: str) -> "CapabilitySet":
        return CapabilitySet(self.provided, self.gaps | {name})

    def names(self) -> frozenset[str]:
        """What goes on ``PageObservation.capabilities`` (gaps included)."""
        return self.provided | self.gaps


@dataclass(frozen=True)
class ObservationRequest:
    """One read. ``level`` is ``"html"`` (markup only), ``"dom"`` (pierced
    tree) or ``"layout"`` (tree plus boxes and computed style). Budgets are
    the 05 section 14 caps; the adapter enforces the time ones, the builder
    the structural ones."""

    level: str = "dom"
    region_root: str | None = None     # a CSS selector; None = the whole page
    max_nodes: int = 30_000
    max_bytes: int = 8_000_000
    max_depth: int = 256
    max_frame_depth: int = 3
    frame_cap: int = 16                # frames read per observation (cross-origin switches included)
    script_deadline_ms: int = 10_000   # per in-page script call
    wall_ms: int = 20_000              # the whole observation, all frames
    epoch: int = 0
    requested_url: str | None = None
    query: str | None = None

    LEVELS = ("html", "dom", "layout")

    def __post_init__(self) -> None:
        if self.level not in self.LEVELS:
            raise ValueError(f"level must be one of {self.LEVELS}")
        for name in ("max_nodes", "max_bytes", "max_depth", "max_frame_depth",
                     "script_deadline_ms", "wall_ms"):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be >= 1")
        if self.frame_cap < 0:
            raise ValueError("frame_cap must be >= 0")

    def limits(self) -> DocLimits:
        return DocLimits(max_nodes=self.max_nodes, max_depth=self.max_depth,
                         max_frame_depth=self.max_frame_depth, max_bytes=self.max_bytes)


@dataclass(frozen=True)
class ObservationOutcome:
    """What ``AccessPort.observe`` returns. ``observation`` is always present."""

    observation: PageObservation
    timed_out: bool = False
    notes: tuple[str, ...] = ()        # adapter-side events: rungs tried, fallbacks


@runtime_checkable
class AccessPort(Protocol):
    """The one call (05 section 5). Implementations live outside the library."""

    def capabilities(self) -> CapabilitySet: ...

    def observe(self, request: ObservationRequest) -> ObservationOutcome: ...


# ---------------------------------------------------------------------------
# Pure steps shared by adapters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadProbe:
    """Cheap page facts read just before and just after the main read.

    ``doc_id`` identifies the document instance (``performance.timeOrigin``
    or a CDP loader id); ``url`` is ``location.href``; ``mutations`` is a
    MutationObserver counter installed by the adapter (``-1`` when absent).
    """

    url: str
    doc_id: str
    mutations: int = -1


def read_flags(before: ReadProbe | None, after: ReadProbe | None) -> frozenset[str]:
    """CT-INV-003 at read time. A different document → navigated and stale;
    same document with a different URL → SPA navigation (``pushState``) and
    stale; changed mutation counter → stale. A missing probe means the read
    could not be bracketed, which counts as stale (fail closed)."""
    if before is None or after is None:
        return frozenset({FLAG_STALE})
    flags: set[str] = set()
    if before.doc_id != after.doc_id:
        flags |= {FLAG_NAVIGATED, FLAG_STALE}
    elif before.url != after.url:
        flags |= {FLAG_SPA_NAVIGATED, FLAG_STALE}
    if before.mutations >= 0 and after.mutations >= 0 and before.mutations != after.mutations:
        flags.add(FLAG_STALE)
    return frozenset(flags)


@dataclass(frozen=True)
class FrameRead:
    """A frame document read on its own (an out-of-process iframe's CDP
    session, or a WebDriver frame switch), keyed by the frame's id."""

    frame_id: str
    document: Mapping[str, Any] | None   # a DOM.getDocument-shaped node, or None
    state: str = "read"                   # FRAME_STATES


@dataclass
class GraftReport:
    grafted: int = 0
    unread: int = 0
    over_cap: int = 0
    states: dict[str, int] = field(default_factory=dict)


def iframe_nodes(root: Mapping[str, Any], max_visit: int = 2_000_000) -> list[dict[str, Any]]:
    """Every iframe/frame element node in a pierced tree, in document order.
    Iterative; stops after ``max_visit`` nodes."""
    out: list[dict[str, Any]] = []
    stack: list[Any] = [root.get("root", root) if isinstance(root, Mapping) else {}]
    seen = 0
    while stack and seen < max_visit:
        n = stack.pop()
        seen += 1
        if not isinstance(n, dict):
            continue
        if n.get("nodeType") == 1 and str(n.get("localName") or n.get("nodeName") or "").lower() \
                in ("iframe", "frame"):
            out.append(n)
        kids: list[Any] = []
        for key in ("shadowRoots", "children"):
            v = n.get(key)
            if isinstance(v, list):
                kids.extend(v)
        cd = n.get("contentDocument")
        if isinstance(cd, dict):
            kids.append(cd)
        stack.extend(reversed(kids))
    return out


def graft_frames(root: dict[str, Any], reads: Mapping[str, FrameRead], frame_cap: int,
                 unread_state: str = FRAME_CROSS_ORIGIN_UNREAD) -> GraftReport:
    """Graft separately read frame documents under their ``<iframe>`` by
    frame id (mutates ``root``: the adapter owns the payload).

    * An iframe with a ``contentDocument`` already present is left alone.
    * An iframe whose frame id has a read gets it as ``contentDocument``,
      or, when the read failed, ``frameState`` set to the read's state.
    * An iframe with no read is marked ``unread_state``.
    * At most ``frame_cap`` frames are grafted; the rest are ``frame-cap``.
    """
    rep = GraftReport()
    for node in iframe_nodes(root):
        if isinstance(node.get("contentDocument"), Mapping):
            continue
        fid = str(node.get("frameId") or "")
        r = reads.get(fid) if fid else None
        if r is not None and r.document is not None and r.state == "read":
            if rep.grafted >= frame_cap:
                node["frameState"] = FRAME_CAP
                rep.over_cap += 1
            else:
                node["contentDocument"] = dict(r.document)
                rep.grafted += 1
                continue
        elif r is not None:
            node["frameState"] = r.state if r.state in FRAME_STATES else FRAME_DETACHED
            rep.unread += 1
        elif node.get("frameState") not in FRAME_STATES:
            node["frameState"] = unread_state
            rep.unread += 1
        st = str(node.get("frameState"))
        rep.states[st] = rep.states.get(st, 0) + 1
    return rep


FRAME_PROBLEM_FLAGS = {FRAME_DETACHED: "frame-detached", FRAME_NAVIGATED: "frame-navigated"}


def flags_from_frames(obs: PageObservation) -> frozenset[str]:
    """Read flags implied by the frame states of an observation."""
    out = {FRAME_PROBLEM_FLAGS[f.state] for f in obs.frames if f.state in FRAME_PROBLEM_FLAGS}
    if out:
        out.add("partial")
    return frozenset(out)


__all__ = [
    "AccessPort", "CapabilitySet", "FrameRead", "GraftReport", "ObservationOutcome",
    "ObservationRequest", "ReadProbe", "flags_from_frames", "graft_frames", "iframe_nodes",
    "read_flags", "CLOSED_SHADOW_UNSEEN", "CROSS_ORIGIN_UNSEEN",
]

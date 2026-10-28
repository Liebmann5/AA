"""The query builder's request/result/offer vocabulary — frozen data, no I/O.

QueryRequest is the typed intermediate form every consumer shares: the
builder's surfaces produce one, the composer consumes one, and the second
chain's automated planner will manipulate the same shape. Nothing here holds
a live object (no profile, no driver, no store).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class QueryRequest(_Frozen):
    """What the user wants to search for, on one named surface."""

    surface: str
    phrases: tuple[str, ...] = ()
    any_of: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    in_title: tuple[str, ...] = ()
    site: str | None = None
    location: str = ""
    options: tuple[tuple[str, str], ...] = ()
    template: str | None = None


class QueryNote(_Frozen):
    """One plain-language sentence about what was dropped or refused, and why."""

    severity: Literal["info", "refused"]
    topic: str
    message: str


class QueryResult(_Frozen):
    """The bar text and/or URL, plus every note the user must see."""

    surface: str
    display_name: str
    bar_text: str | None
    url: str | None
    notes: tuple[QueryNote, ...] = ()


class OfferedChoice(_Frozen):
    """One labelled choice for an option (e.g. day -> "Past 24 hours")."""

    key: str
    label: str


class OfferedCapability(_Frozen):
    """One capability a surface offers, after the verification rule is applied."""

    key: str
    label: str
    explanation: str
    channel: str
    status: str
    choices: tuple[OfferedChoice, ...] = ()


class SurfaceOffer(_Frozen):
    """A search surface as the builder may offer it."""

    name: str
    display_name: str
    kind: str
    summary: str
    usage_note: str
    operators: tuple[OfferedCapability, ...] = ()
    options: tuple[OfferedCapability, ...] = ()
    templates: tuple[str, ...] = ()


class BuilderDefaults(_Frozen):
    """One-click starting points read from the user's profile. Read-only."""

    titles: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()
    workplace_types: tuple[str, ...] = ()

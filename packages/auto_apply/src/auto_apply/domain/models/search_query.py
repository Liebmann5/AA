"""The query builder's request/result/offer vocabulary — frozen data, no I/O.

QueryRequest is the typed intermediate form every consumer shares: the
builder's surfaces produce one, the composer consumes one, and a future
automated planner manipulates the same shape. Nothing here holds a live
object (no profile, no driver, no store).

The helpers below shape and render that vocabulary. They take strings and
frozen values, never live objects; the locale-dependent renderer takes an
injected translator, so every helper stays pure.
"""

from __future__ import annotations

from collections.abc import Callable
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


class PlatformOffer(_Frozen):
    """A hiring platform the builder can target, with its verification label.

    The label is computed once by the service, from the shared locale
    strings, so every surface renders the same words; a measured or
    vendor-verified platform carries an empty label (no badge).
    """

    name: str
    status: str
    label: str = ""


def _split_terms(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(",") if part.strip())


def build_request(
    *,
    surface: str,
    terms: str = "",
    any_of: str = "",
    exclude: str = "",
    in_title: str = "",
    location: str = "",
    site: str | None = None,
    options: tuple[tuple[str, str], ...] = (),
    template: str | None = None,
) -> QueryRequest:
    """Shape one QueryRequest from a surface's raw strings.

    Search words are exact phrases: the comma-separated terms — typed, or
    picked from the saved-titles one-clicks a surface shows — map to
    ``phrases``. ``required`` stays in the model; the surfaces never
    produce it.
    """
    return QueryRequest(
        surface=surface,
        phrases=_split_terms(terms),
        any_of=_split_terms(any_of),
        exclude=_split_terms(exclude),
        in_title=_split_terms(in_title),
        location=location.strip(),
        site=site,
        options=options,
        template=template,
    )


def describe_request(request: QueryRequest) -> str:
    """One line for the recent list: the surface, then what was asked for."""
    parts: list[str] = []
    parts.extend(request.phrases)
    if request.any_of:
        parts.append(" | ".join(request.any_of))
    parts.extend(f"-{term}" for term in request.exclude)
    parts.extend(f"intitle:{term}" for term in request.in_title)
    if request.site:
        parts.append(f"site:{request.site}")
    if request.location:
        parts.append(request.location)
    body = " ".join(parts) if parts else "(no terms)"
    if request.options:
        body += " [" + " ".join(f"{key}={value}" for key, value in request.options) + "]"
    return f"{request.surface}: {body}"


def platform_display_text(offer: PlatformOffer) -> str:
    """The one picker line for a platform: its name, plus its label if any."""
    if not offer.label:
        return offer.name
    return f"{offer.name} — {offer.label}"


def format_result_lines(
    result: QueryResult,
    translate: Callable[[str], str] = lambda key: key,
) -> list[str]:
    """The result as display lines.

    Notes render verbatim: they are the composer's plain-language sentences
    and carry their own wording. The two labels are locale-dependent, so the
    caller injects its translator; the default returns keys unchanged.
    """
    lines: list[str] = []
    if result.bar_text is not None:
        lines.append(f"{translate('builder.result.bar')}: {result.bar_text}")
    if result.url is not None:
        lines.append(f"{translate('builder.result.link')}: {result.url}")
    for note in result.notes:
        lines.append(f"  {note.message}")
    return lines


def resolved_remember_request(
    request: QueryRequest, restriction: str | None
) -> QueryRequest:
    """Fold a resolved site: restriction into the request being remembered.

    A remembered platform or company query is stored resolved, so it replays
    identically as an engine query.
    """
    if not restriction:
        return request
    return request.model_copy(update={"site": restriction})

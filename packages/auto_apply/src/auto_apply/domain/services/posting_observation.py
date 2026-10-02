"""Pure string derivations for job-posting research observations.

These three helpers were moved here verbatim from ``DiscoveryWorkflow``
(application/workflows/discovery_workflow.py), where they lived as
``@staticmethod`` members reachable only through a sibling workflow;
``ApplicationsWorkflow`` carried a second, body-identical copy of
``_infer_jurisdiction``. One definition of each now lives in the domain,
where every workflow can reach it without importing another workflow.

They are pure string→string mappings: no I/O, no state, no imports outside
the stdlib.

The two location matchers were moved here with two known substring-matching
warts ("Chicago, IL" -> CA; "Washington, DC" -> WA). Item 4 replaced them
with whole-token readers; the block comment above infer_jurisdiction says
how a location is read, and tests/workflows/test_posting_observation.py
measures both against a ground-truth table.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Location resolution (item 4).
#
# The matchers below replace two substring matchers that read "ca" inside
# "chicago", "co" inside "concord" and "la" inside "atlanta". Measured on
# 7101c42 over a 107-location ground-truth table: 33 jurisdictions wrong, 22
# of them a pay-transparency law assigned where none applies ("Canada" ->
# CA, "Memphis, TN" -> HI), and 25 metros wrong. A wrong jurisdiction makes
# ST-01 report a violation of a law that does not cover the posting.
#
# How they read a location now, with no site knowledge:
#   * the string is split into segments at commas, slashes, parentheses,
#     bullets and spaced dashes ("Hybrid - Chicago, IL" -> Hybrid | Chicago
#     | IL);
#   * a two-letter state code counts only as a WHOLE token — upper case
#     anywhere ("Remote (CA)"), or any case as the first word of a segment
#     after the first ("chicago, il"). So "in" and "or" in prose are words,
#     not Indiana and Oregon;
#   * a full state name counts as a whole phrase. "Washington" and "New
#     York" are also cities, so as STATE names they count only when they
#     are a later segment ("Spokane, Washington") or say "state";
#   * a city counts as a whole phrase, and only where the stated state
#     agrees with its metro: "Arlington, VA" is the DC metro, "Arlington,
#     TX" is Dallas, "Portland, ME" is neither. A city named with no state
#     resolves only if it is the metro's principal city and nothing marks
#     the location as outside the US ("Birmingham, UK" does not);
#   * when a location names several places, the first one that resolves
#     wins — every place a posting names is a place it covers.
#
# Deterministic, pure, standard library only.
# ---------------------------------------------------------------------------

#: USPS codes of the 50 states and DC.
US_STATE_CODES: frozenset[str] = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
})

#: Full state names (normalised) to USPS code.
US_STATE_NAMES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT",
    "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
    "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
    "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}

#: Codes that are also everyday words ("Remote IN Chicago", "NY OR NJ").
#: They count only as the first word of a later segment ("Honolulu, HI").
_WORD_LIKE_CODES: frozenset[str] = frozenset({"IN", "OR", "ME", "HI", "OK", "OH", "LA"})

#: State names that are also city names.
_AMBIGUOUS_STATE_NAMES: frozenset[str] = frozenset({"washington", "new york"})

#: Words that place a location outside the US. Only consulted for a city
#: named without a state, so the list need not be complete to be safe.
_NON_US_MARKERS: frozenset[str] = frozenset({
    "uk", "united kingdom", "england", "scotland", "wales", "ireland",
    "canada", "ontario", "quebec", "british columbia", "alberta",
    "on", "bc", "qc", "ab", "india", "germany", "france", "spain",
    "netherlands", "mexico", "brazil", "australia", "philippines",
    "poland", "singapore", "japan", "china", "israel",
})

#: The jurisdictions pay_transparency_laws.yaml defines. States map to
#: themselves; New York City is a city-level law (NYC) and New York State
#: outside the city has no entry in that file, so it resolves to None. A
#: pin (tests/workflows/test_posting_observation.py) holds this set equal
#: to the file's keys, so a law added there cannot go unreachable here.
LAW_JURISDICTIONS: frozenset[str] = frozenset({
    "CA", "CO", "DC", "HI", "IL", "MA", "MD", "MN", "NJ", "NYC", "RI", "WA",
})

#: Places inside New York City (normalised phrases).
_NYC_PLACES: tuple[str, ...] = (
    "new york city", "nyc", "manhattan", "brooklyn", "queens", "bronx",
    "staten island",
)


@dataclass(frozen=True)
class _Metro:
    """One col_index.yaml metro: its exact key, principal city names, and
    the other cities in it. States come from the key's suffix."""

    key: str
    principal: tuple[str, ...]
    satellite: tuple[str, ...] = ()
    #: The law jurisdiction of the principal city when it is not simply
    #: the first state of the key ("NYC" for New York).
    city_jurisdiction: str = ""

    @property
    def jurisdiction(self) -> str:
        return self.city_jurisdiction or self.states[0]

    @property
    def states(self) -> tuple[str, ...]:
        return tuple(self.key.rsplit(", ", 1)[-1].split("-"))


#: Every metro in col_index.yaml except "Remote" (a pin holds the two
#: equal). Principal names may resolve without a state; satellite names
#: (towns whose names recur across the country) need the metro's state.
METROS: tuple[_Metro, ...] = (
    _Metro("San Francisco-Oakland-Berkeley, CA",
           ("san francisco", "sf bay", "bay area"), ("oakland", "berkeley")),
    _Metro("San Jose-Sunnyvale-Santa Clara, CA",
           ("san jose", "silicon valley"), ("sunnyvale", "santa clara")),
    _Metro("New York-Newark-Jersey City, NY-NJ",
           ("new york", "new york city", "nyc", "manhattan", "brooklyn",
            "queens", "bronx", "staten island"), (), city_jurisdiction="NYC"),
    _Metro("Los Angeles-Long Beach-Anaheim, CA",
           ("los angeles",), ("long beach", "anaheim", "santa monica", "culver city")),
    _Metro("Seattle-Tacoma-Bellevue, WA", ("seattle",), ("tacoma", "bellevue")),
    _Metro("Boston-Cambridge-Newton, MA-NH",
           ("boston",), ("cambridge", "newton", "somerville")),
    _Metro("Washington-Arlington-Alexandria, DC-VA-MD-WV",
           ("washington",), ("arlington", "alexandria", "dc", "district of columbia")),
    _Metro("San Diego-Chula Vista-Carlsbad, CA",
           ("san diego",), ("chula vista", "carlsbad")),
    _Metro("Denver-Aurora-Lakewood, CO",
           ("denver",), ("aurora", "lakewood", "boulder")),
    _Metro("Austin-Round Rock-Georgetown, TX",
           ("austin",), ("round rock", "georgetown")),
    _Metro("Chicago-Naperville-Elgin, IL-IN-WI", ("chicago",), ("elgin",)),
    _Metro("Portland-Vancouver-Hillsboro, OR-WA",
           ("portland",), ("vancouver", "hillsboro")),
    _Metro("Miami-Fort Lauderdale-Pompano Beach, FL",
           ("miami",), ("fort lauderdale", "pompano beach")),
    _Metro("Atlanta-Sandy Springs-Alpharetta, GA",
           ("atlanta",), ("sandy springs", "alpharetta")),
    _Metro("Dallas-Fort Worth-Arlington, TX", ("dallas", "fort worth"), ("arlington",)),
    _Metro("Phoenix-Mesa-Chandler, AZ", ("phoenix",), ("mesa", "chandler")),
    _Metro("Minneapolis-St. Paul-Bloomington, MN-WI",
           ("minneapolis", "st paul", "saint paul"), ("bloomington",)),
    _Metro("Philadelphia-Camden-Wilmington, PA-NJ-DE-MD",
           ("philadelphia",), ("camden", "wilmington")),
    _Metro("Charlotte-Concord-Gastonia, NC-SC",
           ("charlotte",), ("concord", "gastonia")),
    _Metro("Raleigh-Cary, NC", ("raleigh",), ("cary",)),
    _Metro("Nashville-Davidson--Murfreesboro--Franklin, TN",
           ("nashville",), ("murfreesboro", "franklin")),
    _Metro("Columbus, OH", ("columbus",), ()),
    _Metro("Indianapolis-Carmel-Anderson, IN",
           ("indianapolis",), ("carmel", "anderson")),
    _Metro("Pittsburgh, PA", ("pittsburgh",), ()),
    _Metro("St. Louis, MO-IL", ("st louis", "saint louis"), ()),
    _Metro("Cincinnati, OH-KY-IN", ("cincinnati",), ()),
    _Metro("Cleveland-Elyria, OH", ("cleveland",), ("elyria",)),
    _Metro("Detroit-Warren-Dearborn, MI", ("detroit",), ("warren", "dearborn")),
    _Metro("Kansas City, MO-KS", ("kansas city",), ()),
    _Metro("Memphis, TN-MS-AR", ("memphis",), ()),
    _Metro("Oklahoma City, OK", ("oklahoma city",), ()),
    _Metro("Birmingham-Hoover, AL", ("birmingham",), ("hoover",)),
)

#: Cities whose principal name is ambiguous with a state name or a bare
#: word, so they need a state even as principal ("Washington" alone is not
#: the DC metro; "Columbus" alone could be Ohio or Georgia).
_PRINCIPAL_NEEDS_STATE: frozenset[str] = frozenset({
    "washington", "columbus", "portland", "birmingham", "aurora",
})

#: Between places: "Princeton, NJ / New York, NY", "Hybrid - Chicago, IL",
#: "New York or Chicago". Within a place, commas separate its parts.
_PLACE_SPLIT = re.compile(r"[;|/•·()\[\]\n]+|\s[-–—]\s|\s+(?:or|and|&)\s+", re.I)
_STATE_CODE_TOKEN = re.compile(r"\b[A-Za-z]{2}\b")


def _norm(text: str) -> str:
    """Lower-case, drop dots (st. louis -> st louis, d.c. -> dc), collapse
    everything that is not a letter or digit to single spaces, pad."""
    text = text.lower().replace(".", "")
    return " " + re.sub(r"[^a-z0-9]+", " ", text).strip() + " "


def _has(padded: str, phrase: str) -> bool:
    return f" {phrase} " in padded


@dataclass(frozen=True)
class _Place:
    """What one location string says, in the order it says it."""

    states: tuple[str, ...]          # USPS codes, in order of mention
    nyc: bool                        # names a place inside New York City
    metros: tuple[_Metro, ...]       # metros it names, resolved, in order
    jurisdictions: tuple[str, ...]   # law jurisdictions, in order


def _parts(location: str) -> list[list[str]]:
    """The location as places, each a list of comma-separated parts."""
    places = []
    for place in _PLACE_SPLIT.split(location):
        parts = [part.strip() for part in place.split(",") if part.strip()]
        if parts:
            places.append(parts)
    return places


def _part_states(raw: str, later: bool) -> list[tuple[int, str]]:
    """States named in one part, with their offsets. ``later`` is True for a
    part after the first of its place (where "il" and "Washington" are
    states rather than words or cities)."""
    padded = _norm(raw)
    found: list[tuple[int, str]] = []
    for match in _STATE_CODE_TOKEN.finditer(raw):
        code = match.group(0).upper()
        if code not in US_STATE_CODES:
            continue
        first_word = match.start() == len(raw) - len(raw.lstrip())
        anywhere = match.group(0).isupper() and code not in _WORD_LIKE_CODES
        if anywhere or (later and first_word):
            found.append((match.start(), code))
    # A later part whose first word normalises to a code ("D.C.",
    # "tx 78701") is that state too; dots were the only obstacle.
    first = padded.split()[0].upper() if padded.strip() else ""
    if later and len(first) == 2 and first in US_STATE_CODES:
        if all(code != first for _, code in found):
            found.append((0, first))
    for name, code in US_STATE_NAMES.items():
        if not _has(padded, name):
            continue
        if name in _AMBIGUOUS_STATE_NAMES:
            as_state = (later and padded.strip() == name) or _has(
                padded, f"{name} state"
            )
            if not as_state:
                continue
        found.append((padded.index(f" {name} "), code))
    return sorted(found)


def _read_location(location: str) -> _Place:
    places = _parts(location)
    whole = _norm(location)

    # ── states, in order of mention ──────────────────────────────────────
    states: list[str] = []
    nyc = False
    marks: list[str] = []            # law jurisdictions, in order of mention
    city_parts: list[str] = []       # normalised parts that may name a city
    for parts in places:
        place_states: list[str] = []
        for index, raw in enumerate(parts):
            place_states.extend(code for _, code in _part_states(raw, index > 0))
            padded = _norm(raw)
            # A later part that IS an ambiguous state name ("Albany, New
            # York") is the state, never the city of the same name.
            if not (index > 0 and padded.strip() in _AMBIGUOUS_STATE_NAMES):
                city_parts.append(padded)
        place_nyc = any(_has(_norm(", ".join(parts)), p) for p in _NYC_PLACES) or (
            _norm(parts[0]).strip() == "new york"
            and (len(parts) == 1 or "NY" in place_states)
        )
        if place_nyc:
            nyc = True
            marks.append("NYC")
        # New York State has no entry in the law file; NYC is handled above.
        marks.extend(c for c in place_states if c != "NY" and c in LAW_JURISDICTIONS)
        states.extend(place_states)

    non_us = any(_has(whole, m) for m in _NON_US_MARKERS) and not states

    # ── metros, in order of mention ──────────────────────────────────────
    hits: list[tuple[tuple[int, int], _Metro]] = []
    for metro in METROS:
        best: tuple[int, int] | None = None
        for name in metro.principal + metro.satellite:
            if states:
                ok = any(s in metro.states for s in states)
            else:
                ok = (
                    name in metro.principal
                    and name not in _PRINCIPAL_NEEDS_STATE
                    and not non_us
                )
            if not ok:
                continue
            for index, padded in enumerate(city_parts):
                if _has(padded, name):
                    at = (index, padded.index(f" {name} "))
                    best = at if best is None or at < best else best
                    break
        if best is not None:
            hits.append((best, metro))
    metros = tuple(m for _, m in sorted(hits, key=lambda h: h[0]))

    # ── jurisdictions: named places first; a city's own state only when
    # the location names no state at all ("Greater Chicago Area") ────────
    if not states and not nyc:
        marks.extend(
            m.jurisdiction for m in metros if m.jurisdiction in LAW_JURISDICTIONS
        )
    jurisdictions: list[str] = []
    for code in marks:
        if code not in jurisdictions:
            jurisdictions.append(code)
    return _Place(tuple(states), nyc, metros, tuple(jurisdictions))


def infer_jurisdiction(location: str) -> str | None:
    """The pay-transparency jurisdiction a location string names, or None.

    Returns a key of pay_transparency_laws.yaml (LAW_JURISDICTIONS): a state
    code, "NYC" for a place inside New York City, or "DC". None when the
    location names no place with a law in that file — including New York
    State outside the city, non-US places, "Remote" and bare "Washington",
    which could be the state or the capital. When several places are named,
    the first that has a law is returned. See the block comment above for
    how the string is read.
    """
    if not location:
        return None
    found = _read_location(location).jurisdictions
    return found[0] if found else None


def infer_metro_area(location: str) -> str | None:
    """The col_index.yaml metro (MSA key) a location string names, or None.

    A city counts as a whole phrase and only where any state given agrees
    with the metro's states; a city named with no state resolves only when
    it is the metro's principal city, is not ambiguous on its own
    (_PRINCIPAL_NEEDS_STATE), and nothing marks the place as outside the US.
    The first resolved metro is returned.
    """
    if not location:
        return None
    metros = _read_location(location).metros
    return metros[0].key if metros else None


def looks_like_generic_apply_url(url: str) -> bool:
    """Detect if an 'Apply' link is broken or just drops the user on a homepage.

    Returns True if the URL scheme is mailto: or the path is empty / root.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
        if parsed.scheme == "mailto":
            return True
        # Normalize path to remove trailing slash
        path = parsed.path.rstrip("/")
        if not path or path == "":
            return True
        return False
    except Exception:
        return False

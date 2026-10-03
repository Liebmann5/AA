"""Tests for the posting-observation move (item 2 of 12).

Two concerns live here rather than in test_vetting_workflow.py because they
are about the MOVE, not about vetting behaviour:

* T5: DiscoveryWorkflow no longer emits job-posting observations — asserted
  on the module AST, not a substring, so a commented-out call cannot pass it.
* T6: the three field-derivation helpers, now module-level functions in
  domain/services/posting_observation.py, keep their exact behaviour.

Prior test coverage of the three helpers was ZERO — a grep of tests/ for
their names found no call sites before this item. The T6 tables below are
new coverage, not a port. It began with two labelled wart pins asserting the
substring matchers' behaviour; item 4 replaced the matchers and those rows
now assert the right answers (see the ground-truth tables below).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from auto_apply.application.workflows import discovery_workflow
from auto_apply.domain.services.posting_observation import (
    LAW_JURISDICTIONS,
    METROS,
    US_STATE_CODES,
    infer_jurisdiction,
    infer_metro_area,
    looks_like_generic_apply_url,
)


def test_discovery_workflow_never_calls_observe_job_posting() -> None:
    """T5: the discovery stage must not emit job-posting observations.

    The assertion walks the parsed AST looking for any call whose attribute
    or bare name is ``observe_job_posting`` — a commented-out or stringified
    call site cannot satisfy it. Fails against the pre-change tree, where
    _enqueue_vet_tasks contains exactly such a call.
    """
    tree = ast.parse(
        Path(discovery_workflow.__file__).read_text(encoding="utf-8")
    )
    offenders = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "observe_job_posting"
            )
            or (
                isinstance(node.func, ast.Name)
                and node.func.id == "observe_job_posting"
            )
        )
    ]
    assert offenders == []


# ── Location matchers (item 4) ──────────────────────────────────────────────
#
# The matchers were moved here with substring warts, pinned as such. Item 4
# replaced them. The rows below are ground truth: (location, the pay-
# transparency jurisdiction AA has a law for or None, the col_index metro or
# None). Measured on 7101c42 (the substring matchers): over GROUND_TRUTH,
# 33 jurisdictions wrong — 22 of them a law assigned where none applies — and
# 25 metros wrong; over HELD_OUT (written before the new matchers were run
# on it), 9 and 21. Both tables were written by hand for this item; real
# posting locations from dev_data/ are the stronger test and item 5's
# labelling should add them.

# fmt: off
SF="San Francisco-Oakland-Berkeley, CA"; SJ="San Jose-Sunnyvale-Santa Clara, CA"; NY="New York-Newark-Jersey City, NY-NJ"
LA="Los Angeles-Long Beach-Anaheim, CA"; SEA="Seattle-Tacoma-Bellevue, WA"; BOS="Boston-Cambridge-Newton, MA-NH"
DCM="Washington-Arlington-Alexandria, DC-VA-MD-WV"; SD="San Diego-Chula Vista-Carlsbad, CA"; DEN="Denver-Aurora-Lakewood, CO"
AUS="Austin-Round Rock-Georgetown, TX"; CHI="Chicago-Naperville-Elgin, IL-IN-WI"; PDX="Portland-Vancouver-Hillsboro, OR-WA"
MIA="Miami-Fort Lauderdale-Pompano Beach, FL"; ATL="Atlanta-Sandy Springs-Alpharetta, GA"; DFW="Dallas-Fort Worth-Arlington, TX"
PHX="Phoenix-Mesa-Chandler, AZ"; MSP="Minneapolis-St. Paul-Bloomington, MN-WI"; PHL="Philadelphia-Camden-Wilmington, PA-NJ-DE-MD"
CLT="Charlotte-Concord-Gastonia, NC-SC"; RAL="Raleigh-Cary, NC"; NSH="Nashville-Davidson--Murfreesboro--Franklin, TN"
CMH="Columbus, OH"; IND="Indianapolis-Carmel-Anderson, IN"; PIT="Pittsburgh, PA"; STL="St. Louis, MO-IL"; CIN="Cincinnati, OH-KY-IN"
CLE="Cleveland-Elyria, OH"; DET="Detroit-Warren-Dearborn, MI"; KC="Kansas City, MO-KS"; MEM="Memphis, TN-MS-AR"
OKC="Oklahoma City, OK"; BHM="Birmingham-Hoover, AL"

GROUND_TRUTH: list[tuple[str, str | None, str | None]] = [
 ("San Francisco, CA", "CA", SF), ("Oakland, CA", "CA", SF), ("San Francisco Bay Area", "CA", SF),
 ("San Jose, CA", "CA", SJ), ("Sunnyvale, CA", "CA", SJ), ("Los Angeles, CA", "CA", LA), ("Santa Monica, CA", "CA", LA),
 ("San Diego, CA", "CA", SD), ("Sacramento, CA", "CA", None), ("Irvine, California", "CA", None),
 ("New York, NY", "NYC", NY), ("New York City Metropolitan Area", "NYC", NY), ("Brooklyn, NY", "NYC", NY),
 ("Buffalo, NY", None, None), ("Albany, New York", None, None), ("Jersey City, NJ", "NJ", None), ("Newark, NJ", "NJ", None),
 ("Seattle, WA", "WA", SEA), ("Bellevue, WA", "WA", SEA), ("Spokane, Washington", "WA", None), ("Bellevue, NE", None, None),
 ("Washington, DC", "DC", DCM), ("Washington, D.C.", "DC", DCM), ("Arlington, VA", None, DCM), ("Arlington, TX", None, DFW),
 ("Alexandria, VA", None, DCM), ("Bethesda, MD", "MD", None), ("Baltimore, MD", "MD", None),
 ("Denver, CO", "CO", DEN), ("Boulder, CO", "CO", DEN), ("Aurora, CO", "CO", DEN), ("Aurora, IL", "IL", None), ("Colorado Springs, CO", "CO", None),
 ("Chicago, IL", "IL", CHI), ("Greater Chicago Area", "IL", CHI), ("Naperville, Illinois", "IL", None),
 ("Boston, MA", "MA", BOS), ("Cambridge, MA", "MA", BOS), ("Cambridge, UK", None, None), ("Somerville, Massachusetts", "MA", BOS),
 ("Minneapolis, MN", "MN", MSP), ("St Paul, MN", "MN", MSP), ("Bloomington, IN", None, None), ("Bloomington, MN", "MN", MSP),
 ("Honolulu, HI", "HI", None), ("Providence, RI", "RI", None),
 ("Austin, TX", None, AUS), ("Austin, TX 78701", None, AUS), ("Round Rock, TX", None, AUS), ("Georgetown, TX", None, AUS),
 ("Dallas, TX", None, DFW), ("Fort Worth, TX", None, DFW), ("Atlanta, GA", None, ATL), ("Alpharetta, GA", None, ATL),
 ("Portland, OR", None, PDX), ("Portland, ME", None, None), ("Miami, FL", None, MIA), ("Phoenix, AZ", None, PHX), ("Mesa, AZ", None, PHX),
 ("Philadelphia, PA", None, PHL), ("Wilmington, DE", None, PHL), ("Wilmington, NC", None, None), ("Camden, NJ", "NJ", PHL),
 ("Charlotte, NC", None, CLT), ("Concord, NC", None, CLT), ("Concord, CA", "CA", None), ("Raleigh, NC", None, RAL), ("Cary, NC", None, RAL),
 ("Nashville, TN", None, NSH), ("Franklin, TN", None, NSH), ("Columbus, OH", None, CMH), ("Columbus, GA", None, None),
 ("Indianapolis, IN", None, IND), ("Carmel, IN", None, IND), ("Carmel, CA", "CA", None), ("Pittsburgh, PA", None, PIT),
 ("St. Louis, MO", None, STL), ("Cincinnati, OH", None, CIN), ("Cleveland, OH", None, CLE), ("Detroit, MI", None, DET),
 ("Warren, MI", None, DET), ("Dearborn, MI", None, DET), ("Kansas City, MO", None, KC), ("Memphis, TN", None, MEM),
 ("Oklahoma City, OK", None, OKC), ("Birmingham, AL", None, BHM), ("Birmingham, UK", None, None), ("Salt Lake City, UT", None, None),
 ("Lansing, MI", None, None), ("Silicon Valley", "CA", SJ), ("Plano, TX", None, None), ("Laramie, WY", None, None),
 ("Remote", None, None), ("Remote - US", None, None), ("United States", None, None), ("Remote (California)", "CA", None),
 ("Hybrid - Chicago, IL", "IL", CHI), ("New York, NY (Hybrid)", "NYC", NY), ("Remote in Colorado", "CO", None),
 ("Anywhere in the US", None, None), ("Canada", None, None), ("Toronto, ON", None, None), ("Vancouver, BC", None, None),
 ("Coral Gables, FL", None, None), ("Wichita, KS", None, None), ("Omaha, NE", None, None), ("Mason, OH", None, None),
]

HELD_OUT: list[tuple[str, str | None, str | None]] = [
 ("Palo Alto, CA", "CA", None), ("Mountain View, California", "CA", None), ("Santa Clara, CA", "CA", SJ),
 ("Berkeley, CA", "CA", SF), ("Long Beach, CA", "CA", LA), ("Anaheim, CA", "CA", LA), ("Carlsbad, CA", "CA", SD),
 ("Manhattan, NY", "NYC", NY), ("Queens, New York", "NYC", NY), ("Rochester, NY", None, None), ("Hoboken, NJ", "NJ", None),
 ("Tacoma, WA", "WA", SEA), ("Redmond, Washington", "WA", None), ("Lakewood, CO", "CO", DEN), ("Lakewood, NJ", "NJ", None),
 ("Fort Collins, CO", "CO", None), ("Elgin, IL", "IL", CHI), ("Evanston, IL", "IL", None), ("Newton, MA", "MA", BOS),
 ("Worcester, MA", "MA", None), ("Saint Paul, Minnesota", "MN", MSP), ("Rochester, MN", "MN", None),
 ("Annapolis, MD", "MD", None), ("Silver Spring, Maryland", "MD", None), ("Kailua, HI", "HI", None),
 ("Warwick, RI", "RI", None), ("Houston, TX", None, None), ("San Antonio, TX", None, None), ("Plano, Texas", None, None),
 ("Tempe, AZ", None, None), ("Chandler, AZ", None, PHX), ("Chandler, OK", None, None), ("Hillsboro, OR", None, PDX),
 ("Vancouver, WA", "WA", PDX), ("Fort Lauderdale, FL", None, MIA), ("Pompano Beach, Florida", None, MIA),
 ("Sandy Springs, GA", None, ATL), ("Durham, NC", None, None), ("Murfreesboro, TN", None, NSH), ("Franklin, MA", "MA", None),
 ("Anderson, SC", None, None), ("Anderson, IN", None, IND), ("Elyria, OH", None, CLE), ("Dearborn, Michigan", None, DET),
 ("Overland Park, KS", None, None), ("Kansas City, KS", None, KC), ("Hoover, AL", None, BHM), ("Gastonia, NC", None, CLT),
 ("Remote, USA", None, None), ("Remote - Seattle, WA", "WA", SEA), ("Onsite - Denver, Colorado", "CO", DEN),
 ("London, UK", None, None), ("Bangalore, India", None, None), ("Berlin, Germany", None, None),
 ("Chicago, IL 60606", "IL", CHI), ("Boston, Massachusetts, United States", "MA", BOS), ("United States (Remote)", None, None),
 ("New York, New York, United States", "NYC", NY), ("Washington DC-Baltimore Area", "DC", DCM), ("Denver Metropolitan Area", "CO", DEN),
]
# fmt: on


@pytest.mark.parametrize("table", ["GROUND_TRUTH", "HELD_OUT"])
def test_matchers_agree_with_the_ground_truth(table: str) -> None:
    """TEETH — 33 + 9 jurisdiction and 25 + 21 metro rows fail on 7101c42.
    Every disagreement is listed, so one failure shows the whole damage."""
    rows = GROUND_TRUTH if table == "GROUND_TRUTH" else HELD_OUT
    wrong = [
        (location, "jurisdiction", infer_jurisdiction(location), jurisdiction)
        for location, jurisdiction, _ in rows
        if infer_jurisdiction(location) != jurisdiction
    ] + [
        (location, "metro", infer_metro_area(location), metro)
        for location, _, metro in rows
        if infer_metro_area(location) != metro
    ]
    assert wrong == []


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("", None),
        # The two former wart pins, now right.
        ("Chicago, IL", "IL"),
        ("Washington, DC", "DC"),
        ("Washington, D.C.", "DC"),
        # Bare "Washington" could be the state or the capital: no guess.
        ("Washington", None),
        ("Seattle, Washington", "WA"),
        # New York State outside the city has no entry in the law file.
        ("Buffalo, NY", None),
        ("New York", "NYC"),
        # Codes count as whole tokens; everyday words do not.
        ("Canada", None),
        ("Boston, England", None),
        ("Remote IN Chicago", "IL"),
        ("Providence, RI", "RI"),
        # Several places: the first one with a law, in the order written.
        ("Princeton, NJ / New York, NY", "NJ"),
        ("New York, NY / Princeton, NJ", "NYC"),
        ("Austin, TX or Chicago, IL", "IL"),
    ],
)
def test_infer_jurisdiction(location: str, expected: str | None) -> None:
    """GUARD — the decisions the ground-truth tables rest on, named one by
    one so a change to any of them is a visible, deliberate edit."""
    assert infer_jurisdiction(location) == expected


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("", None),
        ("NEW YORK", "New York-Newark-Jersey City, NY-NJ"),
        # The former "la" wart rows, now right.
        ("Atlanta, GA", "Atlanta-Sandy Springs-Alpharetta, GA"),
        ("Dallas, TX", "Dallas-Fort Worth-Arlington, TX"),
        ("Philadelphia, PA", "Philadelphia-Camden-Wilmington, PA-NJ-DE-MD"),
        ("Oakland, CA", "San Francisco-Oakland-Berkeley, CA"),
        # A town that recurs across the country needs its state.
        ("Arlington, VA", "Washington-Arlington-Alexandria, DC-VA-MD-WV"),
        ("Arlington, TX", "Dallas-Fort Worth-Arlington, TX"),
        ("Portland, ME", None),
        ("Portland", None),
        # A principal city named alone resolves, unless marked non-US.
        ("Chicago", "Chicago-Naperville-Elgin, IL-IN-WI"),
        ("Birmingham, UK", None),
        ("Boston, England", None),
        # A satellite town named alone is not enough to place it.
        ("Arlington", None),
        ("Cambridge", None),
        ("Bozeman, MT", None),
    ],
)
def test_infer_metro_area(location: str, expected: str | None) -> None:
    """GUARD — the metro decisions, named one by one."""
    assert infer_metro_area(location) == expected


def test_every_law_jurisdiction_is_reachable_and_real() -> None:
    """TEETH — RI is in pay_transparency_laws.yaml and the old matcher could
    never return it. The set the matcher can return now equals the file's
    keys, so a law added to the file cannot go unreachable silently."""
    import yaml

    from auto_apply.domain.services import posting_observation

    path = (
        Path(posting_observation.__file__).resolve().parents[2]
        / "resources" / "research" / "pay_transparency_laws.yaml"
    )
    keys = set(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert set(LAW_JURISDICTIONS) == keys


def test_every_metro_is_a_col_index_key() -> None:
    """GUARD — the metro list and col_index.yaml name the same metros
    ("Remote" is a COL default, not a place), and every metro's states are
    real codes, so a metro the detector cannot look up cannot be returned."""
    import yaml

    from auto_apply.domain.services import posting_observation

    path = (
        Path(posting_observation.__file__).resolve().parents[2]
        / "resources" / "research" / "col_index.yaml"
    )
    keys = set(yaml.safe_load(path.read_text(encoding="utf-8"))) - {"Remote"}
    assert {m.key for m in METROS} == keys
    for metro in METROS:
        assert set(metro.states) <= US_STATE_CODES, metro.key


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("", False),
        ("mailto:hr@example.com", True),
        ("https://example.com", True),
        ("https://example.com/", True),
        ("https://example.com/careers/job/123", False),
        # Malformed IPv6 netloc: urlparse raises, exercising the except branch.
        ("http://[::1", False),
    ],
)
def test_looks_like_generic_apply_url(url: str, expected: bool) -> None:
    """T6: every branch of the generic-apply-URL heuristic, incl. the defensive except."""
    assert looks_like_generic_apply_url(url) is expected

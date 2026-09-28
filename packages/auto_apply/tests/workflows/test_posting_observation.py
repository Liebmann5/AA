"""Tests for the posting-observation move (item 2 of 12).

Two concerns live here rather than in test_vetting_workflow.py because they
are about the MOVE, not about vetting behaviour:

* T5: DiscoveryWorkflow no longer emits job-posting observations — asserted
  on the module AST, not a substring, so a commented-out call cannot pass it.
* T6: the three field-derivation helpers, now module-level functions in
  domain/services/posting_observation.py, keep their exact behaviour.

Prior test coverage of the three helpers was ZERO — a grep of tests/ for
their names found no call sites before this item. The T6 tables below are
new coverage, not a port, including two explicitly labelled wart pins that
assert the CURRENT substring-matching behaviour.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from auto_apply.application.workflows import discovery_workflow
from auto_apply.domain.services.posting_observation import (
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


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("", None),
        ("San Francisco, CA", "CA"),
        ("San Diego", "CA"),
        ("New York, NY", "NYC"),
        ("Seattle, WA", "WA"),
        ("Denver, CO", "CO"),
        ("Springfield, Illinois", "IL"),
        ("Baltimore, MD", "MD"),
        ("Honolulu, HI", "HI"),
        # Bare "dc" is the only spelling that reaches the DC clause — every
        # "washington dc" variant matches the WA clause first (see wart pins).
        ("dc", "DC"),
        ("Trenton, New Jersey", "NJ"),
        ("Boston, MA", "MA"),
        ("Minneapolis, MN", "MN"),
        ("Austin, TX", None),
        # ── Wart pins: these assert the CURRENT substring-matching behaviour,
        # moved verbatim from DiscoveryWorkflow. A future fix to the matcher
        # must change these on purpose, not by accident.
        ("Chicago, IL", "CA"),  # "ca" is a substring of "chicago"; CA runs first
        ("Washington, DC", "WA"),  # "washington" matches WA before DC is checked
    ],
)
def test_infer_jurisdiction(location: str, expected: str | None) -> None:
    """T6: one case per clause of the jurisdiction matcher, verbatim behaviour."""
    assert infer_jurisdiction(location) == expected


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("", None),
        ("San Francisco, CA", "San Francisco-Oakland-Berkeley, CA"),
        ("NEW YORK", "New York-Newark-Jersey City, NY-NJ"),
        ("Los Angeles", "Los Angeles-Long Beach-Anaheim, CA"),
        ("Seattle, WA", "Seattle-Tacoma-Bellevue, WA"),
        ("Washington, DC", "Washington-Arlington-Alexandria, DC-VA-MD-WV"),
        ("Austin, TX", "Austin-Round Rock-Georgetown, TX"),
        ("Chicago, IL", "Chicago-Naperville-Elgin, IL-IN-WI"),
        ("St. Louis, MO", "St. Louis, MO-IL"),
        ("Birmingham, AL", "Birmingham-Hoover, AL"),
        ("Bozeman, MT", None),
        # ── Wart pins, the "la" family. The Los Angeles tuple contains the bare
        # keyword "la", and it is checked 4th of 32 — so every location whose
        # name merely CONTAINS the letters "la" is captured by Los Angeles
        # before its own entry is reached. Measured over 20 major US metros: 8
        # resolve to Los Angeles. This is worse than a None: metro_area feeds
        # the cost-of-living lookup in the research record, so a wrong MSA is a
        # populated value that looks like data.
        #
        # Moved verbatim with the function; a future fix must change these rows
        # on purpose.
        ("Atlanta, GA", "Los Angeles-Long Beach-Anaheim, CA"),
        ("Dallas, TX", "Los Angeles-Long Beach-Anaheim, CA"),
        ("Philadelphia, PA", "Los Angeles-Long Beach-Anaheim, CA"),
        # Oakland is named IN the San Francisco MSA string and still lands in LA,
        # because the SF tuple matches on "san francisco"/"sf bay"/"bay area" only.
        ("Oakland, CA", "Los Angeles-Long Beach-Anaheim, CA"),
    ],
)
def test_infer_metro_area(location: str, expected: str | None) -> None:
    """T6: guard, hit (incl. uppercase input), and miss branches of the MSA map."""
    assert infer_metro_area(location) == expected


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

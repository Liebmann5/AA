"""Pins for the discovery-observation record shape (§4b).

The record observes employers, platforms, and pages — never the user. These
pins lock the shape, the null observer's zero cost, and the structural
absence of user-data fields.
"""

from __future__ import annotations

import dataclasses

import pytest

from auto_apply.domain.ports.research_port import (
    DiscoveryCandidateObservation,
    DiscoveryCardObservation,
    DiscoveryObservation,
    NullResearchObserver,
)


def _observation() -> DiscoveryObservation:
    return DiscoveryObservation(
        provider="TestProvider",
        page_host="serp.example.com",
        page_state="normal",
        blocked=False,
        architecture="identifier_js",
        card_count=2,
        resolved_count=1,
        multi_route_count=1,
        deferred_count=0,
        no_destination_count=0,
        sponsored_card_count=0,
        activation_attempts=1,
        activation_resolved=1,
        learned_identity=("data-job-ref",),
        cards=(
            DiscoveryCardObservation(
                card_index=0,
                title="Pipeline Engineer",
                resolution_state="resolved",
                selected_host="boards.example.org",
                candidates=(
                    DiscoveryCandidateObservation(
                        original_url="/out?u=zz",
                        resolved_url="https://boards.example.org/jobs/2",
                        resolved_host="boards.example.org",
                        anchor_text="Apply for this role",
                        source="revealed",
                        outcome="selected",
                        apply_intent=True,
                        title_overlap=0.0,
                        method="no decodable payload; wrapper kept as navigable",
                    ),
                ),
            ),
            DiscoveryCardObservation(
                card_index=1,
                title="Coastal Engineer",
                resolution_state="multi_route",
                selected_host="",
                candidates=(
                    DiscoveryCandidateObservation(
                        original_url="https://serp.example.com/y.js?ad_domain=shopexample.co",
                        resolved_url="https://serp.example.com/y.js?ad_domain=shopexample.co",
                        resolved_host="serp.example.com",
                        anchor_text="",
                        source="static",
                        outcome="rejected",
                        rejection_reason="advertising evidence",
                        ad_evidence=("query key 'ad_domain' contains advertising token ['ad']",),
                    ),
                ),
            ),
        ),
    )


def test_record_constructs_and_is_frozen() -> None:
    observation = _observation()
    assert observation.card_count == 2
    assert observation.cards[0].candidates[0].outcome == "selected"
    assert observation.cards[1].candidates[0].rejection_reason == "advertising evidence"
    with pytest.raises(dataclasses.FrozenInstanceError):
        observation.card_count = 99  # type: ignore[misc]


def test_null_observer_costs_nothing() -> None:
    observer = NullResearchObserver()
    assert observer.is_enabled is False
    observer.observe_discovery(_observation())  # must not raise


def test_record_carries_no_user_data_fields() -> None:
    """The page URL is deliberately absent: it would carry the search query."""
    field_names = {f.name for f in dataclasses.fields(DiscoveryObservation)}
    for forbidden in ("page_url", "query", "search_url", "user", "profile", "session_id"):
        assert forbidden not in field_names
    assert "page_host" in field_names

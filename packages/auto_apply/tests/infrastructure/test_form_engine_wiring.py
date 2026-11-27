"""Pins for building the application step engine in the composition root.

Built and never connected is this codebase's signature defect, so these pins
build the real orchestrator and look at the engine the ApplicationsWorkflow
actually holds — and at what each ``applications.*`` setting does to it.
"""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import MagicMock, patch

from auto_apply.application.services.form_engine import FormStepEngine
from auto_apply.domain.models.profile import UserProfile
from auto_apply.infrastructure.composition_root import build_orchestrator
from auto_apply.infrastructure.registry import _RUNTIME_DEFAULTS, CapabilitiesRegistry


def _profile() -> UserProfile:
    return UserProfile.model_validate({
        "profile_name": "test",
        "personal_info": {
            "first_name": "T", "last_name": "U", "email": "t@example.com",
            "phone_number": "000", "street_address": "", "city": "", "state": "",
            "zip_code": "",
        },
        "links": {},
        "career_summary": "A test profile for validation purposes, written to satisfy the "
                          "fifty character minimum length requirement.",
        "search_preferences": {"desired_job_titles": ["Developer"],
                               "preferred_locations": ["Remote"]},
        "politeness_settings": {},
    })


def _registry(low_resource: bool = True, **applications: Any) -> MagicMock:
    config = copy.deepcopy(dict(_RUNTIME_DEFAULTS))
    config["applications"] = {**config.get("applications", {}), **applications}
    registry = MagicMock(spec=CapabilitiesRegistry)
    registry.get_active_profile.return_value = _profile()
    registry.get_runtime_profile.return_value = MagicMock()
    registry.is_low_resource_environment.return_value = low_resource
    registry.is_research_enabled.return_value = False
    registry.get_all_effective_config.return_value = config
    registry.get_session_plan.return_value = MagicMock()
    registry.get_allowed_browsers.return_value = []
    registry.discovery_requires_live_browser.return_value = False
    registry.get_viable_candidates.return_value = []
    registry.build_capability_profile.return_value = MagicMock()
    return registry


def _engine(registry: MagicMock) -> Any:
    orchestrator = build_orchestrator(registry, driver=MagicMock())
    return orchestrator._workflows["ApplicationsWorkflow"]._form_engine


def _sources(engine: FormStepEngine) -> list[str]:
    return [s.name for s in engine._sources]


def test_the_engine_is_built_and_handed_to_the_applications_workflow() -> None:
    engine = _engine(_registry())
    assert isinstance(engine, FormStepEngine)
    assert _sources(engine) == ["session", "profile", "saved"], (
        "generated drafts are off by default"
    )


def test_legacy_keeps_the_previous_filler() -> None:
    assert _engine(_registry(form_engine="legacy")) is None


def test_no_browser_means_no_engine() -> None:
    orchestrator = build_orchestrator(_registry(), driver=None)
    assert orchestrator._workflows["ApplicationsWorkflow"]._form_engine is None


def test_legal_answers_ask_keeps_legal_questions_for_the_person() -> None:
    engine = _engine(_registry(legal_answers="ask"))
    profile_source = next(s for s in engine._sources if s.name == "profile")
    assert profile_source._legal_from_profile is False


def test_answer_sources_order_and_unknown_names() -> None:
    engine = _engine(_registry(answer_sources=["saved", "profile", "nonsense"]))
    assert _sources(engine) == ["session", "saved", "profile"], (
        "remember_answers keeps the session memory first; unknown names are ignored"
    )
    engine = _engine(_registry(answer_sources=["profile"], remember_answers=False))
    assert _sources(engine) == ["profile"]


@patch("auto_apply.adapters.secondary.reasoning.gpt4all_adapter.GPT4AllAdapter", autospec=True)
def test_generated_drafts_only_when_turned_on(_gpt4all: MagicMock) -> None:
    assert "generated" not in _sources(_engine(_registry(low_resource=False)))
    on = _engine(_registry(low_resource=False, generated_answers=True))
    assert _sources(on)[-1] == "generated"


def test_settings_reach_the_engine() -> None:
    engine = _engine(_registry(review_each_step=True, min_answer_confidence=0.9,
                               script_fill_fallback=False, max_pages=5))
    s = engine._settings
    assert s.review_each_step and s.fill.min_confidence == 0.9
    assert not s.actuator.script_fallback and s.max_steps == 5

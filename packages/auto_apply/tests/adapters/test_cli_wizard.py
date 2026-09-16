"""Unit tests for adapters/primary/cli/wizard.py (stage U3, turn 2 rewrite).

input() is monkeypatched so no real stdin is required.

The previous suite asserted on the keys of the untyped dict the wizard used
to emit — and nothing checked whether any consumer read those keys. That is
precisely the defect this arc exists to remove, and key-shape assertions are
what let it live. This suite asserts on SessionRequest fields instead,
preserving each test's original intent (default fallbacks, schema labels,
multiline link input, max_results parsing).

Pin labels are honest:
    TEETH — fail against the pre-change tree for the reason stated.
    GUARD — passes on both trees; the change must not break it.

The four strategy tests are deleted with the strategy prompt itself: nothing
in the codebase ever consumed the answer (session_controller's shim names the
key dead; runtime_defaults.yaml's discovery_strategy is a different concept).
A suite asserting on a dead question is how the question survived this long.
"""

from unittest.mock import MagicMock, patch

from auto_apply.adapters.primary.cli.wizard import CLIWizard
from auto_apply.application.agent.context import SessionStatistics
from auto_apply.application.services.session_controller import SessionController
from auto_apply.domain.models.session_plan import SessionExecutionMode, SessionPlan
from auto_apply.domain.models.task_priority import TaskPriority
from auto_apply.domain.models.ui_contract import EntryPoint, SessionRequest
from auto_apply.domain.models.work_unit import TaskType


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _mock_profile(titles=("Data Engineer",), locations=("Boston",)):
    prefs = MagicMock()
    prefs.desired_job_titles = list(titles)
    prefs.preferred_locations = list(locations)
    profile = MagicMock()
    profile.search_preferences = prefs
    return profile


def _run_wizard(inputs: list[str], profile=None) -> SessionRequest | None:
    """Runs the wizard with a fixed sequence of mocked input() responses."""
    wizard = CLIWizard(profile=profile)
    with patch("builtins.input", side_effect=inputs):
        return wizard.run()


def _controller(profile) -> SessionController:
    """SessionController with mocked registry/db/orchestrator; network stubbed."""
    plan = SessionPlan(session_id="pin-test")
    registry = MagicMock()
    registry.get_session_plan.return_value = plan
    registry.get_active_profile.return_value = profile
    db = MagicMock()
    db.get_queue_stats.return_value = {
        "pending": 0, "in_progress": 0, "completed": 0,
        "failed": 0, "skipped": 0, "permanently_failed": 0,
    }
    orchestrator = MagicMock()
    orchestrator.session_plan = plan
    orchestrator.context = MagicMock()
    orchestrator.context.session_id = "pin-test"
    orchestrator.context.stats = SessionStatistics()
    orchestrator.state_machine = MagicMock()
    orchestrator.task_queue = db
    controller = SessionController(registry=registry, db=db, orchestrator=orchestrator)
    controller._check_network_connectivity = lambda: True
    return controller


def _queued(controller: SessionController):
    return [call.args[0] for call in controller.db.queue_task.call_args_list]


# ─────────────────────────────────────────────────────────────────────────────
# TEETH — fail against the pre-change tree
# ─────────────────────────────────────────────────────────────────────────────

def test_run_returns_a_session_request():
    """TEETH: the wizard's output is typed.

    Fails pre-U3 — run() returned an untyped dict and the shim had to
    translate it."""
    result = _run_wizard(["", "", "", "", "", ""])
    assert isinstance(result, SessionRequest)


def test_collect_links_only_yields_discover_only():
    """TEETH: choosing "collect links only" yields DISCOVER_ONLY.

    Fails pre-turn-2 — the wizard had no exit-axis question at all."""
    result = _run_wizard(["", "3", "", "", "", ""])
    assert result is not None
    assert result.entry is EntryPoint.SEARCH
    assert result.execution_mode is SessionExecutionMode.DISCOVER_ONLY
    assert result.execution_mode.includes_application is False


def test_collect_and_check_yields_discover_and_vet():
    """TEETH: choosing "collect and check" yields DISCOVER_AND_VET."""
    result = _run_wizard(["", "2", "", "", "", ""])
    assert result is not None
    assert result.execution_mode is SessionExecutionMode.DISCOVER_AND_VET
    assert result.execution_mode.includes_vetting is True
    assert result.execution_mode.includes_application is False


def test_url_entry_check_first_yields_vet_and_apply():
    """TEETH: pasted-links "check first" yields VET_AND_APPLY.

    The paste-links menu cannot offer "collect" options (the user supplied
    the links), so only apply-now and check-first appear."""
    result = _run_wizard(["2", "2", "https://jobs.example.com/9", ""])
    assert result is not None
    assert result.entry is EntryPoint.DIRECT_URLS
    assert result.execution_mode is SessionExecutionMode.VET_AND_APPLY
    assert result.execution_mode.includes_vetting is True
    assert result.execution_mode.includes_application is True


def test_providers_menu_restricts_to_the_typed_engine():
    """TEETH: typing "bing" at the engine question yields providers=("bing",).

    Fails pre-turn-2 — SessionRequest had no providers field."""
    result = _run_wizard(["", "", "bing", "", "", ""])
    assert result is not None
    assert result.providers == ("bing",)


def test_providers_menu_drops_unknown_names_with_a_note(capsys):
    """TEETH: unknown engine names are dropped, and the user is told.

    Silent acceptance would let a typo quietly change the session; silent
    dropping would hide it. The note is the honest middle."""
    result = _run_wizard(["", "", "bing, linkedin", "", "", ""])
    assert result is not None
    assert result.providers == ("bing",)
    assert "linkedin" in capsys.readouterr().out


def test_direct_links_mode_maps_to_direct_urls_apply_only():
    """TEETH: paste-links mode yields entry=DIRECT_URLS with an
    execution_mode whose includes_vetting is False.

    Fails pre-U3: the wizard emitted the string "direct_links", which is not
    an EntryPoint at all, and no execution mode existed in its output."""
    result = _run_wizard(
        ["2", "", "https://jobs.example.com/1", "https://jobs.example.com/2", ""]
    )
    assert isinstance(result, SessionRequest)
    assert result.entry is EntryPoint.DIRECT_URLS
    assert result.execution_mode.includes_vetting is False
    assert result.execution_mode.includes_application is True
    assert result.urls == (
        "https://jobs.example.com/1",
        "https://jobs.example.com/2",
    )


def test_comma_separated_titles_become_a_tuple():
    """TEETH: typing "ML Engineer, Data Scientist" yields a tuple of two.

    Fails pre-U3: the wizard kept it as a single string."""
    result = _run_wizard(["", "", "", "ML Engineer, Data Scientist", "", ""])
    assert result is not None
    assert result.keywords == ("ML Engineer", "Data Scientist")


def test_typed_answers_reach_the_queued_tasks_not_the_profile_defaults():
    """TEETH: the original defect, closed end to end.

    The pre-U2 controller read only "mode" and "input" from the wizard's
    dict; the titles and locations the user typed were discarded and the
    profile's were seeded instead ("collected exactly one location, seeded
    queue contained two"). Drive initialize_session with the wizard's output
    and assert the queued task carries the typed answers. Fails on the
    pre-U3 wizard: its dict produced profile-derived tasks here."""
    profile = _mock_profile(
        titles=["FallbackTitle"], locations=["FallbackCity", "OtherCity"]
    )
    request = _run_wizard(
        ["", "", "", "TypedTitle", "TypedCity", ""], profile=profile
    )
    assert request is not None

    controller = _controller(profile)
    task_count = controller.initialize_session(request)

    tasks = _queued(controller)
    assert task_count == 1, (
        f"typed exactly one title and one location but {task_count} tasks "
        f"were queued — the profile fallback fired"
    )
    task = tasks[0]
    assert task.task_type is TaskType.DISCOVER
    assert task.priority == TaskPriority.DISCOVER
    assert task.payload["query"] == "TypedTitle"
    assert task.payload["location"] == "TypedCity"


# ─────────────────────────────────────────────────────────────────────────────
# GUARD — defaults and fallbacks (pass on both trees)
# ─────────────────────────────────────────────────────────────────────────────

def test_enter_everywhere_yields_wizard_defaults():
    """GUARD: pressing Enter at every prompt still yields the defaults —
    full pipeline, all engines, hardcoded title/location/max fallbacks.

    This is the muscle-memory pin: an existing user's habit produces exactly
    the behavior they had before the exit-axis question existed."""
    result = _run_wizard(["", "", "", "", "", ""])
    assert isinstance(result, SessionRequest)
    assert result.entry is EntryPoint.SEARCH
    assert result.execution_mode is SessionExecutionMode.FULL_PIPELINE
    assert result.providers == ()
    assert result.keywords == ("Software Engineer",)
    assert result.location == "Remote"
    assert result.max_results == 100


def test_keywords_default_from_profile():
    result = _run_wizard(
        ["", "", "", "", "", ""],
        profile=_mock_profile(titles=["ML Engineer", "Data Scientist"]),
    )
    assert result is not None
    assert result.keywords == ("ML Engineer", "Data Scientist")


def test_location_default_from_profile():
    result = _run_wizard(
        ["", "", "", "", "", ""], profile=_mock_profile(locations=["Seattle"])
    )
    assert result is not None
    assert result.location == "Seattle"


def test_user_can_override_profile_defaults():
    result = _run_wizard(
        ["", "", "", "Backend Engineer", "Austin", ""],
        profile=_mock_profile(titles=["Data Engineer"], locations=["Boston"]),
    )
    assert result is not None
    assert result.keywords == ("Backend Engineer",)
    assert result.location == "Austin"


def test_empty_profile_titles_falls_back_to_hardcoded():
    result = _run_wizard(
        ["", "", "", "", "", ""], profile=_mock_profile(titles=[])
    )
    assert result is not None
    assert result.keywords == ("Software Engineer",)


def test_empty_profile_locations_falls_back_to_hardcoded():
    result = _run_wizard(
        ["", "", "", "", "", ""], profile=_mock_profile(locations=[])
    )
    assert result is not None
    assert result.location == "Remote"


def test_direct_links_with_no_links_returns_none():
    """GUARD: the one "nothing to do" outcome.

    Pre-U3 this returned {} and startup exited on its falsiness; now it
    returns None and startup exits on the explicit None check — same exit,
    typed instead of truthy."""
    assert _run_wizard(["2", "", ""]) is None


# ─────────────────────────────────────────────────────────────────────────────
# Schema label resolution (unchanged behavior)
# ─────────────────────────────────────────────────────────────────────────────

def test_schema_label_returns_field_label():
    wizard = CLIWizard()
    label = wizard._schema_label("search_preferences.desired_job_titles", "FALLBACK")
    assert label == "Desired Job Titles"


def test_schema_label_returns_fallback_for_unknown_key():
    wizard = CLIWizard()
    label = wizard._schema_label("nonexistent.key", "My Fallback")
    assert label == "My Fallback"


def test_schema_label_prefers_schema_over_fallback_for_known_key():
    wizard = CLIWizard()
    label = wizard._schema_label("search_preferences.preferred_locations", "Location")
    assert label == "Preferred Locations"


# ─────────────────────────────────────────────────────────────────────────────
# max_results
# ─────────────────────────────────────────────────────────────────────────────

def test_max_results_from_user_input():
    result = _run_wizard(["", "", "", "", "", "50"])
    assert result is not None
    assert result.max_results == 50


def test_max_results_defaults_to_100_when_empty():
    result = _run_wizard(["", "", "", "", "", ""])
    assert result is not None
    assert result.max_results == 100


def test_max_results_defaults_to_100_on_bad_input():
    result = _run_wizard(["", "", "", "", "", "not-a-number"])
    assert result is not None
    assert result.max_results == 100

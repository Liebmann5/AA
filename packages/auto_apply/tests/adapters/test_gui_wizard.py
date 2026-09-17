"""Pins for the GUI session wizard (stage U3, turn 3).

The old GUI wizard emitted an untyped dict with two of four entry points and
no exit axis. These pins cover the rewritten wizard's request-building and
label vocabulary — all display-free: no Tk widgets are constructed anywhere
in this file.

Pin labels are honest:
    TEETH — fail against the pre-change tree for the reason stated.
    GUARD — passes on both trees; the GUI's correct half must not regress.
"""

from __future__ import annotations

import ast
from pathlib import Path

from auto_apply.adapters.primary.cli import wizard as cli_wizard
from auto_apply.adapters.primary.gui import wizard as gui_wizard
from auto_apply.application.services.session_controller import (
    _LEGACY_ENTRY_TO_EXECUTION_MODE,
)
from auto_apply.domain.models.session_plan import SessionExecutionMode, SessionPlan
from auto_apply.domain.models import ui_contract
from auto_apply.domain.models.ui_contract import (
    ENTRY_POINT_LABELS,
    EntryPoint,
    SessionRequest,
    outcome_options_for_entry,
    provider_vocabulary,
)

_PKG_ROOT = Path(__file__).resolve().parents[2]
_APP_PY = _PKG_ROOT / "src" / "auto_apply" / "adapters" / "primary" / "gui" / "app.py"


# ─────────────────────────────────────────────────────────────────────────────
# TEETH
# ─────────────────────────────────────────────────────────────────────────────

def test_build_session_request_returns_a_session_request() -> None:
    """TEETH: the GUI wizard's output is typed.

    Fails pre-turn-3 — gui/wizard.py returned a plain dict with 'mode' and
    'input' keys."""
    request = gui_wizard.build_session_request(
        entry=EntryPoint.SEARCH,
        execution_mode=SessionExecutionMode.FULL_PIPELINE,
        keywords_text="Python Dev",
    )
    assert isinstance(request, SessionRequest)


def test_all_four_entry_points_are_reachable() -> None:
    """TEETH: the GUI can build a request for every EntryPoint member.

    Fails pre-turn-3 — the old wizard had exactly two radios ("discovery"
    and "direct"); VET_URLS and COMPANY_PAGES were unreachable on this
    surface even though their seeders worked."""
    built: dict[EntryPoint, SessionRequest] = {}
    for entry in EntryPoint:
        built[entry] = gui_wizard.build_session_request(
            entry=entry,
            execution_mode=SessionExecutionMode.FULL_PIPELINE,
            keywords_text="Engineer",
            urls_text="https://example.com/j/1",
        )
    assert set(built) == set(EntryPoint)
    for entry, request in built.items():
        assert request.entry is entry


def test_entry_point_labels_cover_every_member() -> None:
    """TEETH: the entry radio group has a label for every EntryPoint."""
    assert set(ENTRY_POINT_LABELS) == set(EntryPoint)
    assert all(label.strip() for label in ENTRY_POINT_LABELS.values())


def test_gui_and_cli_read_labels_from_one_source() -> None:
    """TEETH: both adapters import the SAME vocabulary objects.

    The parity rule is asserted as object identity, never as literal string
    comparison — two surfaces agreeing because they read one source, not
    because two copies happen to match today."""
    assert gui_wizard.outcome_options_for_entry is ui_contract.outcome_options_for_entry
    assert cli_wizard.outcome_options_for_entry is ui_contract.outcome_options_for_entry
    assert gui_wizard.ENTRY_POINT_LABELS is ui_contract.ENTRY_POINT_LABELS
    assert gui_wizard.provider_vocabulary is ui_contract.provider_vocabulary
    assert cli_wizard.provider_vocabulary is ui_contract.provider_vocabulary


def test_outcome_options_for_entry_follows_the_b2_ruling() -> None:
    """TEETH: "collect" options exist only where the pipeline discovers jobs.

    DIRECT_URLS cannot be "collected" (the user supplied the links), and
    VET_URLS gains the no-submit VET_ONLY outcome — decided this turn."""
    direct = outcome_options_for_entry(EntryPoint.DIRECT_URLS)
    assert [m for _, m in direct] == [
        SessionExecutionMode.APPLY_ONLY,
        SessionExecutionMode.VET_AND_APPLY,
    ]

    vet = outcome_options_for_entry(EntryPoint.VET_URLS)
    assert [m for _, m in vet] == [
        SessionExecutionMode.VET_AND_APPLY,
        SessionExecutionMode.VET_ONLY,
    ]

    search = outcome_options_for_entry(EntryPoint.SEARCH)
    assert [m for _, m in search] == [
        SessionExecutionMode.FULL_PIPELINE,
        SessionExecutionMode.DISCOVER_AND_VET,
        SessionExecutionMode.DISCOVER_ONLY,
    ]

    # Company pages ARE a search — same options.
    assert outcome_options_for_entry(EntryPoint.COMPANY_PAGES) == search


def test_menu_default_matches_legacy_meaning_for_every_entry() -> None:
    """TEETH (the lock): the menu's first option equals the legacy meaning.

    The menu default and the legacy label meaning are the same fact — pinned
    to stay equal rather than trusted to stay equal."""
    for entry in EntryPoint:
        menu_default = outcome_options_for_entry(entry)[0][1]
        assert menu_default is _LEGACY_ENTRY_TO_EXECUTION_MODE[entry], (
            f"{entry.name}: menu default {menu_default.value} != legacy "
            f"{_LEGACY_ENTRY_TO_EXECUTION_MODE[entry].value}"
        )


def test_app_py_passes_the_request_through() -> None:
    """TEETH: app.py hands the wizard's SessionRequest to the controller.

    Static pin — no Tk construction. Asserts the call site passes the
    request object, not a dict it rebuilt."""
    source = _APP_PY.read_text(encoding="utf-8")
    assert "SessionRequest" in source
    assert "initialize_session(request)" in source
    assert 'config_data' not in source, (
        "the old untyped config_data dict survived in app.py"
    )


# ─────────────────────────────────────────────────────────────────────────────
# GUARDS — the GUI's correct half must not regress
# ─────────────────────────────────────────────────────────────────────────────

def test_discovery_path_produces_what_it_produced_before() -> None:
    """GUARD: the discovery entry keeps its shape — keywords, location, cap,
    providers, and the full-pipeline default."""
    request = gui_wizard.build_session_request(
        entry=EntryPoint.SEARCH,
        execution_mode=SessionExecutionMode.FULL_PIPELINE,
        keywords_text="Python Dev, Backend Engineer",
        location="Austin",
        max_results=100,
        providers=("google", "bing", "indeed"),
    )
    assert request.entry is EntryPoint.SEARCH
    assert request.execution_mode is SessionExecutionMode.FULL_PIPELINE
    assert request.keywords == ("Python Dev", "Backend Engineer")
    assert request.location == "Austin"
    assert request.max_results == 100
    assert request.providers == ("google", "bing", "indeed")


def test_paste_links_path_produces_what_it_produced_before() -> None:
    """GUARD: the direct-links entry keeps its shape — urls tuple, apply-only."""
    request = gui_wizard.build_session_request(
        entry=EntryPoint.DIRECT_URLS,
        execution_mode=SessionExecutionMode.APPLY_ONLY,
        urls_text="https://jobs.example.com/1\nhttps://jobs.example.com/2\n",
    )
    assert request.entry is EntryPoint.DIRECT_URLS
    assert request.urls == (
        "https://jobs.example.com/1",
        "https://jobs.example.com/2",
    )
    assert request.execution_mode.includes_vetting is False
    assert request.execution_mode.includes_application is True


def test_empty_keywords_and_location_stay_empty_for_profile_fallback() -> None:
    """GUARD: empty criteria remain empty — the controller's profile
    fallback fills them, exactly as the old GUI's raw-input path did."""
    request = gui_wizard.build_session_request(
        entry=EntryPoint.SEARCH,
        execution_mode=SessionExecutionMode.FULL_PIPELINE,
        keywords_text="",
        location="",
    )
    assert request.keywords == ()
    assert request.location == ""


def test_providers_are_collected_only_on_the_search_path() -> None:
    """GUARD: pasted links do not search engines — providers are dropped
    for non-SEARCH entries, the same rule the CLI enforces by not asking."""
    request = gui_wizard.build_session_request(
        entry=EntryPoint.DIRECT_URLS,
        execution_mode=SessionExecutionMode.APPLY_ONLY,
        urls_text="https://example.com/j/1",
        providers=("bing",),
    )
    assert request.providers == ()


def test_urls_split_on_newlines_and_blank_lines_are_dropped() -> None:
    request = gui_wizard.build_session_request(
        entry=EntryPoint.VET_URLS,
        execution_mode=SessionExecutionMode.VET_AND_APPLY,
        urls_text="  https://a.example/1  \n\nhttps://b.example/2\n   ",
    )
    assert request.urls == ("https://a.example/1", "https://b.example/2")


def test_provider_vocabulary_matches_the_plan_field_default() -> None:
    """GUARD: the vocabulary has one source — SessionPlan's field default."""
    assert provider_vocabulary() == tuple(
        SessionPlan.model_fields["active_providers"].default
    )


def test_gui_wizard_module_imports_without_a_display() -> None:
    """GUARD: importing gui.wizard requires no display.

    This test's import of gui_wizard at module top IS the assertion — if
    importing the module constructed a window or required a display, the
    suite would fail at collection."""
    assert callable(gui_wizard.build_session_request)
    assert gui_wizard.SessionConfigWizard is not None

"""Pins for the GUI query-builder window and its parity with the CLI screen.

Every pin exercises the widget-free helpers in gui/search_window.py or the
service/port/controller vocabulary; none constructs Tk (the
test_gui_research_window.py precedent). The module under test imports tkinter,
which is safe on the CI baseline — the window itself is never instantiated.

Labels are honest: the window did not exist before this change, so the GUI
pins fail against the old tree by import error (coverage of a new surface).
The vocabulary-alignment and parity pins are TEETH for the rulings this change
makes — they fail if the two surfaces drift into two vocabularies, or if a
remembered platform query stops replaying identically.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

from auto_apply.adapters.primary.cli.search_builder_screen import (
    _build as cli_build,
    _remember as cli_remember,
)
from auto_apply.adapters.primary.gui import search_window as gw
from auto_apply.adapters.secondary.discovery.ats_registry import ATSRegistry
from auto_apply.adapters.secondary.discovery.search_surface_registry import (
    list_surface_names,
    load_surface,
)
from auto_apply.application.services.query_builder import QueryBuilderService
from auto_apply.domain.models.search_query import build_request, resolve_and_remember

_PORT_BUILDER_METHODS = (
    "query_surfaces",
    "query_platforms",
    "query_defaults",
    "build_query",
    "build_platform_query",
    "build_company_query",
    "resolve_query_target",
    "remember_query",
    "recent_queries",
    "clear_recent_queries",
)


def _service(recent_path: Path) -> QueryBuilderService:
    """A real builder service over a throwaway recent file."""
    return QueryBuilderService(
        profile=None,
        load_spec=load_surface,
        list_names=list_surface_names,
        ats_registry=ATSRegistry(),
        recent_path=recent_path,
    )


def test_service_port_and_controller_share_the_builder_vocabulary():
    """TEETH: the two surfaces must not drift into two vocabularies.

    The pre-session service, the port, and the controller all expose the
    identical builder method names. Mutation caught: renaming one side, or a
    port method the service does not implement."""
    from auto_apply.application.services.session_controller import SessionController
    from auto_apply.domain.ports.ui_port import UIPort

    for name in _PORT_BUILDER_METHODS:
        assert callable(getattr(QueryBuilderService, name, None)), f"service missing {name}"
        assert callable(getattr(UIPort, name, None)), f"port missing {name}"
        assert callable(getattr(SessionController, name, None)), f"controller missing {name}"


def test_gui_and_cli_build_identically(tmp_path):
    """TEETH (parity): the same platform search built through the GUI helper
    and through the CLI's build path produces the identical result."""
    service = _service(tmp_path / "recent.json")
    request = build_request(surface="google", terms="Software Engineer")
    gui_result = gw.build_for_target(service, request, platform="jobvite")
    cli_result = cli_build(service, request, "jobvite", None)
    assert gui_result == cli_result
    assert gui_result.bar_text == 'site:jobs.jobvite.com ("Software Engineer")'


def test_remembered_platform_query_replays_identically_across_surfaces(tmp_path):
    """TEETH (ruling 2): a platform query remembered from the GUI helper and
    one remembered from the CLI replay identically, resolved."""
    gui_service = _service(tmp_path / "gui_recent.json")
    cli_service = _service(tmp_path / "cli_recent.json")
    request = build_request(surface="google", terms="Software Engineer")
    resolve_and_remember(gui_service, request, platform="jobvite")
    cli_remember(cli_service, request, "jobvite", None)
    gui_recent = gui_service.recent_queries()
    cli_recent = cli_service.recent_queries()
    assert gui_recent == cli_recent
    assert gui_recent[0].site == "jobs.jobvite.com"
    assert (
        gui_service.build_query(gui_recent[0]).bar_text
        == cli_service.build_query(cli_recent[0]).bar_text
    )


def test_preview_never_remembers_and_explicit_actions_do():
    """TEETH: building a preview calls no write; an explicit action remembers
    exactly once, resolved. Mutation caught: remember on build, or a copy
    forgetting."""
    builder = MagicMock()
    request = build_request(surface="google", terms="x")
    gw.build_for_target(builder, request)
    builder.remember_query.assert_not_called()
    resolve_and_remember(builder, request)
    builder.resolve_query_target.assert_called_once()
    builder.remember_query.assert_called_once()


def test_offered_input_fields_hide_unsupported_operators(tmp_path):
    """TEETH: LinkedIn offers no any_of/exclude/intitle, so the GUI hides those
    fields; Google offers all three. Mutation caught: showing a field the
    surface cannot express, which would silently drop it on compose."""
    service = _service(tmp_path / "recent.json")
    offers = {o.name: o for o in service.query_surfaces()}
    google_fields = gw.offered_input_fields(offers["google"])
    assert {"any_of", "exclude", "intitle"} <= google_fields
    linkedin_fields = gw.offered_input_fields(offers["linkedin"])
    assert not ({"any_of", "exclude", "intitle"} & linkedin_fields)


def test_result_lines_render_refusals_and_never_blank(tmp_path):
    """TEETH: a refusal result renders its note lines, never a blank result."""
    service = _service(tmp_path / "recent.json")
    result = service.build_platform_query(
        "workday", build_request(surface="linkedin", terms="x")
    )
    lines = gw.result_lines(result, lambda key: key)
    assert lines
    assert any("site" in line.lower() for line in lines)


def test_window_is_offline_except_explicit_open():
    """GUARD (source): the window imports no network/browser library; the only
    outward call is webbrowser.open. Mutation caught: an added network import."""
    source = Path(gw.__file__).read_text(encoding="utf-8")
    banned = ("socket", "requests", "httpx", "selenium", "playwright", "urllib")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(banned), alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(banned), node.module
    assert "webbrowser.open" in source


def test_window_announces_and_closes_accessibly():
    """GUARD (source): Escape and the close button decline; outcomes are
    announced as text in a status label; the preview takes keyboard focus.
    What this pin CANNOT check headless: real Tab traversal and screen-reader
    behaviour — said plainly, mirroring the lifecycle window."""
    source = Path(gw.__file__).read_text(encoding="utf-8")
    assert '"<Escape>"' in source
    assert "WM_DELETE_WINDOW" in source
    assert "takefocus=True" in source
    assert "_status_var.set" in source


def test_gui_notes_follow_the_locale_and_never_crash__teeth(tmp_path):
    """TEETH: the GUI's translator path (window labels first, then the
    locale) renders a note with values in Spanish, without raising. Mutation
    caught: a translator contract that passes values the GUI's one-argument
    translator cannot take (it raised TypeError), or notes left in English
    because the GUI translator only knew the window's labels."""
    from auto_apply.adapters.primary.gui.strings import locale_text  # noqa: PLC0415
    from auto_apply.application.services.i18n import configure_locale  # noqa: PLC0415

    result = _service(tmp_path / "recent.json").build_query(
        build_request(surface="google", terms="Software Engineer", location="Seattle, WA")
    )
    labels = {"builder.result.bar": "Texto", "builder.result.link": "Enlace"}
    try:
        configure_locale(language="es")
        lines = gw.result_lines(result, lambda key: labels.get(key) or locale_text(key))
    finally:
        configure_locale(language="en")  # restore default for other tests
    text = "\n".join(lines)
    assert "no tiene lugar para una ubicación" in text
    assert "Seattle, WA" in text

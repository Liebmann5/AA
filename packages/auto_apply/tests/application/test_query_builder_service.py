"""Pins for the query-builder service (turn 1 of the query-builder chain).

Label honesty:
  GUARD (new surface) — the service did not exist before this change, so no
  pin could be run against the old tree. Mutation coverage is named per pin.
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from auto_apply.adapters.secondary.discovery.search_surface_registry import (
    SearchSurfaceError,
    list_surface_names,
    load_surface,
)
from auto_apply.application.services.query_builder import (
    DEFAULT_RECENT_PATH,
    QueryBuilderService,
)
from auto_apply.application.services.uninstall.engine import (
    DATA_ROOT_KNOWN_ENTRIES,
)
from auto_apply.domain.config import USER_DATA_DIR
from auto_apply.domain.models.search_query import QueryRequest


def _service(tmp_path: Path, profile=None) -> QueryBuilderService:
    return QueryBuilderService(
        profile=profile,
        load_spec=load_surface,
        list_names=list_surface_names,
        recent_path=tmp_path / "query_builder_recent.json",
    )


def test_defaults_offer_the_profiles_saved_titles(tmp_path, minimal_valid_profile):
    """GUARD. Mutation caught: reading a different field, or none."""
    service = _service(tmp_path, profile=minimal_valid_profile)
    assert service.defaults().titles == ("Software Engineer",)


def test_defaults_are_empty_without_a_profile(tmp_path):
    """GUARD. Mutation caught: inventing defaults."""
    assert _service(tmp_path).defaults().titles == ()


def test_building_a_query_never_writes_to_the_profile(tmp_path, minimal_valid_profile):
    """GUARD (nothing is written to the profile by building). Mutation
    caught: any mutation of the profile during build."""
    service = _service(tmp_path, profile=minimal_valid_profile)
    before = minimal_valid_profile.model_dump_json()
    service.build(QueryRequest(surface="google", phrases=("x",)))
    assert minimal_valid_profile.model_dump_json() == before


def test_unverified_and_uncomposable_capabilities_are_never_offered(tmp_path):
    """GUARD (the verification rule). Mutation caught: offering link:/cache:/
    inanchor:/udm, which the catalog records as unverified."""
    offers = {o.name: o for o in _service(tmp_path).surfaces()}
    google = offers["google"]
    operator_keys = {c.key for c in google.operators}
    assert {"site", "phrase", "exclude", "any_of", "intitle"} <= operator_keys
    assert "link" not in operator_keys
    assert "cache" not in operator_keys
    assert "inanchor" not in operator_keys
    option_keys = {c.key for c in google.options}
    assert "date" in option_keys
    assert "plain_web" not in option_keys


def test_build_leaves_the_recent_file_untouched(tmp_path):
    """GUARD (the preview rule): building writes nothing — turn 3's surfaces
    may rebuild a preview on every keystroke, so recording on build would
    store half-typed queries. Mutation caught: build() calling _record_recent."""
    service = _service(tmp_path)
    service.build(QueryRequest(surface="google", phrases=("x",)))
    service.build(QueryRequest(surface="google", phrases=("y",)))
    assert service.recent() == ()
    assert not (tmp_path / "query_builder_recent.json").exists()


def test_remember_caps_at_five(tmp_path):
    """GUARD. Mutation caught: the cap growing or being removed."""
    service = _service(tmp_path)
    for i in range(7):
        service.remember(QueryRequest(surface="google", phrases=(f"term-{i}",)))
    recent = service.recent()
    assert len(recent) == 5
    assert recent[0].phrases == ("term-6",)


def test_remember_deduplicates(tmp_path):
    """GUARD. Mutation caught: duplicates accumulating."""
    service = _service(tmp_path)
    service.remember(QueryRequest(surface="google", phrases=("same",)))
    service.remember(QueryRequest(surface="google", phrases=("same",)))
    assert len(service.recent()) == 1


def test_clear_recent_removes_the_file(tmp_path):
    """GUARD. Mutation caught: leaving the file (empty or not) behind."""
    service = _service(tmp_path)
    service.remember(QueryRequest(surface="google", phrases=("x",)))
    service.clear_recent()
    assert service.recent() == ()
    assert not (tmp_path / "query_builder_recent.json").exists()


def test_the_recent_file_lives_in_the_data_home_and_uninstall_knows_it():
    """GUARD (ruling 4): the file is in the data home and in the
    uninstaller's known entries. Mutation caught: moving the file or dropping
    the uninstall entry."""
    assert DEFAULT_RECENT_PATH.parent == USER_DATA_DIR
    assert DEFAULT_RECENT_PATH.name in DATA_ROOT_KNOWN_ENTRIES


def test_build_returns_bar_url_and_plain_notes(tmp_path):
    """GUARD. Mutation caught: the service dropping the notes or a form."""
    result = _service(tmp_path).build(
        QueryRequest(
            surface="google",
            phrases=("Software Engineer",),
            options=(("date", "day"),),
        )
    )
    assert result.bar_text == '("Software Engineer")'
    assert result.url is not None and "tbs=qdr%3Ad" in result.url
    assert result.notes


def test_an_unknown_surface_fails_loudly(tmp_path):
    """GUARD. Mutation caught: a quiet empty result for an unknown surface."""
    with pytest.raises(SearchSurfaceError):
        _service(tmp_path).build(QueryRequest(surface="nonsense", phrases=("x",)))


def test_the_builder_modules_import_no_network_browser_or_research_code():
    """GUARD (structural no-network / no-research pin). Mutation caught:
    any of the builder modules importing a network, browser or research
    module."""
    root = Path(__file__).resolve().parents[2] / "src" / "auto_apply"
    modules = [
        root / "domain" / "models" / "search_surface.py",
        root / "domain" / "models" / "search_query.py",
        root / "domain" / "services" / "query_composer.py",
        root / "application" / "services" / "query_builder.py",
        root / "adapters" / "secondary" / "discovery" / "search_surface_registry.py",
    ]
    banned = ("socket", "requests", "httpx", "webbrowser", "selenium", "playwright", "urllib.request")
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(banned), f"{path.name}: {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(banned), f"{path.name}: {node.module}"
                assert ".browser" not in node.module, f"{path.name}: {node.module}"
                assert ".network" not in node.module, f"{path.name}: {node.module}"
                assert "research" not in node.module, f"{path.name}: {node.module}"


def test_the_session_controller_exposes_the_builder():
    """GUARD (turn-3 seam): the controller holds the injected service.
    Mutation caught: dropping the dependency or the property."""
    from auto_apply.application.services.session_controller import SessionController

    controller = SessionController(
        registry=MagicMock(),
        db=MagicMock(),
        orchestrator=MagicMock(),
        query_builder="SENTINEL",
    )
    assert controller.query_builder == "SENTINEL"

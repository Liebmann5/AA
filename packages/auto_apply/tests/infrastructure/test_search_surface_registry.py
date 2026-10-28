"""Pins for the search-surface catalog loader.

Label honesty:
  GUARD (new surface) — the catalog did not exist before this change, so no
  pin could be run against the old tree. Mutation coverage is named per pin.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from auto_apply.adapters.secondary.discovery.search_surface_registry import (
    SearchSurfaceError,
    list_surface_names,
    load_surface,
    load_surface_bundled,
)
from auto_apply.adapters.secondary.discovery.strategies.selector_loader import (
    SelectorLoader,
)
from auto_apply.domain.models.search_surface import VerificationStatus
from auto_apply.domain.services.query_composer import EXPRESSIBLE_OPERATORS

_ALL_SURFACES = ["google", "bing", "indeed", "duckduckgo", "linkedin"]

_MINI = """name: mini
display_name: Mini
kind: engine
homepage: "https://mini.example"
text_query:
  or_token: "OR"
urls:
  web:
    base: "https://mini.example/s"
    parameters:
      - {name: q, source: query}
default_url: web
operators:
  - name: phrase
    label: "Exact"
    explanation: "Exact words."
    syntax: '"{value}"'
    status: vendor
"""


def _write(directory: Path, name: str, text: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.surface.yaml").write_text(text, encoding="utf-8")


@pytest.mark.parametrize("name", _ALL_SURFACES)
def test_every_bundled_surface_loads_and_validates(name):
    """GUARD. Mutation caught: a malformed or incomplete bundled entry."""
    spec = load_surface(name)
    assert spec.name == name
    assert spec.display_name
    assert spec.default_url in spec.urls


def test_a_missing_surface_fails_loudly():
    """GUARD. Mutation caught: returning an empty/default spec instead."""
    with pytest.raises(SearchSurfaceError):
        load_surface("does-not-exist")


def test_an_unknown_field_in_bundled_data_fails_loudly(tmp_path):
    """GUARD (no hidden fallback). Mutation caught: ignoring unknown keys."""
    bundled = tmp_path / "bundled"
    _write(bundled, "mini", _MINI + "bogus_key: true\n")
    loader = SelectorLoader(bundled_dir=bundled, user_override_dir=tmp_path / "user")
    with pytest.raises(SearchSurfaceError):
        load_surface("mini", loader=loader)


def test_malformed_bundled_yaml_fails_loudly(tmp_path):
    """GUARD. Mutation caught: swallowing the parse error."""
    bundled = tmp_path / "bundled"
    _write(bundled, "mini", "{not: valid: yaml: [")
    loader = SelectorLoader(bundled_dir=bundled, user_override_dir=tmp_path / "user")
    with pytest.raises(SearchSurfaceError):
        load_surface("mini", loader=loader)


def test_a_malformed_user_override_falls_back_to_bundled(tmp_path, caplog):
    """GUARD (user-data precedent): a bad user override warns and is ignored.
    Mutation caught: letting the bad override break loading, or silently
    applying it."""
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    _write(bundled, "mini", _MINI)
    _write(user, "mini", "{not: valid: yaml: [")
    loader = SelectorLoader(bundled_dir=bundled, user_override_dir=user)
    with caplog.at_level("WARNING"):
        spec = load_surface("mini", loader=loader)
    assert spec.name == "mini"


def test_a_user_override_prepends_operators(tmp_path):
    """GUARD (engines' merge semantics reused). Mutation caught: the user
    entry landing anywhere but first, or replacing the list."""
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    _write(bundled, "mini", _MINI)
    _write(
        user,
        "mini",
        "operators:\n"
        "  - name: custom_op\n"
        '    label: "Custom"\n'
        '    explanation: "A custom operator."\n'
        '    syntax: "custom:{value}"\n'
        "    status: vendor\n",
    )
    loader = SelectorLoader(bundled_dir=bundled, user_override_dir=user)
    spec = load_surface("mini", loader=loader)
    assert spec.operators[0].name == "custom_op"
    assert spec.operators[-1].name == "phrase"


def test_a_measured_entry_without_a_date_fails_loudly(tmp_path):
    """GUARD: a measurement without a date is a claim, not a measurement.
    Mutation caught: letting status=measured slide without verified_on."""
    bundled = tmp_path / "bundled"
    _write(
        bundled,
        "mini",
        _MINI.replace("status: vendor", "status: measured"),
    )
    loader = SelectorLoader(bundled_dir=bundled, user_override_dir=tmp_path / "user")
    with pytest.raises(SearchSurfaceError):
        load_surface("mini", loader=loader)


@pytest.mark.parametrize("name", _ALL_SURFACES)
def test_every_entry_has_a_status_and_measured_entries_have_a_date(name):
    """GUARD. Mutation caught: an entry without a status, or measured
    without verified_on, getting into bundled data."""
    spec = load_surface(name)
    for entry in (*spec.operators, *spec.url_options):
        assert entry.status in set(VerificationStatus)
        if entry.status is VerificationStatus.MEASURED:
            assert entry.verified_on
            assert entry.source


@pytest.mark.parametrize("name", _ALL_SURFACES)
def test_template_references_resolve(name):
    """GUARD. Mutation caught: default_url/automation_url/date_parameter
    pointing at nothing."""
    spec = load_surface(name)
    assert spec.default_url in spec.urls
    if spec.automation_url is not None:
        template = spec.urls[spec.automation_url]
        if template.date_parameter is not None:
            assert any(
                o.name == template.date_parameter and o.option == "date"
                for o in spec.url_options
            )


@pytest.mark.parametrize("name", ["google", "bing", "indeed"])
def test_automation_date_codes_cover_every_instruction_range(name):
    """GUARD (byte identity depends on it). Mutation caught: a date_range
    value SearchInstruction allows missing from the catalog."""
    spec = load_surface(name)
    template = spec.urls[spec.automation_url]
    option = next(
        o
        for o in spec.url_options
        if o.name == template.date_parameter and o.option == "date"
    )
    assert {"hour", "day", "week", "month", "year"} <= set(option.codes)


@pytest.mark.parametrize("name", _ALL_SURFACES)
def test_offered_operators_are_composable(name):
    """GUARD (offered can never outrun composable). Mutation caught: an
    offered operator the composer cannot emit."""
    spec = load_surface(name)
    offered = {
        VerificationStatus.VENDOR,
        VerificationStatus.MEASURED,
        VerificationStatus.THIRD_PARTY,
    }
    for op in spec.operators:
        if op.composable and op.status in offered:
            assert op.name in EXPRESSIBLE_OPERATORS


def test_list_surface_names_covers_the_five():
    """GUARD. Mutation caught: a bundled file never being listed."""
    names = list_surface_names()
    for name in _ALL_SURFACES:
        assert name in names


def test_automation_reads_the_bundled_catalog_only(tmp_path):
    """GUARD (review ruling): a user override must never change what
    automation sends. load_surface_bundled ignores the override even when
    the merged load would apply it. Mutation caught: the automation read
    consulting the user override directory."""
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    _write(bundled, "mini", _MINI)
    _write(user, "mini", _MINI.replace('"https://mini.example/s"', '"https://evil.example/s"'))
    loader = SelectorLoader(bundled_dir=bundled, user_override_dir=user)
    merged = load_surface("mini", loader=loader)
    assert merged.urls["web"].base == "https://evil.example/s"
    bundled_spec = load_surface_bundled("mini", loader=loader)
    assert bundled_spec.urls["web"].base == "https://mini.example/s"

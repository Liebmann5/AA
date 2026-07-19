"""Enforcement test: the inline fallback must stay identical to runtime_defaults.yaml.

Root cause this guards against
------------------------------
``registry._RUNTIME_DEFAULTS_FALLBACK`` is a hand-maintained duplicate of
``resources/runtime_defaults.yaml``.  It is returned verbatim whenever the YAML
cannot be loaded (missing package data in a frozen/PyInstaller build, unreadable
file, malformed YAML).  If the two drift, AA silently runs on *different*
configuration in fallback mode than in normal mode — which breaks the
reproducibility guarantee the research pipeline depends on, and does so with no
warning to the user.

A drift of this exact kind was live in the tree: the YAML carried nine keys the
fallback had never been updated with (four flat timing values plus the
``vetting``/``discovery``/``applications``/``browser``/``gpt4all`` sections), so
fallback mode silently dropped them.

These tests fail loudly the moment anyone edits one source without the other.
"""

from __future__ import annotations

from typing import Any

import pytest

yaml = pytest.importorskip("yaml")

from auto_apply.infrastructure.registry import (  # noqa: E402
    _DEFAULTS_YAML,
    _RUNTIME_DEFAULTS_FALLBACK,
)


@pytest.fixture(scope="module")
def yaml_defaults() -> dict[str, Any]:
    assert (
        _DEFAULTS_YAML.is_file()
    ), f"packaged runtime_defaults.yaml missing at {_DEFAULTS_YAML}"
    with _DEFAULTS_YAML.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(
        data, dict
    ), "runtime_defaults.yaml top-level value is not a mapping"
    return data


def test_fallback_has_no_missing_keys(yaml_defaults: dict[str, Any]) -> None:
    """Every YAML key must exist in the fallback, or it vanishes in fallback mode."""
    missing = sorted(set(yaml_defaults) - set(_RUNTIME_DEFAULTS_FALLBACK))
    assert not missing, (
        "runtime_defaults.yaml defines keys absent from _RUNTIME_DEFAULTS_FALLBACK. "
        f"These are silently lost when the YAML cannot be loaded: {missing}"
    )


def test_fallback_has_no_extra_keys(yaml_defaults: dict[str, Any]) -> None:
    """The fallback must not invent keys the YAML does not document."""
    extra = sorted(set(_RUNTIME_DEFAULTS_FALLBACK) - set(yaml_defaults))
    assert not extra, (
        "_RUNTIME_DEFAULTS_FALLBACK defines keys absent from runtime_defaults.yaml, "
        f"so they are undocumented and unreachable in normal mode: {extra}"
    )


def test_fallback_values_match_yaml(yaml_defaults: dict[str, Any]) -> None:
    """Identical keys must carry identical values — including nested sections."""
    drift = {
        k: {"yaml": yaml_defaults[k], "fallback": _RUNTIME_DEFAULTS_FALLBACK[k]}
        for k in set(yaml_defaults) & set(_RUNTIME_DEFAULTS_FALLBACK)
        if yaml_defaults[k] != _RUNTIME_DEFAULTS_FALLBACK[k]
    }
    assert not drift, (
        "_RUNTIME_DEFAULTS_FALLBACK has drifted from runtime_defaults.yaml. "
        f"Fallback mode would silently use different values: {drift}"
    )

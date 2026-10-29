"""Pins for the automation platform vocabulary (QueryBuilderService).

Label honesty: the vocabulary is new surface. Each pin names the mutation it
catches. The structural pin (no platform list in an adapter) is the one the
architecture depends on.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from auto_apply.adapters.primary.cli.wizard import CLIWizard
from auto_apply.adapters.primary.gui.wizard import SessionConfigWizard
from auto_apply.adapters.secondary.discovery.ats_registry import ATSRegistry
from auto_apply.application.services.query_builder import QueryBuilderService

_PKG_ROOT = Path(__file__).resolve().parents[2]
_CLI_WIZARD = _PKG_ROOT / "src" / "auto_apply" / "adapters" / "primary" / "cli" / "wizard.py"
_GUI_WIZARD = _PKG_ROOT / "src" / "auto_apply" / "adapters" / "primary" / "gui" / "wizard.py"


def _service(registry) -> QueryBuilderService:
    return QueryBuilderService(
        profile=None,
        load_spec=None,
        list_names=None,
        ats_registry=registry,
        recent_path=Path("/nonexistent/recent.json"),
    )


def test_vocabulary_covers_every_registered_platform() -> None:
    """TEETH: the picker and the registry can never drift.

    Mutation caught: a filtered or hardcoded subset."""
    registry = ATSRegistry()
    offers = _service(registry).automation_platform_vocabulary()
    assert {o.name for o in offers} == {
        d.name for d in registry.all_descriptors() if d.hosts
    }
    assert len(offers) >= 30


def test_eligibility_matches_the_automation_floor_exactly() -> None:
    """TEETH: only measured/vendor are eligible — the rule, not today's data.

    Mutation caught: widening the floor (e.g. admitting third_party), or
    inverting it."""
    for offer in _service(ATSRegistry()).automation_platform_vocabulary():
        assert offer.eligible == (offer.status in {"measured", "vendor"}), offer.name


def test_ineligible_platforms_carry_a_reason() -> None:
    """TEETH: no surface ever has to invent a refusal reason.

    Mutation caught: an empty reason on an ineligible platform."""
    offers = _service(ATSRegistry()).automation_platform_vocabulary()
    ineligible = [o for o in offers if not o.eligible]
    assert ineligible, "the registry currently has unverified platforms"
    assert all(o.reason for o in ineligible)


def test_vocabulary_degrades_empty_without_a_registry() -> None:
    """TEETH: no registry → empty vocabulary, never an exception.

    Mutation caught: raising on a missing registry."""
    assert _service(None).automation_platform_vocabulary() == ()


@pytest.mark.parametrize("wizard_path", [_CLI_WIZARD, _GUI_WIZARD])
def test_no_hardcoded_platform_names_in_wizards(wizard_path) -> None:
    """TEETH (structural): no adapter holds its own platform list.

    Mutation caught: any registry platform name appearing as a literal in a
    wizard."""
    source = wizard_path.read_text(encoding="utf-8")
    names = {d.name for d in ATSRegistry().all_descriptors()}
    offenders = [
        name
        for name in names
        if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", source)
    ]
    assert not offenders, (
        f"{wizard_path.name} hardcodes platform names: {offenders} — "
        "the vocabulary must come from the registry through the service"
    )


def test_both_wizards_take_the_vocabulary_parameter() -> None:
    """TEETH: both surfaces receive the vocabulary, neither computes it.

    Mutation caught: a wizard dropping the parameter."""
    assert "platforms_vocabulary" in inspect.signature(CLIWizard.__init__).parameters
    assert (
        "platforms_vocabulary"
        in inspect.signature(SessionConfigWizard.__init__).parameters
    )

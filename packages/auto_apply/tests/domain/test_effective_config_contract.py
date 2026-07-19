"""Guardrail: the typed effective-config must never silently default.

This is the structural replacement for the diagnostic pins that hardcoded a
mirror of ``SessionPlan.from_config`` / ``BehaviorParameters.from_config``'s
broken nested reads. Those pins could only enumerate a fixed list of keys. This
one holds for *every* field at once, by construction:

  * every field resolves from the real merged config (completeness), and
  * a missing key raises at construction rather than falling through to a
    hardcoded default (the exact defect class the whole config audit chased).

As consumers migrate onto EffectiveConfig, a mistyped or renamed key becomes an
import-time / construction-time failure instead of a value that is silently
wrong for years.
"""

from __future__ import annotations

import pytest

yaml = pytest.importorskip("yaml")

from auto_apply.domain.models.effective_config import EffectiveConfig  # noqa: E402
from auto_apply.infrastructure.registry import _RUNTIME_DEFAULTS  # noqa: E402


def test_every_field_resolves_from_the_real_merged_config() -> None:
    """No EffectiveConfig field may fall back to a default the config can't set."""
    merged = dict(_RUNTIME_DEFAULTS)
    unmapped = [name for name in EffectiveConfig.model_fields if name not in merged]
    assert not unmapped, (
        f"EffectiveConfig fields with no key in the merged runtime config: "
        f"{unmapped}. Each would take a hardcoded default no user, admin or "
        f"clamp could ever change — the silent-default defect this object exists "
        f"to make impossible."
    )
    # And it actually builds from that config.
    EffectiveConfig.from_mapping(merged)


def test_missing_key_raises_instead_of_defaulting() -> None:
    """Drop a required key: construction must fail loudly, not default."""
    from pydantic import ValidationError  # noqa: PLC0415

    broken = dict(_RUNTIME_DEFAULTS)
    broken.pop("max_applications_per_session")
    with pytest.raises(ValidationError):
        EffectiveConfig.from_mapping(broken)


def test_effective_config_is_frozen() -> None:
    """Resolved once, shared safely: the object must be immutable."""
    from pydantic import ValidationError  # noqa: PLC0415

    ec = EffectiveConfig.from_mapping(dict(_RUNTIME_DEFAULTS))
    with pytest.raises(ValidationError):
        ec.max_applications_per_session = 999  # type: ignore[misc]

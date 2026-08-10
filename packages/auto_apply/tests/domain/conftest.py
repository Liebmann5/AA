"""Domain-layer shared fixtures.

NodeMap is defined here so that test modules in tests/domain/ can do
``from conftest import NodeMap`` without relying on sys.path tricks that
break when pytest has already cached the domain-level conftest module.
"""

import pytest

from auto_apply.domain.models.math_dom import DOMNode, Geometry


class NodeMap:
    """Identity-keyed mapping usable wherever ``dict[DOMNode, ...]`` is expected.

    Uses ``id(node)`` internally so unhashable DOMNode objects can serve
    as logical keys without triggering ``TypeError: unhashable type: 'dict'``.
    """

    def __init__(self, pairs=()):
        self._store: dict[int, object] = {}
        for k, v in pairs:
            self._store[id(k)] = v

    def get(self, key, default=None):
        return self._store.get(id(key), default)

    def __getitem__(self, key):
        return self._store[id(key)]

    def __setitem__(self, key, value):
        self._store[id(key)] = value

    def __contains__(self, key):
        return id(key) in self._store


# ─────────────────────────────────────────────────────────────────────────────
# ThrottlingFilter construction
# ─────────────────────────────────────────────────────────────────────────────
#
# ThrottlingFilter takes three REQUIRED keyword-only limits. That is deliberate
# (test_cooldown_failsafe: an omitted limit must be a construction error, never
# a silent permissive default) but it means every test that builds one by hand
# breaks the next time a limit is added — which is exactly what happened when
# daily_application_limit and max_applications_per_company landed and three
# cooldown tests started failing on TypeError instead of on cooldown logic.
#
# One builder, so the next limit is a one-line change here. The fail-safe
# property itself stays pinned in test_cooldown_failsafe, not here.

_COMPOSITION_ROOT_LIMITS = {
    # The values composition_root.py:226-243 injects, via
    # registry.get_effective_config / get_effective_settings.
    "cooldown_days_default": 180,
    "daily_application_limit": 50,
    "max_applications_per_company": 3,
}


@pytest.fixture
def make_throttling_filter():
    """Factory fixture: build a ThrottlingFilter with production limits.

    A fixture rather than an importable helper because the suite runs with
    ``--import-mode=importlib`` (pyproject ``addopts``), under which
    ``from conftest import ...`` does not resolve.
    """
    return _build_throttling_filter


def _build_throttling_filter(*, profile=None, job_repo=None, **overrides):
    """Build a ThrottlingFilter with production limits, overridable per test."""
    from unittest.mock import MagicMock  # noqa: PLC0415

    from auto_apply.domain.models.profile import ApplicationPreferences  # noqa: PLC0415
    from auto_apply.domain.vetting.throttling_filter import (  # noqa: PLC0415
        ThrottlingFilter,
    )

    unknown = set(overrides) - set(_COMPOSITION_ROOT_LIMITS)
    if unknown:
        raise TypeError(
            f"make_throttling_filter got unexpected limit(s) {sorted(unknown)}. "
            f"Known limits: {sorted(_COMPOSITION_ROOT_LIMITS)}. If "
            f"ThrottlingFilter gained a new one, add it to "
            f"_COMPOSITION_ROOT_LIMITS with the value composition_root injects."
        )

    if profile is None:
        profile = MagicMock()
        profile.application_preferences = ApplicationPreferences()
    if job_repo is None:
        job_repo = MagicMock()
        job_repo.get_company_mandate_cooldown.return_value = 0

    return ThrottlingFilter(
        profile, job_repo, **{**_COMPOSITION_ROOT_LIMITS, **overrides}
    )

"""A missing cooldown must fail safe, not fail open.

Why this exists
---------------
``test_cooldown_authority.py`` correctly forced the three fixes it pinned: the
``max(0, None, 180)`` crash, the inverted hierarchy, and the hardcoded
``DEFAULT_COOLDOWN_DAYS``. All three went green.

It also let a regression through, because the tests construct
``ThrottlingFilter(profile, job_repo)`` and assert only on the *shape* of the
result:

    assert isinstance(cooldown, int)   # 0 is an int

The class constant that was removed was a **fail-safe**::

    DEFAULT_COOLDOWN_DAYS: int = 180

What replaced it is a **fail-open**::

    def __init__(self, profile, job_repo, cooldown_days_default: int = 0)

Any construction that does not inject the value now yields a zero-day cooldown —
AA re-applies to the same company immediately, up to
``MAX_APPLICATIONS_PER_COMPANY``, within a single session. ``composition_root``
does inject it, so production is correct today. The defect is that the safe
behaviour now depends on every future call site remembering, and the failure is
silent: no exception, no log, just a cooldown of zero.

This is the same shape as every other defect in this audit — ``getattr(x, "y",
d)``, ``dict.get("y", d)``, a clamp written to a key nobody reads. A default
value standing in for a missing contract. The fix moved the pattern; it did not
remove it.

The safe form has no default::

    def __init__(self, profile, job_repo, *, cooldown_days_default: int)

A missing injection then fails at construction, loudly, on the first run — which
is what the class constant achieved by accident and what these tests are here to
preserve on purpose.

``registry.get_effective_config(key)`` has the same shape: its ``default`` is
``None``. ``composition_root`` calls it without one, so a missing key yields
``cooldown_days_default=None`` and the ``TypeError`` returns one frame further
out. The parity test currently guarantees the key exists in both sources — that
guarantee is doing more work than it looks like.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from auto_apply.domain.models.profile import ApplicationPreferences
from auto_apply.domain.vetting.throttling_filter import ThrottlingFilter


def _filter(**kwargs) -> ThrottlingFilter:
    profile = MagicMock()
    profile.application_preferences = ApplicationPreferences()  # cooldown_days=None
    job_repo = MagicMock()
    job_repo.get_company_mandate_cooldown.return_value = 0  # no mandate recorded
    return ThrottlingFilter(profile, job_repo, **kwargs)


def test_cooldown_default_has_no_fail_open_fallback() -> None:
    """The injected system default must be required, not optional."""
    sig = inspect.signature(ThrottlingFilter.__init__)
    param = sig.parameters.get("cooldown_days_default")
    assert param is not None, (
        "ThrottlingFilter no longer accepts cooldown_days_default. The system "
        "default tier has to come from somewhere."
    )
    assert param.default is inspect.Parameter.empty, (
        f"cooldown_days_default defaults to {param.default!r}. A caller that "
        f"forgets to inject it gets a zero-day cooldown and AA re-applies to the "
        f"same company immediately — silently. The removed class constant "
        f"(DEFAULT_COOLDOWN_DAYS = 180) failed safe; an optional parameter fails "
        f"open. Make it required so a missing injection raises at construction."
    )


def test_no_mandate_and_no_user_preference_is_not_zero_days() -> None:
    """The behaviour the class constant used to guarantee."""
    filt = _filter(cooldown_days_default=180)
    assert filt._calculate_cooldown_authority("Acme") == 180

    # And the shape assertion that let the regression through:
    # isinstance(0, int) is True, so `assert isinstance(cooldown, int)` cannot
    # distinguish 180 from a zero-day cooldown. Assert the value.
    assert filt._calculate_cooldown_authority("Acme") != 0, (
        "A profile with no company mandate and no user preference resolved to a "
        "zero-day cooldown."
    )

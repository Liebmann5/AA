"""The company cooldown must not crash, and must respect the hierarchy it documents.

Three defects on one code path
------------------------------
``ThrottlingFilter.filter()`` is reached on every vetted job. Everything below
``get_last_applied_date()`` only executes when the user has prior history with
that company, which is why an empty test database never sees any of it.

**1. It crashes.**

``_calculate_cooldown_authority()`` does::

    user_pref = getattr(
        getattr(self._profile, "application_preferences", None),
        "cooldown_days",
        0,
    )
    return max(company_mandate, user_pref, self.DEFAULT_COOLDOWN_DAYS)

``ApplicationPreferences.cooldown_days`` defaults to ``None``. ``getattr``'s
``0`` fallback only fires when the *attribute is missing* — the attribute exists
and holds ``None``, so ``user_pref`` is ``None`` and ``max(0, None, 180)``
raises ``TypeError: '>' not supported between instances of 'NoneType' and 'int'``.

Every profile that has not explicitly set ``cooldown_days`` — which is the
default — crashes here on the second application to any company.

This fires *before* the naive/aware datetime subtraction on the next line, so it
is the first of two crashes stacked on the same three lines.

**2. The documented hierarchy is inverted.**

The docstring promises::

    Hierarchy of Authority:
    1. Company Mandate (scraped from "Thank You" page text).
    2. User Preference (profile settings).
    3. System Default (180 days).

``max()`` gives the opposite. The system default is a 180-day *floor*, so tiers
1 and 2 can only ever lengthen the wait, never shorten it:

    company says 30d, user wants 7d  -> max(30, 7, 180)  = 180
    company says 0d,  user wants 14d -> max(0, 14, 180)  = 180

A company that explicitly invites reapplication after 30 days is overruled. A
user who asks for a 7-day cooldown is overruled. Only a company demanding *more*
than 180 days is honoured — which is the one case where the "authority" of the
company was never in question.

**3. It makes the per-company cap unreachable.**

``MAX_APPLICATIONS_PER_COMPANY = 3`` gates on a count, but the cooldown gate
blocks any second application to the same company for at least 180 days. Reaching
a count of 3 requires 360+ days. In practice AA applies to **one job per company
per six months** — so a user who finds three good roles at one company applies to
exactly one of them, and the other two are silently rejected as "Cooldown Active"
for half a year.

For a tool whose purpose is helping people get hired, that is a product defect,
not a tuning issue.
"""

from __future__ import annotations

import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "auto_apply"


def test_cooldown_authority_survives_a_default_profile() -> None:
    """The default profile must not crash the cooldown calculation."""
    from unittest.mock import MagicMock  # noqa: PLC0415

    from auto_apply.domain.models.profile import ApplicationPreferences  # noqa: PLC0415
    from auto_apply.domain.vetting.throttling_filter import (  # noqa: PLC0415
        ThrottlingFilter,
    )

    profile = MagicMock()
    profile.application_preferences = ApplicationPreferences()  # cooldown_days=None
    job_repo = MagicMock()
    job_repo.get_company_mandate_cooldown.return_value = 0

    # cooldown_days_default is required and keyword-only: test_cooldown_failsafe
    # forbids an optional default, because a caller that forgets one gets a
    # zero-day cooldown silently. 180 is the value composition_root injects.
    filt = ThrottlingFilter(profile, job_repo, cooldown_days_default=180)
    try:
        cooldown = filt._calculate_cooldown_authority("Acme")
    except TypeError as exc:
        pytest.fail(
            f"_calculate_cooldown_authority crashed on a default profile: {exc}. "
            f"ApplicationPreferences.cooldown_days defaults to None, and "
            f"getattr(obj, 'cooldown_days', 0) returns None rather than 0 because "
            f"the attribute exists. max(0, None, 180) then raises. This fires on "
            f"the second application to any company."
        )
    assert isinstance(cooldown, int)


def test_company_mandate_can_shorten_the_cooldown() -> None:
    """The docstring says the company mandate is tier-1 authority."""
    from unittest.mock import MagicMock  # noqa: PLC0415

    from auto_apply.domain.models.profile import ApplicationPreferences  # noqa: PLC0415
    from auto_apply.domain.vetting.throttling_filter import (  # noqa: PLC0415
        ThrottlingFilter,
    )

    profile = MagicMock()
    profile.application_preferences = ApplicationPreferences(cooldown_days=7)
    job_repo = MagicMock()
    job_repo.get_company_mandate_cooldown.return_value = 30  # "reapply after 30 days"

    filt = ThrottlingFilter(profile, job_repo, cooldown_days_default=180)
    cooldown = filt._calculate_cooldown_authority("Acme")

    assert cooldown <= 30, (
        f"Company mandated a 30-day cooldown and the user asked for 7, but AA "
        f"resolved {cooldown}. max(company, user, DEFAULT_COOLDOWN_DAYS) makes the "
        f"180-day system default a floor, so the documented 'Hierarchy of "
        f"Authority' is inverted: tiers 1 and 2 can only lengthen the wait."
    )


def test_cooldown_default_is_configurable() -> None:
    """A hardcoded 180-day floor cannot be tuned by config or policy."""
    src = (SRC / "domain" / "vetting" / "throttling_filter.py").read_text(
        encoding="utf-8"
    )
    assert "DEFAULT_COOLDOWN_DAYS: int = 180" not in src, (
        "ThrottlingFilter.DEFAULT_COOLDOWN_DAYS is a hardcoded class constant. "
        "Combined with max(), it is a 180-day floor no user, admin policy or "
        "config value can lower — and it makes MAX_APPLICATIONS_PER_COMPANY=3 "
        "unreachable in under 360 days."
    )

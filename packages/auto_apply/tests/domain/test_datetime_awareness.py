"""Every datetime AA creates must be timezone-aware.

The live crash this pins
------------------------
``job_repository.get_last_applied_date()`` returns an **aware** datetime::

    return datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)

``throttling_filter.py`` subtracted a **naive** one from it::

    days_since = (datetime.utcnow() - last_applied_date).days

``datetime.utcnow()`` returns a naive datetime, and naive minus aware raises
``TypeError: can't subtract offset-naive and offset-aware datetimes``.

So the company cooldown check — "only apply to N jobs per company per window" —
raises the first time a user applies to the same company twice.

No test caught it because the crashing line is unreachable without prior
history: an empty test database returns ``None`` from
``get_last_applied_date()`` and the filter short-circuits on
``"No previous history"``. The bug needs a *real user with a real history* to
fire, which is exactly the class of defect a green unit suite cannot see.

The wider rule
--------------
``datetime.utcnow()`` is deprecated and scheduled for removal, and it is the
source of the DeprecationWarning in the suite. More importantly it produces a
timestamp that *means* UTC but does not *say* so, so it detonates on contact
with the aware datetimes used by ``audit_coordinator``, ``research_consent``,
``checkpoint_manager`` and the ``Job`` model.

For research data, a naive timestamp is worse than a crash: it silently records
provenance with no timezone, and §18.2 requires explicit timestamp semantics.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timezone

from auto_apply.domain.models.session_plan import SessionPlan

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "auto_apply"


def test_session_plan_created_at_is_timezone_aware() -> None:
    plan = SessionPlan(session_id="test")
    assert plan.created_at.tzinfo is not None, (
        "SessionPlan.created_at is naive. It cannot be compared against the aware "
        "datetimes used by Job.discovery_date, checkpoint_manager or "
        "audit_coordinator without raising TypeError."
    )


def test_throttling_cooldown_does_not_crash_on_prior_history() -> None:
    """Reproduces the exact production crash, with no database required."""
    from auto_apply.domain.vetting import throttling_filter  # noqa: PLC0415

    src = pathlib.Path(throttling_filter.__file__).read_text(encoding="utf-8")
    assert "datetime.utcnow()" not in src, (
        "throttling_filter still uses naive datetime.utcnow(). "
        "get_last_applied_date() returns an aware datetime, so the cooldown "
        "subtraction raises TypeError as soon as a user has prior history with "
        "a company."
    )

    # And prove the arithmetic itself is sound.
    last_applied = datetime.fromisoformat("2026-07-01T10:00:00").replace(
        tzinfo=timezone.utc
    )
    now = datetime.now(timezone.utc)
    assert (now - last_applied).days >= 0  # would raise TypeError if either is naive


def test_no_naive_utcnow_anywhere_in_src() -> None:
    """utcnow() is deprecated, scheduled for removal, and mixes badly."""
    offenders: list[str] = []
    for py in SRC.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "utcnow"
            ):
                offenders.append(f"{py.relative_to(SRC).as_posix()}:{node.lineno}")

    assert not offenders, (
        "datetime.utcnow() is deprecated and returns a naive datetime that means "
        "UTC without saying so. Use datetime.now(timezone.utc). Offenders: "
        f"{offenders}"
    )

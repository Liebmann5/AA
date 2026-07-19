"""AA must stop applying when it hits the limit the user was promised.

The finding
-----------
``max_applications_per_session`` is defined, defaulted, merged, clamped and
displayed in twelve places:

  * ``registry.py:100``            — fallback default of 50
  * ``registry.py:408``            — low-resource clamp to ``min(x, 25)``
  * ``registry.py:693``            — fed into ``ResolvedCapabilityProfile``
  * ``capability_profile.py:47``   — carried on the capability profile
  * ``execution.py:90``            — a second default of 50
  * ``session_plan.py:111,176``    — a third default of 50, read by nobody
  * ``policy.py:111,208``          — admin cap, ``min(user_effective, admin_cap)``
  * ``profile.py:496``             — derived from ``daily_application_limit``
  * ``policy_manager.py:114``      — a fourth default of 50
  * ``policy_enforcement.py:190``  — writes the admin-clamped value back to config
  * ``settings_editor.py:209``     — a GUI spinbox the user can set
  * ``registry.py:28``             — the docstring example

Nothing counts applications during a run and stops.

``ExecutionContext.stats.applications_submitted`` exists and is incremented, but
every single reference to it is a report, a log line, a checkpoint field, or a
success-rate calculation. There is no comparison against any cap anywhere in
``src/``.

``ThrottlingFilter`` looks like the enforcement point and is not:

  * ``MAX_APPLICATIONS_PER_COMPANY: int = 3`` is a hardcoded class constant. It
    *is* enforced (line 58), but it never reads config, so a user or admin who
    sets ``max_applications_per_company: 1`` is ignored. It coincides with the
    YAML's value of 3, which is why nobody noticed.
  * ``self._daily_limit`` is computed in ``__init__`` from
    ``profile.app_config.daily_application_limit`` and then never read. AST
    confirms: one write at line 32, zero reads.

Why this one is different
-------------------------
The other dead fields are architecture problems. This is a promise problem.

A user sets "apply to at most 5 jobs" in the GUI spinbox and AA applies to every
job discovery finds. An institution deploys AA at a library with an admin cap of
10 and the cap does nothing. On a 2GB machine the low-resource clamp lowers the
limit to 25 and AA ignores that too.

Applications are irreversible. A cap that is computed but not enforced is worse
than no cap, because the interface promises it.
"""

from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "auto_apply"


def test_daily_limit_is_read_after_being_computed() -> None:
    """ThrottlingFilter computes a daily limit and throws it away."""
    tree = ast.parse(
        (SRC / "domain" / "vetting" / "throttling_filter.py").read_text(encoding="utf-8")
    )
    reads = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
        and n.attr == "_daily_limit"
        and isinstance(n.ctx, ast.Load)
    ]
    assert reads, (
        "ThrottlingFilter._daily_limit is assigned in __init__ from "
        "profile.app_config.daily_application_limit and never read. The user's "
        "daily application limit is computed on every run and discarded."
    )


def test_per_company_cap_is_configurable() -> None:
    """A hardcoded constant cannot honour a user or admin setting."""
    from auto_apply.domain.vetting.throttling_filter import (  # noqa: PLC0415
        ThrottlingFilter,
    )

    src = (SRC / "domain" / "vetting" / "throttling_filter.py").read_text(
        encoding="utf-8"
    )
    assert "MAX_APPLICATIONS_PER_COMPANY: int = 3" not in src, (
        f"ThrottlingFilter.MAX_APPLICATIONS_PER_COMPANY is hardcoded to "
        f"{ThrottlingFilter.MAX_APPLICATIONS_PER_COMPANY} and never reads config. "
        f"runtime_defaults.yaml sets max_applications_per_company: 3 — the same "
        f"value, which is why the disconnect is invisible. Set it to 1 and AA "
        f"still applies 3 times."
    )


def test_session_application_cap_is_enforced() -> None:
    """Twelve definitions, zero gates.

    Fails until some code path compares a running application count against the
    effective ``max_applications_per_session`` and refuses to continue past it.
    """
    gates: list[str] = []
    for py in SRC.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left, *node.comparators]
            names = {
                o.attr
                for o in operands
                if isinstance(o, ast.Attribute)
            } | {
                o.id for o in operands if isinstance(o, ast.Name)
            }
            counted = names & {"applications_submitted", "applications_attempted"}
            capped = {n for n in names if "max_applications" in n or n == "_daily_limit"}
            if counted and capped:
                gates.append(f"{py.relative_to(SRC).as_posix()}:{node.lineno}")

    assert gates, (
        "No code path compares a running application count against "
        "max_applications_per_session. The value is defaulted in four places, "
        "clamped by the low-resource profile and the admin policy, exposed as a "
        "GUI spinbox, and enforced nowhere. AA will apply to every job discovery "
        "finds. Applications are irreversible; this cap is a promise, not a "
        "preference."
    )

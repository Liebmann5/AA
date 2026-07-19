"""Enforcement: settings the user writes must actually reach the SessionPlan.

What this pins
--------------
``SessionPlan.from_config()`` reads a *nested* config shape::

    config["applications"]["max_applications_per_session"]
    config["browser"]["headless"]
    config["research"]["enabled"]
    config["session"]["execution_mode"]

``resources/runtime_defaults.yaml`` provides a *flat* shape for exactly those
values::

    max_applications_per_session: 50
    headless_mode: false
    enable_research_collection: false

The two never meet. Every lookup misses and falls through to the hardcoded
default baked into ``from_config``. Nothing raises. Nothing logs. The values
happen to coincide with the defaults for most keys, so the plan *looks* correct
on inspection — which is why this survived years of review.

It does not coincide for ``headless``: the YAML says ``headless_mode: false``
and AA runs headless anyway. A headless browser cannot show a CAPTCHA, an MFA
prompt, or a submission confirmation to a human — so this silently disables the
visible half of HITL on the exact worst-case machines AA exists to serve.

``config["session"]`` and ``config["research"]`` do not exist in the YAML at
all, so ``execution_mode`` can only ever be FULL_PIPELINE and research can only
ever be off, regardless of what any user or admin writes.

README.md claims: "All configuration layers are merged at startup; no
hard-coded defaults can override the YAML." That is precisely inverted.

This is the same defect class as the ``_RUNTIME_DEFAULTS_FALLBACK`` shape drift:
two sources describing the same settings with no contract binding them. Fixing
the values without binding the shapes will only reintroduce it.
"""

from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

from auto_apply.domain.models.session_plan import (  # noqa: E402
    SessionExecutionMode,
    SessionPlan,
)
from auto_apply.domain.models.timing import BehaviorParameters  # noqa: E402


@pytest.fixture(scope="module")
def yaml_cfg() -> dict:
    p = list(pathlib.Path(__file__).resolve().parents[2].rglob("runtime_defaults.yaml"))
    assert p, "runtime_defaults.yaml not found"
    return yaml.safe_load(p[0].read_text(encoding="utf-8"))


def _plan(cfg: dict) -> SessionPlan:
    return SessionPlan.from_config(
        session_id="test", config=cfg, behavior=BehaviorParameters.from_config(cfg)
    )


def test_headless_is_not_a_second_source_of_truth() -> None:
    """`SessionPlan.headless` is a decoy and should be deleted, not wired.

    Correcting an earlier wrong call of my own: the browser *does* honour
    `headless_mode`. `RuntimeProfile.headless` (registry.py) reads the flat key,
    which exists, and `browser_cascade.py:208` launches from that. That path
    works.

    `SessionPlan.headless` is the problem. It reads a nested `browser.headless`
    that the YAML never defines, so it is permanently `True` — and nothing reads
    it. Two objects claim to describe the same browser state and disagree, which
    is the second source of truth the philosophy forbids. Wiring the plan field
    up would create a real conflict where today there is only a dead one.

    The fix is deletion. This test fails while the decoy exists.
    """
    assert "headless" not in SessionPlan.model_fields, (
        "SessionPlan.headless still exists. RuntimeProfile.headless already owns "
        "browser state and is the field that actually reaches the browser; this "
        "one is populated from a config section that does not exist and is read "
        "by nobody. Delete it rather than teaching it to lie accurately."
    )


def test_user_edits_to_runtime_defaults_take_effect(yaml_cfg: dict) -> None:
    """runtime_defaults.yaml's own header says power users may edit it directly."""
    cfg = dict(yaml_cfg)
    cfg["max_applications_per_session"] = 5
    cfg["max_applications_per_company"] = 1
    cfg["max_discovery_results_per_query"] = 7

    plan = _plan(cfg)
    ignored = {
        k: {"user_set": u, "aa_used": g}
        for k, u, g in [
            ("max_applications_per_session", 5, plan.max_applications_per_session),
            ("max_applications_per_company", 1, plan.max_applications_per_company),
            ("max_results_per_query", 7, plan.max_results_per_query),
        ]
        if u != g
    }
    assert not ignored, f"user settings silently ignored by SessionPlan: {ignored}"


def test_execution_mode_is_selectable(yaml_cfg: dict) -> None:
    """Standard + Customizable Execution Modes are a headline AA feature."""
    cfg = dict(yaml_cfg)
    cfg.setdefault("session", {})["execution_mode"] = "discover_only"
    got = _plan(cfg).execution_mode
    assert got != SessionExecutionMode.FULL_PIPELINE, (
        f"asked for discover_only, got {got}. If runtime_defaults.yaml has no "
        f"'session' section, execution_mode is pinned to FULL_PIPELINE forever."
    )

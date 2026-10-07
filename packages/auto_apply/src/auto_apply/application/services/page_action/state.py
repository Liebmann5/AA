"""PageActionContext — the one shared state object of the interaction tool.

The facade builds this exactly once from the resolved effective config and
hands it to every component. It is the ONLY thing components may share:
configuration (already low-resource-adjusted by the registry), the seeded
RNG streams, the motion profile, and the live session state (virtual cursor,
last measured viewport, capability gaps already logged, warmup flag).

Components never reach into each other's internals; they talk through this
context plus each other's public methods, injected at construction. The
boundary is pinned by tests/architecture/test_page_action_boundary.py.
"""
from __future__ import annotations

import random

from auto_apply.domain.models.motion_profile import MotionConfig
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.ports.interaction_primitives_port import DomReadinessPort


class PageActionContext:
    """Everything the tool's components share. Built once, by the facade."""

    def __init__(
        self,
        *,
        browser: BrowserInterface,
        cfg: dict,
        rng: random.Random | None,
        pointer_rng: random.Random | None,
        wheel_rng: random.Random | None,
        readiness: DomReadinessPort | None,
    ) -> None:
        self.browser: BrowserInterface = browser

        # Seeded streams. Pointer and wheel get their own so pacing draws
        # cannot shift the motion streams (reproducibility).
        self.rng: random.Random = rng if rng is not None else random.Random()
        self.pointer_rng: random.Random = (
            pointer_rng if pointer_rng is not None else self.rng
        )
        self.wheel_rng: random.Random = (
            wheel_rng if wheel_rng is not None else self.rng
        )

        # Optional DOM-stability readiness: when injected (the composition
        # root wires the shared DOMObserver), feed settles are measured, not
        # slept. None keeps the configured fixed wait.
        self.readiness: DomReadinessPort | None = readiness

        # ── Resolved timing configuration (already low-resource-adjusted) ──
        self.micro_peak_ms: float = float(cfg.get("micro_timing_peak_ms", 80.0))
        self.macro_min_s: float = float(cfg.get("macro_pause_min_s", 1.5))
        self.macro_max_s: float = float(cfg.get("macro_pause_max_s", 4.5))
        self.settle_min_s: float = float(cfg.get("settle_min_s", 0.3))
        self.settle_max_s: float = float(cfg.get("settle_max_s", 1.2))
        self.min_action_delay_s: float = max(
            0.0, float(cfg.get("min_action_delay_ms", 500)) / 1000.0
        )
        self.human_timing: bool = bool(cfg.get("enable_human_timing", True))
        self.occlusion_guard: bool = bool(cfg.get("occlusion_guard", True))
        self.navigation_retries: int = max(1, int(cfg.get("navigation_retries", 3)))
        self.infinite_scroll_settle_s: float = float(
            cfg.get("infinite_scroll_settle_s", 2.0)
        )
        # Bound on waiting for a pane's offset to settle after wheel input
        # before measuring it (C1): Playwright's wheel returns before the
        # page scrolls and smooth scrolling animates afterwards.
        self.scroll_settle_s: float = float(cfg.get("scroll_settle_timeout_s", 0.6))

        # One typed, validated profile drives every pointer/wheel behaviour.
        self.motion: MotionConfig = MotionConfig.from_mapping(cfg)

        # ── Live session state ────────────────────────────────────────────
        # Virtual cursor: the last viewport-CSS-px position the tool moved
        # the pointer to. None until the first planned move, and reset on
        # every navigation (a new document invalidates stored positions).
        self.cursor: tuple[int, int] | None = None
        self.last_viewport: tuple[int, int] | None = None
        # Capability gaps already logged (once per gap per session).
        self.logged_caps: set[str] = set()
        # One-time warmup flag for the first navigation of the session.
        self.warmed_up: bool = False

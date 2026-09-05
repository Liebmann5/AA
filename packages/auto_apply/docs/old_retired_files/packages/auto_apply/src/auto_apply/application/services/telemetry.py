# RETIRED FROM: packages/auto_apply/src/auto_apply/application/services/telemetry.py
"""Provides the self-healing telemetry feedback loop for AutoApply.

While ResearchCollector gathers data on the job market, the TelemetryTracker
gathers data on the Agent's own execution performance. It tracks the success
and failure rates of specific DOM locators and strategies per domain, allowing
the agent to 'learn' when a website updates its layout.
"""


import json
import logging
import threading
from typing import Any
from urllib.parse import urlparse

from auto_apply.domain.config import APP_DATA_DIR
from auto_apply.domain.events import Event

logger = logging.getLogger(__name__)

class TelemetryService:
    """Passive EventBus subscriber that tracks execution reliability."""

    def __init__(self, event_bus: Any):
        self._event_bus = event_bus
        self._telemetry_file = APP_DATA_DIR / "agent_telemetry.json"

        # In-memory cache: { "domain.com": { "strategy_or_selector": { "success": 10, "fail": 2 } } }  # noqa: E501
        self._stats: dict[str, dict[str, dict[str, int]]] = {}
        self._lock = threading.Lock()

        self._load()
        self._subscribe()

    def _subscribe(self) -> None:
        """Hooks into the EventBus to listen for execution outcomes."""
        self._event_bus.subscribe(Event.FORM_FIELD_FILLED, self._on_success)
        self._event_bus.subscribe(Event.FORM_FIELD_FAILED, self._on_failure)
        self._event_bus.subscribe(Event.APPLICATION_SUBMITTED, self._on_success)
        self._event_bus.subscribe(Event.APPLICATION_FAILED, self._on_failure)

    def get_confidence_score(self, url: str, key: str) -> float:
        """Calculates the historical probability of success for a strategy/selector.

        Used by the PageActionService to decide whether to trust a cached
        CSS selector or fall back to the AOM/Heuristic scanner immediately.

        Returns:
            float: A score between 0.0 (always fails) and 1.0 (always succeeds).
                   Defaults to 0.8 for unseen strategies to encourage exploration.
        """
        domain = self._extract_domain(url)
        with self._lock:
            domain_stats = self._stats.get(domain, {})
            item_stats = domain_stats.get(key)

            if not item_stats:
                return 0.8  # Optimistic default for unknown strategies

            total = item_stats["success"] + item_stats["fail"]
            if total == 0:
                return 0.8

            # Bayesian smoothing: we add a small baseline to prevent
            # 1 failure from completely destroying a strategy's score.
            return (item_stats["success"] + 1) / (total + 2)

    def _on_success(self, payload: dict) -> None:
        """Records a successful execution."""
        self._record_outcome(payload, success=True)

    def _on_failure(self, payload: dict) -> None:
        """Records a failed execution."""
        self._record_outcome(payload, success=False)

    def _record_outcome(self, payload: dict, success: bool) -> None:
        """Updates the probabilistic model in a thread-safe manner."""
        url = payload.get("url", "")
        strategy_key = payload.get("strategy") or payload.get("field_type") or "unknown_strategy"  # noqa: E501

        if not url:
            return

        domain = self._extract_domain(url)

        with self._lock:
            if domain not in self._stats:
                self._stats[domain] = {}
            if strategy_key not in self._stats[domain]:
                self._stats[domain][strategy_key] = {"success": 0, "fail": 0}

            if success:
                self._stats[domain][strategy_key]["success"] += 1
            else:
                self._stats[domain][strategy_key]["fail"] += 1

        # We don't save to disk on every event to save I/O overhead.
        # Disk saves are triggered by the Orchestrator during shutdown.

    def save(self) -> None:
        """Persists the learned telemetry to disk."""
        with self._lock:
            try:
                self._telemetry_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self._telemetry_file, 'w', encoding='utf-8') as f:
                    json.dump(self._stats, f, indent=2)
                logger.info("TelemetryService: Saved execution learning data.")
            except Exception as e:
                logger.error(f"TelemetryService: Failed to save data: {e}")

    def _load(self) -> None:
        """Loads historical execution data."""
        if not self._telemetry_file.exists():
            return
        try:
            with open(self._telemetry_file, encoding='utf-8') as f:
                self._stats = json.load(f)
        except Exception as e:
            logger.warning(f"TelemetryService: Failed to load history: {e}")
            self._stats = {}

    @staticmethod
    def _extract_domain(url: str) -> str:
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return "unknown"
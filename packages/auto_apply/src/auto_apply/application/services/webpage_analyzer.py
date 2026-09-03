"""Application service that orchestrates mathematical webpage understanding.

This service coordinates the perception and reasoning ports to produce a
complete `WebpageStructure` from a live browser page. It is the primary
entry point for the deterministic analysis pipeline.

It depends on abstractions (ports), not concrete implementations, ensuring
Hexagonal Architecture compliance.
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from auto_apply.domain.models.math_webpage import WebpageStructure
from auto_apply.domain.ports.math_perception_port import MathematicalPerceptionPort
from auto_apply.domain.ports.math_reasoning_port import FormUnderstandingPort

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Custom Exceptions for Granular Error Handling
# -----------------------------------------------------------------------------

# Failure and configuration types are shared with the mathematical analyzer.
# Re-exported here so every existing import of this module keeps working.
from auto_apply.application.services.analysis_contracts import (
    AnalysisTimeoutError,
    AnalyzerConfig,
    PerceptionError,
    ReasoningError,
    WebpageAnalysisError,
)


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# WebpageAnalyzer
# -----------------------------------------------------------------------------

class WebpageAnalyzer:
    """Orchestrate the mathematical analysis of a webpage.

    This service is stateless with respect to the page being analyzed.
    It receives its dependencies via constructor injection.

    Example:
        perception = MathDOMAdapter(browser)
        reasoning = MathFormUnderstandingService()
        config = AnalyzerConfig(extraction_timeout_seconds=20.0)
        analyzer = WebpageAnalyzer(perception, reasoning, config)

        structure = analyzer.analyze()
        if structure:
            print(f"Found {len(structure.forms)} forms")
    """

    def __init__(
        self,
        perception_port: MathematicalPerceptionPort,
        reasoning_port: FormUnderstandingPort,
        config: AnalyzerConfig | None = None,
    ) -> None:
        """Initialize with required ports and optional configuration.

        Args:
            perception_port: Adapter that extracts the DOM tree with geometry.
            reasoning_port: Service that performs segmentation and analysis.
            config: Configuration parameters; defaults to AnalyzerConfig().
        """
        self._perception = perception_port
        self._reasoning = reasoning_port
        self._config = config or AnalyzerConfig()

        # Small fixed pool prevents unbounded thread creation for timeout enforcement.
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="webpage_analyzer"
        )

    def __del__(self):
        """Ensure executor is shut down cleanly when the instance is garbage collected."""
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=False)

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the internal thread pool executor.

        Args:
            wait: If True, wait for all pending tasks to complete.
        """
        self._executor.shutdown(wait=wait)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def analyze(self) -> WebpageStructure | None:
        """Extract and analyze the currently loaded page.

        This method orchestrates the full pipeline:
            1. Extract the DOM tree via the perception port (with retries).
            2. Obtain page metadata (URL, title) from the perception port.
            3. Pass the tree and metadata to the reasoning port for analysis.
            4. Return the resulting WebpageStructure.

        Returns:
            A populated WebpageStructure, or None if analysis fails completely.

        Raises:
            PerceptionError: If extraction fails after all retries.
            ReasoningError: If reasoning fails and fallback is disabled.
            AnalysisTimeoutError: If any phase exceeds its configured time limit.
        """
        start_time = time.perf_counter()
        logger.info("Starting webpage analysis")

        dom_root = self._extract_with_retries()
        if dom_root is None:
            raise PerceptionError("Failed to extract DOM tree after all retries")

        url = self._get_current_url()
        title = self._get_page_title()
        logger.debug("Page metadata: url=%s, title=%s", url, title)

        structure = self._perform_reasoning(dom_root, url, title)

        elapsed = time.perf_counter() - start_time
        if self._config.enable_performance_logging:
            logger.info(
                "Webpage analysis completed in %.2f seconds | forms=%d fields=%d",
                elapsed,
                len(structure.forms) if structure else 0,
                sum(len(f.all_fields) for f in structure.forms) if structure else 0,
            )

        return structure

    # -------------------------------------------------------------------------
    # Extraction with Retry & Timeout
    # -------------------------------------------------------------------------

    def _extract_with_retries(self) -> Any | None:
        """Attempt DOM extraction with exponential backoff.

        Returns:
            DOM root node or None if all attempts fail.
        """
        # Widened from AnalysisTimeoutError | None: the second except clause
        # assigns a bare Exception, so the honest type is BaseException | None.
        last_error: BaseException | None = None
        delay = self._config.retry_delay_seconds

        for attempt in range(self._config.max_retries + 1):
            try:
                logger.debug(
                    "Extraction attempt %d/%d",
                    attempt + 1,
                    self._config.max_retries + 1,
                )
                return self._extract_with_timeout()
            except AnalysisTimeoutError as e:
                last_error = e
                logger.warning("Extraction timeout (attempt %d)", attempt + 1)
            except Exception as e:
                last_error = e
                logger.warning("Extraction failed (attempt %d): %s", attempt + 1, e)

            if attempt < self._config.max_retries:
                time.sleep(delay)
                delay *= 2

        logger.error("All extraction attempts failed")
        if last_error and self._config.fallback_to_partial:
            return None
        raise PerceptionError("DOM extraction failed") from last_error

    def _extract_with_timeout(self) -> Any | None:
        """Perform extraction with a timeout using the executor."""
        def extract():
            return self._perception.extract_full_dom_tree()

        return self._run_with_timeout(
            extract,
            self._config.extraction_timeout_seconds,
            "DOM extraction"
        )

    def _run_with_timeout(
        self,
        func: Callable[[], Any],
        timeout_seconds: float,
        operation_name: str
    ) -> Any:
        """Execute a callable with a timeout using a thread pool.

        Args:
            func: The callable to execute.
            timeout_seconds: Maximum time to wait.
            operation_name: Name used in log messages.

        Returns:
            The result of func().

        Raises:
            AnalysisTimeoutError: If the operation exceeds timeout_seconds.
            Exception: Any exception raised by func().
        """
        future = self._executor.submit(func)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError:
            future.cancel()
            logger.error("%s timed out after %.2f seconds", operation_name, timeout_seconds)
            raise AnalysisTimeoutError(f"{operation_name} timed out")
        except Exception:
            raise

    # -------------------------------------------------------------------------
    # Reasoning Phase
    # -------------------------------------------------------------------------

    def _perform_reasoning(
        self, dom_root: Any, url: str, title: str
    ) -> WebpageStructure | None:
        """Execute reasoning with a timeout using the executor."""
        def reason():
            return self._reasoning.analyze(dom_root, url=url, title=title)

        try:
            return self._run_with_timeout(
                reason,
                self._config.reasoning_timeout_seconds,
                "Form reasoning"
            )
        except AnalysisTimeoutError:
            if self._config.fallback_to_partial:
                return self._build_partial_structure(dom_root, url, title)
            raise
        except Exception as e:
            logger.error("Reasoning failed: %s", e, exc_info=True)
            if self._config.fallback_to_partial:
                return self._build_partial_structure(dom_root, url, title)
            raise ReasoningError("Form understanding analysis failed") from e

    def _build_partial_structure(self, dom_root: Any, url: str, title: str) -> WebpageStructure:
        """Construct a minimal WebpageStructure when reasoning fails."""
        logger.info("Building partial WebpageStructure as fallback")
        return WebpageStructure(
            url=url,
            title=title,
            dom_root=dom_root,
            forms=[],
            job_listings=[],
            is_captcha_present=False,
            is_login_wall=False,
        )

    # -------------------------------------------------------------------------
    # Metadata Helpers
    # -------------------------------------------------------------------------

    def _get_current_url(self) -> str:
        """Return the current page URL, or empty string if unavailable."""
        if hasattr(self._perception, "get_current_url"):
            return self._perception.get_current_url() or ""
        return ""

    def _get_page_title(self) -> str:
        """Return the current page title, or empty string if unavailable."""
        if hasattr(self._perception, "get_page_title"):
            return self._perception.get_page_title() or ""
        return ""


# -----------------------------------------------------------------------------
# Factory for Convenient Construction
# -----------------------------------------------------------------------------

class WebpageAnalyzerFactory:
    """Factory to create a fully configured WebpageAnalyzer.

    This is a convenience for wiring in the composition root.
    """

    @staticmethod
    def create(
        perception_port: MathematicalPerceptionPort,
        reasoning_port: FormUnderstandingPort | None = None,
        config: AnalyzerConfig | None = None,
    ) -> WebpageAnalyzer:
        """Create an analyzer with provided or default reasoning service.

        Args:
            perception_port: The perception adapter (required).
            reasoning_port: The reasoning service; if None, uses
                MathFormUnderstandingService with default settings.
            config: Configuration; if None, uses AnalyzerConfig().

        Returns:
            A ready-to-use WebpageAnalyzer.
        """
        if reasoning_port is None:
            from auto_apply.domain.services.dom_segmentation import (  # noqa: PLC0415
                MathFormUnderstandingService,
            )
            reasoning_port = MathFormUnderstandingService()

        return WebpageAnalyzer(perception_port, reasoning_port, config)

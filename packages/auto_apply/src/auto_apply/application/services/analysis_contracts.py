
"""Shared failure and configuration types for webpage analysis.

Both analyzers defined these five types independently, with identical bodies
and identical field defaults. Two definitions of an exception class are worse
than they look: ``except PerceptionError`` bound to one module's class silently
fails to catch the other module's, so a caller can be correct against one
analyzer and quietly wrong against the other.

One definition each, imported by both.
"""

from dataclasses import dataclass


class WebpageAnalysisError(Exception):
    """Base exception for webpage analysis failures."""
    pass


class PerceptionError(WebpageAnalysisError):
    """Raised when DOM extraction fails."""
    pass


class ReasoningError(WebpageAnalysisError):
    """Raised when the reasoning engine fails."""
    pass


class AnalysisTimeoutError(WebpageAnalysisError):
    """Raised when analysis exceeds configured time limit."""
    pass


@dataclass(frozen=True)
class AnalyzerConfig:
    """Immutable configuration for webpage analysis.

    Attributes:
        enable_performance_logging: Log timing information for each step.
        extraction_timeout_seconds: Maximum time allowed for DOM extraction.
        reasoning_timeout_seconds: Maximum time allowed for reasoning phase.
        fallback_to_partial: If True, attempt to return partial results on
            non-critical failures.
        max_retries: Number of retry attempts for transient extraction failures.
        retry_delay_seconds: Base delay between retries (exponential backoff).
    """
    enable_performance_logging: bool = True
    extraction_timeout_seconds: float = 30.0
    reasoning_timeout_seconds: float = 60.0
    fallback_to_partial: bool = False
    max_retries: int = 2
    retry_delay_seconds: float = 1.0

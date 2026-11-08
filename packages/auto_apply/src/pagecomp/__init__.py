"""pagecomp: page comprehension toolkit (sans-IO, standard library only).

Public API (05 section 10): ``observe_html``, ``observe_cdp``, ``Analyzer``,
``analyze``, ``Trace``, plus the result types. The library imports nothing
from AA; AA adapts to it.
"""

from __future__ import annotations

from pagecomp.analyzer import Analysis, Analyzer, ResultCache
from pagecomp.observation import PageObservation, observe_cdp, observe_html
from pagecomp.results import Abstain, Evidence, Ok, Stale, Timeout
from pagecomp.trace import Trace

__version__ = "0.5.1"

__all__ = [
    "Abstain", "Analysis", "Analyzer", "Evidence", "Ok", "PageObservation", "ResultCache",
    "Stale", "Timeout", "Trace", "analyze", "observe_cdp", "observe_html", "__version__",
]


def analyze(obs: PageObservation, *tools: str, **kw: object) -> dict[str, object]:
    """Run the named tools (default: ``family``) and return their results."""
    an = Analyzer(obs, **kw)  # type: ignore[arg-type]
    return {t: an.get(t).result for t in (tools or ("family",))}

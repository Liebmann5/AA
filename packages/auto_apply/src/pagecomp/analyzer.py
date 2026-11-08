"""The analyzer: a demand-driven, memoized query graph over one observation.

Shape (the owner's "read once, offer every tool, re-read incrementally"
idea, made safe; see docs/BLUEPRINT.md section 3):

* **Demand-driven.** Nothing runs until a consumer asks ``get(tool_id)``.
  A tool asks for what it needs through ``q.need``; only declared needs are
  allowed, so the graph is explicit and acyclic (checked at start-up).
* **Memoized on content, not on time.** The cache key is
  ``(observation content hash, tool, versions and parameters of the tool's
  dependency closure)``. A re-observed unchanged page reuses every result;
  a changed page reuses nothing it should not. The epoch is carried on each
  result for consumers and never used as a cache key.
* **Bounded.** The cache is an LRU with an entry cap; the analysis has a
  work-unit budget (deterministic, no clock) and every tool a unit cap.
  Exhausting either yields ``Timeout``, never a hang.
* **Contained.** A tool that raises yields ``Abstain("tool-error:...")``
  and the failure is traced; other tools keep working (CT-FR-033). In
  ``strict`` mode (tests) the exception propagates.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pagecomp.observation import PageObservation
from pagecomp.params import ParameterSet
from pagecomp.registry import Registry
from pagecomp.results import Abstain, Ok, Result, Stale, Timeout, fingerprint
from pagecomp.trace import ToolRun, Trace


class UndeclaredDependency(RuntimeError):
    pass


class _OutOfUnits(Exception):
    pass


class _DependencyFailed(Exception):
    def __init__(self, tool: str, result: Result) -> None:
        super().__init__(tool)
        self.tool = tool
        self.result = result


@dataclass(frozen=True)
class Analysis:
    """A tool result stamped with where and when it came from."""

    tool: str
    result: Result
    epoch: int
    content_hash: str


class ResultCache:
    """LRU of results shared by analyzers (bounded: CT-NFR-018)."""

    def __init__(self, max_entries: int = 512) -> None:
        self.max_entries = max_entries
        self._data: OrderedDict[tuple[str, ...], Result] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple[str, ...]) -> Result | None:
        value = self._data.get(key)
        if value is None:
            self.misses += 1
            return None
        self._data.move_to_end(key)
        self.hits += 1
        return value

    def put(self, key: tuple[str, ...], value: Result) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)


class Query:
    """What a running tool may touch: the observation, its params, its needs."""

    __slots__ = ("_an", "_tool", "_needs", "obs", "params", "_units", "_limit")

    def __init__(self, analyzer: "Analyzer", tool: str, needs: tuple[str, ...],
                 params: Mapping[str, Any], limit: int) -> None:
        self._an = analyzer
        self._tool = tool
        self._needs = needs
        self.obs = analyzer.obs
        self.params = params
        self._units = 0
        self._limit = limit

    @property
    def doc(self):  # noqa: ANN201 - Doc, kept untyped to avoid an import cycle
        return self.obs.doc

    def tick(self, n: int = 1) -> None:
        """Charge ``n`` work units; past the cap the tool times out."""
        self._units += n
        if self._units > self._limit or not self._an._charge(n):
            raise _OutOfUnits()

    def need(self, tool_id: str) -> Result:
        if tool_id not in self._needs:
            raise UndeclaredDependency(f"{self._tool} asked for undeclared {tool_id}")
        return self._an._run(tool_id)

    def need_ok(self, tool_id: str) -> Any:
        """The dependency's value, or abstain this tool with its reason."""
        res = self.need(tool_id)
        if isinstance(res, Ok):
            return res.value
        raise _DependencyFailed(tool_id, res)

    def maybe(self, tool_id: str) -> Any | None:
        """The dependency's value if it succeeded, else ``None``."""
        res = self.need(tool_id)
        return res.value if isinstance(res, Ok) else None


class Analyzer:
    def __init__(
        self,
        obs: PageObservation,
        *,
        registry: Registry | None = None,
        params: ParameterSet | None = None,
        cache: ResultCache | None = None,
        trace: Trace | None = None,
        budget_units: int = 20_000_000,
        strict: bool = False,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if registry is None:
            from pagecomp.tools import default_registry

            registry = default_registry()
        registry.check_acyclic()
        self.obs = obs
        self.registry = registry
        self.params = params or registry.default_params()
        self.cache = cache if cache is not None else ResultCache()
        self.trace = trace if trace is not None else Trace()
        self.budget = budget_units
        self.used = 0
        self.strict = strict
        self.clock = clock
        self._running: list[str] = []
        self._local: dict[str, Result] = {}

    def _charge(self, n: int) -> bool:
        self.used += n
        return self.used <= self.budget

    def _key(self, tool_id: str) -> tuple[str, ...]:
        closure = self.registry.closure(tool_id)
        versions = ",".join(f"{t}@{self.registry.get(t).version}" for t in closure)
        return (self.obs.content_hash, tool_id, versions, self.params.tool_hash(closure))

    def get(self, tool_id: str) -> Analysis:
        result = self._run(tool_id)
        return Analysis(tool_id, result, self.obs.epoch, self.obs.content_hash)

    def value(self, tool_id: str) -> Any:
        """Convenience: the value if ``Ok``, else ``None``."""
        res = self._run(tool_id)
        return res.value if isinstance(res, Ok) else None

    def check(self, analysis: Analysis, current_epoch: int) -> Result | Stale:
        """Gate for acting: a finding from another epoch is ``Stale``."""
        if analysis.epoch != current_epoch:
            return Stale(analysis.epoch, current_epoch)
        return analysis.result

    def _run(self, tool_id: str) -> Result:
        if tool_id in self._local:
            return self._local[tool_id]
        if tool_id in self._running:
            raise UndeclaredDependency("cycle: " + " -> ".join(self._running + [tool_id]))
        spec = self.registry.get(tool_id)
        key = self._key(tool_id)
        cached = self.cache.get(key)
        if cached is not None:
            self._local[tool_id] = cached
            self._record(spec, key, cached, 0, True, None)
            return cached
        params = dict((p.name, p.default) for p in spec.params)
        params.update(self.params.for_tool(tool_id))
        limit = int(params.get("max_units", spec.default_units))
        q = Query(self, tool_id, spec.needs, params, limit)
        self._running.append(tool_id)
        start = self.clock() if self.clock else None
        outcome_reason = ""
        try:
            result = spec.run(q, params)
            if not isinstance(result, (Ok, Abstain, Timeout)):
                result = Abstain(f"tool-contract: returned {type(result).__name__}")
        except _OutOfUnits:
            result = Timeout(None, q._units)
        except _DependencyFailed as dep:
            inner = dep.result
            why = inner.reason if isinstance(inner, (Abstain, Timeout)) else "failed"
            result = Abstain(f"needs {dep.tool}: {why}")
        except UndeclaredDependency:
            raise
        except Exception as exc:  # contained failure (CT-FR-033)
            if self.strict:
                raise
            result = Abstain(f"tool-error: {type(exc).__name__}")
            outcome_reason = "error"
        finally:
            self._running.pop()
        duration = (self.clock() - start) * 1000.0 if (self.clock and start is not None) else None
        self.cache.put(key, result)
        self._local[tool_id] = result
        self._record(spec, key, result, q._units, False, duration, outcome_reason)
        return result

    def _record(self, spec: Any, key: tuple[str, ...], result: Result, units: int,
                hit: bool, duration: float | None, forced: str = "") -> None:
        if isinstance(result, Ok):
            outcome, reason = "ok", ""
        elif isinstance(result, Timeout):
            outcome, reason = "timeout", result.reason
        else:
            outcome, reason = ("error" if forced else "abstain"), result.reason
        self.trace.append(ToolRun(
            seq=self.trace.next_seq(), tool=spec.id, ct_id=spec.ct_id,
            tool_version=spec.version, params_hash=key[3], input_hash=key[0],
            output_hash=fingerprint(result)[:16], outcome=outcome, reason=reason[:120],
            units=units, cache_hit=hit, epoch=self.obs.epoch, duration_ms=duration,
        ))

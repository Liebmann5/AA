"""Tool registry (05 section 2, seam rule).

A tool is a ``ToolSpec``: an id, the blueprint id it implements, a version,
the tools it may ask for (``needs``), its declared parameters, and a pure
``run(q, params) -> Result``. Swapping an implementation means registering
another spec under the same id with another version; the trace records which
version ran. Dependencies are declared, not discovered: a tool that asks for
an undeclared tool is a programming error and fails loudly in tests, which
is what keeps the query graph from turning into a service locator.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pagecomp.params import ParameterSet, ParamSpec

if TYPE_CHECKING:
    from pagecomp.analyzer import Query
    from pagecomp.results import Result


@dataclass(frozen=True)
class ToolSpec:
    id: str
    ct_id: str
    version: str
    run: "Callable[[Query, Mapping[str, Any]], Result]"
    needs: tuple[str, ...] = ()
    params: tuple[ParamSpec, ...] = ()
    summary: str = ""
    default_units: int = 2_000_000


@dataclass
class Registry:
    tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec, *, replace: bool = False) -> None:
        if spec.id in self.tools and not replace:
            raise ValueError(f"tool {spec.id!r} already registered")
        self.tools[spec.id] = spec

    def get(self, tool_id: str) -> ToolSpec:
        try:
            return self.tools[tool_id]
        except KeyError:
            raise KeyError(f"unknown tool {tool_id!r}") from None

    def closure(self, tool_id: str) -> tuple[str, ...]:
        """The tool and everything it may (transitively) need, sorted."""
        seen: set[str] = set()
        todo = [tool_id]
        while todo:
            t = todo.pop()
            if t in seen:
                continue
            seen.add(t)
            todo.extend(self.get(t).needs)
        return tuple(sorted(seen))

    def check_acyclic(self) -> None:
        state: dict[str, int] = {}

        def visit(t: str, path: tuple[str, ...]) -> None:
            if state.get(t) == 2:
                return
            if state.get(t) == 1:
                raise ValueError("dependency cycle: " + " -> ".join(path + (t,)))
            state[t] = 1
            for n in self.get(t).needs:
                visit(n, path + (t,))
            state[t] = 2

        for t in self.tools:
            visit(t, ())

    def specs(self) -> Mapping[str, Iterable[ParamSpec]]:
        return {t: s.params for t, s in self.tools.items()}

    def default_params(self) -> ParameterSet:
        return ParameterSet.from_specs(self.specs())

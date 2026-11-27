"""The query graph: demand, memoization on content, epochs, budgets, containment, trace."""

from __future__ import annotations

import pytest

from pagecomp import Abstain, Analyzer, Ok, ResultCache, Stale, Timeout, observe_html
from pagecomp.analyzer import UndeclaredDependency
from pagecomp.params import ParameterSet, ParamSpec
from pagecomp.registry import Registry, ToolSpec
from pagecomp.tools import default_registry

PAGE = "<main><h1>Engineer</h1><p>secret-user-words</p></main>"


def _obs(html=PAGE, epoch=0, url="https://jobs.example/secret-path?q=secret-user-words"):
    return observe_html(html, url=url, epoch=epoch, query="secret-user-words")


def _tiny_registry(calls):
    def base(q, p):
        calls.append("base")
        q.tick(1)
        return Ok(len(q.doc))

    def top(q, p):
        calls.append("top")
        return Ok(q.need_ok("base") * int(p["k"]))

    def rogue(q, p):
        return q.need("base")  # undeclared

    def boom(q, p):
        raise ZeroDivisionError

    def spin(q, p):
        while True:
            q.tick(1000)

    reg = Registry()
    reg.register(ToolSpec("base", "T-1", "1", base))
    reg.register(ToolSpec("top", "T-2", "1", top, needs=("base",), params=(ParamSpec("k", 2),)))
    reg.register(ToolSpec("rogue", "T-3", "1", rogue))
    reg.register(ToolSpec("boom", "T-4", "1", boom))
    reg.register(ToolSpec("spin", "T-5", "1", spin, default_units=50_000))
    reg.register(ToolSpec("needs_boom", "T-6", "1", lambda q, p: Ok(q.need_ok("boom")), needs=("boom",)))
    return reg


def test_demand_driven_and_memoized_within_analysis():
    calls = []
    an = Analyzer(_obs(), registry=_tiny_registry(calls))
    assert calls == []
    a = an.get("top").result
    b = an.get("top").result
    assert isinstance(a, Ok) and a == b
    assert calls == ["top", "base"]


def test_cache_keys_on_content_not_epoch():
    calls = []
    reg = _tiny_registry(calls)
    cache = ResultCache()
    Analyzer(_obs(epoch=1), registry=reg, cache=cache).get("top")
    Analyzer(_obs(epoch=2), registry=reg, cache=cache).get("top")
    assert calls == ["top", "base"], "same content at a later epoch reuses results"
    Analyzer(_obs(PAGE + "<p>changed</p>", epoch=2), registry=reg, cache=cache).get("top")
    assert calls == ["top", "base", "top", "base"], "changed content recomputes"


def test_parameters_are_part_of_the_key():
    calls = []
    reg = _tiny_registry(calls)
    cache = ResultCache()
    p1 = reg.default_params()
    p2 = p1.with_overrides(reg.specs(), {"top": {"k": 3}}, reason="test")
    r1 = Analyzer(_obs(), registry=reg, cache=cache, params=p1).value("top")
    r2 = Analyzer(_obs(), registry=reg, cache=cache, params=p2).value("top")
    assert r2 == r1 // 2 * 3
    assert calls.count("base") == 1, "base's own parameters did not change: reused"


def test_stale_findings_are_refused():
    an = Analyzer(_obs(epoch=4), registry=_tiny_registry([]))
    finding = an.get("base")
    assert isinstance(an.check(finding, 4), Ok)
    assert an.check(finding, 5) == Stale(4, 5)


def test_undeclared_dependency_fails_loudly():
    with pytest.raises(UndeclaredDependency):
        Analyzer(_obs(), registry=_tiny_registry([])).get("rogue")


def test_errors_are_contained_and_propagate_as_abstain():
    an = Analyzer(_obs(), registry=_tiny_registry([]))
    assert an.get("boom").result == Abstain("tool-error: ZeroDivisionError")
    dep = an.get("needs_boom").result
    assert isinstance(dep, Abstain) and dep.reason.startswith("needs boom")
    assert isinstance(an.get("base").result, Ok), "other tools keep working"
    with pytest.raises(ZeroDivisionError):
        Analyzer(_obs(), registry=_tiny_registry([]), strict=True).get("boom")


def test_budget_gives_timeout_not_hang():
    res = Analyzer(_obs(), registry=_tiny_registry([])).get("spin").result
    assert isinstance(res, Timeout) and res.units_used > 50_000
    res2 = Analyzer(_obs(), registry=_tiny_registry([]), budget_units=10).get("spin").result
    assert isinstance(res2, Timeout)


def test_trace_carries_no_page_text_or_url():
    an = Analyzer(_obs(), strict=True)
    for t in ("family", "formread", "listing"):
        an.get(t)
    blob = repr(list(an.trace))
    assert "secret" not in blob and "jobs.example" not in blob
    assert an.trace.summary()["family"]["ok"] == 1


def test_cache_is_bounded():
    cache = ResultCache(max_entries=3)
    reg = _tiny_registry([])
    for k in range(5):
        Analyzer(_obs(PAGE + f"<i>{k}</i>"), registry=reg, cache=cache).get("top")
    assert len(cache) == 3


def test_safety_parameters_cannot_be_tuned():
    reg = default_registry()
    base = reg.default_params()
    with pytest.raises(PermissionError):
        base.with_overrides(reg.specs(), {"formread": {"c_trap": 1.0}}, reason="tune")
    owner = base.with_overrides(reg.specs(), {"formread": {"c_trap": 20.0}}, reason="owner ruling",
                                owner_safety_override=True)
    assert owner.hash != base.hash and owner.provenance[-1] == "owner ruling"
    with pytest.raises(ValueError):
        base.with_overrides(reg.specs(), {"records": {"tau": 5.0}}, reason="out of bounds")


def test_default_registry_is_acyclic_and_every_tool_runs_on_an_empty_page():
    reg = default_registry()
    an = Analyzer(observe_html("", url="about:blank"), registry=reg, strict=True)
    for tool in reg.tools:
        res = an.get(tool).result
        assert isinstance(res, (Ok, Abstain, Timeout)), tool


def test_parameter_set_hash_is_order_independent():
    a = ParameterSet({"x": {"a": 1, "b": 2}, "y": {}})
    b = ParameterSet({"y": {}, "x": {"b": 2, "a": 1}})
    assert a.hash == b.hash

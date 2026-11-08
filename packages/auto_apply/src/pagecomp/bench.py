"""S0: measure, then cap (05 s14, 06 s11; CT-NFR-004/005).

Runs on the owner's machine with **synthetic pages only** (no captures, no
network): result lists, application forms, deep nesting and shadow-DOM
pages at several sizes. For each size it measures parse time, analysis time
(family, joblist, formread, controls, views) and peak traced memory, then
fits ``T(n) = a + b·n`` and ``M(n) = c + d·n`` by least squares.

Two time figures, with different jobs:

* the **target** (CT-NFR-004, 1.0 s): what a typical page should take. It is
  reported (how many nodes fit in it) but it does not set the cap;
* the **ceiling** (3.0 s): the longest any one page may take. It does set
  the cap, together with memory:

    N_ceiling = (T_ceiling - a) / b,   N_mem = (M_budget - c) / d,
    max_nodes = floor(min(N_ceiling, N_mem) / 1000) · 1000

A machine whose budgets fit fewer than 1,000 nodes gets no recommendation
(and a non-zero exit), never a cap rounded up past its budgets.

Why the cap is not set by the target: a page over the cap is truncated, and
a truncated application form is missing questions. Cutting real pages to
save half a second turns slowness into wrong answers. The cap is a guard
against pathological pages (endless feeds, generated markup), not a speed
control. The ceiling is an operational budget, configurable with
``--ceiling-s``, not a measured worst case: 3 s is about what the browser
itself spent loading and settling one page on the owner's laptop in one
live log (2026-11-07: 3-4 s from navigation to a validated page), so a page
at the cap takes about as long to read as to reach. The bench runs without
a browser competing for the CPU. Memory is 64 MiB per observation
(a 2 GB machine with a browser running). Every number is printed and saved,
so the cap is a measured consequence of the machine, not a guess.
"""

from __future__ import annotations

import gc
import json
import math
import os
import platform
import sys
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from pagecomp.analyzer import Analyzer, ResultCache
from pagecomp.doc import Doc, DocLimits, from_html
from pagecomp.observation import PageObservation


def page_list(n_cards: int) -> str:
    cards = "".join(
        f'<li class="c c{k % 7}"><div><h3><a href="https://jobs.example/job/{k}{k:04d}">'
        f'<span>Software Engineer {k}</span></a></h3><div>Acme {k % 50}</div><div>Remote</div>'
        f'<ul><li>Python</li><li>SQL</li></ul><time>{k % 30} days ago</time></div></li>'
        for k in range(n_cards))
    filt = "".join(f'<label><input type=checkbox name=f value={k}> Option {k}</label>' for k in range(12))
    return (f"<html><head><title>Jobs</title></head><body><header><nav>"
            + "".join(f'<a href="/n{k}">Menu {k}</a>' for k in range(10))
            + f"</nav><form role=search action=/search><input name=q value='software engineer'>"
              f"<input name=l><button>Search</button></form></header><aside><h4>Job type</h4>{filt}</aside>"
              f"<main><ul>{cards}</ul><nav aria-label=pagination><a href='?p=2' rel=next>Next</a></nav></main>"
              "</body></html>")


def page_form(n_fields: int) -> str:
    rows = "".join(
        f'<div class=row><label for=f{k}>Question {k} *</label><input id=f{k} name=q{k}></div>'
        if k % 4 else
        f'<fieldset><legend>Choice {k} *</legend>'
        + "".join(f'<label><input type=radio name=r{k} value={j}> Answer {j}</label>' for j in range(3))
        + "</fieldset>"
        for k in range(n_fields))
    return (f"<html><body><main><h1>Apply</h1><form><label for=fn>First name *</label><input id=fn "
            f"autocomplete=given-name><label for=em>Email *</label><input id=em type=email>"
            f"<label for=cv>Resume</label><input id=cv type=file>{rows}<button type=submit>Submit"
            f"</button></form></main></body></html>")


def page_deep(depth: int) -> str:
    return "<html><body>" + "<div>" * depth + "deep" + "</div>" * depth + "</body></html>"


def page_shadow(n_hosts: int) -> str:
    one = ('<x-field><template shadowrootmode=open><label for=i>Field</label><input id=i>'
           '</template></x-field>')
    return "<html><body><form>" + one * n_hosts + "</form></body></html>"


KINDS: dict[str, tuple[Callable[[int], str], tuple[int, ...], tuple[int, ...]]] = {
    "list": (page_list, (20, 100, 300, 800, 1600), (20, 100, 300)),
    "form": (page_form, (10, 50, 200, 600, 1200), (10, 50, 200)),
    "shadow": (page_shadow, (20, 200, 800, 2000), (20, 200)),
    "deep": (page_deep, (50, 500, 2000), (50, 500)),
}


@dataclass(frozen=True)
class Sample:
    kind: str
    size: int
    nodes: int
    html_chars: int
    parse_s: float
    analyze_s: float
    peak_mib: float
    truncated: tuple[str, ...]
    errors: tuple[str, ...]      # tools that raised: such a sample is invalid


_URL = "https://jobs.example/search?q=software+engineer"
_TOOLS = ("family", "joblist", "formread", "controls", "views")


def _once(html: str, limits: DocLimits) -> tuple[float, float, tuple[Doc, tuple[str, ...]]]:
    t0 = time.perf_counter()
    doc = from_html(html, _URL, limits)
    t1 = time.perf_counter()
    an = Analyzer(PageObservation(_URL, "bench", doc, query="software engineer"), cache=ResultCache(64))
    for tool in _TOOLS:
        an.get(tool)
    t2 = time.perf_counter()
    errors = tuple(sorted({r.tool for r in an.trace if r.outcome == "error"}))
    return t1 - t0, t2 - t1, (doc, errors)


def _measure(kind: str, gen: Callable[[int], str], size: int, limits: DocLimits,
             repeats: int = 3) -> Sample:
    """Time without tracing (median of ``repeats``), then memory in a separate
    traced pass: tracemalloc slows every allocation, so one pass cannot
    measure both."""
    html = gen(size)
    times: list[tuple[float, float, tuple[Doc, tuple[str, ...]]]] = []
    doc: Doc | None = None
    errors: tuple[str, ...] = ()
    for _ in range(repeats):
        gc.collect()
        times.append(_once(html, limits))
        doc, errors = times[-1][2]
    times.sort(key=lambda t: t[0] + t[1])
    parse_s, analyze_s, _ = times[len(times) // 2]
    gc.collect()
    tracemalloc.start()
    _once(html, limits)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert doc is not None
    return Sample(kind, size, len(doc), len(html), round(parse_s, 5), round(analyze_s, 5),
                  round(peak / 2**20, 3), tuple(f"{t.kind}@{t.limit}" for t in doc.truncations), errors)


def fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Least squares ``y = a + b·x``; b is clamped ≥ 0 (cost never falls with size)."""
    n = len(xs)
    if n < 2:
        return (ys[0] if ys else 0.0, 0.0)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    b = max(b, 0.0)
    return (my - b * mx, b)


#: The smallest cap worth recommending: below it a results page of ~20
#: records (about 1,000 nodes) cannot be read whole.
MIN_CAP = 1000


def recommend(samples: list[Sample], target_s: float, ceiling_s: float,
              budget_mib: float) -> dict[str, Any]:
    if ceiling_s < target_s:
        raise ValueError("the time ceiling must be at least the target")
    ns = [float(s.nodes) for s in samples]
    a, b = fit(ns, [s.parse_s + s.analyze_s for s in samples])
    c, d = fit(ns, [s.peak_mib for s in samples])

    def within(budget: float, base: float, per: float) -> float:
        return (budget - base) / per if per > 0 else math.inf

    n_target = within(target_s, a, b)
    n_ceiling = within(ceiling_s, a, b)
    n_mem = within(budget_mib, c, d)
    raw = min(n_ceiling, n_mem, 200_000)

    def finite(x: float) -> int | None:
        return max(0, int(x)) if math.isfinite(x) else None

    if raw < MIN_CAP:
        # Never round a cap *up* past the budgets: a machine that cannot read
        # MIN_CAP nodes within them gets no recommendation, and says why.
        return {
            "error": f"the budgets fit fewer than {MIN_CAP} nodes on this machine",
            "nodes_within_ceiling": finite(n_ceiling),
            "nodes_within_memory_budget": finite(n_mem),
            "budgets": {"target_seconds": target_s, "ceiling_seconds": ceiling_s, "mib": budget_mib},
        }
    cap = int(raw // 1000) * 1000 if math.isfinite(raw) else 200_000

    return {
        "time_model_s": {"a": round(a, 6), "b_per_node": b},
        "memory_model_mib": {"c": round(c, 3), "d_per_node": d},
        "bytes_per_node": round(d * 2**20, 1),
        "nodes_within_target": finite(n_target),
        "nodes_within_ceiling": finite(n_ceiling),
        "nodes_within_memory_budget": finite(n_mem),
        "recommended_max_nodes": cap,
        "limited_by": "time" if n_ceiling <= n_mem else "memory",
        "seconds_at_cap": round(a + b * cap, 3),
        "mib_at_cap": round(c + d * cap, 2),
        "budgets": {"target_seconds": target_s, "ceiling_seconds": ceiling_s, "mib": budget_mib},
    }


def run(quick: bool = False, target_s: float = 1.0, ceiling_s: float = 3.0, budget_mib: float = 64.0,
        progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    limits = DocLimits(max_nodes=200_000, max_depth=4096)
    samples: list[Sample] = []
    for kind, (gen, sizes, quick_sizes) in KINDS.items():
        for size in (quick_sizes if quick else sizes):
            s = _measure(kind, gen, size, limits)
            samples.append(s)
            if progress:
                progress(f"{kind:7} size {size:5}  nodes {s.nodes:7}  parse {s.parse_s:7.3f}s  "
                         f"analyze {s.analyze_s:7.3f}s  peak {s.peak_mib:8.2f} MiB")
    broken = sorted({e for s in samples for e in s.errors})
    if broken:
        rec: dict[str, Any] = {"error": "tools raised during measurement; no cap is recommended",
                                  "tools": broken}
    else:
        rec = recommend([s for s in samples if s.kind in ("list", "form", "shadow")],
                        target_s, ceiling_s, budget_mib)
    return {
        "machine": {"platform": platform.platform(), "python": sys.version.split()[0],
                    "implementation": platform.python_implementation(), "cpus": os.cpu_count(),
                    "machine": platform.machine()},
        "samples": [asdict(s) for s in samples],
        "recommendation": rec,
        "note": "synthetic pages; tracemalloc measures Python allocations only (the browser is extra)",
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="pagecomp bench", description=__doc__.split("\n\n")[0])
    ap.add_argument("--quick", action="store_true", help="smaller sizes (about 10 seconds)")
    ap.add_argument("--target-s", type=float, default=1.0,
                    help="seconds a typical page should take (CT-NFR-004); reported, does not set the cap")
    ap.add_argument("--ceiling-s", type=float, default=3.0,
                    help="seconds the largest allowed page may take; sets the cap")
    ap.add_argument("--budget-mib", type=float, default=64.0, help="MiB per observation")
    ap.add_argument("--out", default="pagecomp_bench.json", help="where to save the JSON report")
    args = ap.parse_args(argv)
    report = run(args.quick, args.target_s, args.ceiling_s, args.budget_mib, progress=print)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    r = report["recommendation"]
    if "error" in r:
        detail = f": {', '.join(r['tools'])}" if "tools" in r else ""
        print(f"\nNO CAP RECOMMENDED: {r['error']}{detail}; report saved to {args.out}")
        return 1
    print(f"\nrecommended max_nodes: {r['recommended_max_nodes']} (limited by {r['limited_by']}): "
          f"about {r['seconds_at_cap']} s and {r['mib_at_cap']} MiB for a page that large; "
          f"pages up to {r['nodes_within_target']} nodes meet the {r['budgets']['target_seconds']} s target; "
          f"{r['bytes_per_node']} bytes/node; report saved to {args.out}")
    return 0

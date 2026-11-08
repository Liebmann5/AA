"""S0 bench and S6 command line."""

from __future__ import annotations

import json

import pytest

from pagecomp import __main__ as cli
from pagecomp import bench


def test_fit_and_recommend_from_a_linear_machine():
    a, b = bench.fit([1000, 2000, 4000], [0.11, 0.21, 0.41])
    assert abs(a - 0.01) < 1e-9 and abs(b - 1e-4) < 1e-12
    samples = [bench.Sample("list", 0, n, 0, 0.0, 0.01 + 1e-4 * n, 1 + 1e-4 * n, (), ()) for n in (1000, 5000, 9000)]
    rec = bench.recommend(samples, target_s=1.0, ceiling_s=1.0, budget_mib=64)
    assert rec["recommended_max_nodes"] == 9000 and rec["limited_by"] == "time"
    rec = bench.recommend(samples, target_s=1.0, ceiling_s=3.0, budget_mib=64)
    # The target is reported; only the ceiling (and memory) set the cap.
    assert rec["nodes_within_target"] == 9900
    assert rec["recommended_max_nodes"] == 29000 and rec["seconds_at_cap"] == 2.91
    with pytest.raises(ValueError):
        bench.recommend(samples, target_s=2.0, ceiling_s=1.0, budget_mib=64)


def test_budgets_too_small_give_no_cap_not_a_rounded_up_one(tmp_path):
    """Review finding (2026-11-08): the cap was floored at 1,000 nodes even
    when the budgets fit fewer, so the report recommended a cap that broke
    both budgets. Now: no recommendation, the reason, and exit code 1."""
    samples = [bench.Sample("list", 0, n, 0, 0.0, 0.01 + 1e-4 * n, 1 + 1e-4 * n, (), ()) for n in (1000, 5000, 9000)]
    rec = bench.recommend(samples, target_s=0.001, ceiling_s=0.001, budget_mib=0.001)
    assert "recommended_max_nodes" not in rec and "fewer than 1000" in rec["error"]
    assert rec["nodes_within_ceiling"] == 0
    out = tmp_path / "b.json"
    assert bench.main(["--quick", "--target-s", "0.001", "--ceiling-s", "0.001",
                       "--budget-mib", "0.001", "--out", str(out)]) == 1


def test_owner_laptop_measurement_gives_the_shipped_default():
    """The owner's laptop (2026-11-08: 2 CPUs, Python 3.14) measured
    T(n) = 0.123 s + 98.5 us/node and 230 bytes/node. At the 3 s ceiling
    that is 29,000 nodes, which AA's config uses there; the largest of
    the 97 owner captures (12,899 nodes) takes about 1.4 s there."""
    a, b = 0.123144, 9.8518325935132e-05
    c, d = 1.232, 0.0002190459579659137
    samples = [bench.Sample("list", 0, n, 0, 0.0, a + b * n, c + d * n, (), ()) for n in (417, 13677, 27277)]
    rec = bench.recommend(samples, target_s=1.0, ceiling_s=3.0, budget_mib=64)
    assert rec["recommended_max_nodes"] == 29000 and rec["limited_by"] == "time"
    assert rec["nodes_within_target"] == 8900
    assert round(a + b * 12899, 1) == 1.4


def test_quick_bench_runs_every_tool_without_errors(tmp_path):
    out = tmp_path / "b.json"
    assert bench.main(["--quick", "--out", str(out)]) == 0
    rep = json.loads(out.read_text())
    assert not any(s["errors"] for s in rep["samples"])
    assert rep["recommendation"]["recommended_max_nodes"] >= 1000


def test_cli_analyze_review_version(tmp_path, capsys):
    page = tmp_path / "p.html"
    page.write_text("<main><ul>" + "".join(
        f'<li><h3><a href="https://jobs.example/job/{k}001">Engineer {k}</a></h3></li>' for k in range(5))
        + "</ul></main>", encoding="utf-8")
    assert cli.main(["analyze", str(page), "--url", "https://jobs.example/s?q=engineer", "--query", "engineer"]) == 0
    assert "job list: 5 records" in capsys.readouterr().out
    assert cli.main(["analyze", str(page), "--url", "https://jobs.example/", "--json", "--tools", "family"]) == 0
    assert json.loads(capsys.readouterr().out)["family"]["ok"] is True
    rv = tmp_path / "r.html"
    assert cli.main(["review", str(page), "--url", "https://jobs.example/", "--out", str(rv)]) == 0
    assert rv.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    capsys.readouterr()
    assert cli.main(["version"]) == 0 and capsys.readouterr().out.strip() == "0.5.1"


def test_package_metadata_version_matches_the_code():
    import re
    from pathlib import Path

    import pagecomp
    path = Path(pagecomp.__file__).resolve().parents[2] / "pyproject.toml"
    meta = path.read_text(encoding="utf-8") if path.is_file() else ""
    if not re.search(r'^name = "pagecomp"', meta, re.MULTILINE):
        pytest.skip("vendored copy: the version lives in the standalone package's pyproject")
    m = re.search(r'^version = "([^"]+)"', meta, re.MULTILINE)
    assert m is not None and m.group(1) == pagecomp.__version__

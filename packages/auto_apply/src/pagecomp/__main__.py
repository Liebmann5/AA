"""Command line (S6: the standalone library).

    python -m pagecomp analyze page.html --url https://... [--query "..."] [--json]
    python -m pagecomp analyze dom.json --cdp --url https://...
    python -m pagecomp review page.html --url https://... --out review.html
    python -m pagecomp bench [--quick] [--out pagecomp_bench.json]
    python -m pagecomp version

Reads local files only; never touches the network.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pagecomp import Analyzer, __version__, observe_cdp, observe_html
from pagecomp.results import Ok, _canon


def _load(args: argparse.Namespace):  # noqa: ANN202
    raw = Path(args.file).read_text(encoding="utf-8", errors="replace")
    if args.cdp:
        return observe_cdp(json.loads(raw), url=args.url, query=args.query)
    return observe_html(raw, url=args.url, query=args.query)


def _summary(an: Analyzer) -> list[str]:
    lines = []
    fam = an.value("family")
    if fam is not None:
        lines.append(f"page: {fam.family} (p={fam.p:.2f})" + (f"  overlays: {', '.join(fam.overlays)}" if fam.overlays else ""))
    jl = an.value("joblist")
    if jl is not None:
        lines.append(f"job list: {len(jl.records)} records")
        for r in jl.records[:15]:
            dest = r.link.url if r.link and r.link.kind != "opaque" else (f"opaque → {r.link.expected_host}" if r.link else "")
            lines.append(f"  - {r.title[:70]}  [{r.state}] {dest[:80]}")
    fr = an.value("formread")
    if fr is not None and fr.fields:
        lines.append(f"questions: {len(fr.fields)}")
        for f in fr.fields[:25]:
            lines.append(f"  - {f.label[:50]!r} {f.field_type} {f.required} {f.decision}")
    ctl = an.value("controls")
    if ctl is not None:
        known = [b for b in ctl.bindings if b.piece != "unknown"]
        if known:
            lines.append("controls: " + ", ".join(f"{b.piece}({b.widget_kind})" for b in known[:20]))
    tr = an.obs.doc.truncations
    if tr:
        lines.append("truncated: " + ", ".join(f"{t.kind}@{t.limit}" for t in tr))
    return lines


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["bench"]:
        from pagecomp import bench

        return bench.main(argv[1:])
    ap = argparse.ArgumentParser(prog="pagecomp")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("analyze", "review"):
        p = sub.add_parser(name)
        p.add_argument("file")
        p.add_argument("--url", required=True)
        p.add_argument("--query", default=None)
        p.add_argument("--cdp", action="store_true", help="the file is a pierced DOM.getDocument JSON")
        if name == "analyze":
            p.add_argument("--json", action="store_true")
            p.add_argument("--tools", default="family,joblist,formread,controls,views")
        else:
            p.add_argument("--out", default="pagecomp_review.html")
    sub.add_parser("version")
    sub.add_parser("bench", help="measure time and memory on this machine (see bench --help)")
    args = ap.parse_args(argv)
    if args.cmd == "version":
        print(__version__)
        return 0
    an = Analyzer(_load(args))
    if args.cmd == "review":
        from pagecomp import workbench

        Path(args.out).write_text(workbench.review_html(an, title=f"pagecomp review: {args.url}"), encoding="utf-8")
        print(f"wrote {args.out}")
        return 0
    if args.json:
        out = {}
        for t in args.tools.split(","):
            res = an.get(t.strip()).result
            out[t] = {"ok": isinstance(res, Ok), "value": _canon(res.value) if isinstance(res, Ok) else None,
                      "reason": getattr(res, "reason", "")}
        json.dump(out, sys.stdout, indent=1, default=str)
        print()
        return 0
    print("\n".join(_summary(an)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

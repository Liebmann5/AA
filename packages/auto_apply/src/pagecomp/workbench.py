"""Workbench, review mode (S8; CT-FR-027/028; CT-ALG-026).

Two pure pieces for contributors:

* ``classify_failure`` (ALG-026): from the trace, the findings and what the
  engine did, which kind of failure a page is:
  ``ACCESS_BLOCKED`` (challenge / login wall), ``TOOL_DEFECT`` (a tool
  errored), ``MISSING_TOOL`` (a tool the engine needs abstained),
  ``WORKFLOW_BUG`` (confident findings, and the engine acted against them),
  ``WORKFLOW_CHANGE`` (findings right, but the plan lacks a step the page
  needs: a consent banner, a modal, an entry chooser, a guest sign-in
  overlay, a next page), ``UNKNOWN_PHENOMENON`` (nothing matches: a new
  ledger row is due), or ``OK``.
* ``review_html``: one self-contained HTML page. On the left, what the page
  is (family, overlays, records, fields, controls, views). On the right, every
  universal tool, the ones that ran highlighted and the ones that did not
  dimmed, and the three engines' stages with their state.

Explore mode (run tools live on a page) lives in AA, which owns the browser;
it calls the same ``Analyzer``. The report may contain page text and URLs:
it is a local file for the owner, never part of a shared trace.
"""

from __future__ import annotations

import html
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pagecomp.analyzer import Analyzer
from pagecomp.results import Ok

ENGINE_STAGES: dict[str, tuple[tuple[str, str], ...]] = {
    "Discovery": (("arrive", "arrival"), ("what page", "family"), ("job list", "joblist"),
                  ("records", "listing"), ("search controls", "controls")),
    "Vetting": (("what page", "family"), ("barriers", "verdict"), ("posting data", "structured"),
                ("views", "views")),
    "Applications": (("what page", "family"), ("forms", "forms"), ("questions", "formread"),
                     ("barriers", "verdict")),
}
ENGINE_NEEDS = {"Discovery": ("joblist",), "Vetting": ("family", "structured"), "Applications": ("formread",)}

OK, ACCESS_BLOCKED, TOOL_DEFECT, MISSING_TOOL = "OK", "ACCESS_BLOCKED", "TOOL_DEFECT", "MISSING_TOOL"
WORKFLOW_BUG, WORKFLOW_CHANGE, UNKNOWN_PHENOMENON = "WORKFLOW_BUG", "WORKFLOW_CHANGE", "UNKNOWN_PHENOMENON"


@dataclass(frozen=True)
class FailureClass:
    kind: str
    evidence: tuple[str, ...]
    needed_steps: tuple[str, ...]


def needed_steps(an: Analyzer) -> tuple[str, ...]:
    """Steps the page itself asks for, from findings only."""
    steps: list[str] = []
    fam = an.value("family")
    if fam is not None:
        if any(o.startswith("consent") for o in fam.overlays):
            steps.append("dismiss_consent")
        if "login" in fam.overlays:
            steps.append("dismiss_sign_in_overlay")
        if "dialog" in fam.overlays:
            steps.append("handle_dialog")
        if fam.family == "application_entry":
            steps.append("choose_entry")
    ctl = an.value("controls")
    if ctl is not None and (ctl.by_piece("page_next") or ctl.by_piece("load_more")):
        steps.append("advance_page")
    return tuple(steps)


def classify_failure(an: Analyzer, *, engine: str, plan_steps: Iterable[str] = (),
                     acted_against: Iterable[str] = ()) -> FailureClass:
    """``acted_against``: tool ids whose confident finding the engine contradicted
    (e.g. it filled a field the reading marked TRAP)."""
    ev: list[str] = []
    verdict = an.value("verdict")
    if verdict is not None and verdict.kind in ("challenge", "login"):
        return FailureClass(ACCESS_BLOCKED, (f"verdict {verdict.kind}",), ())
    for tool in ENGINE_NEEDS.get(engine, ()):
        an.get(tool)
    runs = list(an.trace)
    errors = sorted({r.tool for r in runs if r.outcome == "error"})
    if errors:
        return FailureClass(TOOL_DEFECT, tuple(f"{t} raised" for t in errors), ())
    against = sorted(set(acted_against))
    if against:
        return FailureClass(WORKFLOW_BUG, tuple(f"engine acted against {t}" for t in against), ())
    missing = [t for t in ENGINE_NEEDS.get(engine, ()) if not isinstance(an.get(t).result, Ok)]
    need = needed_steps(an)
    lacking = tuple(s for s in need if s not in set(plan_steps))
    fam = an.value("family")
    if missing:
        if fam is not None and fam.family == "unknown":
            ev.append("family unknown")
            return FailureClass(UNKNOWN_PHENOMENON, tuple(ev + [f"{t} abstained" for t in missing]), lacking)
        return FailureClass(MISSING_TOOL, tuple(f"{t} abstained" for t in missing), lacking)
    if lacking:
        return FailureClass(WORKFLOW_CHANGE, tuple(f"page needs {s}" for s in lacking), lacking)
    return FailureClass(OK, (), need)


def _e(x: Any) -> str:
    return html.escape(str(x), quote=True)


def review_html(an: Analyzer, *, title: str = "pagecomp review", failure: FailureClass | None = None,
                max_rows: int = 60) -> str:
    """A self-contained review page (no scripts, no external resources)."""
    obs = an.obs
    tools = sorted(an.registry.tools)
    for t in ("family", "joblist", "formread", "controls", "views"):
        an.get(t)
    ran: dict[str, str] = {}
    for r in an.trace:
        ran[r.tool] = r.outcome
    fam = an.value("family")
    left: list[str] = []
    left.append(f"<p><strong>URL</strong> {_e(obs.url)}</p>")
    if fam is not None:
        left.append(f"<p><strong>Page</strong> {_e(fam.family)} (p={fam.p:.2f}, margin {fam.margin:.2f})"
                    + (f"; overlays: {_e(', '.join(fam.overlays))}" if fam.overlays else "") + "</p>")
    if failure is not None:
        left.append(f"<p><strong>Failure class</strong> {_e(failure.kind)}: {_e('; '.join(failure.evidence))}</p>")
    trunc = obs.doc.truncations
    if trunc:
        left.append("<p><strong>Truncated</strong> " + _e(", ".join(f"{t.kind}@{t.limit}" for t in trunc)) + "</p>")
    jl = an.value("joblist")
    if jl is not None:
        rows = "".join(f"<tr><td>{_e(r.title)}</td><td>{_e(r.state)}</td><td>{_e(r.link.kind if r.link else '')}</td>"
                       f"<td>{_e((r.link.url if r.link and r.link.kind != 'opaque' else (r.link.expected_host if r.link else ''))[:90])}</td></tr>"
                       for r in jl.records[:max_rows])
        left.append(f"<h2>Job list ({len(jl.records)} records)</h2><table><thead><tr><th>Title</th><th>State</th>"
                    f"<th>Link</th><th>Destination</th></tr></thead><tbody>{rows}</tbody></table>")
    fr = an.value("formread")
    if fr is not None and fr.fields:
        rows = "".join(f"<tr><td>{_e(f.label[:80])}</td><td>{_e(f.field_type)}</td><td>{_e(f.required)}</td>"
                       f"<td>{_e(f.decision)}</td><td>{_e(f.label_source)}</td></tr>" for f in fr.fields[:max_rows])
        left.append(f"<h2>Questions ({len(fr.fields)})</h2><table><thead><tr><th>Label</th><th>Type</th>"
                    f"<th>Required</th><th>Decision</th><th>Label from</th></tr></thead><tbody>{rows}</tbody></table>")
    ctl = an.value("controls")
    if ctl is not None and ctl.bindings:
        rows = "".join(f"<tr><td>{_e(b.widget_kind)}</td><td>{_e(b.piece)}</td><td>{_e(b.name[:60])}</td>"
                       f"<td>{_e(b.apply_mode)}</td></tr>" for b in ctl.bindings[:max_rows])
        left.append(f"<h2>Controls ({len(ctl.bindings)})</h2><table><thead><tr><th>Widget</th><th>Piece</th>"
                    f"<th>Name</th><th>Applies</th></tr></thead><tbody>{rows}</tbody></table>")
    vm = an.value("views")
    if vm is not None:
        rows = "".join(f"<li>{_e(v.kind)}: {_e(v.locator[:100])}</li>" for v in vm.views)
        left.append(f"<h2>Views</h2><p>record key {_e(vm.record_key)}</p><ul>{rows}</ul>")
    right: list[str] = ["<h2>Tools</h2><ul class=tools>"]
    for t in tools:
        spec = an.registry.get(t)
        state = ran.get(t)
        cls = "used" if state else "unused"
        right.append(f"<li class={cls}><span>{_e(t)}</span> <small>{_e(spec.ct_id)} v{_e(spec.version)}"
                     f"{' · ' + _e(state) if state else ' · not run'}</small></li>")
    right.append("</ul><h2>Engines</h2>")
    for eng, stages in ENGINE_STAGES.items():
        items = "".join(f"<li class={'used' if ran.get(tool) == 'ok' else ('warn' if ran.get(tool) else 'unused')}>"
                        f"{_e(name)} <small>({_e(tool)}: {_e(ran.get(tool, 'not run'))})</small></li>"
                        for name, tool in stages)
        right.append(f"<h3>{_e(eng)}</h3><ol>{items}</ol>")
    css = ("body{font:15px/1.5 system-ui,sans-serif;margin:0;color:#111;background:#fff}"
           "main{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:24px;padding:24px}"
           "table{border-collapse:collapse;width:100%;font-size:13px}td,th{border:1px solid #ccc;padding:4px 6px;"
           "text-align:left;vertical-align:top}th{background:#f2f2f2}ul.tools{list-style:none;padding:0}"
           "li.used{color:#0b3d0b;font-weight:600}li.unused{color:#6b6b6b}li.warn{color:#8a4b00}"
           "small{font-weight:400}h1{font-size:20px;margin:16px 24px 0}h2{font-size:17px}h3{font-size:15px}"
           "@media (prefers-color-scheme: dark){body{background:#111;color:#eee}th{background:#222}"
           "td,th{border-color:#444}li.used{color:#8fe08f}li.unused{color:#9a9a9a}li.warn{color:#f0b060}}")
    return ("<!DOCTYPE html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'><title>{_e(title)}</title>"
            f"<style>{css}</style></head><body><h1>{_e(title)}</h1><main><section aria-label='What the page is'>"
            + "".join(left) + "</section><aside aria-label='Tools and engines'>" + "".join(right)
            + "</aside></main></body></html>")


def ledger_coverage(ledger_rows: Iterable[Mapping[str, str]]) -> dict[str, int]:
    """CT-FR-027: counts by status from the capability ledger's rows
    (``{"id": ..., "status": "[x]"|"[~]"|"[ ]"}``), as AA's ledger file holds them."""
    out: dict[str, int] = {}
    for row in ledger_rows:
        s = row.get("status", "?")
        out[s] = out.get(s, 0) + 1
    return out

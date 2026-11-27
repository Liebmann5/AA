"""Page family (CT-T-007 decision, CT-ALG-006): one answer to "what page is this?".

LR-18 found five separate "is this page usable?" checks in AA. This tool is
the single definition the engines should ask.

The verdict's barrier kinds dominate unchanged (challenge, login, error,
closed, applied, confirmation): they are returned with ``p = 1``. Otherwise
a log-linear model over documented features, ``p = softmax(score / T)``,
decides among ``result_list``, ``job_description``, ``application_form``
and ``other``, and abstains to ``unknown`` unless ``p >= 0.6`` and the
margin to the runner-up is ``>= 0.2`` (06 section 3). Weights are hand-set
and listed below; fitting them (regularised logistic regression, fixed
seed) waits for the gold set.

Features (each in [0, 1] unless noted):

* ``joblist``: the job-list gate passed (its share);
* ``list``: a non-navigation run of records carrying heading and link, size over 8;
* ``list_size``: records in the job list over 10, capped at 1;
* ``runs``: best run score, squashed ``x/(1+|x|)``;
* ``posting``: exactly one JSON-LD JobPosting (0.5 for several), halved when
  the page shows fewer than 2 prose blocks (metadata without a description);
* ``apply``: an apply control (link or button) is present (``links.is_apply_text``);
* ``form``: identity evidence of the best application-purpose form:
  distinct identity field types among its fillable questions (name, email,
  phone, résumé, address, LinkedIn) over 3, capped at 1. ``type=email``,
  ``type=tel``, ``type=file`` and autofill tokens are structural; names are
  lexicon evidence. Search, login and filter forms never count (EC-41), and
  a job-alert box (email + keywords) scores 1/3, not 1;
* ``file``: a file control in an application form;
* ``prose``: paragraph-like text blocks over 10, capped at 1;
* ``entry``: >= 2 distinct shown controls that each start an application a
  different way (``links.is_entry_choice``). With no identity form and
  little prose this is ``application_entry``: the step before the form
  (Workday's chooser). Over a posting's prose it is a modal on a posting,
  which stays ``job_description`` with a ``dialog`` overlay.
* ``text``: visible text mass, ``log10(chars)/5`` capped at 1.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pagecomp.params import ParamSpec
from pagecomp.registry import ToolSpec
from pagecomp.results import Evidence, Ok
from pagecomp.links import is_apply_text, is_entry_choice
from pagecomp.tools.joblist import job_related_list

FAMILIES = ("result_list", "job_description", "application_form", "application_entry", "other")
IDENTITY = {"first_name": "name", "last_name": "name", "full_name": "name", "email": "email",
            "phone": "phone", "resume": "resume", "file": "resume", "address": "address",
            "linkedin": "linkedin", "postal_code": "address", "city": "address"}
BARRIERS = {"challenge", "login", "error", "closed", "applied", "confirmation"}

WEIGHTS: dict[str, dict[str, float]] = {
    "result_list": {"bias": -1.0, "joblist": 4.0, "list_size": 2.0, "list": 1.5, "runs": 1.0, "posting": -3.0,
                    "form": -1.5, "apply": -0.5},
    "job_description": {"bias": -1.0, "posting": 3.5, "apply": 1.5, "prose": 1.5, "text": 0.5,
                        "joblist": -1.5, "form": -2.0, "entry": -2.0},
    "application_form": {"bias": -1.0, "form": 5.0, "file": 1.5, "joblist": -3.0, "entry": -1.0},
    "application_entry": {"bias": -1.0, "entry": 5.0, "prose": -3.0, "form": -4.0, "joblist": -3.0},
    "other": {"bias": 0.5},
}


@dataclass(frozen=True)
class Family:
    family: str              # one of FAMILIES, a barrier kind, or "unknown"
    p: float
    margin: float
    scores: tuple[tuple[str, float], ...]
    features: tuple[tuple[str, float], ...]
    overlays: tuple[str, ...]


def _squash(x: float) -> float:
    return x / (1.0 + abs(x))


def _run(q: Any, params: Mapping[str, Any]) -> Ok[Family]:
    verdict = q.need_ok("verdict")
    if verdict.kind in BARRIERS:
        return Ok(Family(verdict.kind, 1.0, 1.0, (), (), verdict.overlays),
                  evidence=(Evidence("barrier", verdict.kind),))
    structured = q.maybe("structured")
    forms = q.maybe("forms")
    text = q.maybe("pagetext")
    records = q.maybe("records")
    joblist = q.maybe("joblist")
    doc = q.doc
    feats: dict[str, float] = {"bias": 1.0}
    if joblist is not None:
        feats["joblist"] = joblist.share
        feats["list_size"] = min(1.0, len(joblist.reading.records) / 10.0)
    else:
        # No list of *postings*: a list of job-related results (search or
        # category pages) still makes a result list (joblist 0.3.0 split the
        # two; the page family keeps the broader reading it had before).
        listing = q.maybe("listing")
        share, n = job_related_list(listing, q.obs.query) if listing is not None else (0.0, 0)
        feats["joblist"] = share
        feats["list_size"] = min(1.0, n / 10.0)
    feats["runs"] = _squash(records.runs[0].score) if records is not None and records.runs else 0.0
    # A results page of any kind (web results, not only postings): a
    # non-navigation run of >= 4 records that carry a heading and a link.
    feats["list"] = 0.0
    if records is not None:
        for run in records.runs[:5]:
            if not run.feature("chrome") and not run.feature("menu_like") and run.feature("carries") >= 0.8:
                feats["list"] = max(feats["list"], min(1.0, len(run.members) / 8.0))
    n_post = len(structured.postings) if structured is not None else 0
    feats["posting"] = 1.0 if n_post == 1 else (0.5 if n_post > 1 else 0.0)
    apply = 0.0
    for a in list(doc.elements("a")) + list(doc.elements("button")):
        if is_apply_text(doc.accessible_name(a)):
            apply = 1.0
            break
    feats["apply"] = apply
    # Entry choices: >= 2 shown controls that each start an application a
    # different way, and no form asking for identity yet (Workday's chooser).
    vis = q.maybe("visibility")
    entries = set()
    for a in list(doc.elements("a")) + list(doc.elements("button")) + \
            [i for i in doc.elements() if (doc.attr(i, "role") or "") == "button"]:
        if vis is not None and vis.hidden(a):
            continue
        name = doc.accessible_name(a)
        if is_entry_choice(name):
            entries.add(" ".join(name.casefold().split()))
    feats["entry"] = 1.0 if len(entries) >= 2 else 0.0
    form = file = 0.0
    reading = q.maybe("formread")
    if forms is not None and reading is not None:
        per_form: dict[int, set[str]] = {}
        for f in reading.fields:
            if f.decision == "FILL" and f.field_type in IDENTITY:
                per_form.setdefault(f.form, set()).add(IDENTITY[f.field_type])
        for k, info in enumerate(forms.forms):
            if info.purpose != "application":
                continue
            ident = min(1.0, len(per_form.get(k, ())) / 3.0)
            form = max(form, ident)
            # A file control counts only beside identity fields: an image-search
            # upload box (a results page's "search by image") is not a résumé.
            if ident > 0 and any(c.type == "file" for c in forms.of_form(k)):
                file = 1.0
    feats["form"], feats["file"] = form, file
    feats["prose"] = min(1.0, text.prose_blocks / 10.0) if text is not None else 0.0
    # JSON-LD is metadata: Workday ships the posting's JobPosting on its
    # "Start Your Application" step too. A description page also *shows*
    # description prose; without >= 2 prose blocks the posting signal is halved.
    if feats["posting"] and text is not None and text.prose_blocks < 2:
        feats["posting"] *= 0.5
    feats["text"] = min(1.0, math.log10(1 + len(text.text)) / 5) if text is not None else 0.0
    temp = float(params["temperature"])
    scores = {f: sum(w * feats.get(name, 0.0) for name, w in WEIGHTS[f].items()) for f in FAMILIES}
    mx = max(scores.values())
    exps = {f: math.exp((s - mx) / temp) for f, s in scores.items()}
    z = sum(exps.values())
    probs = sorted(((exps[f] / z, f) for f in FAMILIES), reverse=True)
    (p1, f1), (p2, _f2) = probs[0], probs[1]
    decided = f1 if p1 >= float(params["min_p"]) and p1 - p2 >= float(params["min_margin"]) else "unknown"
    return Ok(Family(decided, round(p1, 6), round(p1 - p2, 6),
                     tuple((f, round(scores[f], 6)) for f in FAMILIES),
                     tuple(sorted((k, round(v, 6)) for k, v in feats.items())), verdict.overlays),
              confidence=round(p1, 6), margin=round(p1 - p2, 6),
              evidence=(Evidence("top", f1, round(p1, 6)),))


TOOL = ToolSpec(
    id="family", ct_id="CT-T-007", version="0.3.0", run=_run,
    needs=("verdict", "structured", "forms", "formread", "pagetext", "records", "joblist", "listing",
           "visibility"),
    params=(ParamSpec("temperature", 1.0, 0.1, 10.0), ParamSpec("min_p", 0.6, 0.0, 1.0),
            ParamSpec("min_margin", 0.2, 0.0, 1.0)),
    summary="the single page-family answer (LR-18)",
)

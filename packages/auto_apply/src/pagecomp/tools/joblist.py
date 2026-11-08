"""The job-list gate: which run, if any, is a list of job postings.

Problem it closes (owner run 2026-11-02): Bing's home page news cards were
read as job records because "a repeated run with titles and links" is true
of any feed. A run is a **job list** only when its records look like
postings, on evidence that needs no site list inside the library:

* destination path tokens of postings (``job``, ``jobs``, ``careers``,
  ``position``, ``posting``, ``opening``, ``vacancy``, ``req``, ``apply``...)
  **with an identifier** (>= 3 digits or a >= 24-character slug): 1.0; the
  token alone (a category page such as ``/c/audit-jobs``) 0.5;
* runs inside navigation landmarks or shaped like menus never qualify;
* destination host in the consumer's posting-host list (AA passes its ATS
  registry, the single source of truth; the library names no site);
* **query echo**: the title shares words with the search that led here;
* role words in the title (a lexicon: evidence only, never required, so a
  non-English list can still pass on the structural signals).

Per record ``s = path + 1.0·host + 1.0·echo + 0.5·role``; a record is
job-like at ``s >= 1`` **and** when its destination is *specific*: an
identifier in its path or query (an identified item with no posting word
scores ``path = 0.5``), or a posting host. Without that, a list of
related searches (Indeed's ``/q-junior-web-developer-...-jobs.html``:
category token 0.5 + role word 0.5) passed while Indeed's real cards
(``/rc/clk?jk=…``: no posting word) failed (owner capture 2026-11-03;
the same failure in the live run of 2026-11-07). A run passes when ``>= min_share`` of its records
are job-like **and** ``>= min_resolved`` share have a route (resolved or
opaque). The best passing run by ``run score + 2·share`` is chosen; with
none, the tool abstains ``no-job-list`` and lists the top runs' shares so a
human (or the Workbench) can see why.
"""

from __future__ import annotations

import dataclasses
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pagecomp import links as L
from pagecomp.params import ParamSpec
from pagecomp.registry import ToolSpec
from pagecomp.results import Abstain, Evidence, Ok
from pagecomp.text import token_set
from pagecomp.tools.listing import RecordReading, RunReading
from pagecomp.tools.records import signature_similarity

ROLE_WORDS = frozenset({
    "engineer", "developer", "manager", "analyst", "designer", "scientist", "specialist",
    "technician", "nurse", "assistant", "associate", "coordinator", "consultant",
    "administrator", "architect", "director", "intern", "internship", "lead", "officer",
    "representative", "supervisor", "operator", "driver", "accountant", "clerk", "teacher",
    "therapist", "programmer", "sre", "devops", "backend", "frontend", "fullstack",
    "software", "senior", "junior", "principal", "staff", "head", "agent", "advisor",
    "recruiter", "writer", "editor", "counsel", "attorney", "mechanic", "electrician",
    "cashier", "planner", "buyer", "chef", "cook", "pharmacist", "physician",
})
_STOP = frozenset({"site", "the", "and", "for", "with", "jobs", "job", "near", "remote", "or"})


@dataclass(frozen=True)
class RecordJobness:
    score: float
    path: float
    host: bool
    echo: bool
    role: bool
    specific: bool = True   # the destination names one item (identifier) or is a posting host
    clone: bool = False     # a hidden copy (aria-hidden) of a visible record: a decoy

    @property
    def job_like(self) -> bool:
        return self.score >= 1.0 and self.specific and not self.clone


@dataclass(frozen=True)
class JobList:
    run_index: int
    reading: RunReading
    share: float
    routed_share: float
    per_record: tuple[RecordJobness, ...]
    others: tuple[int, ...]      # indexes of further passing runs (lists split by ads/sections)
    merged: tuple[RecordReading, ...] = ()   # the chosen run plus same-shaped passing runs
    merged_jobness: tuple[RecordJobness, ...] = ()   # one per ``records`` entry

    @property
    def record_jobness(self) -> tuple[RecordJobness, ...]:
        """Jobness for every entry of ``records``, in the same order."""
        return self.merged_jobness or self.per_record

    @property
    def records(self) -> tuple[RecordReading, ...]:
        """Every record of the list: one list split into several runs
        (Indeed renders its cards in several sibling lists) is read whole."""
        return self.merged or self.reading.records


def _dest(rec: RecordReading) -> str:
    if rec.link is None:
        return ""
    return rec.link.url if rec.link.kind != L.OPAQUE else ""


def _query_words(query: str | None) -> frozenset[str]:
    if not query:
        return frozenset()
    words = set()
    for t in token_set(query, 3):
        if ":" in t or t in _STOP:
            continue
        words.add(t)
    return frozenset(words)


def jobness(rec: RecordReading, qwords: frozenset[str], hosts: tuple[str, ...]) -> RecordJobness:
    url = _dest(rec)
    try:
        parts = urllib.parse.urlsplit(url) if url else None
    except ValueError:
        parts = None
    host = (parts.hostname or "").lower() if parts else ""
    if not host and rec.link is not None and rec.link.kind == L.OPAQUE:
        host = rec.link.expected_host
    path = L.posting_path(url) if url else 0.0
    on_host = bool(host) and any(host == h or host.endswith("." + h) for h in hosts)
    # Specific: the destination names one item (``links.specific_destination``:
    # Indeed's ``/rc/clk?jk=...``, Greenhouse's ``/jobs/4012345``, a slug
    # after ``/jobs/``), or sits on a posting host; for an opaque route, an
    # identifier shown in the rendered breadcrumb counts.
    # A category or related-search link (``/q-software-engineer-...-jobs.html``,
    # ``/c/audit-jobs``) names a *search*, not a posting.
    ident = False
    if url:
        ident = L.specific_destination(url)
    elif rec.link is not None and rec.link.kind == L.OPAQUE:
        ident = L.has_identifier(rec.link.expected_path)
    if ident and path == 0.0:
        path = 0.5   # an identified item with no posting word in its path
    title_words = token_set(rec.title, 3)
    echo = bool(qwords) and len(title_words & qwords) >= max(1, min(2, len(qwords)))
    role = bool(title_words & ROLE_WORDS)
    s = path + (1.0 if on_host else 0.0) + (1.0 if echo else 0.0) + (0.5 if role else 0.0)
    return RecordJobness(s, path, on_host, echo, role, ident or on_host)


def job_related_list(listing: Any, query: str | None) -> tuple[float, int]:
    """``(share, records)`` of the best run whose records are *about* jobs
    (score >= 1 without the specificity test), by the default thresholds.

    For the page-family features only: a results page of category links
    ("1,034 software engineer jobs in Chicago | Glassdoor") is still a
    result list, though it is not a list of postings. ``(0.0, 0)`` if none."""
    qwords = _query_words(query)
    best = (0.0, 0)
    for rr in listing.runs:
        if not rr.records or rr.run.feature("chrome") or rr.run.feature("menu_like") \
                or rr.run.feature("nested_share") >= 0.5:
            continue
        per = [jobness(r, qwords, ()) for r in rr.records]
        share = sum(1 for p in per if p.score >= 1.0) / len(per)
        routed = sum(1 for r in rr.records if r.state == L.RESOLVED) / len(per)
        if share >= 0.5 and routed >= 0.5 and len(per) >= 2 and share > best[0]:
            best = (share, len(per))
    return best


def _norm_title(t: str) -> str:
    return " ".join(t.casefold().split())


def _hidden_from_assistive_tech(rec: RecordReading, vis: Any) -> bool:
    if vis is None:
        return False
    nodes = list(rec.nodes) + ([rec.title_node] if rec.title_node >= 0 else [])
    return any(vis.aria_hidden[n] for n in nodes)


def decoy_clones(listing: Any, vis: Any) -> set[tuple[int, int]]:
    """(run, record) positions of hidden copies of visible records.

    A results page can carry decoy cards: a copy of a real card, hidden from
    assistive technology (``aria-hidden="true"``, often ``tabindex="-1"``),
    whose link carries a made-up identifier. A person never reaches it; a
    bot that follows it identifies itself. Measured on Indeed (owner capture
    2026-11-03: ``job_fedcba9876543210``; live run 2026-11-08: ``jk=
    456789abcdef0123`` and ``jk=abcdef0123456789``, each a copy of a visible
    card, two of them visited). A hidden record whose title is also a
    visible record's title is such a copy. Hidden records with no visible
    twin are left alone (a carousel may hide real slides)."""
    if vis is None:
        return set()
    visible: set[str] = set()
    hidden: list[tuple[int, int, str]] = []
    for k, rr in enumerate(listing.runs):
        for j, rec in enumerate(rr.records):
            t = _norm_title(rec.title)
            if not t:
                continue
            if _hidden_from_assistive_tech(rec, vis):
                hidden.append((k, j, t))
            else:
                visible.add(t)
    return {(k, j) for k, j, t in hidden if t in visible}


def _run(q: Any, params: Mapping[str, Any]) -> Ok[JobList] | Abstain:
    listing = q.need_ok("listing")
    clones = decoy_clones(listing, q.maybe("visibility"))
    per_run: dict[int, tuple[RecordJobness, ...]] = {}
    hosts = tuple(h.strip().lower() for h in str(params["posting_hosts"]).split(",") if h.strip())
    qwords = _query_words(q.obs.query)
    best: tuple[float, JobList] | None = None
    passing: list[int] = []
    seen: list[str] = []
    for k, rr in enumerate(listing.runs):
        if not rr.records:
            continue
        if rr.run.feature("chrome") or rr.run.feature("menu_like"):
            seen.append(f"run {k}: navigation/menu, not a list of postings")
            continue
        if rr.run.feature("nested_share") >= 0.5:
            seen.append(f"run {k}: a list of lists, its members are not records")
            continue
        per = tuple(dataclasses.replace(jobness(r, qwords, hosts), clone=(k, j) in clones)
                    for j, r in enumerate(rr.records))
        share = sum(1 for p in per if p.job_like) / len(per)
        routed = sum(1 for r in rr.records if r.state == L.RESOLVED) / len(per)
        seen.append(f"run {k}: job-like {share:.2f}, routed {routed:.2f}, n={len(per)}")
        per_run[k] = per
        if share >= float(params["min_share"]) and routed >= float(params["min_routed"]) \
                and len(per) >= int(params["min_records"]):
            passing.append(k)
            value = rr.run.score + 2.0 * share
            if best is None or value > best[0]:
                best = (value, JobList(k, rr, round(share, 6), round(routed, 6), per, ()))
    ev = tuple(Evidence("run-jobness", s) for s in seen[:8])
    if not qwords:
        ev += (Evidence("no-query", "query echo unavailable: observation carries no search words"),)
    if best is None:
        return Abstain("no-job-list", ev)
    chosen = best[1]
    if clones:
        ev += (Evidence("decoy-clones", f"{len(clones)} hidden copies of visible records, not job-like"),)
    others = tuple(k for k in passing if k != chosen.run_index)
    tau = float(params["merge_tau"])
    merged = list(chosen.reading.records)
    merged_per = list(chosen.per_record)
    for k in others:
        rr = listing.runs[k]
        if signature_similarity(chosen.reading.run, rr.run) >= tau:
            merged.extend(rr.records)
            merged_per.extend(per_run[k])
    chosen = JobList(chosen.run_index, chosen.reading, chosen.share, chosen.routed_share,
                     chosen.per_record, others, tuple(merged), tuple(merged_per))
    return Ok(chosen, confidence=min(1.0, best[1].share), evidence=ev)


TOOL = ToolSpec(
    id="joblist", ct_id="CT-T-008/G", version="0.4.0", run=_run, needs=("listing", "visibility"),
    params=(
        ParamSpec("min_share", 0.5, 0.0, 1.0, doc="share of records that must look like postings"),
        ParamSpec("min_routed", 0.5, 0.0, 1.0, doc="share of records with a usable route"),
        ParamSpec("min_records", 2, 1, 100),
        ParamSpec("merge_tau", 0.75, 0.3, 1.0,
                  doc="consensus-skeleton similarity for merging a split list's runs"),
        ParamSpec("posting_hosts", "", doc="comma-separated hosts from the consumer's ATS registry"),
    ),
    summary="the job-list gate over ranked runs",
)

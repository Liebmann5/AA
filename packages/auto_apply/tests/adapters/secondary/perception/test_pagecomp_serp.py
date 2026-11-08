"""S6 step 1: search-results pages read by pagecomp.

The page shapes are the failures of the live run of 2026-11-07: Indeed's
cards titled by their "full details of ..." label, Indeed's related-search
links taken for jobs, and the DOM miner re-reading a page the reader had
judged empty.
"""

from __future__ import annotations

from typing import Any

from auto_apply.adapters.secondary.discovery.components.page_understanding_extractor import (
    FallbackSerpExtractor,
)
from auto_apply.adapters.secondary.perception.pagecomp_serp import (
    NOT_A_JOB_LIST,
    PagecompSerpAdapter,
    _card_fields,
    query_from_url,
)
from auto_apply.domain.ports.page_understanding_port import PageContext, SERPStructure
from pagecomp.access import ObservationOutcome
from pagecomp.observation import observe_html

URL = "https://www.indeed.com/jobs?q=Backend+Engineer&l=Chicago%2C+IL"

CARDS = "".join(
    f'<li><div class="job_seen_beacon"><h2 class="jobTitle">'
    f'<a href="/rc/clk?jk={k:016x}&amp;bb=oHxDlT{k}" aria-label="full details of Backend Engineer {k}">'
    f'<span title="Backend Engineer {k}">Backend Engineer {k}</span></a></h2>'
    f'<div><span data-testid="company-name">Acme Corp {k}</span>'
    f'<div data-testid="text-location">Chicago, IL</div></div>'
    f'<div><span>$120,000 - $150,000 a year</span></div><span>Posted 3 days ago</span></div></li>'
    for k in range(8))
RELATED = "".join(
    f'<li><a href="/q-backend-engineer-{w}-l-chicago,-il-jobs.html">backend engineer {w}</a></li>'
    for w in ("remote", "entry level", "senior", "python", "java", "intern"))
# Indeed's decoy: a hidden copy of a visible card with a made-up id (live run
# 2026-11-08 visited two of these: jk=456789abcdef0123, jk=abcdef0123456789).
DECOY = ('<li><div class="job_seen_beacon" aria-hidden="true" tabindex="-1"><h2 class="jobTitle">'
         '<a href="/viewjob?jk=456789abcdef0123">Backend Engineer 3</a></h2>'
         '<div><span>Acme Corp 3</span><div>Chicago, IL</div></div></div></li>')
INDEED = (f"<html><body><main><ul class='jobsearch-ResultsList'>{CARDS}{DECOY}</ul></main>"
          f"<aside><h3>People also searched</h3><ul>{RELATED}</ul></aside></body></html>")
ONLY_RELATED = f"<html><body><main><h1>Searches</h1><ul>{RELATED}</ul></main></body></html>"


class FakeBrowser:
    def __init__(self, html: str, url: str = URL) -> None:
        self.html = html
        self.current_url = url
        self.title = "jobs"

    def execute_script(self, script: str, *args: Any) -> Any:
        return self.html


class Legacy:
    def __init__(self) -> None:
        self.serp_calls = 0

    def analyze_serp(self, context: PageContext) -> SERPStructure:
        self.serp_calls += 1
        return SERPStructure()

    def analyze_form(self, context: PageContext) -> Any:
        return "form"

    def analyze_job_listing(self, context: PageContext) -> Any:
        return "listing"


def _no_access(*_a: Any, **_k: Any) -> Any:
    raise RuntimeError("no browser access in this test")


def _adapter(html: str, legacy: Legacy | None = None, **kw: Any) -> PagecompSerpAdapter:
    kw.setdefault("access_factory", _no_access)
    return PagecompSerpAdapter(legacy or Legacy(), FakeBrowser(html), **kw)


def test_indeed_cards_are_read_with_visible_titles_company_and_routes() -> None:
    legacy = Legacy()
    s = _adapter(INDEED, legacy).analyze_serp(PageContext(url=URL))
    titles = [c.title for c in s.job_cards]
    assert titles == [f"Backend Engineer {k}" for k in range(8)], titles
    assert not any(t.startswith("full details of") for t in titles)
    assert [c.company for c in s.job_cards] == [f"Acme Corp {k}" for k in range(8)]
    assert all(c.location == "Chicago, IL" for c in s.job_cards)
    assert all(c.url.startswith("https://www.indeed.com/rc/clk?jk=") for c in s.job_cards)  # no decoy
    assert all(c.resolution_state == "resolved" for c in s.job_cards)
    assert legacy.serp_calls == 0 and s.page_verdict == ""


def test_a_page_of_related_searches_is_not_a_job_list_and_the_miner_is_not_asked() -> None:
    legacy = Legacy()
    adapter = _adapter(ONLY_RELATED, legacy)
    s = adapter.analyze_serp(PageContext(url=URL))
    assert s.job_cards == () and s.page_verdict == NOT_A_JOB_LIST
    assert legacy.serp_calls == 0

    class Fast:
        last_card_count = 0
        last_page_verdict = NOT_A_JOB_LIST

        def mine_jobs(self, source_name: str) -> list[Any]:
            return []

    class Miner:
        calls = 0

        def mine_jobs(self, source_name: str) -> list[Any]:
            Miner.calls += 1
            return ["junk"]

    chooser = FallbackSerpExtractor(Fast(), Miner())
    assert chooser.mine_jobs("Indeed") == [] and Miner.calls == 0
    assert chooser.route_label == "fast:not-a-job-list"


def test_access_read_is_used_when_it_returns_a_page() -> None:
    used = []

    class Access:
        def __init__(self, target: Any, prefer_cdp: bool = True) -> None:
            used.append(prefer_cdp)

        def observe(self, request: Any) -> ObservationOutcome:
            assert request.query == "Backend Engineer" and request.max_nodes == 29000
            return ObservationOutcome(observe_html(INDEED, url=URL, query=request.query), False, ("cdp",))

    s = _adapter("<html></html>", access_factory=Access,
                 access={"max_nodes": 29000, "prefer_cdp": False}).analyze_serp(PageContext(url=URL))
    assert used == [False] and len(s.job_cards) == 8


def test_unreadable_page_and_reader_errors_fall_back_to_the_previous_reader() -> None:
    legacy = Legacy()

    class Dead(FakeBrowser):
        def execute_script(self, script: str, *args: Any) -> Any:
            raise RuntimeError("browser gone")

    PagecompSerpAdapter(legacy, Dead(""), access_factory=_no_access).analyze_serp(PageContext(url=URL))
    assert legacy.serp_calls == 1
    adapter = _adapter(INDEED, legacy)
    assert adapter.analyze_form(PageContext()) == "form"
    assert adapter.analyze_job_listing(PageContext()) == "listing"


def test_posting_hosts_from_the_ats_registry_reach_the_gate() -> None:
    adapter = _adapter(INDEED, posting_hosts=["greenhouse.io", " Lever.co ", ""])
    assert adapter._params.for_tool("joblist")["posting_hosts"] == "greenhouse.io,lever.co"


def test_query_and_card_fields() -> None:
    assert query_from_url(URL) == "Backend Engineer"
    assert query_from_url("https://www.google.com/search?q=site%3Agreenhouse.io+backend") \
        == "site:greenhouse.io backend"
    assert query_from_url("https://jobs.example/") is None
    assert _card_fields(["Backend Engineer", "Easily apply", "PwC", "12 Days Ago", "Hybrid",
                         "Chicago, IL", "99K-232K Annually"], "Backend Engineer") == ("PwC", "Chicago, IL")
    assert _card_fields(["DoorDash USA", "Los Angeles, CA"], "Engineer") == ("DoorDash USA", "Los Angeles, CA")
    assert _card_fields(["Acme", "Remote"], "Engineer") == ("Acme", "Remote")
    assert _card_fields(["https://x.breezy.hr › p › 1", "Posted today"], "T") == ("", "")


GOOGLE_URL = "https://www.google.com/search?q=site%3Ajobs.jobvite.com+%28%22Backend+Engineer%22%29"
GOOGLE = "<html><body><div id=search>" + "".join(
    f'<div class="g"><a href="https://www.google.com/goto?url=CAESaQHEIkXX{k}ps5J-FMErPI3-uLvCN34nwjoVgXqYGg-rMNPtp4yhpzJ36ASZ7vZvcej" jsname="UWckNb">'
    f'<h3>Backend Engineer {k} - Acme {k}</h3><div><cite>https://jobs.jobvite.com › acme{k} › job › oX{k}abcdE</cite>'
    f'</div></a><div>Acme {k} is hiring a Backend Engineer to build APIs.</div></div>'
    for k in range(6)) + "</div></body></html>"


def test_opaque_results_carry_the_destination_the_page_shows() -> None:
    """Google's /goto hides the destination; the card keeps the destination the
    page shows beside it, so the site-search shape check can use it."""
    s = PagecompSerpAdapter(Legacy(), FakeBrowser(GOOGLE, GOOGLE_URL), access_factory=_no_access,
                            posting_hosts=["jobvite.com"]).analyze_serp(PageContext(url=GOOGLE_URL))
    assert len(s.job_cards) == 6
    assert all(c.url.startswith("https://www.google.com/goto?url=") for c in s.job_cards)
    assert all(c.shown_destination.startswith("jobs.jobvite.com") for c in s.job_cards), \
        [c.shown_destination for c in s.job_cards]


BING_URL = "https://www.bing.com/search?q=site%3Ajobs.jobvite.com+%22Backend+Engineer%22"
BING = "<html><body><main><h2>Web results</h2><ol id=b_results>" + "".join(
    f'<li class="b_algo"><div>greenhouse.io</div><cite>https://job-boards.greenhouse.io › co{k} › jobs</cite>'
    f'<h2><a href="https://job-boards.greenhouse.io/co{k}/jobs/53941280{k:02d}">'
    f'Job Application for Backend Engineer at Co {k}</a></h2>'
    f'<p>Co {k} is hiring a backend engineer for APIs.</p></li>'
    for k in range(6)) + "</ol></main></body></html>"


def test_an_engine_card_never_names_the_company() -> None:
    """TEETH. Live run 2026-11-08: Google cards got company "Web results"
    (the engine's section heading) and "Jobvite" (the site name); Bing's
    Greenhouse cards would all share "greenhouse.io". One shared company
    lets the per-company application cap block every other hit. On an
    engine's page the company stays unknown; a job board's cards still name
    their employer (the Indeed test above)."""
    s = PagecompSerpAdapter(Legacy(), FakeBrowser(BING, BING_URL), access_factory=_no_access,
                            posting_hosts=["greenhouse.io"],
                            engine_hosts=["bing.com", "google.com"]).analyze_serp(PageContext(url=BING_URL))
    assert len(s.job_cards) == 6
    assert all(c.company == "" for c in s.job_cards), [c.company for c in s.job_cards]
    indeed = _adapter(INDEED, engine_hosts=["bing.com", "google.com"]).analyze_serp(PageContext(url=URL))
    assert indeed.job_cards[0].company == "Acme Corp 0"


def test_a_page_that_is_not_a_job_list_logs_what_it_did_hold(caplog) -> None:
    """The live run of 2026-11-08 logged only "job-like 0.00, n=9" for a
    Google site search that kept nothing; what the nine results were could
    not be told from the log."""
    import logging

    boards = "<html><body><main><ol>" + "".join(
        f'<li><h2><a href="https://board{k}.example/q-backend-engineer-l-chicago-jobs.html">'
        f"Backend Engineer jobs in Chicago {k}</a></h2><p>Browse jobs</p></li>" for k in range(4)
    ) + "</ol></main></body></html>"
    caplog.set_level(logging.INFO)
    s = PagecompSerpAdapter(Legacy(), FakeBrowser(boards, BING_URL), access_factory=_no_access,
                            engine_hosts=["bing.com"]).analyze_serp(PageContext(url=BING_URL))
    assert s.page_verdict == NOT_A_JOB_LIST
    line = next(r.getMessage() for r in caplog.records if "no list of job postings" in r.getMessage())
    assert "first results: 'Backend Engineer jobs in Chicago 0' @ board0.example" in line, line

"""Slice S1 acceptance on cleaned real pages: every fixture yields at least one
record with both a title and an eligible link, and every card gets one fate.

Fixtures (``fixtures/``) are cleaned rendered DOMs from the comprehension
blueprint's pass-2 specimens, taken in a data-centre container on 2026-11-02
(environment ``cloud``). They are kept on the owner's machine and never
committed (``fixtures/.gitignore``); a pin whose page is absent skips. They
guard code against regressions; they are never
proof of AA's live behaviour (CT-Q-027). Each file's first line names its
source and the cleaning applied.

Google's results page cannot be reached from a data centre, and Lever's
``robots.txt`` restricts automated capture, so neither was captured here. The owner saves them on his own machine to the paths below; until a file
is there, its pin skips and says how to supply it.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.browser

FIXTURES = Path(__file__).parent / "fixtures"
OWNER = FIXTURES / "owner"

# (file, page URL the record resolves against, minimum records with title and link)
COMMITTED = [
    ("bing_site_jobvite.html",
     "https://www.bing.com/search?q=site%3Ajobs.jobvite.com+software+engineer", 8),
    ("jobvite_nutanix.html", "https://jobs.jobvite.com/nutanix", 50),
    ("linkedin_guest_jobs.html",
     "https://www.linkedin.com/jobs/search/?keywords=software%20engineer", 4),
    ("ashby_linear.html", "https://jobs.ashbyhq.com/linear", 10),
]

OWNER_SUPPLIED = [
    ("google_results.html", "https://www.google.com/search"),
    ("lever_board.html", "https://jobs.lever.co/"),
]

_HOW = (
    "Save it on your own machine: open the page in Chrome in a private window "
    "(signed out), let it load, open DevTools (F12) > Elements, right-click the "
    "<html> line > Copy > Copy outerHTML, paste into a new UTF-8 file saved as "
    "{path}. Put the page's address on the first line as an HTML comment: "
    "<!-- Source: https://... -->"
)


def _read_serp(chrome, page_server, name: str, html: str, page_url: str):
    from auto_apply.adapters.secondary.browser.selenium_adapter import SeleniumAdapter
    from auto_apply.adapters.secondary.discovery.components.page_understanding_extractor import (
        PageUnderstandingExtractor,
    )
    from auto_apply.adapters.secondary.perception.math_dom_adapter import (
        MathDOMAdapter,
        MathPageUnderstandingAdapter,
    )
    from auto_apply.domain.services.dom_segmentation import MathFormUnderstandingService

    page_server(chrome, f"/{name}", html)
    understanding = MathPageUnderstandingAdapter(
        MathDOMAdapter(SeleniumAdapter(chrome)), MathFormUnderstandingService()
    )
    # The extractor reads the page URL from the browser; report the source URL
    # so links resolve as they did on the live page.
    browser = SimpleNamespace(current_url=page_url, title="")
    extractor = PageUnderstandingExtractor(understanding, browser)
    jobs = extractor.mine_jobs("Fixture")
    return jobs, extractor.last_page_record


def _assert_accepts(jobs, record, minimum: int) -> None:
    from auto_apply.domain.models.page_record import DecisionStage

    assert len(jobs) >= max(1, minimum), record.to_level(1)["counts"]
    assert all(job.title.strip() and job.url.startswith("http") for job in jobs)
    found = [d.card_index for d in record.decisions if d.stage is DecisionStage.FOUND]
    fates = [d.card_index for d in record.decisions if d.stage is DecisionStage.FATE]
    assert sorted(found) == sorted(fates) == list(range(len(found)))
    assert record.observation is not None and record.observation.node_count > 0


@pytest.mark.parametrize("name,page_url,minimum", COMMITTED, ids=[c[0] for c in COMMITTED])
def test_fixture_resolves_records_with_title_and_link(
    chrome, page_server, name: str, page_url: str, minimum: int
) -> None:
    path = FIXTURES / name
    if not path.is_file():
        pytest.skip(f"{name} is kept on the owner's machine, not committed; absent here.")
    html = path.read_text(encoding="utf-8")
    assert len(html.encode("utf-8")) < 300_000
    jobs, record = _read_serp(chrome, page_server, name, html, page_url)
    _assert_accepts(jobs, record, minimum)


def _strip_active_content(html: str) -> str:
    """An owner-saved page may still hold scripts; never run them here."""
    html = re.sub(r"(?is)<script\b.*?</script\s*>", "", html)
    html = re.sub(r"(?is)<meta[^>]+http-equiv\s*=\s*['\"]?refresh[^>]*>", "", html)
    return re.sub(r"(?i)\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html)


def test_owner_supplied_pages_resolve_records(chrome, page_server) -> None:
    """Google (required) and Lever (optional) pages saved by the owner.

    Skips, naming the path and the steps, until the Google page is there.
    """
    supplied = [(n, u) for n, u in OWNER_SUPPLIED if (OWNER / n).is_file()]
    if not (OWNER / "google_results.html").is_file():
        pytest.skip("google_results.html not supplied yet. "
                    + _HOW.format(path=OWNER / "google_results.html"))
    for name, default_url in supplied:
        html = (OWNER / name).read_text(encoding="utf-8", errors="replace")
        match = re.search(r"Source:\s*(https?://\S+?)\s*-->", html[:2000])
        page_url = match.group(1) if match else default_url
        jobs, record = _read_serp(
            chrome, page_server, name, _strip_active_content(html), page_url
        )
        _assert_accepts(jobs, record, 1)

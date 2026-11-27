"""S8: failure classes (ALG-026) and the review page."""

from __future__ import annotations

from html.parser import HTMLParser

from pagecomp import Analyzer, observe_html
from pagecomp import workbench as W

LIST = ("<main><ul>" + "".join(f'<li><h3><a href="https://jobs.example/job/{k}001">Engineer {k}</a></h3></li>'
                               for k in range(6)) + "</ul><a rel=next href='?p=2'>Next</a></main>")


def _an(html, url="https://jobs.example/search?q=engineer", query="engineer"):
    return Analyzer(observe_html(html, url=url, query=query))


def test_access_blocked():
    an = _an("<iframe src='https://challenges.cloudflare.com/x'></iframe>", url="https://x.example/cdn-cgi/challenge")
    assert W.classify_failure(an, engine="Discovery").kind == W.ACCESS_BLOCKED


def test_workflow_change_when_plan_lacks_a_needed_step():
    fc = W.classify_failure(_an(LIST), engine="Discovery", plan_steps=())
    assert fc.kind == W.WORKFLOW_CHANGE and fc.needed_steps == ("advance_page",)
    assert W.classify_failure(_an(LIST), engine="Discovery", plan_steps=("advance_page",)).kind == W.OK


def test_workflow_bug_when_engine_contradicts_a_confident_finding():
    fc = W.classify_failure(_an(LIST), engine="Discovery", plan_steps=("advance_page",),
                            acted_against=("formread",))
    assert fc.kind == W.WORKFLOW_BUG


def test_missing_tool_and_unknown_phenomenon():
    fc = W.classify_failure(_an("<main><h1>About us</h1></main>"), engine="Discovery")
    assert fc.kind in (W.MISSING_TOOL, W.UNKNOWN_PHENOMENON) and "joblist abstained" in fc.evidence[-1]


class _Check(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.scripts = [], 0

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.scripts += tag == "script"


def test_review_page_is_self_contained_and_marks_used_tools():
    an = _an(LIST + "<form><label for=e>Email</label><input id=e type=email></form>")
    page = W.review_html(an, failure=W.classify_failure(an, engine="Discovery"))
    c = _Check()
    c.feed(page)
    assert c.scripts == 0 and "http-equiv" not in page and "<link" not in page
    assert "class=used><span>joblist" in page and "class=unused><span>arrival" in page
    assert "Job list (6 records)" in page and "Discovery" in page and "Applications" in page
    assert "&lt;" not in page.split("<h1>")[0]


def test_review_escapes_hostile_text():
    an = _an('<main><ul>' + "".join(f'<li><h3><a href="https://j.example/job/{k}001">'
                                    f'&lt;script&gt;x{k}&lt;/script&gt;</a></h3></li>' for k in range(4)) + "</ul></main>",
             query="script")
    page = W.review_html(an)
    assert "<script>" not in page


def test_ledger_coverage_counts():
    assert W.ledger_coverage([{"status": "[x]"}, {"status": "[ ]"}, {"status": "[x]"}]) == {"[x]": 2, "[ ]": 1}

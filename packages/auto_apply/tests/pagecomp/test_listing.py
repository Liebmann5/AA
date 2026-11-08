"""CT-T-009 record reading: title choice."""

from __future__ import annotations

from pagecomp import observe_html
from pagecomp.tools.listing import read_record


def _card_title(card_html: str) -> str:
    obs = observe_html(f"<main><ul><li>{card_html}</li></ul></main>", url="https://jobs.example/search?q=x")
    doc = obs.doc
    li = next(i for i in range(len(doc)) if doc.tag_name(i) == "li")
    return read_record(doc, (li,), None, "https://jobs.example/search?q=x").title


def test_a_heading_wrapping_a_posting_link_beats_one_wrapping_a_company_link():
    """Review round 2 (2026-11-08): for <h3><a href=...>Title</a></h3> the
    posting-address evidence was never counted (the anchor is *inside* the
    heading), so an earlier heading linking to the company page won."""
    card = ('<h2><a href="/company/acme-corporation">Acme Corporation Inc</a></h2>'
            '<h3><a href="/jobs/view/4012345">Backend Engineer</a></h3><span>Chicago, IL</span>')
    assert _card_title(card) == "Backend Engineer"


def test_related_searches_are_not_the_job_list_real_cards_are():
    """Indeed's results page carries a run of real cards (links with no
    posting word: /rc/clk?jk=...) and a run of related searches (category
    links with role words). v0.4 chose the related searches."""
    from pagecomp import Analyzer
    cards = "".join(
        f'<li><div><h2><a href="/rc/clk?jk={k:016x}&amp;bb=abc">Software Engineer {k}</a></h2>'
        f'<span>Acme {k}</span><span>Chicago, IL</span></div></li>' for k in range(10))
    related = "".join(
        f'<li><a href="/q-software-engineer-{w}-l-chicago,-il-jobs.html">software engineer {w}</a></li>'
        for w in ("junior", "senior", "intern", "remote", "entry", "lead", "staff", "contract"))
    html = f"<main><ul>{cards}</ul></main><aside><h3>People also searched</h3><ul>{related}</ul></aside>"
    an = Analyzer(observe_html(html, url="https://www.indeed.com/jobs?q=backend&l=Chicago", query="backend"))
    titles = [r.title for r in an.value("joblist").records]
    assert titles and all(t.startswith("Software Engineer ") for t in titles), titles


def test_hidden_copies_of_visible_cards_are_decoys_not_jobs():
    """Indeed plants a hidden copy (aria-hidden, tabindex -1, made-up id) of
    a real card; following it identifies a bot. Live run 2026-11-08 visited
    two such links (jk=456789abcdef0123, jk=abcdef0123456789)."""
    from pagecomp import Analyzer
    cards = "".join(
        f'<li><div><h2><a href="/rc/clk?jk={k:016x}&amp;bb=abc">Software Engineer {k}</a></h2>'
        f'<span>Acme {k}</span></div></li>' for k in range(6))
    decoy = ('<li><div aria-hidden="true" tabindex="-1"><h2><a href="/viewjob?jk=fedcba9876543210">'
             'Software Engineer 3</a></h2><span>Acme 3</span></div></li>')
    lone_hidden_slide = ('<li><div aria-hidden="true"><h2><a href="/rc/clk?jk=00000000000000aa">'
                         'Data Engineer</a></h2><span>Beta</span></div></li>')
    html = f"<main><ul>{cards}{decoy}{lone_hidden_slide}</ul></main>"
    v = Analyzer(observe_html(html, url="https://www.indeed.com/jobs?q=software+engineer",
                              query="software engineer")).value("joblist")
    by_url = {r.link.url: p for r, p in zip(v.records, v.record_jobness)}
    assert by_url["https://www.indeed.com/viewjob?jk=fedcba9876543210"].clone
    assert not by_url["https://www.indeed.com/viewjob?jk=fedcba9876543210"].job_like
    assert not by_url["https://www.indeed.com/rc/clk?jk=00000000000000aa"].clone   # no visible twin
    assert sum(1 for p in v.record_jobness if p.job_like) == 7   # 6 cards + the lone hidden slide

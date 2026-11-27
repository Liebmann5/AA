"""Records (ALG-001..003): lemma properties and the defects they fix."""

from __future__ import annotations

import random

from pagecomp import Analyzer, Ok, observe_html
from pagecomp.tools.records import ruzicka


def _ms(rnd, keys=12, hi=5):
    return {k: rnd.randint(1, hi) for k in rnd.sample(range(30), rnd.randint(1, keys))}


def _j(a, b):
    return ruzicka(a, b, sum(a.values()), sum(b.values()))


def test_lemma1_soergel_distance_is_a_metric():
    rnd = random.Random(1)
    for _ in range(400):
        a, b, c = _ms(rnd), _ms(rnd), _ms(rnd)
        assert abs(_j(a, b) - _j(b, a)) < 1e-12
        assert _j(a, a) == 1.0
        assert (1 - _j(a, c)) <= (1 - _j(a, b)) + (1 - _j(b, c)) + 1e-12


def test_lemma2_tolerance_bound():
    rnd = random.Random(2)
    for _ in range(400):
        a = _ms(rnd)
        b = dict(a)
        for _ in range(rnd.randint(0, 3)):
            k = rnd.randrange(40)
            b[k] = b.get(k, 0) + 1
        s = sum(a.values())
        d = sum(abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b))
        if d < s:
            assert _j(a, b) >= (s - d) / s - 1e-12


CARD = ('<li class="{cls}"><div><h3><a href="https://boards.example/jobs/{n}123">'
        '<span>{title}</span></a></h3><div>Acme</div><div>Remote</div>{badge}</div></li>')


def _board(n=8, promoted=(), badge=()):
    items = []
    for k in range(n):
        items.append(CARD.format(cls="card promoted featured" if k in promoted else "card", n=k,
                                 title=f"Backend Engineer {k}",
                                 badge="<span>New</span>" if k in badge else ""))
    nav = "".join(f'<li><a href="/p{k}"><span>Menu {k}</span></a></li>' for k in range(6))
    return f"<nav><ul>{nav}</ul></nav><main><ul>{''.join(items)}</ul></main>"


def _top(html, query=None):
    an = Analyzer(observe_html(html, url="https://boards.example/search", query=query), strict=True)
    return an, an.value("records")


def test_promoted_and_badged_cards_stay_in_one_run_defects_1_and_8():
    an, recs = _top(_board(promoted=(2, 5), badge=(3,)))
    top = recs.runs[0]
    assert len(top.members) == 8
    assert an.obs.doc.tag_name(top.parent) == "ul"


def test_navigation_runs_rank_below_content_and_never_pass_the_gate():
    an, recs = _top(_board())
    nav_runs = [r for r in recs.runs if r.feature("chrome")]
    assert nav_runs and recs.runs[0].feature("chrome") == 0
    jl = an.value("joblist")
    assert jl is not None and len(jl.reading.records) == 8


def test_two_row_records_found_with_window_2():
    rows = "".join(f'<tr><td><a href="https://x.example/job/{k}001">Data Engineer {k}</a></td></tr>'
                   f'<tr><td><span>{k} points</span> | <span>2 hours ago</span> | <span>discuss</span></td></tr>'
                   for k in range(10))
    _, recs = _top(f"<table><tbody>{rows}</tbody></table>")
    assert any(r.width == 2 and len(r.members) == 10 for r in recs.runs)


def test_title_from_full_subtree_and_link_resolved():
    an, _ = _top(_board(), query="backend engineer")
    jl = an.value("joblist")
    rec = jl.reading.records[0]
    assert rec.title == "Backend Engineer 0"
    assert rec.state == "resolved" and rec.link.url.startswith("https://boards.example/jobs/")


def test_no_repeat_abstains():
    an = Analyzer(observe_html("<main><h1>One posting</h1><p>Text</p></main>", url="https://x.example/"))
    res = an.get("records").result
    assert not isinstance(res, Ok) and res.reason == "no-repeat"


def test_news_feed_is_not_a_job_list():
    cards = "".join(f'<li><h3><a href="https://news.example/2026/11/{k}/story-about-markets">'
                    f'Markets rally as stocks climb {k}</a></h3><p>Reuters</p></li>' for k in range(8))
    an = Analyzer(observe_html(f"<main><ul>{cards}</ul></main>", url="https://www.bing.com/?form=REDIRERR",
                               query="backend engineer jobs"))
    res = an.get("joblist").result
    assert not isinstance(res, Ok) and res.reason == "no-job-list"


def test_one_ad_between_cards_is_bridged_not_a_split():
    cards = [CARD.format(cls="card", n=k, title=f"Backend Engineer {k}", badge="") for k in range(8)]
    ad = '<li class="ad"><iframe src="https://ads.example/x"></iframe><p>Sponsored</p></li>'
    html = f"<main><ul>{''.join(cards[:4])}{ad}{''.join(cards[4:])}</ul></main>"
    _, recs = _top(html)
    top = recs.runs[0]
    assert len(top.members) == 8 and len(top.gaps) == 1


def test_two_foreign_blocks_do_not_bridge():
    cards = [CARD.format(cls="card", n=k, title=f"Backend Engineer {k}", badge="") for k in range(8)]
    gap = '<li><h2>More jobs</h2></li><li><p>Newsletter</p><input name=email></li>'
    _, recs = _top(f"<main><ul>{''.join(cards[:4])}{gap}{''.join(cards[4:])}</ul></main>")
    assert max(len(r.members) for r in recs.runs) == 4


def test_a_list_split_across_sibling_lists_is_read_whole():
    def ul(lo, hi):
        return "<ul>" + "".join(CARD.format(cls="card", n=k, title=f"Backend Engineer {k}", badge="")
                                for k in range(lo, hi)) + "</ul>"
    html = f"<main>{ul(0, 5)}<div class=promo><p>Ad</p></div>{ul(5, 9)}{ul(9, 12)}</main>"
    an, _ = _top(html, query="backend engineer")
    jl = an.value("joblist")
    assert len(jl.reading.records) == 5 and len(jl.records) == 12
    titles = [r.title for r in jl.records]
    assert len(set(titles)) == 12

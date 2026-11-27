"""S9a: Controls (CT-T-027) per widget kind, and ALG-027 effect outcomes."""

from __future__ import annotations

from pagecomp import Analyzer, observe_html
from pagecomp import effect as E

RESULTS = ("<main><ul>" + "".join(
    f'<li><h3><a href="https://jobs.example/job/{k}001">Engineer {k}</a></h3><p>Acme</p></li>'
    for k in range(6)) + "</ul></main>")


def _controls(html, url="https://jobs.example/search?q=engineer"):
    return Analyzer(observe_html(html, url=url), strict=True).value("controls")


def _one(ctl, piece):
    found = ctl.by_piece(piece)
    assert found, (piece, [(b.widget_kind, b.piece, b.name) for b in ctl.bindings])
    return found[0]


def test_search_and_location_boxes():
    ctl = _controls('<form role=search action="/search"><input name=q value="engineer">'
                    '<input name=l placeholder="City, state"><button>Search</button></form>' + RESULTS)
    kw = _one(ctl, "keywords")
    assert kw.widget_kind == "text" and kw.current == ("engineer",) and kw.region == "search"
    assert _one(ctl, "location").widget_kind == "text"


def test_select_sort_with_current_default():
    ctl = _controls('<label for=s>Sort by</label><select id=s><option>Relevance</option>'
                    '<option selected>Date</option></select>' + RESULTS)
    b = _one(ctl, "sort")
    assert b.widget_kind == "select" and b.options == ("Relevance", "Date") and b.current == ("Date",)


def test_checkbox_facet_group_named_by_heading():
    html = ('<aside><h4>Job type</h4><div>'
            '<label><input type=checkbox name=jt value=ft checked> Full-time</label>'
            '<label><input type=checkbox name=jt value=pt> Part-time</label>'
            '<label><input type=checkbox name=jt value=c> Contract</label></div></aside>' + RESULTS)
    b = _one(_controls(html), "job_type")
    assert b.widget_kind == "checkbox_group" and b.current == ("Full-time",) and b.region == "facet_sidebar"


def test_unknown_named_group_becomes_a_facet_never_unknown_operated():
    html = ('<aside><h4>Team</h4><div><label><input type=checkbox name=t> Platform</label>'
            '<label><input type=checkbox name=t> Data</label></div></aside>' + RESULTS)
    b = _controls(html).bindings[0]
    assert b.piece == "facet:team"


def test_radio_date_posted_and_switch_remote():
    html = ('<fieldset><legend>Date posted</legend>'
            '<label><input type=radio name=d checked> Any time</label>'
            '<label><input type=radio name=d> Past week</label></fieldset>'
            '<button role=switch aria-checked=false>Remote only</button>' + RESULTS)
    ctl = _controls(html)
    assert _one(ctl, "date_posted").widget_kind == "radio_group"
    sw = _one(ctl, "remote")
    assert sw.widget_kind == "switch" and sw.current == ("false",)


def test_menu_button_with_options_from_aria_controls():
    html = ('<button aria-haspopup=listbox aria-expanded=false aria-controls=m>Date posted</button>'
            '<ul id=m role=listbox hidden><li role=option>Last 24 hours</li><li role=option>Past week</li></ul>'
            + RESULTS)
    b = _one(_controls(html), "date_posted")
    assert b.widget_kind == "menu_button" and b.options == ("Last 24 hours", "Past week")


def test_slider_salary_with_bounds():
    html = ('<div role=slider aria-label="Minimum salary" aria-valuemin=0 aria-valuemax=300000 '
            'aria-valuenow=50000 tabindex=0></div>' + RESULTS)
    b = _one(_controls(html), "salary")
    assert b.widget_kind == "slider" and (b.minimum, b.maximum, b.current) == ("0", "300000", ("50000",))


def test_chip_is_a_removable_current_filter():
    html = '<div class=chips><span>Remote<button aria-label="Remove Remote filter">×</button></span></div>' + RESULTS
    b = _one(_controls(html), "remote")
    assert b.widget_kind == "chip" and b.region == "chip_bar"


def test_pagination_kinds():
    html = (RESULTS + '<nav aria-label="Pagination"><a href="?p=1" aria-current=page>1</a>'
            '<a href="?p=2">2</a><a href="?p=3">3</a><a rel=next href="?p=2">Next</a></nav>'
            '<button>Load more</button><a href="/blog">Read more</a>')
    ctl = _controls(html)
    assert _one(ctl, "page_number").current == ("1",)
    assert _one(ctl, "page_next").href == "?p=2"
    assert _one(ctl, "load_more").widget_kind == "link_set"
    assert all(b.name != "Read more" for b in ctl.bindings)


def test_drawer_and_apply_button_modes():
    html = ('<div role=dialog aria-label=Filters><label><input type=checkbox name=r> Remote</label>'
            '<label><input type=checkbox name=r> Hybrid</label></div>'
            '<form action="/jobs"><label for=s>Sort</label><select id=s><option>Newest</option></select>'
            '<button type=submit>Show results</button></form>' + RESULTS)
    ctl = _controls(html)
    assert _one(ctl, "remote").apply_mode == "drawer"
    assert _one(ctl, "sort").apply_mode == "apply_button"


def test_consent_and_application_controls_are_not_search_controls():
    html = ('<div id=onetrust-consent-sdk><label><input type=checkbox name=c> Analytics</label>'
            '<label><input type=checkbox name=c> Ads</label></div>'
            '<form><label for=e>Email</label><input id=e type=email><label for=f>First name</label>'
            '<input id=f><label for=r>Resume</label><input id=r type=file></form>')
    assert _controls(html).bindings == ()


# -- ALG-027 -----------------------------------------------------------------

B = frozenset({"a", "b", "c", "d"})


def test_effect_applied_learns_one_parameter():
    r = E.effect_check(B, frozenset({"a", "x", "y"}), url_b="https://j/s?q=e&utm_source=z",
                       url_a="https://j/s?q=e&remote=1&utm_source=w")
    assert r.outcome == E.APPLIED and r.candidate == ("remote", "1") and r.jaccard < 1


def test_effect_no_effect_even_when_url_moved_php226():
    r = E.effect_check(B, B, url_b="https://j/s?q=e", url_a="https://j/s?q=e&remote=1")
    assert r.outcome == E.NO_EFFECT and "url_changed" in r.evidence and r.candidate is None


def test_effect_empty_result_is_applied():
    r = E.effect_check(B, frozenset(), url_b="https://j/s", url_a="https://j/s?pay=500k",
                       after_empty_state=True)
    assert r.outcome == E.APPLIED and r.empty


def test_effect_contradicted_records():
    r = E.effect_check(B, frozenset({"x", "y"}), url_b="u", url_a="v", contradicted=2)
    assert r.outcome == E.CONTRADICTED


def test_effect_unknown_when_truncated_or_no_identities():
    assert E.effect_check(B, B, url_b="u", url_a="u", truncated=True).outcome == E.UNKNOWN
    assert E.effect_check(frozenset(), frozenset(), url_b="u", url_a="v").outcome == E.UNKNOWN


def test_count_mismatch_ph228():
    r = E.effect_check(B, frozenset({"a", "x", "y"}), url_b="u", url_a="v", count_a=1, page_size=25)
    assert "count_mismatch" in r.evidence


def test_two_confirmations_on_different_queries_promote():
    pl = E.ParameterLearner()
    assert not pl.confirm("jobs.example", "remote", "Remote", ("remote", "1"), "engineer")
    assert not pl.confirm("jobs.example", "remote", "Remote", ("remote", "1"), "Engineer ")
    assert pl.confirm("jobs.example", "remote", "Remote", ("remote", "1"), "nurse")
    assert pl.learned() == [("jobs.example", "remote", "Remote", "remote", "1")]


def test_confirm_and_reset_and_counts():
    assert E.confirm_candidate(frozenset("abcdefghij"), frozenset("abcdefghij"))
    assert not E.confirm_candidate(frozenset("abcd"), frozenset("wxyz"))
    assert E.reset_check(("Any",), ("Any",), ("Remote",)) == E.RESET
    assert E.total_count("Showing 1-25 of 1,234 jobs") == 1234
    assert E.total_count("312 jobs found") == 312
    assert E.says_empty("Sorry, no jobs found for your search")


def test_record_sets_from_a_real_reading():
    an = Analyzer(observe_html(RESULTS, url="https://jobs.example/search?q=engineer", query="engineer"))
    rs = E.record_set(an.value("joblist").records)
    assert len(rs) == 6 and all(x.startswith("https://jobs.example/job/") for x in rs)

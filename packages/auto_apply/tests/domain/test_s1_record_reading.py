"""Slice S1 pins: reading a title and a link from each record of a result list.

Synthetic DOM shapes for the cases the S1 trace found on real pages
(fixtures under tests/integration/result_lists/): a heading whose text sits
in a nested element (defect 4), two anchors in one card that lead to the same
destination, table rows titled only by their link (no heading), a footer list
that out-numbers the results, and a detected node below the record root.
Tests named ``..._teeth`` were written first and fail at the branch head.
"""

from __future__ import annotations

from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.ports.page_understanding_port import CardResolutionState
from auto_apply.domain.services.card_static_resolution import (
    extract_card_title,
    resolve_card_group,
)
from auto_apply.domain.services.dom_segmentation import MathFormUnderstandingService
from auto_apply.domain.services.url_evidence import evaluate_candidates

BOARD_URL = "https://jobs.board.example/acme"
SERP_URL = "https://search.example/search?q=engineer"


def _n(tag="div", attrs=(), text="", geom=None, children=(), depth=0) -> DOMNode:
    return DOMNode(
        tag=tag, attributes=tuple(attrs), text=text, geometry=geom,
        children=tuple(children), depth=depth,
    )


def _box(y: float, h: float = 90.0) -> Geometry:
    return Geometry(x=0, y=y, width=600, height=h)


def _serp_card(i: int, y: float, *, href: str, title_words: str) -> DOMNode:
    """A result card whose heading text is nested two elements deep."""
    heading = _n("h2", children=(
        _n("a", attrs=(("href", href),), children=(
            _n("strong", text=title_words), _n("span", text=f"role {i}"),
        )),
    ))
    url_line = _n("div", children=(_n("a", attrs=(("href", href),), text="search.example"),))
    return _n("li", attrs=(("class", "r"), ("data-id", f"k{i}")), geom=_box(y),
              children=(heading, url_line, _n("p", text="Snippet text")))


# ── defect 4: full-subtree text ───────────────────────────────────────────────


def test_heading_title_nested_in_span_teeth() -> None:
    card = _n("div", attrs=(("data-id", "a1"),), geom=_box(0), children=(
        _n("h3", children=(_n("span", text="Senior Platform Engineer"),)),
        _n("a", attrs=(("href", "/job/1"),), text="View"),
    ))
    assert extract_card_title(card) == "Senior Platform Engineer"


def test_heading_title_nested_two_levels_resolves_title_and_link_teeth() -> None:
    cards = [
        _serp_card(i, 100.0 * i, href=f"https://careers.acme.example/job/{i}",
                   title_words="Software Engineer")
        for i in range(3)
    ]
    root = _n("body", children=(_n("ol", children=cards),))
    job_cards, _ = resolve_card_group(cards, root, SERP_URL)
    assert [c.title for c in job_cards] == ["Software Engineer role 0",
                                             "Software Engineer role 1",
                                             "Software Engineer role 2"]
    assert all(c.url.startswith("https://careers.acme.example/job/") for c in job_cards)


def test_python_subtree_text_is_capped_and_flagged() -> None:
    from auto_apply.domain.models.math_dom import TEXT_CAP

    long = "word " * (TEXT_CAP // 2)
    node = _n("h3", children=(_n("span", text=long),))
    text, truncated = node.subtree_text()
    assert len(text) <= TEXT_CAP and truncated is True
    short, flag = _n("h3", children=(_n("span", text="Nurse"),)).subtree_text()
    assert (short, flag) == ("Nurse", False)


def test_adapter_supplied_full_text_and_name_win() -> None:
    node = DOMNode(tag="h3", full_text="Visible Title", accessible_name="Named Title")
    assert node.subtree_text() == ("Visible Title", False)
    assert extract_card_title(_n("div", children=(node,))) == "Named Title"


# ── one destination is one route ──────────────────────────────────────────────


def test_same_destination_anchors_are_one_route_teeth() -> None:
    cards = [
        _serp_card(i, 100.0 * i, href=f"https://www.search.example/ck/a?u=a1{'Q' * 50}{i}",
                   title_words="Data Analyst")
        for i in range(2)
    ]
    root = _n("body", children=(_n("ol", children=cards),))
    job_cards, _ = resolve_card_group(cards, root, SERP_URL)
    assert [c.resolution_state for c in job_cards] == [CardResolutionState.RESOLVED.value] * 2


def test_two_distinct_destinations_stay_multi_route() -> None:
    children = (
        _n("h3", text="Marine Engineer"),
        _n("a", attrs=(("href", f"/out?u={'Z9xQ' * 20}1"),), text="Apply now"),
        _n("a", attrs=(("href", f"/out?u={'Z9xQ' * 20}2"),), text="Apply now"),
    )
    card = _n("div", attrs=(("data-id", "x"),), geom=_box(0), children=children)
    root = _n("body", children=(card,))
    job_cards, _ = resolve_card_group([card], root, SERP_URL)
    assert job_cards[0].resolution_state == CardResolutionState.MULTI_ROUTE.value


# ── rows titled by their link (no heading) ────────────────────────────────────


def _row(i: int, title: str) -> DOMNode:
    return _n("tr", geom=_box(40.0 * i, 40), children=(
        _n("td", children=(_n("a", attrs=(("href", f"/acme/job/o{i}Xq"),), text=title),)),
        _n("td", text="Remote"),
    ))


_TITLES = ("Finance Manager", "Financial Analyst", "IT Audit Project Manager")


def test_anchor_named_rows_without_heading_resolve_teeth() -> None:
    rows = [_row(i, t) for i, t in enumerate(_TITLES)]
    root = _n("body", children=(_n("main", children=(_n("table", children=(_n("tbody", children=rows),)),)),))
    job_cards, report = resolve_card_group(rows, root, BOARD_URL)
    assert [c.title for c in job_cards] == list(_TITLES)
    assert [c.url for c in job_cards] == [f"https://jobs.board.example/acme/job/o{i}Xq" for i in range(3)]
    assert {c.title_source for c in job_cards} == {"anchor_name"}
    assert report.record_level == "detected"


def test_anchor_named_rows_inside_footer_get_no_title() -> None:
    rows = [_row(i, t) for i, t in enumerate(("About", "Accessibility", "User Agreement"))]
    root = _n("body", children=(_n("footer", children=(_n("table", children=rows),)),))
    job_cards, _ = resolve_card_group(rows, root, BOARD_URL)
    assert [c.title for c in job_cards] == ["", "", ""]


def test_anchor_names_repeating_across_rows_are_not_titles() -> None:
    rows = [_row(i, "Apply") for i in range(3)]
    root = _n("body", children=(_n("table", children=rows),))
    job_cards, _ = resolve_card_group(rows, root, BOARD_URL)
    assert [c.title for c in job_cards] == ["", "", ""]


# ── record root: the title can be above the detected node ─────────────────────


def test_record_root_lifts_to_level_holding_title_and_link_teeth() -> None:
    items = []
    for i in range(3):
        snippet = _n("div", attrs=(("data-snippet", f"s{i}"),), geom=_box(100.0 * i + 40, 40),
                     children=(_n("span", text=f"Snippet {i} about the role"),))
        items.append(_n("li", geom=_box(100.0 * i), children=(
            _n("a", attrs=(("href", f"https://careers.acme.example/job/{i}"),), children=(
                _n("h3", text=f"Welder {i}"),
            )),
            snippet,
        )))
    root = _n("body", children=(_n("ol", children=items),))
    detected = [li.children[1] for li in items]
    job_cards, report = resolve_card_group(detected, root, SERP_URL)
    assert [c.title for c in job_cards] == ["Welder 0", "Welder 1", "Welder 2"]
    assert all(c.url for c in job_cards)
    assert report.record_level == "+1"
    # identity is still learned where it is distinct, below the record root
    assert job_cards[0].identity_attribute == "data-snippet"


# ── dead-end wording inside a real title ──────────────────────────────────────


def test_dead_end_words_inside_job_titles_are_not_dead_ends_teeth() -> None:
    items = [
        {"href": "https://careers.acme.example/job/7", "text": "Help Desk Technician", "source": "static"},
        {"href": "https://careers.acme.example/job/8", "text": "Reporting Analyst - Terms and Pricing", "source": "static"},
    ]
    candidates, rejections = evaluate_candidates(
        items, title="Help Desk Technician", serp_host="search.example", base_url=SERP_URL
    )
    assert len(candidates) == 2 and not rejections


def test_dead_end_links_are_still_rejected() -> None:
    items = [{"href": f"https://search.example/{p}", "text": t, "source": "static"}
             for p, t in (("privacy", "Privacy Policy"), ("terms", "Terms of Use"),
                          ("help", "Help"), ("settings", "Cookie settings"))]
    candidates, rejections = evaluate_candidates(items, title="", serp_host="search.example",
                                                 base_url=SERP_URL)
    assert not candidates
    assert {r.reason for r in rejections} == {"dead-end text"}


# ── edge cases from 12 that S1 touches ────────────────────────────────────────


def test_link_without_href_is_never_a_resolved_link() -> None:
    cards = [_n("div", attrs=(("data-id", f"n{i}"),), geom=_box(100.0 * i), children=(
        _n("h3", text=f"Mechanic {i}"), _n("a", text="Details"),
    )) for i in range(2)]
    root = _n("body", children=cards)
    job_cards, _ = resolve_card_group(cards, root, BOARD_URL)
    assert all(c.url == "" for c in job_cards)
    assert all(not c.candidates for c in job_cards)
    assert {c.resolution_state for c in job_cards} == {CardResolutionState.NO_DESTINATION.value}


def test_identical_cards_are_separate_records() -> None:
    cards = [_serp_card(0, 100.0 * i, href="https://careers.acme.example/job/same",
                        title_words="Line Cook") for i in range(3)]
    root = _n("body", children=(_n("ol", children=cards),))
    job_cards, _ = resolve_card_group(cards, root, SERP_URL)
    assert len(job_cards) == 3
    assert [c.card_index for c in job_cards] == [0, 1, 2]
    assert all(c.url == "https://careers.acme.example/job/same" for c in job_cards)


def test_empty_list_returns_no_records() -> None:
    job_cards, report = resolve_card_group([], _n("body"), SERP_URL)
    assert job_cards == [] and report.record_level == ""


# ── chrome landmarks do not compete with the results ─────────────────────────


def _footer_item(i: int) -> DOMNode:
    return _n("li", attrs=(("data-tracking", "footer"),), geom=_box(2000.0 + 40 * i, 40),
              children=(_n("a", attrs=(("href", f"/legal/{i}"),), text=f"Footer link {i}"),))


def _result_item(i: int) -> DOMNode:
    return _n("li", attrs=(("data-id", f"r{i}"),), geom=_box(100.0 * i), children=(
        _n("h3", text=f"Electrician {i}"),
        _n("a", attrs=(("href", f"/jobs/view/{i}"),), text="View"),
    ))


def test_footer_list_does_not_outrank_results_teeth() -> None:
    results = [_result_item(i) for i in range(3)]
    footer = [_footer_item(i) for i in range(9)]
    root = _n("body", children=(
        _n("main", children=(_n("ul", children=results),)),
        _n("footer", children=(_n("ul", children=footer),)),
    ))
    structure = MathFormUnderstandingService().analyze(root, url=BOARD_URL, title="")
    assert [id(n) for n in structure.job_listings] == [id(n) for n in results]
    assert structure.listing_facts is not None
    assert structure.listing_facts.chrome_excluded == 9


def test_header_inside_article_is_not_chrome() -> None:
    cards = [_n("article", geom=_box(100.0 * i), children=(
        _n("header", children=(_n("div", attrs=(("data-id", f"h{i}"),), geom=_box(100.0 * i, 60),
                                  children=(_n("h2", text=f"Nurse {i}"),
                                            _n("a", attrs=(("href", f"/n/{i}"),), text="Open"))),)),
    )) for i in range(2)]
    root = _n("body", children=(_n("main", children=cards),))
    structure = MathFormUnderstandingService().analyze(root, url=BOARD_URL, title="")
    assert structure.listing_facts is not None
    assert structure.listing_facts.chrome_excluded == 0
    assert len(structure.job_listings) == 2


def test_block_with_title_and_company_link_is_not_the_record_teeth() -> None:
    """LinkedIn guest list shape: the detected block holds the title and a
    company link; the posting link (named by a visually hidden span) is its
    sibling, one level up."""
    cards, infos = [], []
    for i in range(3):
        info = _n("div", geom=_box(100.0 * i + 10, 60), children=(
            _n("h3", text=f"Java Developer {i}"),
            _n("h4", children=(_n("a", attrs=(("href", f"https://social.example/company/c{i % 2}"),),
                                  text="Acme"),)),
        ))
        infos.append(info)
        cards.append(_n("div", attrs=(("data-entity", f"e{i}"),), geom=_box(100.0 * i), children=(
            _n("a", attrs=(("href", f"https://social.example/jobs/view/java-developer-{i}-at-acme"),),
               children=(_n("span", attrs=(("class", "sr-only"),), text=f"Java Developer {i}"),)),
            info,
        )))
    root = _n("body", children=(_n("ul", children=[_n("li", children=(c,)) for c in cards]),))
    job_cards, report = resolve_card_group(infos, root, "https://social.example/jobs/search")
    assert report.record_level == "+1"
    assert [c.url for c in job_cards] == [
        f"https://social.example/jobs/view/java-developer-{i}-at-acme" for i in range(3)]


def test_url_line_block_does_not_become_the_record() -> None:
    """Bing shape: the detected block is the result's URL line (a link named
    by its host); the heading one level up names the record."""
    lines, items = [], []
    for i in range(3):
        href = f"https://www.search.example/ck/a?u=a1{'Q' * 50}{i}"
        line = _n("div", geom=_box(100.0 * i + 50, 30), children=(
            _n("a", attrs=(("href", href),), text=f"site{i}.example"),))
        lines.append(line)
        items.append(_n("li", geom=_box(100.0 * i), children=(
            _n("h2", children=(_n("a", attrs=(("href", href),), text=f"Welder role {i}"),)), line)))
    root = _n("body", children=(_n("ol", children=items),))
    job_cards, report = resolve_card_group(lines, root, SERP_URL)
    assert report.record_level == "+1"
    assert [c.title for c in job_cards] == ["Welder role 0", "Welder role 1", "Welder role 2"]
    assert {c.title_source for c in job_cards} == {"heading"}

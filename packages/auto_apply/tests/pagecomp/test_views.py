"""S9b views (CT-T-028), ALG-028/029, and the S9 feed/sitemap channel."""

from __future__ import annotations

from pagecomp import Analyzer, observe_html
from pagecomp import channels as C
from pagecomp import viewmath as V

POSTING = """<html><head>
<link rel=canonical href="https://boards.example/acme/jobs/123">
<link rel=alternate type="application/rss+xml" href="/feed.xml">
<link rel=amphtml href="https://boards.example/amp/acme/jobs/123">
<script type="application/ld+json">{"@type":"JobPosting","title":"Backend Engineer",
"hiringOrganization":{"name":"Acme"},"datePosted":"2026-11-01","url":"https://boards.example/acme/jobs/123",
"jobLocation":{"address":{"addressLocality":"Austin","addressRegion":"TX"}}}</script></head>
<body><h1>Backend Engineer</h1><p>Acme</p><a href="?print=1">Print</a>
<iframe src="https://forms.vendor.example/apply/987"></iframe></body></html>"""


def _views(html, url="https://www.acme.example/careers/backend"):
    return Analyzer(observe_html(html, url=url), strict=True).value("views")


def test_advertised_views_and_record_key():
    vm = _views(POSTING)
    kinds = {v.kind for v in vm.views}
    assert {"feed", "amp", "print", "jsonld", "page", "mirror", "own_url"} <= kinds
    assert vm.record_key == "https://boards.example/acme/jobs/123"
    feed = next(v for v in vm.views if v.kind == "feed")
    assert feed.locator == "https://www.acme.example/feed.xml"
    jl = next(v for v in vm.views if v.kind == "jsonld")
    assert jl.requests == 0 and {"title", "company", "location"} <= set(jl.fields)
    # The block has no description, so the view must not claim one (review
    # finding, 2026-11-08: it used to be claimed unconditionally).
    assert "description" not in jl.fields


def test_jsonld_description_is_read_as_plain_text():
    from pagecomp.tools.structured import DESCRIPTION_CHARS
    block = ('{"@type":"JobPosting","title":"Backend Engineer","hiringOrganization":{"name":"Acme"},'
             '"description":"&lt;p&gt;Build &lt;b&gt;APIs&lt;/b&gt; &amp;amp; services.&lt;/p&gt;"}')
    html = f'<html><head><script type="application/ld+json">{block}</script></head><body><h1>x</h1></body></html>'
    an = Analyzer(observe_html(html, url="https://www.acme.example/jobs/1"), strict=True)
    assert an.value("structured").postings[0].description == "Build APIs & services."
    jl = next(v for v in an.value("views").views if v.kind == "jsonld")
    assert "description" in jl.fields
    huge = '{"@type":"JobPosting","title":"T","description":"' + "<p>word</p> " * 5_000 + '"}'
    html = f'<html><head><script type="application/ld+json">{huge}</script></head><body></body></html>'
    d = Analyzer(observe_html(html, url="https://a.example/"), strict=True).value("structured").postings[0].description
    assert len(d) == DESCRIPTION_CHARS  # 25,000 characters of words, cut to the cap


def test_guest_view_is_recognised_not_a_wall():
    html = ("<main><h1>Engineer</h1><p>" + "About the role. " * 30 + "</p><p>Sign in to see more</p></main>"
            "<div role=dialog aria-modal=true><input type=email name=u><input type=password name=p>"
            "<button>Sign in</button></div>")
    vm = _views(html, url="https://social.example/jobs/view/1")
    assert vm.guest and any(v.kind == "page_guest" for v in vm.views)


def test_equivalent_compatible_distinct():
    page = {"title": "Backend Engineer", "company": "Acme", "location": "Austin, TX",
            "pay": "$120k - $150k", "date_posted": "2026-11-01"}
    feed = {"title": "Backend engineer", "company": "ACME", "location": "Austin",
            "pay": "130000", "date_posted": "Sun, 02 Nov 2026 08:00:00 GMT"}
    assert V.compare_views(page, feed).kind == V.EQUIVALENT
    stale = dict(feed, pay="$40k")
    eq = V.compare_views(page, stale)
    assert eq.kind == V.COMPATIBLE and eq.disagree == ("pay",)
    assert V.compare_views(page, {"title": "Data Scientist", "company": "Acme"}).kind == V.DISTINCT


def test_disagreements_are_kept_not_averaged():
    merged = V.merge_fields([({"pay": "$120k-$150k"}, {"pay": 0.9}), ({"pay": "$40k"}, {"pay": 0.5})])
    assert merged["pay"] == ("$120k-$150k", ("$40k",))


def test_selection_prefers_cheapest_verified_public_view():
    c = V.Candidate
    views = [
        c("page", "https://p", "public", 3, 1, frozenset(V.KIND_ORDER) | {"title", "company", "description"}, "equivalent"),
        c("feed", "https://f", "public", 1, 1, frozenset({"title", "apply_target"}), "equivalent"),
        c("api", "https://a", "public", 1, 1, frozenset({"title", "company", "description"}), "equivalent"),
        c("page_signed_in", "https://s", "needs_sign_in", 0, 0, frozenset({"title", "company", "description"}), "equivalent"),
        c("jsonld", "#", "public", 0, 0, frozenset({"title", "company"}), "unverified"),
    ]
    assert [v.kind for v in V.choose_views(views, {"title", "company", "description"})] == ["api"]
    cover = V.choose_views([views[1], c("jsonld", "#", "public", 0, 0, frozenset({"company"}), "equivalent")],
                           {"title", "company", "apply_target"})
    assert {v.kind for v in cover} == {"feed", "jsonld"}


def test_reverification_sample_is_seeded_and_sized():
    keys = [f"k{i}" for i in range(200)]
    s1 = V.sample_for_reverification(keys, seed=7)
    assert s1 == V.sample_for_reverification(keys, seed=7) and len(s1) == 10
    assert len(V.sample_for_reverification(keys[:5], seed=1)) == 3


RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Jobs</title>
<item><title>Backend Engineer</title><link>https://boards.example/acme/jobs/123</link>
<pubDate>Sun, 02 Nov 2026 08:00:00 GMT</pubDate><guid>123</guid></item></channel></rss>"""
ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Data Engineer</title>
<link rel="alternate" href="https://x.example/j/9"/><id>urn:9</id><updated>2026-11-03T00:00:00Z</updated></entry></feed>"""
SITEMAP = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://x.example/j/1</loc>
<lastmod>2026-11-01</lastmod></url></urlset>"""


def test_channels_parse_rss_atom_sitemap():
    r = C.parse_channel(RSS)
    assert r.kind == "rss" and r.items[0].link.endswith("/123") and r.items[0].guid == "123"
    a = C.parse_channel(ATOM)
    assert a.kind == "atom" and a.items[0].link == "https://x.example/j/9"
    s = C.parse_channel(SITEMAP)
    assert s.kind == "sitemap" and s.items[0].updated == "2026-11-01"


def test_channels_refuse_entity_attacks_and_never_raise():
    bomb = '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]><rss>&lol2;</rss>'
    assert C.parse_channel(bomb).flags == ("refused-declaration",)
    assert C.parse_channel("<rss><channel><item>").flags == ("malformed",)
    assert C.parse_channel("x" * 10, max_bytes=5).flags == ("too-large",)
    assert C.robots_sitemaps("User-agent: *\nSitemap: https://x.example/s.xml\n") == ("https://x.example/s.xml",)


def test_feed_item_vs_page_reading_end_to_end():
    an = Analyzer(observe_html(POSTING, url="https://www.acme.example/careers/backend"))
    p = an.value("structured").postings[0]
    page = {"title": p.title, "company": p.organization, "apply_target": p.url, "date_posted": p.date_posted}
    item = C.parse_channel(RSS).items[0]
    feed = {"title": item.title, "apply_target": item.link, "date_posted": item.published}
    assert V.compare_views(page, feed).kind == V.EQUIVALENT

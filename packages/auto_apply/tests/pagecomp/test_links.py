"""The destination ladder: direct, unwrapped, opaque (with breadcrumb), none."""

from __future__ import annotations

import base64

from pagecomp import links as L
from pagecomp.tools.arrival import check_landing

GOOGLE = "https://www.google.com/search?q=site%3Abreezy.hr+backend"
GOTO = "/goto?url=CAESggEB6zswFcbCZdzS3VMw4a1mwzw0kS6V3U9kfZ9ov-5QJ5_xoblA5IkAzz"


def test_google_goto_is_opaque_with_expected_host_from_breadcrumb():
    cands, rejs = L.evaluate([(1, GOTO, "Senior Backend Engineer", "title-structural")],
                             title="Senior Backend Engineer", page_url=GOOGLE,
                             evidence_texts=["Breezy HR https://norbert-health.breezy.hr › p › 123"])
    assert not rejs and len(cands) == 1
    c = cands[0]
    assert c.kind == L.OPAQUE and c.expected_host == "norbert-health.breezy.hr"
    assert c.url.startswith("https://www.google.com/goto?"), "the wrapper stays navigable"
    state, chosen = L.decide(cands, rejs)
    assert state == L.RESOLVED and chosen is c


def test_opaque_payload_is_never_joined_onto_the_results_host():
    url, how = L.unwrap(GOTO, GOOGLE)
    assert how == "no decodable payload" and "breezy" not in url


def test_bing_ck_a_unwraps_locally():
    payload = "a1" + base64.urlsafe_b64encode(b"https://jobs.lever.co/acme/123").decode().rstrip("=")
    url, how = L.unwrap(f"https://www.bing.com/ck/a?!&&p=abc&u={payload}&ntb=1")
    assert url == "https://jobs.lever.co/acme/123" and "skip2" in how


def test_duckduckgo_uddg_unwraps():
    url, _ = L.unwrap("//duckduckgo.com/l/?uddg=https%3A%2F%2Fboards.greenhouse.io%2Fx%2Fjobs%2F42", "https://duckduckgo.com/")
    assert url == "https://boards.greenhouse.io/x/jobs/42"


def test_arrival_integrity_checks_the_visit_against_the_breadcrumb():
    assert L.arrival_integrity("norbert-health.breezy.hr", "https://norbert-health.breezy.hr/p/1-x") is True
    assert L.arrival_integrity("norbert-health.breezy.hr", "https://ads.example/landing") is False
    assert L.arrival_integrity("", "https://anything/") is None


def test_ads_rejected_with_evidence_tokens_not_text():
    _, rejs = L.evaluate([(1, "https://ad.doubleclick.net/x?ad_domain=jobs", "Apply now", "")],
                         title="", page_url=GOOGLE)
    assert rejs and rejs[0].reason == "advertising evidence"


def test_search_engine_ad_clicks_are_advertising():
    """pagecomp 0.5.2: a paid result's click route is never a destination.
    Bing's /aclk carries the advertiser's address base64-encoded in u=, so
    v0.5.1 unwrapped it and the job-list gate took the ads (owner's plain
    Bing search, 2026-11-08: 18 /aclk links, each under "Sponsored")."""
    dest = base64.urlsafe_b64encode(b"https://www.ziprecruiter.com/jobs/view/1234567").decode()
    for href in (f"https://www.bing.com/aclk?ld=e8AbCdEf&u={dest}&rlid=abc&ntb=1",
                 "https://www.google.com/aclk?sa=l&ai=DChcSEwjAbC&adurl=",
                 "https://www.googleadservices.com/pagead/aclk?sa=L&ai=DChcSEwjAbC&adurl="):
        cands, rejs = L.evaluate([(1, href, "Backend Engineer Jobs", "title-structural")],
                                 title="Backend Engineer Jobs", page_url=GOOGLE)
        assert not cands and rejs and rejs[0].reason == "advertising evidence", href


def test_structural_title_link_beats_textual_echo():
    items = [(1, "/rc/clk?jk=080a02944a4afd88", "full details of Software Engineer I", "title-structural"),
             (2, "/career/software-engineer/salaries/LA", "Software Engineer I salaries", "title")]
    cands, rejs = L.evaluate(items, title="Software Engineer I, Entry-Level", page_url="https://www.indeed.com/jobs")
    state, chosen = L.decide(cands, rejs)
    assert state == L.RESOLVED and chosen.node == 1


def test_two_links_to_one_destination_are_one_route_defect25():
    items = [(1, "https://x.example/job/123", "Engineer", "title-structural"),
             (2, "https://x.example/job/123#apply", "Apply", "")]
    cands, _ = L.evaluate(items, title="Engineer", page_url="https://x.example/")
    assert len(cands) == 1


def test_posting_path_needs_an_identifier():
    assert L.posting_path("https://x.example/companies/k/jobs/7ySmewF-senior-pm") == 1.0
    assert L.posting_path("https://c.example/us/en/c/audit-jobs") == 0.5
    assert L.posting_path("https://www.indeed.com/q-junior-web-developer-l-la-jobs.html") == 0.5
    assert L.posting_path("https://news.example/2026/11/story") == 0.0


def test_check_landing_bing_redirerr_and_home():
    req = "https://www.bing.com/jobs?q=python"
    assert check_landing(req, "https://www.bing.com/?form=REDIRERR").reason == "error-redirect"
    assert check_landing(req, "https://www.bing.com/").reason == "home-page"
    assert check_landing(req, "https://www.bing.com/jobs?q=python&first=1").on_surface
    assert check_landing(req, "https://evil.example/jobs").reason == "different-site"
    assert check_landing(req, "about:blank").reason == "no-page"


def test_specific_destination_names_one_item_not_a_search():
    """joblist 0.3.0: a posting has an identity; a related search does not
    (owner Indeed capture 2026-11-03 and live run 2026-11-07)."""
    from pagecomp.links import specific_destination as sd
    yes = ["https://www.indeed.com/rc/clk?jk=1caad28458bcd22f&bb=xyz&xkcb=SoBb",
           "https://boards.greenhouse.io/acme/jobs/4012345",
           "https://www.welcometothejungle.com/en/companies/acme/jobs/head-of-product-design_paris",
           "https://www.linkedin.com/jobs/view/4012345678/",
           "https://acme.wd1.myworkdayjobs.com/External/job/Phoenix/Engineer_JR0271234"]
    no = ["https://www.indeed.com/q-junior-web-developer-l-los-angeles,-ca-jobs.html",
          "https://www.linkedin.com/jobs/j2ee-developer-jobs",
          "https://www.example.com/c/audit-jobs",
          "https://www.google.com/search?q=entry+level+software+engineer+jobs&sca_esv=a1b2c3d4e5f6&ved=2ahUKEwiAbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
          "https://jobs.example/search?utm_source=abc123def456&from=x9y8z7w6",
          "https://www.builtinchicago.org/jobs/dev-engineering/search/backend-engineer",
          "https://careers.example.com/results/backend-engineer",
          "javascript:void(0)"]
    assert all(sd(u) for u in yes), [u for u in yes if not sd(u)]
    assert not any(sd(u) for u in no), [u for u in no if sd(u)]

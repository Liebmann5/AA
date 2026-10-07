"""Pins for VerifiedPageAdvancer: the ladder order, verification, honest stops.

The fake browser's fingerprint is indexed by EVENTS (navigations + working
clicks), so a click or navigation that changes nothing provably fails
verification — the property the whole component stands on.
"""
from __future__ import annotations

from auto_apply.adapters.secondary.navigation.page_advancer import VerifiedPageAdvancer
from auto_apply.application.services.page_action.result import ActionResult
from auto_apply.domain.models.page_advance import UrlPageTemplate


XP = "/html/body[1]/nav[1]/a[2]"


def _fp(url="https://x.test/s", anchors=3, first="https://x.test/a",
        last="https://x.test/z", height=5000):
    return [url, anchors, first, last, height]


class _FakeTool:
    def __init__(self, browser=None, works=True):
        self._browser = browser
        self._works = works
        self.clicks = []

    def click(self, element):
        self.clicks.append(element)
        if self._works and self._browser is not None:
            self._browser.events += 1
        return ActionResult(True)


class _FakeBrowser:
    """Candidates carry a generated XPath; the element is re-found through
    find_element — exactly the contract the real scans follow, because
    Playwright cannot hand a node back from evaluate (P1)."""

    def __init__(self, *, url="https://x.test/s", fingerprints=None,
                 candidates=None, load_more=None, elements=None):
        self.current_url = url
        self._fps = list(fingerprints) if fingerprints else [_fp()]
        self._candidates = list(candidates or [])
        self._load_more = list(load_more or [])
        self._elements = dict(elements or {})
        self.events = 0
        self.got = []
        self.find_calls = []

    def get(self, url):
        self.got.append(url)
        self.current_url = url
        self.events += 1

    def find_element(self, by, selector):
        self.find_calls.append(selector)
        return self._elements.get(selector)

    def execute_script(self, script, *args):
        if "aria-current" in script:
            return self._candidates.pop(0) if self._candidates else []
        if "more|load" in script:
            return self._load_more.pop(0) if self._load_more else []
        return list(self._fps[min(self.events, len(self._fps) - 1)])


def _advancer(browser, **kwargs):
    kwargs.setdefault("change_timeout_s", 0.4)
    return VerifiedPageAdvancer(browser=browser, **kwargs)


# ── rung 1: URL template ─────────────────────────────────────────────────────


def test_url_template_rung_builds_and_verifies_the_next_url():
    browser = _FakeBrowser(
        url="https://g.test/search?q=jobs",
        fingerprints=[_fp("https://g.test/search?q=jobs"),
                      _fp("https://g.test/search?q=jobs&start=10",
                          first="https://g.test/j10", last="https://g.test/j20")],
    )
    outcome = _advancer(
        browser, url_template=UrlPageTemplate(param="start", first=0, step=10)
    ).advance()
    assert outcome.advanced and outcome.method == "url-template" and outcome.verified
    assert browser.got == ["https://g.test/search?q=jobs&start=10"]


def test_a_fresh_advancer_starts_at_page_one_and_tracks_forward():
    """The shared NumberedPagination leaked its counter across queries; a
    per-query instance starts at 1 by construction."""
    browser = _FakeBrowser(
        url="https://g.test/s",
        fingerprints=[_fp("https://g.test/s"),
                      _fp("https://g.test/s?start=10", first="https://g.test/b"),
                      _fp("https://g.test/s?start=20", first="https://g.test/c")],
    )
    adv = _advancer(browser, url_template=UrlPageTemplate(param="start", first=0, step=10))
    first = adv.advance()
    second = adv.advance()
    assert browser.got == ["https://g.test/s?start=10", "https://g.test/s?start=20"]
    assert first.method == second.method == "url-template"


def test_an_unverified_template_advance_falls_through_to_the_next_rung():
    el = object()
    same = _fp("https://g.test/s")
    browser = _FakeBrowser(
        url="https://g.test/s",
        fingerprints=[same, same, _fp("https://g.test/s3", first="https://g.test/new")],
        candidates=[[{"kind": "rel-next", "score": 100, "text": ">", "xpath": XP}]],
        elements={XP: el},
    )
    tool = _FakeTool(browser)
    outcome = _advancer(
        browser,
        page_action=tool,
        url_template=UrlPageTemplate(param="start", first=0, step=10),
    ).advance()
    assert outcome.method == "rel-next"
    assert tool.clicks == [el]


# ── rungs 2–4: controls ─────────────────────────────────────────────────────


def test_rel_next_wins_and_verifies():
    el = object()
    browser = _FakeBrowser(
        fingerprints=[_fp(), _fp("https://x.test/s2", first="https://x.test/m")],
        candidates=[[{"kind": "rel-next", "score": 100, "text": "2", "xpath": XP}]],
        elements={XP: el},
    )
    outcome = _advancer(browser, page_action=_FakeTool(browser)).advance()
    assert outcome.advanced and outcome.method == "rel-next" and outcome.verified
    assert browser.find_calls == [XP]


def test_structural_next_after_the_current_marker():
    el = object()
    browser = _FakeBrowser(
        fingerprints=[_fp(), _fp("https://x.test/s2", first="https://x.test/m")],
        candidates=[[{"kind": "after-current", "score": 80, "text": "2", "xpath": XP}]],
        elements={XP: el},
    )
    outcome = _advancer(browser, page_action=_FakeTool(browser)).advance()
    assert outcome.method == "structural-next"


def test_numbered_current_plus_one():
    el = object()
    browser = _FakeBrowser(
        fingerprints=[_fp(), _fp("https://x.test/s2", first="https://x.test/m")],
        candidates=[[{"kind": "numbered", "score": 70, "text": "2", "xpath": XP}]],
        elements={XP: el},
    )
    outcome = _advancer(browser, page_action=_FakeTool(browser)).advance()
    assert outcome.method == "numbered"


# ── rungs 5–6: growth-verified ──────────────────────────────────────────────


def test_load_more_requires_growth_not_just_change():
    el = object()
    grew = _fp(anchors=6)
    browser = _FakeBrowser(fingerprints=[_fp(), grew],
                           load_more=[[{"kind": "load-more", "score": 40, "xpath": XP}]],
                           elements={XP: el})
    outcome = _advancer(browser, page_action=_FakeTool(browser)).advance()
    assert outcome.advanced and outcome.method == "load-more"


def test_load_more_without_growth_falls_to_the_scroll_rung():
    el = object()
    browser = _FakeBrowser(fingerprints=[_fp(), _fp(anchors=6)],
                           load_more=[[{"kind": "load-more", "score": 40, "xpath": XP}]],
                           elements={XP: el})

    def _scroll():
        browser.events += 1
        return True

    # The load-more click changes nothing (works=False); the scroll grows.
    outcome = _advancer(
        browser, page_action=_FakeTool(browser, works=False), scroll=_scroll
    ).advance()
    assert outcome.advanced and outcome.method == "scroll-growth"


def test_scroll_growth_is_the_last_rung():
    browser = _FakeBrowser(fingerprints=[_fp(), _fp(anchors=6)])

    def _scroll():
        browser.events += 1
        return True

    outcome = _advancer(browser, scroll=_scroll).advance()
    assert outcome.advanced and outcome.method == "scroll-growth"


# ── honest stops ────────────────────────────────────────────────────────────


def test_a_click_that_changes_nothing_is_no_change_not_a_new_page():
    """TEETH: the old strategies returned True when the click did not raise."""
    el = object()
    browser = _FakeBrowser(
        candidates=[[{"kind": "rel-next", "score": 100, "text": "2", "xpath": XP}]],
        elements={XP: el},
    )
    tool = _FakeTool(browser, works=False)
    outcome = _advancer(browser, page_action=tool).advance()
    assert outcome.advanced is False
    assert outcome.stop_reason == "no-change"
    assert tool.clicks == [el]


def test_nothing_to_click_is_no_next_control():
    outcome = _advancer(_FakeBrowser()).advance()
    assert outcome.advanced is False
    assert outcome.stop_reason == "no-next-control"


def test_without_the_tool_click_rungs_are_honestly_skipped():
    """No tool: template and scroll rungs still work; clicks are not faked."""
    el = object()
    browser = _FakeBrowser(
        candidates=[[{"kind": "rel-next", "score": 100, "text": "2", "xpath": XP}]],
        elements={XP: object()},
    )
    outcome = _advancer(browser).advance()
    assert outcome.advanced is False
    assert outcome.stop_reason == "no-next-control"
    assert browser.events == 0


# ── P3 — verification must not certify its own cause ────────────────────────


def test_a_template_advance_is_not_verified_by_its_own_url_change():
    """TEETH (P3, measured live on the first probe): AA sets the URL itself,
    so a URL change proves nothing. A page that ignores the parameter was
    harvested twice as "page 2" before this ruling."""
    browser = _FakeBrowser(
        url="https://g.test/s",
        fingerprints=[_fp("https://g.test/s"), _fp("https://g.test/s?p=2")],
    )
    outcome = _advancer(
        browser, url_template=UrlPageTemplate(param="p", first=1, step=1)
    ).advance()
    assert outcome.advanced is False
    assert outcome.stop_reason == "no-next-control"


def test_a_click_that_only_changes_the_url_is_not_an_advance():
    """TEETH (P3): a control click that navigates without changing the
    result list is no advance either."""
    browser = _FakeBrowser(
        fingerprints=[_fp(), _fp("https://x.test/s?page=2")],
        candidates=[[{"kind": "rel-next", "score": 100, "text": "2", "xpath": XP}]],
        elements={XP: object()},
    )
    tool = _FakeTool(browser)
    outcome = _advancer(browser, page_action=tool).advance()
    assert outcome.advanced is False
    assert outcome.stop_reason == "no-change"
    assert tool.clicks, "the candidate was never clicked"


# ── P1 — the re-find contract, made permanent ───────────────────────────────


def test_no_advancer_script_returns_a_dom_node() -> None:
    """The contract, pinned: scans return DATA + a re-findable XPath, never
    a node. Playwright's evaluate cannot return one (measured: 'ref:
    <Node>'), so any script that tries kills every control rung on AA's
    default framework."""
    import re

    from auto_apply.adapters.secondary.navigation import page_advancer

    for name in ("_CANDIDATES_JS", "_LOAD_MORE_JS"):
        script = getattr(page_advancer, name)
        assert "xpath:" in script, f"{name} lost the re-find key"
        assert not re.search(r"(?<![a-zA-Z-])el\s*:", script), (
            f"{name} returns a DOM node — Playwright cannot serialise one"
        )


def test_no_src_script_returns_a_dom_node() -> None:
    """The census, made permanent: nothing anywhere in src may ship a script
    that puts a DOM node into an evaluate() result. The two advancer scans
    were the only offenders (measured on both drivers)."""
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "auto_apply"
    pattern = re.compile(r"[{,]\s*el\s*:\s*(el|b|c\.el|elem|element)\b")
    offenders = []
    for path in sorted(src.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
            offenders.append(path.relative_to(src).as_posix())
    assert not offenders, f"scripts returning DOM nodes: {offenders}"

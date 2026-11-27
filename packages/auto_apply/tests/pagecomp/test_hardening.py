"""Every tool, together: hostile input, determinism, privacy, bounds."""

from __future__ import annotations

import os
import random

import pytest

from pagecomp import Abstain, Analyzer, Ok, Timeout, observe_cdp, observe_html
from pagecomp.results import fingerprint
from pagecomp.tools import default_registry

TAGS = ["div", "span", "a", "ul", "li", "form", "input", "select", "option", "label", "button", "table",
        "tr", "td", "iframe", "template", "script", "style", "h3", "p", "fieldset", "legend", "textarea",
        "nav", "aside", "dialog", "x-card", "svg", "link", "meta", "img", "cite", "time"]
ATTRS = ["href", "id", "for", "name", "type", "role", "aria-label", "aria-labelledby", "aria-hidden",
         "hidden", "style", "rel", "srcdoc", "shadowrootmode", "value", "checked", "required", "aria-controls",
         "aria-expanded", "data-href", "autocomplete", "class", "src"]
VALUES = ["", "x", "#", "javascript:alert(1)", "https://jobs.example/job/123", "/goto?url=CAES" + "A" * 50,
          "display:none", "checkbox", "radio", "email", "file", "dialog", "switch", "next", "open", "true",
          "q", "l", "a b c", "‮", "\x00", "<", "&amp;", "🌐", "1" * 400]


def _soup(rnd: random.Random, n: int) -> str:
    out = []
    for _ in range(n):
        r = rnd.random()
        if r < 0.45:
            tag = rnd.choice(TAGS)
            attrs = " ".join(f'{rnd.choice(ATTRS)}="{rnd.choice(VALUES)}"' for _ in range(rnd.randint(0, 3)))
            out.append(f"<{tag} {attrs}>")
        elif r < 0.75:
            out.append(f"</{rnd.choice(TAGS)}>")
        else:
            out.append(rnd.choice(["Apply", "Software Engineer", "required *", "Next", "Sign in", "1,234 jobs",
                                   "Remote", "Sort by", "x" * rnd.randint(0, 300), " ", "{", "]]>"]))
    return "".join(out)


@pytest.mark.parametrize("seed", range(40))
def test_every_tool_survives_tag_soup_strictly(seed):
    rnd = random.Random(seed)
    html = _soup(rnd, rnd.randint(0, 600))
    an = Analyzer(observe_html(html, url=rnd.choice(["https://a.example/s?q=x", "", "about:blank", "not a url"]),
                               query=rnd.choice([None, "software engineer", ""]),
                               requested_url=rnd.choice([None, "https://a.example/jobs?q=x"])),
                  strict=True)
    for tool in default_registry().tools:
        assert isinstance(an.get(tool).result, (Ok, Abstain, Timeout)), tool


@pytest.mark.parametrize("seed", range(15))
def test_every_tool_survives_malformed_cdp(seed):
    rnd = random.Random(1000 + seed)

    def node(depth):
        k = rnd.random()
        if depth > 6 or k < 0.2:
            return {"nodeType": 3, "nodeValue": rnd.choice(VALUES)}
        n = {"nodeType": rnd.choice([1, 1, 1, 9, 11, 8, 10, 42]), "localName": rnd.choice(TAGS + [None, 7]),
             "attributes": [rnd.choice(ATTRS), rnd.choice(VALUES)] * rnd.randint(0, 2) + ([1] if rnd.random() < .1 else []),
             "children": [node(depth + 1) for _ in range(rnd.randint(0, 4))]}
        if rnd.random() < 0.1:
            n["shadowRoots"] = [{"nodeType": 11, "shadowRootType": rnd.choice(["open", "closed", "user-agent"]),
                                 "children": [node(depth + 1)]}]
        if rnd.random() < 0.05:
            n["contentDocument"] = {"nodeType": 9, "children": [node(depth + 1)]}
        return n
    an = Analyzer(observe_cdp({"root": {"nodeType": 9, "children": [node(0)]}}, url="https://a.example/"),
                  strict=True)
    for tool in default_registry().tools:
        assert isinstance(an.get(tool).result, (Ok, Abstain, Timeout)), tool


def test_tiny_budget_yields_timeouts_never_hangs():
    rnd = random.Random(5)
    an = Analyzer(observe_html(_soup(rnd, 3000), url="https://a.example/"), budget_units=500, strict=True)
    outcomes = {type(an.get(t).result).__name__ for t in default_registry().tools}
    assert "Timeout" in outcomes or "Abstain" in outcomes


def test_trace_stays_private_for_every_tool():
    an = Analyzer(observe_html("<main><h1>secret-title</h1><a href='https://secret.example/x'>secret</a></main>",
                               url="https://secret.example/path?q=secret", query="secret"), strict=True)
    for tool in default_registry().tools:
        an.get(tool)
    assert "secret" not in repr(list(an.trace))


ROOT = os.environ.get("PAGECOMP_CAPTURES", "")


@pytest.mark.skipif(not ROOT or not os.path.isdir(ROOT), reason="owner captures not available")
def test_every_tool_is_deterministic_on_the_corpus():
    from pagecomp import capture

    for d in capture.iter_captures(ROOT)[::7]:
        a = Analyzer(capture.load(d).observation)
        b = Analyzer(capture.load(d).observation)
        for tool in default_registry().tools:
            assert fingerprint(a.get(tool).result) == fingerprint(b.get(tool).result), (d.name, tool)


def test_a_page_nested_to_the_depth_cap_analyzes_strictly():
    """max_depth is 256 (the largest real capture is 54 deep). Every tool
    must handle a page nested that far, and one nested past it, without
    raising, recursing out, or losing the shallow content."""
    from pagecomp.doc import DocLimits
    inner = '<label for="e">Email</label><input id="e" type="email" required>'
    for levels in (250, 600):
        html = "<form>" + "<div>" * levels + inner + "</div>" * levels + "<button>Submit</button></form>"
        obs = observe_html(html, url="https://jobs.example/apply")
        assert DocLimits().max_depth == 256
        an = Analyzer(obs, strict=True)
        for tool in default_registry().tools:
            assert isinstance(an.get(tool).result, (Ok, Abstain, Timeout)), (levels, tool)
        cut = [t.kind for t in obs.doc.truncations]
        assert ("depth" in cut) == (levels > 250)


@pytest.mark.parametrize("seed", range(20))
def test_parser_open_element_counts_match_the_stack(seed):
    """The parser's O(1) "is a <p> open?" answer must always agree with the
    stack itself, through implied closes, stray end tags and templates."""
    from collections import Counter

    from pagecomp.doc import ROOT, DocLimits, _Builder, _HTMLTree
    rnd = random.Random(7000 + seed)
    html = _soup(rnd, rnd.randint(50, 800))
    b = _Builder(DocLimits())
    parser = _HTMLTree(b, b.add(ROOT, -1, 0, tag="#document", attrs=[("url", "")]), 1, 0)
    step = max(1, len(html) // 25)
    for i in range(0, len(html), step):
        parser.feed(html[i:i + step])
        live = Counter(parser.stack.names())
        assert {k: v for k, v in parser.stack.open.items() if v} == dict(live)


def _cuts(doc):
    return {t.kind: t.count for t in doc.truncations}


def test_parser_work_is_bounded_not_only_its_output():
    """Review findings (2026-11-08): bounded output did not mean bounded work.
    Each case used to take 6-13 s or hundreds of MiB; each must now stop at
    a recorded cap. Sizes are the cap or past it."""
    import time

    from pagecomp.doc import DocLimits, from_cdp, from_html
    lim = DocLimits()
    cases = {
        "one 50 MB text node": "<p>" + "word " * 10_000_000 + "</p>",
        "nesting far past the depth cap": "<div>" * 1_600_000,
        "a million attributes on one element": "<div " + " ".join(f"a{i}" for i in range(1_000_000)) + ">x</div>",
    }
    for name, html in cases.items():
        t = time.perf_counter()
        doc = from_html(html)
        # 0.02-1.3 s on the build machine, about 4x that on the owner's laptop;
        # the quadratic regression this guards against took 25-29 s here.
        assert time.perf_counter() - t < 15.0, name
        assert doc.truncations, name
        assert max(doc.attr_len) <= lim.max_attrs and max(doc.depth) <= lim.max_depth, name
    assert _cuts(from_html("<p>" + "word " * 10_000_000 + "</p>"))["input-chars"] > 0
    deep = from_html("<div>" * 1_600_000)
    assert len(deep) <= lim.max_nodes and _cuts(deep)["input-chars"] > 0
    # Empty attribute names cost nothing before; now each costs at least one unit.
    cdp = {"nodeType": 9, "documentURL": "https://x.example/",
           "children": [{"nodeType": 1, "localName": "div", "attributes": [""] * 4_000_000}]}
    doc = from_cdp(cdp)
    assert len(doc.attr_name) <= lim.max_attrs + 1 and _cuts(doc)["attrs"] == 2_000_000 - lim.max_attrs


def test_shadow_roots_count_against_the_depth_cap():
    """Review finding (2026-11-08). HTML: a declarative shadow root landed one
    level past the cap. DevTools DOM: shadow roots nested directly in shadow
    roots (a malformed payload) had no depth cap at all."""
    from pagecomp.doc import DocLimits, from_cdp, from_html
    cap = DocLimits().max_depth
    html = ("<x-a><template shadowrootmode=open>" * 2000) + "deep" + ("</template></x-a>" * 2000)
    assert max(from_html(html).depth) <= cap   # was cap + 1 (a text node may sit at the cap)
    node = {"nodeType": 1, "localName": "span"}
    for _ in range(20_000):
        node = {"nodeType": 11, "shadowRootType": "open", "shadowRoots": [node]}
    doc = from_cdp({"nodeType": 9, "documentURL": "https://x.example/",
                    "children": [{"nodeType": 1, "localName": "div", "shadowRoots": [node]}]})
    assert max(doc.depth) <= cap and "depth" in _cuts(doc)   # was 20,001


def test_chrome_text_cut_is_recorded_and_scripts_keep_their_own_cap():
    """Chrome's DOM agent sends at most 10,000 characters of a text node
    plus U+2026; that cut must be visible. Script text is capped at
    max_script_chars (65,536), not at the 20,000 of an ordinary text node:
    real JSON-LD blocks reach 16,098 characters in the owner captures."""
    from pagecomp.doc import from_cdp, from_html
    cut = "x" * 10_000 + "…"
    doc = from_cdp({"nodeType": 9, "documentURL": "https://x.example/", "children": [
        {"nodeType": 1, "localName": "script", "attributes": ["type", "application/ld+json"],
         "children": [{"nodeType": 3, "nodeValue": cut}]},
        {"nodeType": 1, "localName": "p", "children": [{"nodeType": 3, "nodeValue": cut}]}]})
    assert _cuts(doc)["cdp-text"] == 2
    body = "y" * 40_000
    doc = from_html(f"<script>{body}</script>")
    assert any(doc.own_text(j) == body for j in range(len(doc))) and "text" not in _cuts(doc)

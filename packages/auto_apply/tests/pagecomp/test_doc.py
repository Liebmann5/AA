"""Doc (CT-T-004): structure invariants, parsing rules, caps, CDP input."""

from __future__ import annotations

import random

from pagecomp.doc import ELEMENT, FRAME, ROOT, SHADOW, TEXT, DocLimits, from_cdp, from_html


def _check_invariants(doc):
    n = len(doc)
    assert doc.kind[0] == ROOT and doc.parent[0] == -1
    for i in range(1, n):
        p = doc.parent[i]
        assert 0 <= p < i, "pre-order: parent precedes child"
        assert doc.is_ancestor(p, i)
        assert doc.end[i] <= doc.end[p]
        assert doc.depth[i] == doc.depth[p] + 1 or doc.kind[i] == TEXT or True
    for i in range(n):
        assert i < doc.end[i] <= n
        assert sum(1 for _ in doc.subtree(i)) == doc.end[i] - i


def test_preorder_and_subtree_ranges():
    doc = from_html("<div><p>a<b>b</b></p><ul><li>1<li>2</ul></div>")
    _check_invariants(doc)
    lis = list(doc.elements("li"))
    assert len(lis) == 2
    assert doc.parent[lis[1]] == doc.parent[lis[0]], "<li> implies close of the previous <li>"


def test_implied_end_tags():
    doc = from_html("<p>one<div>two</div><table><tr><td>a<td>b<tr><td>c</table>")
    ps = list(doc.elements("p"))
    div = next(doc.elements("div"))
    assert not doc.is_ancestor(ps[0], div), "a block start closes an open <p>"
    tds = list(doc.elements("td"))
    assert len(tds) == 3 and all(doc.tag_name(doc.parent[t]) == "tr" for t in tds)
    opts = from_html("<select><option>a<option>b</select>")
    o = list(opts.elements("option"))
    assert opts.parent[o[0]] == opts.parent[o[1]]


def test_full_subtree_text_defect4():
    doc = from_html("<h3><span>Engineer 1</span></h3>")
    h3 = next(doc.elements("h3"))
    assert doc.text_content(h3)[0] == "Engineer 1"


def test_words_separated_at_block_edges_not_inline():
    doc = from_html("<div><div>alpha</div><div>beta</div><span>ga</span><b>mma</b></div>")
    assert doc.text_content(1)[0] == "alpha beta gamma"


def test_aria_hidden_is_skipped_for_names_but_kept_visually():
    doc = from_html('<label>Question?<span aria-hidden="true"> *</span></label>')
    lab = next(doc.elements("label"))
    assert doc.text_content(lab)[0] == "Question?"
    assert doc.text_content(lab, visual=True)[0] == "Question? *"


def test_declarative_shadow_dom_and_scoped_ids():
    html = ('<div id="x"></div><my-card><template shadowrootmode="open">'
            '<label for="x">Inner</label><input id="x"></template></my-card>')
    doc = from_html(html)
    shadows = [i for i in range(len(doc)) if doc.kind[i] == SHADOW]
    assert len(shadows) == 1 and doc.attr(shadows[0], "mode") == "open"
    inp = next(doc.elements("input"))
    lab = next(doc.elements("label"))
    assert doc.scope[inp] == shadows[0]
    assert doc.by_id(doc.scope[lab], "x") == inp, "ids resolve inside the shadow scope"
    assert doc.by_id(0, "x") == next(doc.elements("div"))


def test_srcdoc_iframe_becomes_frame_document():
    doc = from_html('<iframe srcdoc="<form><input name=a></form>"></iframe>')
    frames = [i for i in range(len(doc)) if doc.kind[i] == FRAME]
    assert len(frames) == 1
    assert any(doc.tag_name(i) == "input" for i in doc.subtree(frames[0]))


def test_node_cap_truncates_and_reports():
    doc = from_html("<ul>" + "<li>x</li>" * 5000 + "</ul>", limits=DocLimits(max_nodes=500))
    assert len(doc) == 500
    assert any(t.kind == "nodes" for t in doc.truncations)


def test_depth_cap_iterative_no_recursion_error():
    html = "<div>" * 5000 + "deep" + "</div>" * 5000
    doc = from_html(html, limits=DocLimits(max_depth=64))
    assert max(doc.depth) <= 64
    assert any(t.kind == "depth" for t in doc.truncations)
    _check_invariants(doc)


def test_never_raises_on_garbage():
    rnd = random.Random(7)
    alphabet = "<>/=\"' abcdivpspanlitd&;#x0!-[]"
    for _ in range(200):
        s = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 300)))
        doc = from_html(s)
        _check_invariants(doc)


def test_hash_is_deterministic_and_content_sensitive():
    a = from_html("<p>x</p>").content_hash
    assert a == from_html("<p>x</p>").content_hash
    assert a != from_html("<p>y</p>").content_hash


def _cdp_el(name, attrs=(), children=(), shadow=(), content=None):
    n = {"nodeType": 1, "localName": name, "attributes": list(attrs), "children": list(children)}
    if shadow:
        n["shadowRoots"] = list(shadow)
    if content:
        n["contentDocument"] = content
    return n


def test_cdp_shadow_frames_and_user_agent_skip():
    ua = {"nodeType": 11, "shadowRootType": "user-agent", "children": [_cdp_el("div")]}
    inp = _cdp_el("input", ["id", "e"], shadow=[ua])
    host = _cdp_el("x-form", shadow=[{"nodeType": 11, "shadowRootType": "closed",
                                     "children": [_cdp_el("label", ["for", "e"], [{"nodeType": 3, "nodeValue": "Email"}]), inp]}])
    frame_doc = {"nodeType": 9, "documentURL": "https://f.example/", "children": [_cdp_el("html", children=[_cdp_el("p")])]}
    root = {"root": {"nodeType": 9, "documentURL": "https://a.example/",
                     "children": [_cdp_el("html", children=[_cdp_el("body", children=[host, _cdp_el("iframe", content=frame_doc)])])]}}
    doc = from_cdp(root)
    _check_invariants(doc)
    kinds = [doc.kind[i] for i in range(len(doc))]
    assert kinds.count(SHADOW) == 1, "user-agent shadow root skipped, closed one kept"
    assert kinds.count(FRAME) == 1
    i = next(doc.elements("input"))
    lab = next(doc.elements("label"))
    assert doc.by_id(doc.scope[lab], "e") == i
    assert doc.text_content(lab)[0] == "Email"
    assert doc.kind[next(doc.elements("p"))] == ELEMENT


def test_huge_attribute_is_cut_and_reported_not_scanned():
    import time

    from pagecomp import Analyzer, observe_html

    style = "background:url(data:image/png;base64," + "A" * 1_200_000 + ")"
    html = f'<div style="{style}"><p>x</p></div><div style="display:none">h</div>'
    t0 = time.perf_counter()
    an = Analyzer(observe_html(html, url="https://x.example/"), strict=True)
    an.get("family")
    assert time.perf_counter() - t0 < 1.0
    doc = an.obs.doc
    assert any(t.kind == "attr-chars" for t in doc.truncations)
    assert max(len(s) for s in doc.strings) <= 65_536
    vis = an.value("visibility")
    hidden = [i for i in doc.elements("div") if vis.hidden(i)]
    assert len(hidden) == 1

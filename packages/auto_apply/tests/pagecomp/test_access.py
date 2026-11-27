"""S3 pure pins: access contracts, layout snapshot, frames, slots, caps."""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

import pytest

from pagecomp.access import (
    CapabilitySet,
    FrameRead,
    ObservationRequest,
    ReadProbe,
    graft_frames,
    read_flags,
)
from pagecomp.doc import SHADOW, DocLimits, from_cdp, from_snapshot, origin_of, snapshot_to_tree
from pagecomp.observation import observe_cdp, observe_snapshot
from pagecomp.tools.visibility import compute

FIX = Path(__file__).parent / "fixtures"
SNAP = json.loads((FIX / "s3_snapshot.json").read_text())
DOM = json.loads((FIX / "s3_dom.json").read_text())


def _el(tag, attrs=(), children=(), **kw):
    flat = [x for kv in attrs for x in kv]
    return {"nodeType": 1, "localName": tag, "attributes": flat, "children": list(children), **kw}


def _txt(v):
    return {"nodeType": 3, "nodeValue": v}


def _docnode(url, children):
    return {"nodeType": 9, "documentURL": url, "children": children}


def test_capability_set_rejects_unknown_and_overlap():
    with pytest.raises(ValueError):
        CapabilitySet(frozenset({"SNAPSHOT_HTMLX"}))
    with pytest.raises(ValueError):
        CapabilitySet(frozenset(), frozenset({"VIA_CDP"}))
    c = CapabilitySet(frozenset({"VIA_CDP"})).with_gap("CROSS_ORIGIN_UNSEEN")
    assert c.has("VIA_CDP") and "CROSS_ORIGIN_UNSEEN" in c.names()


def test_request_validates_budgets_and_maps_limits():
    with pytest.raises(ValueError):
        ObservationRequest(level="pixels")
    with pytest.raises(ValueError):
        ObservationRequest(max_nodes=0)
    lim = ObservationRequest(max_nodes=5, max_bytes=9, max_depth=3, max_frame_depth=1).limits()
    assert (lim.max_nodes, lim.max_bytes, lim.max_depth, lim.max_frame_depth) == (5, 9, 3, 1)


def test_read_flags_navigation_spa_mutation_and_missing_probe():
    a = ReadProbe("https://x/a", "1", 3)
    assert read_flags(a, a) == frozenset()
    assert read_flags(a, ReadProbe("https://x/a", "2", 3)) == {"navigated", "stale"}
    assert read_flags(a, ReadProbe("https://x/b", "1", 3)) == {"spa-navigated", "stale"}
    assert read_flags(a, ReadProbe("https://x/a", "1", 4)) == {"stale"}
    assert read_flags(None, a) == {"stale"}


def test_snapshot_flattens_shadow_so_tree_comes_from_pierced_dom():
    flat = from_snapshot(SNAP)
    joined = from_snapshot(SNAP, dom=DOM)
    plain = from_cdp(DOM)
    assert flat.source == "cdp-snapshot-flat"
    assert not any(flat.kind[i] == SHADOW for i in range(len(flat)))      # measured: flattened
    assert joined.structure_hash == plain.structure_hash                  # same tree as from_cdp
    assert joined.content_hash != plain.content_hash                      # layout is in the key


def test_layout_visibility_sees_class_hiding_and_reports_visible():
    doc = from_snapshot(SNAP, dom=DOM)
    vm = compute(doc)
    assert vm.layout_known
    ps = list(doc.elements("p"))
    whys = [vm.why(i) for i in ps]
    assert "display-none" in whys or "no-box" in whys                     # .h{display:none}
    assert "visibility-hidden" in whys                                    # .v{visibility:hidden}
    span = next(doc.elements("span"))
    assert vm.why(span) == "visible" and not vm.hidden(span)
    static = compute(from_cdp(DOM))
    assert static.why(span) == "visible-unproven"


def test_observe_snapshot_declares_layout():
    obs = observe_snapshot(SNAP, dom=DOM, url="about:blank")
    assert {"SNAPSHOT_LAYOUT", "SHADOW_PIERCING"} <= obs.capabilities
    assert obs.complete


def test_slot_assignment_recorded():
    doc = from_cdp(DOM)
    assert doc.slots
    for child, slot in doc.slots.items():
        assert doc.tag_name(slot) == "slot"


def test_frames_carry_url_origin_same_origin_and_sandbox():
    root = _docnode("https://a.example/p", [_el("html", children=[_el("body", children=[
        _el("iframe", [("id", "s"), ("src", "/x")],
            contentDocument=_docnode("https://a.example/x", [_el("html")])),
        _el("iframe", [("id", "x"), ("src", "https://b.example/y")], frameId="F2"),
        _el("iframe", [("id", "d"), ("srcdoc", "<p>")],
            contentDocument=_docnode("about:srcdoc", [_el("html")])),
        _el("iframe", [("id", "b"), ("sandbox", ""), ("srcdoc", "<p>")]),
        _el("iframe", [("id", "k"), ("src", "about:blank")]),
    ])])])
    doc = from_cdp(root)
    f = {doc.attr(x.element, "id"): x for x in doc.frames}
    assert f["s"].same_origin and f["s"].state == "read" and f["s"].document > 0
    assert f["x"].origin == "https://b.example" and not f["x"].same_origin
    assert f["x"].state == "not-loaded"
    assert f["d"].same_origin and f["b"].origin == "null" and f["b"].sandboxed
    assert f["k"].same_origin
    assert doc.attr(f["s"].document, "same-origin") == "1"


def test_graft_by_frame_id_cap_and_detached():
    def page():
        return _docnode("https://a.example/", [_el("html", children=[
            _el("iframe", [("src", "https://b.example/1")], frameId="A"),
            _el("iframe", [("src", "https://c.example/2")], frameId="B"),
            _el("iframe", [("src", "https://d.example/3")], frameId="C"),
            _el("iframe", [("src", "https://e.example/4")], frameId="D")])])
    inner = _docnode("https://b.example/1", [_el("html", children=[_el("input", [("name", "q")])])])
    root = page()
    rep = graft_frames(root, {"A": FrameRead("A", inner), "B": FrameRead("B", inner),
                              "C": FrameRead("C", None, "detached")}, frame_cap=1)
    assert (rep.grafted, rep.over_cap) == (1, 1)
    obs = observe_cdp(root, url="https://a.example/")
    states = sorted(x.state for x in obs.frames)
    assert states == ["cross-origin-unread", "detached", "frame-cap", "read"]
    kinds = {t.kind for t in obs.truncations}
    assert {"frame-detached", "frame-frame-cap", "frame-cross-origin-unread"} <= kinds
    assert not obs.complete


def test_byte_cap_fires_and_is_recorded():
    root = _docnode("u", [_el("html", children=[_el("p", children=[_txt("x" * 500)])
                                                 for _ in range(50)])])
    doc = from_cdp(root, limits=DocLimits(max_bytes=5_000))
    assert any(t.kind == "bytes" for t in doc.truncations)


def test_deep_and_wide_payloads_stay_valid_and_capped():
    deep = _el("div")
    cur = deep
    for _ in range(5_000):
        nxt = _el("div")
        cur["children"] = [nxt]
        cur = nxt
    wide = _el("div", children=[_el("span", children=[_txt("r")]) for _ in range(30_000)])
    root = _docnode("u", [_el("html", children=[_el("body", children=[deep, wide])])])
    doc = from_cdp(root)
    kinds = {t.kind for t in doc.truncations}
    assert {"depth", "nodes"} <= kinds and len(doc) <= DocLimits().max_nodes
    for i in range(1, len(doc)):
        assert 0 <= doc.parent[i] < i


def test_malformed_payloads_never_raise():
    for bad in ({}, {"root": 5}, {"root": {"nodeType": 1, "attributes": 7, "children": [3, None]}},
                {"documents": "x"}, {"documents": [{"nodes": {"parentIndex": [5, -1]}}], "strings": []}):
        from_cdp(bad)
        from_snapshot(bad)
        snapshot_to_tree(bad)


def test_origin_of():
    assert origin_of("https://A.example:443/x") == "https://a.example"
    assert origin_of("http://h:8080/") == "http://h:8080"
    assert origin_of("about:blank") == origin_of("data:text/html,x") == "null"
    assert origin_of("http://[bad") == "null"


CAPS = os.environ.get("PAGECOMP_CAPTURES")


@pytest.mark.skipif(not CAPS, reason="PAGECOMP_CAPTURES not set")
def test_smartrecruiters_pierced_dom_layout_join_matches_from_cdp():
    """Pin 8: the adapter's tree (pierced DOM, joined with any snapshot)
    equals what ``from_cdp`` already reads from the owner's capture."""
    path = next(Path(CAPS, "form-one-page").glob("*smartrecruiters*")) / "dom_pierced.json.gz"
    dom = json.loads(gzip.decompress(path.read_bytes()))
    a = from_cdp(dom)
    b = from_snapshot({"documents": [], "strings": []}, dom=dom)
    assert a.structure_hash == b.structure_hash and len(a) > 10_000
    assert any(a.kind[i] == SHADOW for i in range(len(a)))
    assert sum(1 for _ in a.elements("input")) >= 20

"""S3 pins: the pagecomp access adapter against real headless Chromium.

Two local servers on different sites (``localhost`` and ``127.0.0.1``) give
a real cross-site, out-of-process iframe. Skipped when Playwright, its
Chromium or pagecomp is missing.
"""

from __future__ import annotations

import functools
import os
import http.server
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pagecomp = pytest.importorskip("pagecomp")
pw = pytest.importorskip("playwright.sync_api")

from pagecomp.access import ObservationRequest  # noqa: E402
from pagecomp.doc import ELEMENT, SHADOW  # noqa: E402

from auto_apply.adapters.secondary.perception.pagecomp_access import PagecompAccess  # noqa: E402

FIX = Path(__file__).resolve().parents[3] / "fixtures" / "pagecomp_s3"


class _Handler(http.server.SimpleHTTPRequestHandler):
    xo_origin = ""

    def log_message(self, *a: Any) -> None:  # quiet
        pass

    def do_GET(self) -> None:  # noqa: N802
        path = FIX / self.path.lstrip("/").split("?")[0]
        if not path.is_file():
            self.send_error(404)
            return
        body = path.read_text().replace("XO_ORIGIN", self.xo_origin).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve(host: str, xo: str = "") -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = type("H", (_Handler,), {"xo_origin": xo})
    srv = http.server.ThreadingHTTPServer((host, 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://{host}:{srv.server_address[1]}"


@pytest.fixture(scope="module")
def servers() -> Iterator[tuple[str, str]]:
    b, b_url = _serve("127.0.0.1")
    a, a_url = _serve("localhost", xo=b_url.replace("127.0.0.1", "127.0.0.1"))
    yield a_url, b_url
    a.shutdown()
    b.shutdown()


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    try:
        p = pw.sync_playwright().start()
        # PAGECOMP_CHROMIUM: a Chrome/Chromium binary to use instead of
        # Playwright's own download (for machines that have Chrome already).
        br = p.chromium.launch(executable_path=os.environ.get("PAGECOMP_CHROMIUM") or None)
    except Exception as e:  # no browser in this environment
        pytest.skip(f"chromium unavailable: {e}")
    yield br
    br.close()
    p.stop()


@pytest.fixture()
def page(browser: Any) -> Iterator[Any]:
    pg = browser.new_page()
    yield pg
    pg.close()


def _names(doc: Any) -> set[str]:
    return {doc.attr(i, "name") or "" for i in doc.elements("input")}


def _read(page: Any, url: str, *, cdp: bool = True, **kw: Any) -> Any:
    page.goto(url)
    page.wait_for_timeout(150)
    return PagecompAccess(page, prefer_cdp=cdp).observe(ObservationRequest(**kw))


@pytest.mark.parametrize("cdp", [True, False])
def test_shadow_roots_open_closed_declarative_and_slots(page: Any, servers: Any, cdp: bool) -> None:
    out = _read(page, servers[0] + "/shadow.html", cdp=cdp)
    doc = out.observation.doc
    names = _names(doc)
    assert {"email", "nested", "decl"} <= names
    modes = [doc.attr(i, "mode") for i in range(len(doc)) if doc.kind[i] == SHADOW]
    if cdp:
        assert "secret" in names and "closed" in modes            # CDP sees closed roots
        assert "VIA_CDP" in out.observation.capabilities
        slotted = [i for i in range(len(doc)) if doc.kind[i] == ELEMENT and doc.attr(i, "slot") == "s"]
        assert slotted and doc.tag_name(doc.slots[slotted[0]]) == "slot"
    else:
        assert "secret" not in names                               # never seen by a page script
        assert "CLOSED_SHADOW_UNSEEN" in out.observation.capabilities
        assert any(t.kind == "closed-shadow-suspect" for t in doc.truncations)


@pytest.mark.parametrize("cdp", [True, False])
def test_iframe_in_shadow_root_and_shadow_root_in_iframe(page: Any, servers: Any, cdp: bool) -> None:
    out = _read(page, servers[0] + "/shadow.html", cdp=cdp)
    doc = out.observation.doc
    sf = [f for f in doc.frames if f.url == "about:srcdoc"]
    assert sf and sf[0].state == "read"
    frame_doc = sf[0].document
    assert any(doc.tag_name(i) == "p" for i in doc.subtree(frame_doc))
    out2 = _read(page, servers[0] + "/frames.html", cdp=cdp)
    assert "shadow-in-frame" in _names(out2.observation.doc)


@pytest.mark.parametrize("cdp", [True, False])
def test_frame_kinds_origin_and_state(page: Any, servers: Any, cdp: bool) -> None:
    out = _read(page, servers[0] + "/frames.html", cdp=cdp)
    obs = out.observation
    by_id = {obs.doc.attr(f.element, "id"): f for f in obs.frames}
    assert by_id["same"].same_origin and by_id["same"].state == "read"
    xo = by_id["xo"]
    assert not xo.same_origin and xo.origin.startswith("http://127.0.0.1")
    assert xo.state == "read", xo                                 # OOPIF grafted / switched into
    assert by_id["sd"].same_origin and by_id["sd"].state == "read"
    assert by_id["sb"].sandboxed and by_id["sb"].origin == "null" and not by_id["sb"].same_origin
    assert by_id["blank"].same_origin
    assert {"inner", "srcdoc"} <= _names(obs.doc)
    assert "lazy" in by_id                                        # recorded whatever its load state


def test_frame_cap_fires_and_is_recorded(page: Any, servers: Any) -> None:
    out = _read(page, servers[0] + "/frames.html", cdp=False, frame_cap=0)
    states = {f.state for f in out.observation.frames}
    assert "frame-cap" in states
    assert any(t.kind.startswith("frame-") for t in out.observation.doc.truncations)


@pytest.mark.parametrize("cdp", [True, False])
def test_busy_loop_page_gives_typed_timeout(page: Any, servers: Any, cdp: bool) -> None:
    page.goto(servers[0] + "/busy.html")
    page.wait_for_timeout(300)  # the loop has started
    out = PagecompAccess(page, prefer_cdp=cdp).observe(
        ObservationRequest(script_deadline_ms=800, wall_ms=2000))
    assert out.timed_out
    assert "script-deadline" in out.observation.read_flags
    assert out.observation.stale and not out.observation.complete
    page.wait_for_timeout(8000)


@pytest.mark.parametrize("cdp", [True, False])
def test_node_and_depth_caps_fire_tree_stays_valid(page: Any, servers: Any, cdp: bool) -> None:
    out = _read(page, servers[0] + "/big.html", cdp=cdp, max_nodes=10_000)
    doc = out.observation.doc
    kinds = {t.kind for t in doc.truncations}
    assert "nodes" in kinds
    assert len(doc) <= 10_000
    for i in range(1, len(doc)):                     # pre-order invariant holds
        p = doc.parent[i]
        assert 0 <= p < i and doc.end[p] >= doc.end[i]
    out2 = _read(page, servers[0] + "/big.html", cdp=cdp, max_nodes=60_000)
    assert "depth" in {t.kind for t in out2.observation.doc.truncations}
    assert "partial" in out2.observation.read_flags


@pytest.mark.parametrize("cdp", [True, False])
def test_pushstate_during_read_is_stale(page: Any, servers: Any, cdp: bool) -> None:
    page.goto(servers[0] + "/spa.html")
    acc = PagecompAccess(page, prefer_cdp=cdp)
    real = acc._read_cdp if cdp else acc._read_walk

    def racing(*a: Any) -> Any:
        page.evaluate("history.pushState({}, '', '/next-step')")
        return real(*a)

    if cdp:
        acc._read_cdp = racing  # type: ignore[method-assign]
    else:
        acc._read_walk = racing  # type: ignore[method-assign]
    obs = acc.observe(ObservationRequest()).observation
    assert {"spa-navigated", "stale"} <= obs.read_flags


def test_navigation_during_read_is_stale(page: Any, servers: Any) -> None:
    page.goto(servers[0] + "/spa.html")
    acc = PagecompAccess(page, prefer_cdp=False)
    real = acc._read_walk

    def racing(*a: Any) -> Any:
        page.goto(servers[0] + "/shadow.html")
        return real(*a)

    acc._read_walk = racing  # type: ignore[method-assign]
    obs = acc.observe(ObservationRequest()).observation
    assert {"navigated", "stale"} <= obs.read_flags


def test_frame_detached_during_read_is_partial_not_exception(page: Any, servers: Any) -> None:
    page.goto(servers[0] + "/frames.html")
    page.wait_for_timeout(200)
    acc = PagecompAccess(page, prefer_cdp=False)
    real = acc._walk_frame

    def detaching(handle: Any, *a: Any) -> Any:
        page.evaluate("document.getElementById('xo') && document.getElementById('xo').remove()")
        return real(handle, *a)

    acc._walk_frame = detaching  # type: ignore[method-assign]
    out = acc.observe(ObservationRequest())
    obs = out.observation
    assert any(f.state == "detached" for f in obs.frames)
    assert {"frame-detached", "partial"} <= obs.read_flags


def test_layout_level_gives_real_visibility(page: Any, servers: Any) -> None:
    from pagecomp.tools.visibility import compute

    out = _read(page, servers[0] + "/shadow.html", level="layout")
    obs = out.observation
    assert "SNAPSHOT_LAYOUT" in obs.capabilities
    vm = compute(obs.doc)
    assert vm.layout_known
    hidden_p = [i for i in obs.doc.elements("p") if obs.doc.attr(i, "class") == "hide"]
    assert hidden_p and vm.hidden(hidden_p[0])                    # class-based hiding seen
    email = [i for i in obs.doc.elements("input") if obs.doc.attr(i, "name") == "email"]
    assert email and vm.why(email[0]) == "visible"

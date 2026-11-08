"""AccessPort adapter for pagecomp (S3): one bounded read of a live page.

Rungs, tried in order and recorded as capabilities on the observation:

1. **Chromium with CDP** (``VIA_CDP``). ``DOM.getDocument(depth=-1,
   pierce=true)`` gives open and closed shadow roots and same-process
   frames. Out-of-process (cross-site) iframes are absent from that result:
   each is read through its own CDP session (Playwright
   ``new_cdp_session(frame)``) and grafted under its ``<iframe>`` by frame
   id. At level ``layout`` a ``DOMSnapshot`` is joined on by backend node id.
2. **No CDP** (``VIA_SCRIPT_WALK``: Firefox, WebKit, or CDP refused). One
   batched in-page walk with a hard deadline and the same caps. It sees
   open shadow roots and same-origin frames; cross-origin frames are read
   by switching into each, at most ``frame_cap`` of them and within the
   frame-depth cap. Closed shadow roots cannot be seen from a page script:
   the gap ``CLOSED_SHADOW_UNSEEN`` is always declared on this rung and
   defined custom elements with no open root are counted as suspects.

Every read is bracketed by a probe (URL, document id, mutation count) so a
navigation, a ``pushState`` or a mutation during the read flags the
observation ``stale``. Nothing here raises to the caller: browser errors
become flags, truncations and notes. The page is never written to beyond
installing one MutationObserver counter.

Time bounds. The Playwright rung evaluates through ``wait_for_function``,
whose timeout is enforced outside the page, so a busy-looping page yields a
typed timeout (``ObservationOutcome.timed_out``) instead of a hang. The
Selenium rung relies on the WebDriver script timeout, set to the request's
deadline for the call and restored afterwards. A wall-time budget covers the
whole observation, all frames included.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from pagecomp.access import (
    CLOSED_SHADOW_UNSEEN,
    CROSS_ORIGIN_UNSEEN,
    IFRAME_TRAVERSAL,
    SHADOW_PIERCING,
    SNAPSHOT_HTML,
    SNAPSHOT_LAYOUT,
    VIA_CDP,
    VIA_SCRIPT_WALK,
    CapabilitySet,
    FrameRead,
    ObservationOutcome,
    ObservationRequest,
    ReadProbe,
    flags_from_frames,
    graft_frames,
    iframe_nodes,
    read_flags,
)
from pagecomp.doc import (
    FRAME_CAP,
    FRAME_CROSS_ORIGIN_UNREAD,
    FRAME_DEPTH_CAP,
    FRAME_DETACHED,
    FRAME_TIMEOUT,
    SNAPSHOT_STYLES,
    from_cdp,
)
from pagecomp.doc import from_snapshot
from pagecomp.observation import (
    FLAG_PARTIAL,
    FLAG_SCRIPT_DEADLINE,
    FLAG_WALL_TIME,
    PageObservation,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-page scripts (no page state is changed except one counter)
# ---------------------------------------------------------------------------

PROBE_JS = """() => {
  try {
    if (!window.__pcMut) {
      window.__pcMut = {n: 0};
      new MutationObserver(r => { window.__pcMut.n += r.length; })
        .observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
    }
    return {url: String(location.href), doc: String(performance.timeOrigin), mut: window.__pcMut.n};
  } catch (e) { return {url: String(location.href), doc: '', mut: -1}; }
}"""

#: The walk emits the DOM.getDocument shape so one builder reads both rungs.
WALK_JS = """(opt) => {
  // Output is FLAT (parent index + relation per node): a nested result of a
  // deep page exceeds the drivers' serialisation depth (measured: Playwright
  // "object reference chain is too long" at nesting 5,000).
  const t0 = performance.now();
  const flat = [{nodeType: 9, documentURL: String(location.href), _p: -1, _r: ''}];
  const cut = {}; const xo = [];
  let count = 0, bytes = 0, suspects = 0, deadline = false;
  const CUT = (k, lim, n) => { const e = cut[k] || [lim, 0]; e[1] += (n || 1); cut[k] = e; };
  const stack = [[document.documentElement, 0, 'c', 1, 0]];
  if (opt.root) {
    let r = null; try { r = document.querySelector(opt.root); } catch (e) { r = null; }
    stack.length = 0; if (r) stack.push([r, 0, 'c', 1, 0]); else CUT('region-missing', 0);
  }
  const push = (o, p, r) => { o._p = p; o._r = r; flat.push(o); return flat.length - 1; };
  while (stack.length) {
    if ((count & 255) === 0 && performance.now() - t0 > opt.deadline) { deadline = true; CUT('script-deadline', opt.deadline, stack.length); break; }
    const [n, parent, rel, depth, fd] = stack.pop();
    if (!n) continue;
    if (count >= opt.maxNodes) { CUT('nodes', opt.maxNodes, stack.length + 1); break; }
    if (depth >= opt.maxDepth) { CUT('depth', opt.maxDepth); continue; }
    const t = n.nodeType;
    if (t === 1) {
      const attrs = [];
      for (const a of n.attributes) { attrs.push(a.name, a.value); bytes += a.name.length + a.value.length; }
      if (bytes > opt.maxBytes) { CUT('bytes', opt.maxBytes); break; }
      const o = {nodeType: 1, localName: n.localName, attributes: attrs};
      const tag = n.localName;
      if (tag.indexOf('-') > 0 && !n.shadowRoot && window.customElements && customElements.get(tag)) { suspects++; o.closedShadowSuspect = true; }
      if (tag === 'iframe' || tag === 'frame') {
        let d = null;
        try { d = n.contentDocument; } catch (e) { d = null; }
        o.frameURL = n.src || '';
        if (!d) {
          if (xo.length < opt.frameCap && fd + 1 <= opt.maxFrameDepth) { o.xoIndex = xo.length; xo.push(n); o.frameState = 'cross-origin-unread'; }
          else { o.frameState = (fd + 1 > opt.maxFrameDepth) ? 'frame-depth-cap' : 'frame-cap'; }
        } else if (!d.documentElement) { o.frameState = 'not-loaded'; }
        else if (fd + 1 > opt.maxFrameDepth) { o.frameState = 'frame-depth-cap'; CUT('frame-depth', opt.maxFrameDepth); d = null; }
        o._doc = d;
      }
      const me = push(o, parent, rel);
      count++;
      // Pushed in reverse of visiting order: light children, frame doc, shadow root.
      if (tag !== 'template') {
        const kids = n.childNodes;
        for (let i = kids.length - 1; i >= 0; i--) stack.push([kids[i], me, 'c', depth + 1, fd]);
      }
      if (o._doc) {
        const doc = push({nodeType: 9, documentURL: String(o._doc.URL)}, me, 'd');
        stack.push([o._doc.documentElement, doc, 'c', depth + 2, fd + 1]);
      }
      delete o._doc;
      if (n.shadowRoot) {
        const sr = push({nodeType: 11, shadowRootType: n.shadowRoot.mode}, me, 's');
        const kids = n.shadowRoot.childNodes;
        for (let i = kids.length - 1; i >= 0; i--) stack.push([kids[i], sr, 'c', depth + 2, fd]);
      }
    } else if (t === 3) {
      let v = n.nodeValue || '';
      if (v.length > opt.maxText) { CUT('text', opt.maxText); v = v.slice(0, opt.maxText); }
      bytes += v.length;
      if (bytes > opt.maxBytes) { CUT('bytes', opt.maxBytes); break; }
      push({nodeType: 3, nodeValue: v}, parent, rel);
      count++;
    }
  }
  if (suspects) CUT('closed-shadow-suspect', 0, suspects);
  return {flat: flat, cut: cut, deadline: deadline, xo: xo, ms: performance.now() - t0};
}"""


def unflatten(flat: Any) -> dict[str, Any]:
    """Rebuild the nested ``DOM.getDocument`` shape from the walk's flat list.
    Iterative and total: entries with a bad parent index are dropped."""
    if not isinstance(flat, list) or not flat or not isinstance(flat[0], dict):
        return {"nodeType": 9, "children": []}
    objs: list[dict[str, Any]] = []
    for i, o in enumerate(flat):
        if not isinstance(o, dict):
            objs.append({})
            continue
        p, r = o.pop("_p", -1), o.pop("_r", "")
        o.setdefault("children", [])
        objs.append(o)
        if i == 0 or not isinstance(p, int) or not (0 <= p < i):
            continue
        parent = objs[p]
        if r == "s":
            parent.setdefault("shadowRoots", []).append(o)
        elif r == "d":
            parent["contentDocument"] = o
        else:
            parent.setdefault("children", []).append(o)
    return objs[0]


def _now_ms(clock: Callable[[], float]) -> float:
    return clock() * 1000.0


class PagecompAccess:
    """``AccessPort`` over a Playwright ``Page`` or a Selenium ``WebDriver``.

    ``clock`` is injected (seconds, monotonic) so tests can drive the wall
    budget. ``prefer_cdp=False`` forces the script-walk rung.
    """

    def __init__(self, target: Any, *, clock: Callable[[], float] = time.monotonic,
                 prefer_cdp: bool = True, environment: dict[str, Any] | None = None) -> None:
        self._t = target
        self._clock = clock
        self._prefer_cdp = prefer_cdp
        self._env = dict(environment or {})
        self._kind = "playwright" if hasattr(target, "wait_for_function") else (
            "selenium" if hasattr(target, "execute_script") else "unknown")
        self._cdp: Any = None

    # -- capability detection -------------------------------------------
    def _cdp_send(self) -> Callable[[str, dict[str, Any]], Any] | None:
        if not self._prefer_cdp:
            return None
        try:
            if self._kind == "playwright":
                if self._cdp is None:
                    self._cdp = self._t.context.new_cdp_session(self._t)
                return lambda m, p: self._cdp.send(m, p)
            if self._kind == "selenium" and callable(getattr(self._t, "execute_cdp_cmd", None)):
                return lambda m, p: self._t.execute_cdp_cmd(m, p)
        except Exception as e:  # not Chromium, or CDP refused
            logger.debug("pagecomp_access: CDP unavailable: %s", e)
        return None

    def capabilities(self) -> CapabilitySet:
        if self._cdp_send() is not None:
            return CapabilitySet(frozenset({SNAPSHOT_HTML, SNAPSHOT_LAYOUT, SHADOW_PIERCING,
                                            IFRAME_TRAVERSAL, VIA_CDP}))
        return CapabilitySet(frozenset({SNAPSHOT_HTML, IFRAME_TRAVERSAL, VIA_SCRIPT_WALK}),
                             frozenset({CLOSED_SHADOW_UNSEEN}))

    # -- bounded evaluation ---------------------------------------------
    def _eval(self, ctx: Any, js: str, arg: Any, timeout_ms: float) -> tuple[Any, bool]:
        """(value, timed_out). ``ctx`` is a Playwright Page/Frame or the
        Selenium driver (already switched to the right frame)."""
        timeout_ms = max(1.0, timeout_ms)
        try:
            if self._kind == "playwright":
                h = ctx.wait_for_function(f"(arg) => ({js})(arg) || true", arg=arg,
                                          timeout=timeout_ms, polling="raf")
                return h.json_value(), False
            if self._kind == "selenium":
                d = self._t
                old = None
                try:
                    old = d.timeouts.script
                except Exception:
                    old = None
                d.set_script_timeout(timeout_ms / 1000.0)
                try:
                    return d.execute_script(f"return ({js})(arguments[0]);", arg), False
                finally:
                    if old is not None:
                        d.set_script_timeout(old)
        except Exception as e:
            name = type(e).__name__
            if "Timeout" in name:
                return None, True
            logger.debug("pagecomp_access: evaluation failed: %s", e)
            return None, False
        return None, False

    def _probe(self, budget_ms: float) -> ReadProbe | None:
        v, _ = self._eval(self._t if self._kind == "playwright" else None, PROBE_JS, None,
                          budget_ms)
        if not isinstance(v, dict):
            return None
        return ReadProbe(str(v.get("url", "")), str(v.get("doc", "")), int(v.get("mut", -1)))

    # -- the one call ------------------------------------------------------
    def observe(self, request: ObservationRequest) -> ObservationOutcome:
        start = _now_ms(self._clock)
        notes: list[str] = []
        try:
            return self._observe(request, start, notes)
        except Exception as e:  # last line: a hostile page never raises to the caller
            notes.append(f"adapter-error:{type(e).__name__}")
            doc = from_cdp({}, "", request.limits(), extra_truncations={"adapter-error": (0, 1)})
            obs = PageObservation("", "", doc, request.epoch, request.requested_url,
                                  frozenset(), self._env, request.query,
                                  frozenset({FLAG_PARTIAL, "stale"}), {}, self._kind)
            return ObservationOutcome(obs, False, tuple(notes))

    def _left(self, request: ObservationRequest, start: float) -> float:
        return request.wall_ms - (_now_ms(self._clock) - start)

    def _observe(self, req: ObservationRequest, start: float,
                 notes: list[str]) -> ObservationOutcome:
        deadline = min(req.script_deadline_ms, self._left(req, start))
        before = self._probe(deadline)
        if before is None:
            # Page unresponsive (busy loop) or gone: typed timeout, no further calls.
            notes.append("probe-failed")
            doc = from_cdp({}, "", req.limits(),
                           extra_truncations={"script-deadline": (req.script_deadline_ms, 1)})
            obs = PageObservation("", "", doc, req.epoch, req.requested_url,
                                  self.capabilities().names(), self._env, req.query,
                                  frozenset({FLAG_SCRIPT_DEADLINE, FLAG_PARTIAL, "stale"}),
                                  {"total_ms": _now_ms(self._clock) - start}, self._kind)
            return ObservationOutcome(obs, True, tuple(notes))
        send = self._cdp_send()
        flags: set[str] = set()
        timings: dict[str, float] = {}
        caps: CapabilitySet
        if send is not None and req.region_root is None:
            payload, snap, extra, caps, timed_out = self._read_cdp(send, req, start, notes, flags)
        else:
            payload, extra, caps, timed_out = self._read_walk(req, start, notes, flags)
            snap = None
        timings["read_ms"] = _now_ms(self._clock) - start
        after = self._probe(min(req.script_deadline_ms, max(1.0, self._left(req, start))))
        flags |= read_flags(before, after)
        url = before.url
        if snap is not None:
            doc = from_snapshot(snap, url, req.limits(), dom=payload, extra_truncations=extra)
        else:
            doc = from_cdp(payload, url, req.limits(), extra_truncations=extra)
        title = ""
        try:
            title = str(self._t.title() if callable(self._t.title) else self._t.title)
        except Exception:
            title = ""
        obs = PageObservation(url, title, doc, req.epoch, req.requested_url, caps.names(),
                              self._env, req.query, frozenset(flags), timings, self._kind)
        ff = flags_from_frames(obs)
        if ff or doc.truncations:
            obs = PageObservation(url, title, doc, req.epoch, req.requested_url, caps.names(),
                                  self._env, req.query,
                                  frozenset(flags | ff | ({FLAG_PARTIAL} if doc.truncations else set())),
                                  timings, self._kind)
        timings["total_ms"] = _now_ms(self._clock) - start
        return ObservationOutcome(obs, timed_out, tuple(notes))

    # -- rung 1: CDP -------------------------------------------------------
    def _read_cdp(self, send: Callable[[str, dict[str, Any]], Any], req: ObservationRequest,
                  start: float, notes: list[str], flags: set[str],
                  ) -> tuple[dict[str, Any], Any, dict[str, tuple[int, int]], CapabilitySet, bool]:
        extra: dict[str, tuple[int, int]] = {}
        caps = {SNAPSHOT_HTML, SHADOW_PIERCING, IFRAME_TRAVERSAL, VIA_CDP}
        gaps: set[str] = set()
        try:
            dom = send("DOM.getDocument", {"depth": -1, "pierce": True})
        except Exception as e:
            # Measured: a 5,000-deep page overflows the protocol's CBOR stack.
            # Retry bounded at the depth cap; the cut is recorded.
            notes.append(f"cdp-full-failed:{type(e).__name__}")
            try:
                dom = send("DOM.getDocument", {"depth": req.max_depth, "pierce": True})
                extra["depth"] = (req.max_depth, 1)
            except Exception as e2:
                dom = None
                notes.append(f"cdp-failed:{type(e2).__name__}")
        if not isinstance(dom, dict):
            payload, extra2, c2, to = self._read_walk(req, start, notes, flags)
            return payload, None, extra2, c2, to
        root = dom.get("root", dom) if isinstance(dom, dict) else {}
        snap = None
        if req.level == "layout":
            try:
                snap = send("DOMSnapshot.captureSnapshot",
                            {"computedStyles": list(SNAPSHOT_STYLES), "includePaintOrder": True,
                             "includeDOMRects": False})
                caps.add(SNAPSHOT_LAYOUT)
            except Exception as e:
                notes.append(f"snapshot-failed:{type(e).__name__}")
        reads = self._read_oopifs(root, req, start, notes)
        rep = graft_frames(root, reads, req.frame_cap)
        if rep.unread:
            gaps.add(CROSS_ORIGIN_UNSEEN)
        timed_out = False
        if self._left(req, start) <= 0:
            flags.add(FLAG_WALL_TIME)
            timed_out = True
        return root, snap, extra, CapabilitySet(frozenset(caps), frozenset(gaps)), timed_out

    def _read_oopifs(self, root: dict[str, Any], req: ObservationRequest, start: float,
                     notes: list[str]) -> dict[str, FrameRead]:
        """Read each out-of-process iframe through its own CDP session."""
        missing = [n for n in iframe_nodes(root)
                   if not isinstance(n.get("contentDocument"), dict) and n.get("frameId")]
        reads: dict[str, FrameRead] = {}
        if not missing or self._kind != "playwright":
            if missing:
                notes.append("oopif-needs-frame-switch")
                self._selenium_xo_frames(missing, req, start, notes, reads)
            return reads
        frames_by_id: dict[str, Any] = {}
        budget = req.frame_cap
        for fr in self._t.frames[1: 1 + 4 * req.frame_cap]:
            if budget <= 0 or self._left(req, start) <= 0:
                break
            try:
                s = self._t.context.new_cdp_session(fr)
            except Exception:
                continue  # same-process frame: it is already in the pierced tree
            try:
                tree = s.send("Page.getFrameTree", {})
                fid = str(tree["frameTree"]["frame"]["id"])
                frames_by_id[fid] = s
            except Exception:
                try:
                    s.detach()
                except Exception:
                    pass
        for node in missing:
            fid = str(node.get("frameId"))
            s = frames_by_id.get(fid)
            if s is None:
                continue
            if budget <= 0:
                reads[fid] = FrameRead(fid, None, FRAME_CAP)
                continue
            if self._left(req, start) <= 0:
                reads[fid] = FrameRead(fid, None, FRAME_TIMEOUT)
                continue
            budget -= 1
            try:
                d = s.send("DOM.getDocument", {"depth": -1, "pierce": True})
                reads[fid] = FrameRead(fid, d.get("root", d), "read")
            except Exception:
                reads[fid] = FrameRead(fid, None, FRAME_DETACHED)
        for s in frames_by_id.values():
            try:
                s.detach()
            except Exception:
                pass
        return reads

    def _selenium_xo_frames(self, missing: list[dict[str, Any]], req: ObservationRequest,
                            start: float, notes: list[str], reads: dict[str, FrameRead]) -> None:
        """Selenium has no per-frame CDP session: the frames stay marked
        unread (``CROSS_ORIGIN_UNSEEN``) unless the walk rung is used."""
        for n in missing:
            fid = str(n.get("frameId"))
            reads[fid] = FrameRead(fid, None, FRAME_CROSS_ORIGIN_UNREAD)

    # -- rung 2: script walk -----------------------------------------------
    def _walk_opts(self, req: ObservationRequest, deadline: float) -> dict[str, Any]:
        lim = req.limits()
        return {"root": req.region_root, "deadline": deadline, "maxNodes": req.max_nodes,
                "maxDepth": req.max_depth, "maxFrameDepth": req.max_frame_depth,
                "frameCap": req.frame_cap, "maxText": lim.max_text_chars,
                "maxBytes": req.max_bytes}

    def _read_walk(self, req: ObservationRequest, start: float, notes: list[str],
                   flags: set[str]) -> tuple[dict[str, Any], dict[str, tuple[int, int]],
                                             CapabilitySet, bool]:
        caps = {SNAPSHOT_HTML, IFRAME_TRAVERSAL, VIA_SCRIPT_WALK}
        gaps = {CLOSED_SHADOW_UNSEEN}
        extra: dict[str, tuple[int, int]] = {}
        timed_out = False
        root, xo_handles, to = self._walk_ctx(self._t, req, start, extra, top=True)
        if to:
            flags.add(FLAG_SCRIPT_DEADLINE)
            timed_out = True
        # Cross-origin frames: switch into each (bounded queue, depth-capped).
        queue: list[tuple[Any, dict[str, Any], int]] = []
        for node in iframe_nodes(root):
            k = node.get("xoIndex")
            if isinstance(k, int) and k < len(xo_handles):
                queue.append((xo_handles[k], node, 1))
        reads = 0
        while queue:
            handle, node, fd = queue.pop(0)
            if reads >= req.frame_cap:
                node["frameState"] = FRAME_CAP
                continue
            if fd > req.max_frame_depth:
                node["frameState"] = FRAME_DEPTH_CAP
                continue
            if self._left(req, start) <= 0:
                node["frameState"] = FRAME_TIMEOUT
                flags.add(FLAG_WALL_TIME)
                timed_out = True
                continue
            reads += 1
            if self._kind == "selenium" and fd == 1:
                try:
                    self._t.switch_to.default_content()
                except Exception:
                    pass
            sub, sub_xo, sto = self._walk_frame(handle, req, start, extra)
            if sub is None:
                node["frameState"] = FRAME_DETACHED
                continue
            node.pop("frameState", None)
            node["contentDocument"] = sub
            if sto:
                flags.add(FLAG_SCRIPT_DEADLINE)
            for inner in iframe_nodes(sub):
                k = inner.get("xoIndex")
                if isinstance(k, int) and k < len(sub_xo):
                    queue.append((sub_xo[k], inner, fd + 1))
        if any(n.get("frameState") == FRAME_CROSS_ORIGIN_UNREAD for n in iframe_nodes(root)):
            gaps.add(CROSS_ORIGIN_UNSEEN)
        if self._kind == "selenium":
            try:
                self._t.switch_to.default_content()
            except Exception:
                pass
        return root, extra, CapabilitySet(frozenset(caps), frozenset(gaps)), timed_out

    def _merge_cut(self, extra: dict[str, tuple[int, int]], cut: Any) -> None:
        if not isinstance(cut, dict):
            return
        for k, v in cut.items():
            try:
                lim, cnt = int(v[0]), int(v[1])
            except (TypeError, ValueError, IndexError):
                continue
            old = extra.get(str(k))
            extra[str(k)] = (lim, cnt + (old[1] if old else 0))

    def _walk_ctx(self, ctx: Any, req: ObservationRequest, start: float,
                  extra: dict[str, tuple[int, int]], top: bool,
                  ) -> tuple[dict[str, Any], list[Any], bool]:
        deadline = min(req.script_deadline_ms, max(1.0, self._left(req, start)))
        opts = self._walk_opts(req, deadline)
        if self._kind == "playwright":
            try:
                h = ctx.wait_for_function(f"(o) => ({WALK_JS})(o)", arg=opts,
                                          timeout=deadline + 500, polling="raf")
            except Exception as e:
                if "Timeout" in type(e).__name__:
                    extra["script-deadline"] = (int(req.script_deadline_ms), 1)
                    return {"nodeType": 9, "children": []}, [], True
                extra["read-failed"] = (0, 1)
                return {"nodeType": 9, "children": []}, [], False
            try:
                data = h.evaluate("r => ({flat: r.flat, cut: r.cut, deadline: r.deadline})")
                n_xo = int(h.evaluate("r => r.xo.length"))
                frames = []
                for k in range(min(n_xo, req.frame_cap)):
                    el = h.evaluate_handle(f"r => r.xo[{k}]").as_element()
                    frames.append(el.content_frame() if el is not None else None)
            except Exception as e:
                logger.debug("pagecomp_access: walk result unreadable: %s", e)
                extra["read-failed"] = (0, 1)
                return {"nodeType": 9, "children": []}, [], False
        else:
            v, to = self._eval(None, WALK_JS, opts, deadline + 500)
            if to or not isinstance(v, dict):
                if to:
                    extra["script-deadline"] = (int(req.script_deadline_ms), 1)
                else:
                    extra["read-failed"] = (0, 1)
                return {"nodeType": 9, "children": []}, [], to
            data = v
            frames = list(v.get("xo") or [])
        self._merge_cut(extra, data.get("cut"))
        root = unflatten(data.get("flat"))
        return root, frames, bool(data.get("deadline"))

    def _walk_frame(self, handle: Any, req: ObservationRequest, start: float,
                    extra: dict[str, tuple[int, int]],
                    ) -> tuple[dict[str, Any] | None, list[Any], bool]:
        if handle is None:
            return None, [], False
        if self._kind == "playwright":
            try:
                if handle.is_detached():
                    return None, [], False
            except Exception:
                return None, [], False
            root, xo, to = self._walk_ctx(handle, req, start, extra, top=False)
            return (root if root.get("children") or root.get("documentURL") else None), xo, to
        try:
            # Siblings are read from the top: WebDriver frame switching is
            # relative, so each top-level cross-origin frame starts afresh.
            # Nested cross-origin frames under Selenium are read only along
            # the current path (recorded limitation).
            self._t.switch_to.frame(handle)
        except Exception:
            return None, [], False
        root, xo, to = self._walk_ctx(None, req, start, extra, top=False)
        return root, xo, to

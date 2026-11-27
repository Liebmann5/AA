"""FormPagePort adapter: pagecomp reads the form; one place touches the live page.

Reading. One bounded read of the live page through ``PagecompAccess`` (the
CDP rung on Chromium, the script walk elsewhere: shadow roots included), then
pagecomp's ``forms`` and ``formread`` tools answer: which controls form the
application, how each is labelled, its canonical type, whether it is
required, whether it is a trap. Nothing about a specific site is known here.

Acting. Every element the engine acts on is resolved from its element path
by one small resolver script and identity-checked (tag, and name/id when the
reading had them) before it is returned. The resolver only reads the page.
Elements come back wrapped in the framework's own ``ElementInterface``
adapter, so the shared interaction tool operates them exactly as it operates
every other element in AA.

Framework-specific work lives here and nowhere else in the step engine:

* Selenium — ``execute_script`` returns the element; native selects use
  WebDriver's own option selection; files go to the input through WebDriver
  file upload (hidden inputs included: W3C ``strictFileInteractability`` is
  off by default, so the page's styling is never altered to make an input
  "visible").
* Playwright — ``evaluate_handle`` returns an ``ElementHandle``; a small shim
  lets the existing ``PlaywrightElementAdapter`` drive it; ``select_option``
  and ``set_input_files`` serve selects and files.

Footprint. The scripts here read the page and, for the recorded script
fallback only, set one control's value with the events frameworks listen
for. They add no attributes, no styles, no globals. (The pagecomp access
read installs its own mutation counter, ``window.__pcMut``; that is the
access adapter's documented probe, recorded as an open item.)

Never raises: a browser that cannot answer reads as "not found", an empty
list, or False, per the port's contract.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable, Sequence
from typing import Any

from auto_apply.domain.applications.form_model import (
    FILL,
    ControlRef,
    ControlState,
    FormButton,
    FormLink,
    FormOption,
    FormQuestion,
    FormStep,
    FrameCandidate,
    QuestionKind,
)
from auto_apply.domain.applications.option_matching import is_placeholder, normalize
from auto_apply.domain.ports.browser_port import ElementInterface

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-page scripts. Read-only except set_value_by_script.
# ---------------------------------------------------------------------------

_HELPERS = r"""
function aaVis(el) {
  if (!el || el.nodeType !== 1) return false;
  var shown = null;
  if (el.checkVisibility) {
    try { shown = el.checkVisibility({checkOpacity: false, checkVisibilityCSS: true}); } catch (e) {}
  }
  if (shown === null) {
    if (!el.getClientRects().length) return false;
    var cs = window.getComputedStyle(el);
    shown = cs.visibility !== 'hidden' && cs.display !== 'none';
  }
  if (!shown) return false;
  // Placed wholly left of or above the page ("left:-9999px"): no scrolling
  // reaches it, so no person can see it. The classic trap field. Visually
  // hidden inputs that keep their place (1px, clipped) are not affected.
  var w = (el.ownerDocument && el.ownerDocument.defaultView) || window;
  var r = el.getBoundingClientRect();
  if (r.right + w.scrollX <= 0 || r.bottom + w.scrollY <= 0) return false;
  return true;
}
function aaResolve(spec) {
  var node = document, scope = document, path = spec.path || [];
  for (var i = 0; i < path.length; i++) {
    var rel = path[i][0], k = path[i][1];
    if (rel === 's') {
      var sr = node && node.shadowRoot;
      if (!sr) { node = null; break; }
      node = sr; scope = sr; continue;
    }
    if (rel !== 'c') { node = null; break; }
    var kids = node ? node.children : null;
    if (!kids || k < 0 || k >= kids.length) { node = null; break; }
    node = kids[k];
  }
  function same(el) {
    return !!el && el.nodeType === 1 && el.localName === spec.tag &&
      (!spec.id || el.id === spec.id) &&
      (!spec.name || el.getAttribute('name') === spec.name);
  }
  if (same(node)) return node;
  try {
    if (spec.id) {
      var byId = scope.getElementById ? scope.getElementById(spec.id) : null;
      if (same(byId)) return byId;
    }
    if (spec.name) {
      var list = scope.querySelectorAll(spec.tag + '[name="' + CSS.escape(spec.name) + '"]');
      if (list.length === 1 && same(list[0])) return list[0];
    }
  } catch (e) {}
  return null;
}
function aaIsCombo(el) {
  var r = (el.getAttribute('role') || '').toLowerCase();
  return r === 'combobox' || el.getAttribute('aria-autocomplete') === 'list' ||
    el.getAttribute('aria-haspopup') === 'listbox';
}
// Text a person sees inside ``root``: visible text nodes only, never the
// text of a label, an open option list, an error or a live region inside it,
// nor of the elements in ``skipEls`` (a widget's own popup).
function aaShownText(root, skipEls) {
  var skip = 'label,[role=listbox],[role=option],[role=alert],[aria-live],script,style';
  var out = [], w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), t;
  while ((t = w.nextNode())) {
    var p = t.parentElement;
    if (!p || !aaVis(p)) continue;
    var m = p.closest(skip);
    if (m && (m === root || root.contains(m))) continue;
    if (aaInsideAny(p, skipEls)) continue;
    var v = (t.nodeValue || '').trim();
    if (v) out.push(v);
  }
  return out.join(' ').slice(0, 200);
}
// The popups a widget names as its own (aria-controls / aria-owns): a
// listbox, or a dialog, grid or tree holding one (ARIA 1.2 combobox).
function aaOwnPopups(el) {
  var root = el.getRootNode ? el.getRootNode() : document, out = [];
  ((el.getAttribute('aria-controls') || '') + ' ' +
   (el.getAttribute('aria-owns') || '')).split(/\s+/).forEach(function (id) {
    if (!id) return;
    var p = (root.getElementById && root.getElementById(id)) || document.getElementById(id);
    if (p) out.push(p);
  });
  return out;
}
function aaInsideAny(node, els) {
  if (!els) return false;
  for (var i = 0; i < els.length; i++) if (els[i] === node || els[i].contains(node)) return true;
  return false;
}
// Does ``box`` hold a form control other than ``el`` (or a label)? Then it is
// the field's container, not the widget's own box: its text is not a value.
// Native controls and every interactive ARIA widget count; the widget's own
// popups (``popups``, from aaOwnPopups) and the controls inside them do not.
var AA_CONTROLS = 'input:not([type=hidden]), select, textarea, [role=combobox],' +
  '[role=checkbox], [role=radio], [role=switch], [role=textbox], [role=listbox],' +
  '[role=spinbutton], [role=slider], [role=searchbox], [contenteditable=""],' +
  '[contenteditable=true]';
function aaFieldBoundary(box, el, popups) {
  if (/^(label|form|fieldset|body|html)$/.test(box.localName)) return true;
  if (box.querySelector('label')) return true;
  var cs = box.querySelectorAll(AA_CONTROLS);
  for (var i = 0; i < cs.length; i++) {
    var c = cs[i];
    if (c === el || c.contains(el) || el.contains(c)) continue;
    if (!aaInsideAny(c, popups)) return true;
  }
  return false;
}
// The words that name a control (never its value): its labels, aria-label,
// aria-labelledby, and the legend of its group.
function aaNameOf(c) {
  var parts = [], root = c.getRootNode ? c.getRootNode() : document;
  if (c.labels) for (var i = 0; i < c.labels.length; i++) parts.push(c.labels[i].textContent || '');
  var al = c.getAttribute('aria-label'); if (al) parts.push(al);
  (c.getAttribute('aria-labelledby') || '').split(/\s+/).forEach(function (id) {
    if (!id) return;
    var d = (root.getElementById && root.getElementById(id)) || document.getElementById(id);
    if (d) parts.push(d.textContent || '');
  });
  var fs = c.closest ? c.closest('fieldset') : null;
  if (fs) { var lg = fs.querySelector('legend'); if (lg) parts.push(lg.textContent || ''); }
  return parts.join(' ').replace(/\s+/g, ' ').trim().slice(0, 160);
}
// What a custom combobox shows as its selection. A typeahead shows it in its
// own value; a react-select style widget in a sibling inside the widget's
// box. The walk stops at the field's container, so the question's own label
// is never read as an answer.
function aaComboText(el) {
  if (el.localName !== 'input') return aaShownText(el);
  var v = (el.value || '').trim();
  if (v) return v.slice(0, 200);
  var popups = aaOwnPopups(el), node = el;
  for (var i = 0; i < 4 && node.parentElement; i++) {
    var up = node.parentElement;
    if (aaFieldBoundary(up, el, popups)) break;
    node = up;
    var t = aaShownText(up, popups);
    if (t) return t;
  }
  return '';
}
function aaErrorText(el) {
  var ids = ((el.getAttribute('aria-errormessage') || '') + ' ' +
             (el.getAttribute('aria-describedby') || '')).split(/\s+/);
  var root = el.getRootNode ? el.getRootNode() : document;
  var out = [];
  for (var i = 0; i < ids.length; i++) {
    if (!ids[i]) continue;
    var d = (root.getElementById && root.getElementById(ids[i])) || document.getElementById(ids[i]);
    if (d && aaVis(d)) { var t = (d.innerText || '').trim(); if (t) out.push(t.slice(0, 160)); }
  }
  return out.join(' ');
}
function aaState(el) {
  if (!el) return {present: false};
  var tag = el.localName, type = (el.getAttribute('type') || '').toLowerCase();
  var role = (el.getAttribute('role') || '').toLowerCase();
  var s = {present: true, visible: aaVis(el), own: aaVis(el),
           disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
           value: '', checked: null, files: 0, invalid: false, valueMissing: null, message: ''};
  if (tag === 'input' && (type === 'checkbox' || type === 'radio')) {
    s.checked = !!el.checked;
    if (!s.visible && el.labels && el.labels.length) {
      s.visible = Array.prototype.some.call(el.labels, aaVis);
    }
  } else if (role === 'checkbox' || role === 'radio' || role === 'switch') {
    s.checked = el.getAttribute('aria-checked') === 'true';
  } else if (tag === 'input' && type === 'file') {
    s.files = el.files ? el.files.length : 0;
    s.visible = s.visible || aaVis(el.parentElement) ||
      (el.labels ? Array.prototype.some.call(el.labels, aaVis) : false);
  } else if (tag === 'select') {
    var sel = [];
    for (var j = 0; j < el.options.length; j++) {
      var o = el.options[j];
      if (o.selected && !(j === 0 && o.value === '')) sel.push((o.text || '').trim());
    }
    s.value = sel.join(', ');
  } else if (aaIsCombo(el)) {
    s.value = aaComboText(el);
    s.combo = true;
  } else if (tag === 'input' || tag === 'textarea') {
    s.value = el.value || '';
  } else if (el.isContentEditable) {
    s.value = el.innerText || '';
  } else {
    s.value = (el.getAttribute('aria-valuetext') || el.textContent || '').trim().slice(0, 400);
  }
  if (el.validity) {
    var shown = false;
    try { shown = el.matches(':user-invalid'); } catch (e) { shown = false; }
    s.invalid = !el.validity.valid && shown;
    s.valueMissing = !!el.validity.valueMissing;
    s.message = el.validationMessage || '';
  }
  if (el.getAttribute('aria-invalid') === 'true') s.invalid = true;
  if (s.invalid) { var et = aaErrorText(el); if (et) s.message = et; }
  return s;
}
function aaAllRoots() {
  var roots = [document], out = [document], i = 0;
  while (i < out.length && out.length < 200) {
    var r = out[i++];
    var all = r.querySelectorAll('*');
    for (var j = 0; j < all.length && out.length < 200; j++) {
      if (all[j].shadowRoot) out.push(all[j].shadowRoot);
    }
  }
  return out;
}
function aaOptions(el) {
  var root = el.getRootNode ? el.getRootNode() : document;
  function byId(id) {
    return (root.getElementById && root.getElementById(id)) || document.getElementById(id);
  }
  var holders = [el];
  var anc = el.closest ? el.closest('[role="combobox"]') : null;
  if (anc && anc !== el) holders.push(anc);
  var boxes = [];
  holders.forEach(function (h) {
    ((h.getAttribute('aria-controls') || '') + ' ' + (h.getAttribute('aria-owns') || ''))
      .split(/\s+/).forEach(function (id) { if (id) { var b = byId(id); if (b) boxes.push(b); } });
  });
  var opts = [];
  boxes.forEach(function (b) {
    b.querySelectorAll('[role="option"]').forEach(function (o) {
      if (aaVis(o) && opts.indexOf(o) < 0) opts.push(o);
    });
  });
  if (!opts.length) {
    aaAllRoots().forEach(function (r) {
      r.querySelectorAll('[role="option"]').forEach(function (o) {
        if (aaVis(o) && opts.indexOf(o) < 0) opts.push(o);
      });
    });
  }
  return opts.slice(0, 400);
}
"""

_RESOLVE_JS = _HELPERS + "\nreturn aaResolve(arguments[0]);"
_STATES_JS = _HELPERS + r"""
var specs = arguments[0], out = [];
for (var i = 0; i < specs.length; i++) {
  var el = null;
  try { el = aaResolve(specs[i]); } catch (e) { el = null; }
  try { out.push(aaState(el)); } catch (e) { out.push({present: false}); }
}
return out;
"""
_OPTIONS_JS = _HELPERS + r"""
var el = aaResolve(arguments[0]);
if (!el) return [];
return aaOptions(el).map(function (o) {
  return (o.innerText || o.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 200);
});
"""
_OPTION_EL_JS = _HELPERS + r"""
var el = aaResolve(arguments[0]);
if (!el) return null;
var opts = aaOptions(el);
var k = arguments[1];
return (k >= 0 && k < opts.length) ? opts[k] : null;
"""
_CENSUS_JS = _HELPERS + r"""
// A fingerprint of WHICH questions are shown, not how many: a choice that
// hides one question and shows another changes it (a count would not), and so
// does a re-rendered control that keeps its element but asks something else
// (its label, aria-label or legend changed). The words that NAME a control are
// part of it; the answer a control holds never is.
var h = 2166136261;
function mix(s) { for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; } }
aaAllRoots().forEach(function (r) {
  r.querySelectorAll(AA_CONTROLS).forEach(function (c, k) {
    if (aaVis(c)) mix(c.localName + '|' + (c.getAttribute('name') || '') + '|' +
                      (c.id || '') + '|' + (c.getAttribute('type') || '') + '|' +
                      (c.getAttribute('role') || '') + '|' + aaNameOf(c) + '|' + k + ';');
  });
});
return h;
"""
#: The step position a person sees, from what is SHOWN only (a wizard keeps
#: every step in the document and hides all but one, so document text alone
#: would always say "Step 1 of 3"). Two sources, neither needing a word of any
#: language here: ``aria-current="step"`` (its place among its visible
#: siblings), and short visible texts holding exactly two numbers in any
#: digits — the language layer (``form_language.step_position``) decides which
#: of them is an indicator ("Schritt 2 von 4", "第2步，共4步").
_STEP_JS = _HELPERS + r"""
var out = {texts: [], now: 0, total: 0}, seen = {};
function twoNumbers(t) { var m = t.match(/\p{Nd}+/gu); return !!m && m.length === 2; }
aaAllRoots().forEach(function (r) {
  var w = document.createTreeWalker(r, NodeFilter.SHOW_TEXT), t;
  while ((t = w.nextNode()) && out.texts.length < 30) {
    if (!/\p{Nd}/u.test(t.nodeValue || '')) continue;
    var el = t.parentElement;
    if (!el || !aaVis(el)) continue;
    for (var up = 0; up < 3 && el; up++) {
      var s = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      if (s.length > 80) break;
      if (twoNumbers(s)) { if (!seen[s]) { seen[s] = 1; out.texts.push(s); } break; }
      el = el.parentElement;
    }
  }
});
aaAllRoots().some(function (r) {
  var cur = r.querySelector('[aria-current="step"]');
  if (!cur || !aaVis(cur)) return false;
  var item = cur.closest('li') || cur, list = item.parentElement;
  if (!list) return false;
  var kids = Array.prototype.filter.call(list.children, function (k) { return aaVis(k); });
  var i = kids.indexOf(item);
  if (i >= 0 && kids.length >= 2 && kids.length <= 30) { out.now = i + 1; out.total = kids.length; return true; }
  return false;
});
// Links in the form's area, with the text around them (an assessment, or
// another form the page may say must be completed first), and structural
// signs that the page is a test: an ARIA timer, an in-page code editor.
out.links = []; out.signals = [];
var CONTROLS = 'input,select,textarea,[role=combobox],[role=radiogroup],[role=checkbox]';
function inFormArea(a) {
  if (a.closest('form')) return true;
  for (var p = a.parentElement, k = 0; p && k < 4; p = p.parentElement, k++)
    if (p.querySelector(CONTROLS)) return true;
  return false;
}
function around(a) {
  var b = a.closest('p,li,td,dd,label,legend,fieldset') || a.parentElement;
  return ((b && (b.innerText || b.textContent)) || '').replace(/\s+/g, ' ').trim().slice(0, 300);
}
var linkSeen = {};
aaAllRoots().forEach(function (r) {
  r.querySelectorAll('a[href]').forEach(function (a) {
    if (out.links.length >= 40 || !aaVis(a)) return;
    var href = a.href || '';
    if (!/^https?:/i.test(href) || linkSeen[href] || !inFormArea(a)) return;
    linkSeen[href] = 1;
    out.links.push({href: href.slice(0, 500),
                    text: (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120),
                    context: around(a)});
  });
  if (out.signals.indexOf('role=timer') < 0) {
    var tm = r.querySelector('[role="timer"]');
    if (tm && aaVis(tm)) out.signals.push('role=timer');
  }
  if (out.signals.indexOf('code-editor') < 0) {
    var ed = r.querySelector('.CodeMirror, .cm-editor, .monaco-editor, .ace_editor');
    if (ed && aaVis(ed)) out.signals.push('code-editor');
  }
});
return out;
"""
#: Give one control the keyboard focus without scrolling (the interaction
#: tool scrolls it into view first — the one place AA scrolls a page), so a
#: person asked to answer it in the browser — with a screen reader, a
#: magnifier or the keyboard alone — lands on it.
_FOCUS_JS = _HELPERS + r"""
var el = aaResolve(arguments[0]);
if (!el) return false;
try { el.focus({preventScroll: true}); } catch (e) { try { el.focus(); } catch (e2) { return false; } }
var root = el.getRootNode ? el.getRootNode() : document;
return document.activeElement === el || root.activeElement === el;
"""
_SET_VALUE_JS = _HELPERS + r"""
var el = aaResolve(arguments[0]), value = arguments[1];
if (!el || el.isContentEditable) return false;
var proto = el.localName === 'textarea' ? HTMLTextAreaElement.prototype :
            (el.localName === 'select' ? HTMLSelectElement.prototype : HTMLInputElement.prototype);
var d = Object.getOwnPropertyDescriptor(proto, 'value');
try { el.focus(); } catch (e) {}
if (d && d.set) { d.set.call(el, value); } else { el.value = value; }
el.dispatchEvent(new Event('input', {bubbles: true}));
el.dispatchEvent(new Event('change', {bubbles: true}));
try { el.blur(); } catch (e) {}
return true;
"""

def _as_function(body: str) -> str:
    """Wrap a ``return``-style script body for Playwright's evaluate."""
    return "(args) => { return (function () {" + body + "}).apply(null, args); }"


# ---------------------------------------------------------------------------
# Playwright ElementHandle shim
# ---------------------------------------------------------------------------

class _HandleLocator:
    """Lets ``PlaywrightElementAdapter`` drive an ``ElementHandle``.

    The adapter was written for Locators. A handle answers the same calls;
    ``element_handle`` returns a fresh handle each time because the adapter
    disposes the handles it unwraps after every script call.
    """

    def __init__(self, handle: Any) -> None:
        self._h = handle

    def element_handle(self, timeout: Any = None) -> Any:
        copy = self._h.evaluate_handle("e => e")
        return copy.as_element() or copy

    def click(self, **kw: Any) -> Any:
        return self._h.click(**kw)

    def type(self, text: str, **kw: Any) -> Any:
        return self._h.type(text, **kw)

    def press(self, key: str, **kw: Any) -> Any:
        return self._h.press(key, **kw)

    def get_attribute(self, name: str) -> Any:
        return self._h.get_attribute(name)

    def text_content(self) -> Any:
        return self._h.text_content()

    def bounding_box(self) -> Any:
        return self._h.bounding_box()

    def locator(self, selector: str) -> _HandleQuery:
        return _HandleQuery(self._h, selector)


class _HandleQuery:
    def __init__(self, handle: Any, selector: str) -> None:
        self._h = handle
        self._sel = selector

    def all(self) -> list[_HandleLocator]:
        return [_HandleLocator(h) for h in self._h.query_selector_all(self._sel)]

    @property
    def first(self) -> _HandleFirst:
        return _HandleFirst(self._h.query_selector(self._sel))


class _HandleFirst(_HandleLocator):
    def __init__(self, handle: Any) -> None:
        super().__init__(handle)

    def count(self) -> int:
        return 0 if self._h is None else 1


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------

_NEWSLETTER = re.compile(r"\b(newsletter|subscribe|job alerts?|talent community|sign up for)\b",
                         re.IGNORECASE)
_ACCESS_KEYS = frozenset({"level", "max_nodes", "max_bytes", "max_depth", "max_frame_depth",
                          "frame_cap", "script_deadline_ms", "wall_ms"})


class PagecompFormPage:
    """``FormPagePort`` over pagecomp's reading and the active browser.

    Args:
        browser: AA's ``BrowserInterface`` (Selenium or Playwright adapter, or
            the resilient wrapper around one).
        access: The ``comprehension_access`` config mapping.
        prefer_cdp: Try the CDP rung first on Chromium.
        access_factory: Test seam: a callable ``(raw_target, prefer_cdp=)``
            returning an object with ``observe(request)``.
    """

    def __init__(
        self,
        browser: Any,
        access: dict[str, Any] | None = None,
        *,
        prefer_cdp: bool = True,
        access_factory: Any = None,
    ) -> None:
        self._browser = browser
        self._access_cfg = dict(access or {})
        self._prefer_cdp = bool(self._access_cfg.get("prefer_cdp", prefer_cdp))
        self._factory = access_factory
        self._registry: Any = None
        self._cache: Any = None
        self.last_read_how = ""

    # -- framework plumbing ------------------------------------------------
    def _raw(self) -> Any:
        for name in ("get_raw_page", "get_raw_driver"):
            getter = getattr(self._browser, name, None)
            if callable(getter):
                try:
                    raw = getter()
                except Exception:
                    raw = None
                if raw is not None:
                    return raw
        return None

    def _kind(self, raw: Any) -> str:
        if raw is None:
            return "none"
        if hasattr(raw, "evaluate_handle") and hasattr(raw, "wait_for_function"):
            return "playwright"
        if hasattr(raw, "execute_script") and hasattr(raw, "switch_to"):
            return "selenium"
        return "unknown"

    def _top(self, raw: Any) -> None:
        if self._kind(raw) == "selenium":
            try:
                raw.switch_to.default_content()
            except Exception:
                pass

    def _run(self, body: str, *args: Any) -> Any:
        """Run a ``return``-style script and return plain data."""
        raw = self._raw()
        kind = self._kind(raw)
        if kind == "playwright":
            return raw.evaluate(_as_function(body), list(args))
        if kind == "selenium":
            self._top(raw)
            return raw.execute_script(body, *args)
        return self._browser.execute_script(body, *args)

    def _element(self, body: str, *args: Any) -> ElementInterface | None:
        """Run a script that returns one element, wrapped for the tool."""
        raw = self._raw()
        kind = self._kind(raw)
        try:
            if kind == "selenium":
                self._top(raw)
                found = raw.execute_script(body, *args)
                if found is None:
                    return None
                from auto_apply.adapters.secondary.browser.selenium_adapter import (  # noqa: PLC0415
                    SeleniumElementAdapter,
                )
                return SeleniumElementAdapter(found)
            if kind == "playwright":
                handle = raw.evaluate_handle(_as_function(body), list(args))
                element = handle.as_element()
                if element is None:
                    try:
                        handle.dispose()
                    except Exception:
                        pass
                    return None
                from auto_apply.adapters.secondary.browser.playwright_adapter import (  # noqa: PLC0415
                    PlaywrightElementAdapter,
                )
                return PlaywrightElementAdapter(_HandleLocator(element))  # type: ignore[arg-type]
        except Exception as exc:
            logger.debug("pagecomp_form: element script failed: %s", type(exc).__name__)
        return None

    def _raw_element(self, ref: ControlRef) -> tuple[str, Any]:
        """The framework's own element for ``ref`` (a Playwright handle the
        caller must dispose, or a Selenium WebElement)."""
        raw = self._raw()
        kind = self._kind(raw)
        if ref.in_frame:
            return kind, None
        if kind == "selenium":
            self._top(raw)
            return kind, raw.execute_script(_RESOLVE_JS, ref.as_spec())
        if kind == "playwright":
            handle = raw.evaluate_handle(_as_function(_RESOLVE_JS), [ref.as_spec()])
            element = handle.as_element()
            if element is None:
                _dispose(handle)
            return kind, element
        return kind, None

    # -- FormPagePort --------------------------------------------------------
    def locate(self, ref: ControlRef) -> ElementInterface | None:
        if ref.in_frame:
            return None
        return self._element(_RESOLVE_JS, ref.as_spec())

    def read_states(self, refs: Sequence[ControlRef]) -> list[ControlState]:
        if not refs:
            return []
        specs = [r.as_spec() for r in refs]
        try:
            raw = self._run(_STATES_JS, specs)
        except Exception as exc:
            logger.debug("pagecomp_form: state read failed: %s", type(exc).__name__)
            raw = None
        if not isinstance(raw, list):
            # The read itself failed: unknown, not absent.
            return [ControlState(present=False, read_failed=True) for _ in refs]
        out: list[ControlState] = []
        rows = raw if isinstance(raw, list) else []
        for i, ref in enumerate(refs):
            row = rows[i] if i < len(rows) and isinstance(rows[i], dict) else {}
            if ref.in_frame or not row.get("present"):
                out.append(ControlState(present=False))
                continue
            value = str(row.get("value") or "")
            if (ref.tag == "select" or row.get("combo")) and is_placeholder(value):
                value = ""
            checked = row.get("checked")
            vm = row.get("valueMissing")
            own = row.get("own")
            out.append(ControlState(
                present=True,
                visible=bool(row.get("visible")),
                value=value,
                checked=None if checked is None else bool(checked),
                files=int(row.get("files") or 0),
                disabled=bool(row.get("disabled")),
                invalid=bool(row.get("invalid")),
                value_missing=None if vm is None else bool(vm),
                message=str(row.get("message") or "")[:300],
                own_visible=None if own is None else bool(own),
            ))
        return out

    def listbox_options(self, ref: ControlRef) -> list[str]:
        try:
            raw = self._run(_OPTIONS_JS, ref.as_spec())
        except Exception:
            return []
        return [str(x) for x in raw] if isinstance(raw, list) else []

    def locate_option(self, ref: ControlRef, index: int) -> ElementInterface | None:
        return self._element(_OPTION_EL_JS, ref.as_spec(), int(index))

    def choose_native_option(self, ref: ControlRef, index: int) -> bool:
        el: Any = None
        kind = ""
        try:
            kind, el = self._raw_element(ref)
            if el is None:
                return False
            if kind == "selenium":
                from selenium.webdriver.support.select import Select  # noqa: PLC0415

                Select(el).select_by_index(int(index))
                return True
            if kind == "playwright":
                el.select_option(index=int(index))
                return True
        except Exception as exc:
            logger.debug("pagecomp_form: native select failed: %s", type(exc).__name__)
        finally:
            if kind == "playwright" and el is not None:
                _dispose(el)
        return False

    def set_files(self, ref: ControlRef, path: str) -> bool:
        el: Any = None
        kind = ""
        try:
            kind, el = self._raw_element(ref)
            if el is None:
                return False
            if kind == "selenium":
                el.send_keys(path)
                return True
            if kind == "playwright":
                el.set_input_files(path)
                return True
        except Exception as exc:
            logger.debug("pagecomp_form: file set failed: %s", type(exc).__name__)
        finally:
            if kind == "playwright" and el is not None:
                _dispose(el)
        return False

    def set_value_by_script(self, ref: ControlRef, value: str) -> bool:
        try:
            return bool(self._run(_SET_VALUE_JS, ref.as_spec(), value))
        except Exception:
            return False

    def quiet_detector(self, quiet: int, t_max: float) -> Callable[[object, float], str]:
        """pagecomp's ``Settler`` behind the port (see ``FormPagePort``)."""
        from pagecomp.transitions import SETTLED, Settler  # noqa: PLC0415

        settler = Settler(quiet=max(1, int(quiet)), t_max=max(0.05, float(t_max)))

        def observe(signature: object, now: float) -> str:
            verdict = settler.observe(signature, now)
            if verdict == SETTLED:
                return "settled"
            return "settling" if isinstance(verdict, str) else "timeout"

        return observe

    def focus(self, ref: ControlRef) -> bool:
        if ref.in_frame:
            return False
        try:
            return bool(self._run(_FOCUS_JS, ref.as_spec()))
        except Exception as exc:
            logger.debug("pagecomp_form: focus failed: %s", type(exc).__name__)
            return False

    def control_census(self) -> int:
        try:
            n = self._run(_CENSUS_JS)
        except Exception:
            return -1
        return int(n) if isinstance(n, (int, float)) and not isinstance(n, bool) else -1

    # -- reading ---------------------------------------------------------------
    def _observe(self) -> Any:
        from pagecomp.access import ObservationRequest  # noqa: PLC0415
        from pagecomp.observation import observe_html  # noqa: PLC0415

        url = ""
        try:
            url = str(self._browser.current_url or "")
        except Exception:
            url = ""
        kw = {k: v for k, v in self._access_cfg.items() if k in _ACCESS_KEYS}
        request = ObservationRequest(requested_url=url or None, **kw)
        raw = self._raw()
        if raw is not None:
            try:
                factory = self._factory
                if factory is None:
                    from auto_apply.adapters.secondary.perception.pagecomp_access import (  # noqa: PLC0415
                        PagecompAccess,
                    )
                    factory = PagecompAccess
                outcome = factory(raw, prefer_cdp=self._prefer_cdp).observe(request)
                obs = outcome.observation
                self._top(raw)
                if not outcome.timed_out and len(obs.doc) > 2:
                    self.last_read_how = "access" + (":" + ",".join(outcome.notes[:3])
                                                     if outcome.notes else "")
                    return obs
            except Exception as exc:
                logger.debug("pagecomp_form: access read failed: %s", type(exc).__name__)
        try:
            html = self._browser.execute_script(
                "return document.documentElement ? document.documentElement.outerHTML : '';")
        except Exception:
            html = ""
        if not isinstance(html, str) or not html:
            return None
        self.last_read_how = "html"
        try:
            title = str(self._browser.title or "")
        except Exception:
            title = ""
        return observe_html(html, url=url, title=title, limits=request.limits())

    def read_step(self) -> FormStep | None:
        try:
            obs = self._observe()
        except Exception as exc:
            logger.debug("pagecomp_form: read failed: %s", type(exc).__name__)
            return None
        if obs is None:
            return None
        try:
            live = self._run(_STEP_JS)
            live_step: dict[str, Any] | None = live if isinstance(live, dict) else None
        except Exception:
            live_step = None
        try:
            return self._build(obs, live_step)
        except Exception as exc:
            logger.warning("pagecomp_form: could not build the form step (%s)",
                           type(exc).__name__)
            return None

    def _analyzer(self, obs: Any) -> Any:
        from pagecomp import Analyzer, ResultCache  # noqa: PLC0415
        from pagecomp.tools import default_registry  # noqa: PLC0415

        if self._registry is None:
            self._registry = default_registry()
            self._cache = ResultCache(max_entries=64)
        return Analyzer(obs, registry=self._registry, cache=self._cache)

    def _build(self, obs: Any, live_step: dict[str, Any] | None = None) -> FormStep:
        from pagecomp.doc import ELEMENT, FRAME, SHADOW  # noqa: PLC0415

        an = self._analyzer(obs)
        forms = an.value("forms")
        reading = an.value("formread")
        doc = obs.doc
        notes = tuple(sorted(obs.read_flags)) + ((self.last_read_how,) if self.last_read_how else ())
        frames = tuple(
            FrameCandidate(url=f.url, same_origin=f.same_origin, state=f.state)
            for f in doc.frames if f.url.startswith(("http://", "https://"))
        )
        links, signals = _live_extras(live_step)
        empty = FormStep(url=obs.url, title=obs.title, purpose="none", questions=(), buttons=(),
                         fingerprint=_fp(obs.url, (), ""), frame_candidates=frames,
                         complete_read=obs.complete, read_notes=notes,
                         links=links, test_signals=signals)
        if forms is None or reading is None:
            return empty

        child_index: dict[int, dict[int, int]] = {}

        def element_index(parent: int, node: int) -> int:
            table = child_index.get(parent)
            if table is None:
                table = {}
                k = 0
                for c in doc.children(parent):
                    if doc.kind[c] == ELEMENT:
                        table[c] = k
                        k += 1
                child_index[parent] = table
            return table.get(node, -1)

        def ref_of(node: int, ctype: str = "") -> ControlRef:
            steps: list[tuple[str, int]] = []
            in_frame = in_shadow = False
            i = node
            while i > 0:
                p = doc.parent[i]
                kind = doc.kind[i]
                if kind == SHADOW:
                    steps.append(("s", 0))
                    in_shadow = True
                elif kind == FRAME:
                    steps.append(("d", 0))
                    in_frame = True
                elif kind == ELEMENT:
                    steps.append(("c", element_index(p, i)))
                if p < 0:
                    break
                i = p
            steps.reverse()
            return ControlRef(
                path=tuple(steps), tag=doc.tag_name(node), type=ctype,
                name=doc.attr(node, "name") or "", id=doc.attr(node, "id") or "",
                in_frame=in_frame, in_shadow=in_shadow,
            )

        def label_ref(node: int) -> ControlRef | None:
            cid = doc.attr(node, "id")
            if cid:
                for lab in doc.elements("label"):
                    if doc.attr(lab, "for") == cid and doc.scope[lab] == doc.scope[node]:
                        return ref_of(lab)
            for a in doc.ancestors(node, 6):
                if doc.kind[a] == ELEMENT and doc.tag_name(a) == "label":
                    return ref_of(a)
            return None

        fields_by_form: dict[int, list[Any]] = {}
        for r in reading.fields:
            fields_by_form.setdefault(r.form, []).append(r)

        def score(k: int) -> float:
            fs = fields_by_form.get(k, [])
            fill = sum(1 for r in fs if r.decision == FILL)
            adv = any(b.form == k and b.role in ("next", "submit") for b in forms.buttons)
            return fill + (2.0 if adv else 0.0)

        apps = [k for k, info in enumerate(forms.forms) if info.purpose == "application"
                and fields_by_form.get(k)]
        logins = [k for k, info in enumerate(forms.forms) if info.purpose == "login"]
        if not apps:
            if logins:
                login_qs = tuple(self._questions(doc, forms, fields_by_form.get(logins[0], []),
                                                 ref_of, label_ref))
                return FormStep(url=obs.url, title=obs.title, purpose="login",
                                questions=login_qs, buttons=(),
                                fingerprint=_fp(obs.url, tuple(q.key for q in login_qs), ""),
                                frame_candidates=frames, complete_read=obs.complete,
                                read_notes=notes)
            # No question at all, but controls to go on or send: a review
            # page ("Check your answers", then Submit). Only meaningful after
            # the engine has advanced to it; on a first page it is no form.
            forward = tuple(
                FormButton(role=b.role, text=b.text, control=ref_of(b.node, b.type),
                           final=b.final, button_type=b.type, role_source="pagecomp")
                for b in forms.buttons if b.role in ("next", "submit")
            )
            if forward:
                texts, now, total = _step_facts(live_step, "", obs.title or "")
                return FormStep(url=obs.url, title=obs.title, purpose="review", questions=(),
                                buttons=forward, fingerprint=_fp(obs.url, (), "|".join(texts)),
                                frame_candidates=frames, complete_read=obs.complete,
                                read_notes=notes, language=_declared_lang(doc, -1),
                                step_now=now, step_total=total, step_texts=texts,
                                links=links, test_signals=signals)
            return empty
        best = max(apps, key=lambda k: (score(k), -k))
        chosen = [best]
        for k in apps:
            if k == best:
                continue
            fills = [r for r in fields_by_form.get(k, []) if r.decision == FILL]
            text = doc.text_content(forms.forms[k].root, 2_000)[0]
            if len(fills) >= 2 and not _NEWSLETTER.search(text):
                chosen.append(k)
        chosen_set = set(chosen)
        readings = [r for k in sorted(chosen_set) for r in fields_by_form.get(k, [])]
        readings.sort(key=lambda r: forms.controls[r.controls[0]].node)
        questions = tuple(self._questions(doc, forms, readings, ref_of, label_ref))

        buttons: list[FormButton] = []
        for b in forms.buttons:
            if b.form in chosen_set or (b.form < 0 and b.role in ("next", "submit")):
                buttons.append(FormButton(
                    role=b.role, text=b.text, control=ref_of(b.node, b.type),
                    final=b.final, button_type=b.type, role_source="pagecomp",
                ))
        root = forms.forms[best].root
        form_text = doc.text_content(root, 4_000)[0]
        texts, now, total = _step_facts(live_step, form_text, obs.title or "")
        in_frame = any(q.primary.in_frame for q in questions)
        purpose = "application"
        return FormStep(
            url=obs.url, title=obs.title, purpose=purpose, questions=questions,
            buttons=tuple(buttons), fingerprint=_fp(obs.url, tuple(q.key for q in questions),
                                                    "|".join(texts)),
            frame_candidates=frames, form_in_frame=in_frame,
            complete_read=obs.complete, read_notes=notes,
            language=_declared_lang(doc, root), step_now=now, step_total=total,
            step_texts=texts, links=links, test_signals=signals,
        )

    def _questions(self, doc: Any, forms: Any, readings: list[Any], ref_of: Any,
                   label_ref: Any) -> list[FormQuestion]:
        out: list[FormQuestion] = []
        seen: dict[str, int] = {}
        for r in readings:
            members = [forms.controls[k] for k in r.controls]
            first = members[0]
            if first.type == "hidden":
                continue  # a form's own bookkeeping, never a question
            node = first.node
            kind = _kind_of(doc, r, first)
            refs = tuple(ref_of(c.node, c.type) for c in members)
            options: tuple[FormOption, ...] = ()
            if r.kind in ("radio", "checkbox"):
                opts = []
                for i, c in enumerate(members):
                    label = r.options[i] if i < len(r.options) else ""
                    opts.append(FormOption(
                        label=label or (doc.attr(c.node, "value") or ""),
                        value=doc.attr(c.node, "value") or "",
                        control=refs[i],
                        click_target=label_ref(c.node),
                    ))
                options = tuple(opts)
            elif kind == QuestionKind.CHECKBOX:
                options = (FormOption(label=r.label, value=doc.attr(node, "value") or "",
                                      control=refs[0], click_target=label_ref(node)),)
            elif kind in (QuestionKind.SELECT, QuestionKind.MULTI_SELECT):
                values = [doc.attr(o, "value") or "" for o in range(node, doc.end[node])
                          if doc.is_element(o) and doc.tag_name(o) == "option"]
                options = tuple(
                    FormOption(label=t, value=values[i] if i < len(values) else "")
                    for i, t in enumerate(first.options)
                )
            max_len = doc.attr(node, "maxlength")
            ml = int(max_len) if max_len and max_len.isdigit() and int(max_len) > 0 else None
            ftype = "password" if kind == QuestionKind.PASSWORD else r.field_type
            base = "|".join((first.name, first.id, normalize(r.label)[:80], kind))
            n = seen.get(base, 0)
            seen[base] = n + 1
            out.append(FormQuestion(
                key=base if n == 0 else f"{base}#{n}",
                label=r.label, kind=kind, field_type=ftype, controls=refs,
                type_source=r.type_source, required=r.required,
                required_evidence=tuple(r.evidence), sensitive=bool(r.sensitive),
                decision=r.decision, options=options, description=r.description,
                input_type=first.type, max_length=ml, autocomplete=first.autocomplete,
                label_source=r.label_source,
            ))
        return out


def _dispose(handle: Any) -> None:
    try:
        handle.dispose()
    except Exception:
        pass


def _kind_of(doc: Any, r: Any, c: Any) -> str:
    """The widget shape of one reading."""
    if r.kind == "radio":
        return QuestionKind.RADIO
    if r.kind == "checkbox":
        return QuestionKind.CHECKBOX_GROUP if len(r.controls) > 1 else QuestionKind.CHECKBOX
    t = c.type
    role = (doc.attr(c.node, "role") or "").lower()
    if t == "password":
        return QuestionKind.PASSWORD
    if t == "file":
        return QuestionKind.FILE
    if t == "select":
        return QuestionKind.MULTI_SELECT if doc.has_attr(c.node, "multiple") else QuestionKind.SELECT
    if t in ("role:combobox", "role:listbox") or role == "combobox" or (
            doc.attr(c.node, "aria-autocomplete") or "").lower() == "list" or (
            doc.attr(c.node, "aria-haspopup") or "").lower() == "listbox":
        return QuestionKind.COMBOBOX
    if t in ("checkbox", "role:checkbox", "role:switch"):
        return QuestionKind.CHECKBOX
    if t in ("radio", "role:radio"):
        return QuestionKind.RADIO
    if t == "textarea":
        return QuestionKind.TEXTAREA
    if t in ("date", "month", "week", "datetime-local", "time"):
        return QuestionKind.DATE
    if t in ("contenteditable", "role:textbox", "", "text", "email", "tel", "url",
             "number", "search"):
        return QuestionKind.TEXTAREA if t == "contenteditable" else QuestionKind.TEXT
    return QuestionKind.OTHER


#: Up to three words around two small numbers: a step indicator's shape in
#: the document text, for when the live read is unavailable (any language).
_STEP_WINDOW = re.compile(r"(?:\S+\s+){0,3}\d{1,2}\s*\S{0,12}\s*\d{1,2}(?:\s+\S+){0,3}")


def _live_extras(live: dict[str, Any] | None
                 ) -> tuple[tuple[FormLink, ...], tuple[str, ...]]:
    """(links in the form's area, test signals) from the live read; none
    without it (a document-only read cannot see what is shown)."""
    if live is None:
        return (), ()
    links: list[FormLink] = []
    for item in (live.get("links") or [])[:40]:
        if isinstance(item, dict) and str(item.get("href") or "").strip():
            links.append(FormLink(href=str(item["href"])[:500],
                                  text=str(item.get("text") or "")[:120],
                                  context=str(item.get("context") or "")[:300]))
    signals = tuple(str(x) for x in (live.get("signals") or [])
                    if str(x) in ("role=timer", "code-editor"))
    return tuple(links), signals


def _step_facts(live: dict[str, Any] | None, form_text: str,
                title: str) -> tuple[tuple[str, ...], int, int]:
    """(texts that may be a step indicator, step, steps) — structure only;
    the words are read by the language layer."""
    if live is not None:
        texts = tuple(str(t)[:80] for t in (live.get("texts") or []) if str(t).strip())[:30]
        try:
            now, total = int(live.get("now") or 0), int(live.get("total") or 0)
        except (TypeError, ValueError):
            now, total = 0, 0
        if not (0 < now <= total):
            now, total = 0, 0
        return texts, now, total
    found = [m.group(0)[:80] for m in _STEP_WINDOW.finditer(f"{form_text}\n{title}")]
    return tuple(found[:30]), 0, 0


def _declared_lang(doc: Any, node: int) -> str:
    """The ``lang`` that applies to ``node`` (its own or its nearest
    ancestor's), else the document element's ("" when none is declared)."""
    from pagecomp.doc import ELEMENT  # noqa: PLC0415

    i = node
    while i is not None and i >= 0:
        if doc.kind[i] == ELEMENT:
            v = (doc.attr(i, "lang") or doc.attr(i, "xml:lang") or "").strip()
            if v:
                return v[:35]
        i = doc.parent[i]
    for h in doc.elements("html"):
        v = (doc.attr(h, "lang") or doc.attr(h, "xml:lang") or "").strip()
        if v:
            return v[:35]
    return ""


def _fp(url: str, keys: tuple[str, ...], step_label: str) -> str:
    h = hashlib.sha256()
    h.update((url.split("#", 1)[0]).encode("utf-8", "surrogatepass"))
    for k in sorted(keys):
        h.update(b"\x00" + k.encode("utf-8", "surrogatepass"))
    h.update(b"\x01" + step_label.encode("utf-8", "surrogatepass"))
    return h.hexdigest()[:20]


__all__ = ["PagecompFormPage"]

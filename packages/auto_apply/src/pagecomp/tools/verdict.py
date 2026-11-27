"""Verdict (CT-T-006): what kind of barrier or outcome the page presents.

Ported from AA ``challenge_assessment`` / ``page_assessment`` / ``page_phrases``
(marker lists and the structural rules), over the shared ``Doc``:

* **challenge** ``gated``: a challenge URL marker, or challenge markup
  (iframe/widget/script marker) on a page with no content of its own
  (content = a form with fillable controls, >= 2 formless controls, or an
  apply control). ``embedded`` when challenge markup sits inside a usable
  page. A challenge *script* alone on a content page is a loaded library,
  not a presented challenge. The page title is never read (it is localised
  and vendor-controlled).
* **login wall**: a login URL (whole path segments: ``/register`` inside
  ``/jobs/registered-nurse`` does not match), or a password control in a
  login-purpose form on a page with little other text.
* **overlays**: ``consent`` (a shown container whose id, class or
  accessible name carries a consent-manager marker), ``consent-possible``
  (only a consent manager's script is present), ``dialog`` (a shown modal:
  ``role=dialog``, ``aria-modal``, ``<dialog open>``). Overlays never change
  the page kind: a posting under an application modal is still a posting.
* **closed / applied / confirmation / error**: phrase tables on *visible
  text only*, precedence below challenge and login.

Kinds: ``challenge``, ``login``, ``error``, ``closed``, ``applied``,
``confirmation``, ``content``. Overlays and vendors are separate fields,
so "a results page under a cookie banner" stays a results page.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pagecomp.doc import ELEMENT, TEXT
from pagecomp.params import ParamSpec
from pagecomp.links import is_apply_text
from pagecomp.registry import ToolSpec
from pagecomp.results import Evidence, Ok
from pagecomp.text import key, token_set

CHALLENGE_URL = ("/sorry/", "/challenge/", "/human-challenge/", "/cdn-cgi/", "/checkpoint/",
                 "/verify/", "geo.captcha-delivery.com")
CHALLENGE_IFRAME = ("recaptcha", "hcaptcha", "turnstile", "funcaptcha", "arkose",
                    "challenges.cloudflare.com")
CHALLENGE_WIDGET = ("cf-turnstile", "g-recaptcha", "h-captcha", "cf-chl-widget", "challenge-form",
                    "cf-spinner", "px-captcha")
CHALLENGE_SCRIPT = ("challenge-platform", "captcha-delivery", "challenges.cloudflare.com")
VENDORS = (("captcha-delivery", "datadome"), ("challenges.cloudflare.com", "cloudflare"),
           ("cdn-cgi", "cloudflare"), ("challenge-platform", "cloudflare"), ("cf-turnstile", "cloudflare"),
           ("cf-chl", "cloudflare"), ("g-recaptcha", "recaptcha"), ("recaptcha", "recaptcha"),
           ("h-captcha", "hcaptcha"), ("hcaptcha", "hcaptcha"), ("funcaptcha", "arkose"),
           ("arkose", "arkose"), ("px-captcha", "perimeterx"), ("perimeterx", "perimeterx"))
LOGIN_SEGMENTS = (("login",), ("signin",), ("sign_in",), ("sign-in",), ("auth",), ("register",),
                  ("signup",), ("account", "login"), ("users", "sign_in"), ("sso",))
CONSENT_MARKERS = ("cookie", "consent", "onetrust", "gdpr", "cookiebot", "truste", "osano",
                   "didomi", "usercentrics", "cmp")
CLOSED = ("job closed", "job is closed", "no longer accepting", "position filled",
          "has been filled", "posting expired", "no longer available", "this job has expired",
          "job is no longer", "posting has closed", "no longer open", "job has expired",
          "position is closed", "applications are closed", "job posting has expired",
          "this job is closed", "no longer posted", "requisition is closed")
APPLIED = ("already applied", "already submitted", "you already applied", "you applied on")
CONFIRMED = ("added to your applied jobs", "application received", "application sent",
             "application submission is confirmed", "application submitted", "application was submitted",
             "received your application", "successfully applied", "successfully submitted",
             "thank you for applying", "thank you for completing", "thanks for applying",
             "we have received your", "we received your", "your application has been submitted")
ERROR = ("page not found", "404 not found", "this page doesn't exist", "this page does not exist",
         "the page you requested", "page you are looking for")


@dataclass(frozen=True)
class Verdict:
    kind: str
    challenge: str            # "gated" | "embedded" | "clear"
    login_wall: bool
    overlays: tuple[str, ...]
    vendors: tuple[str, ...]
    signals: tuple[str, ...]
    phrases: tuple[str, ...]  # which phrase table rows matched (never page text beyond them)


def login_url(url: str) -> bool:
    try:
        segs = [s for s in urllib.parse.urlsplit(url or "").path.lower().split("/") if s]
    except ValueError:
        return False
    for marker in LOGIN_SEGMENTS:
        w = len(marker)
        for s in range(len(segs) - w + 1):
            if tuple(segs[s:s + w]) == marker:
                return True
    return False


def _in_dialog(doc: Any, i: int) -> bool:
    for a in [i, *doc.ancestors(i, 40)]:
        if doc.kind[a] != ELEMENT:
            continue
        if (doc.attr(a, "role") or "") in ("dialog", "alertdialog") or doc.attr(a, "aria-modal") == "true" \
                or doc.tag_name(a) == "dialog":
            return True
    return False


def _matched(text: str, table: tuple[str, ...]) -> list[str]:
    return [p for p in table if p in text]


def _run(q: Any, params: Mapping[str, Any]) -> Ok[Verdict]:
    doc = q.doc
    url_l = (q.obs.url or "").lower()
    text = q.need_ok("pagetext")
    forms = q.maybe("forms")
    q.tick(len(doc))
    signals: list[str] = []
    vendors: set[str] = set()
    iframe = widget = script = False
    consent_nodes = 0
    consent_script = False
    dialogs = 0
    vis = q.maybe("visibility")
    for i in range(len(doc)):
        if doc.kind[i] != ELEMENT:
            if doc.kind[i] == TEXT and doc.tag_name(doc.parent[i]) == "script":
                body = doc.own_text(i)[:20_000].lower()
                if any(m in body for m in CHALLENGE_SCRIPT):
                    script = True
                    vendors.update(v for m, v in VENDORS if m in body)
            continue
        tag = doc.tag_name(i)
        idcls = f"{doc.attr(i, 'id') or ''} {doc.attr(i, 'class') or ''}".lower()
        src = (doc.attr(i, "src") or "").lower()
        if tag == "iframe" and any(m in src for m in CHALLENGE_IFRAME):
            iframe = True
        if any(m in idcls for m in CHALLENGE_WIDGET):
            widget = True
        if tag == "script" and any(m in src for m in CHALLENGE_SCRIPT):
            script = True
        blob = f"{idcls} {src}"
        vendors.update(v for m, v in VENDORS if m in blob)
        role = doc.attr(i, "role") or ""
        named = f"{idcls} {(doc.attr(i, 'aria-label') or '').lower()}"
        shown = not (vis is not None and vis.hidden(i))
        is_dialog = role in ("dialog", "alertdialog") or doc.attr(i, "aria-modal") == "true" or (
            tag == "dialog" and doc.has_attr(i, "open"))
        if shown and any(m in named for m in CONSENT_MARKERS) and (
                is_dialog or role == "region" or tag in ("div", "section", "aside", "dialog")):
            consent_nodes += 1
        elif shown and is_dialog:
            dialogs += 1
        if tag == "script" and any(m in src for m in ("consent", "cookie", "onetrust", "cookiebot", "gdpr")):
            consent_script = True
    # "The page carries its own content" is structural (AA ruling, probe_item12):
    # a form with a visible fillable control, >= 2 formless controls, an apply
    # control, a JSON-LD posting, or paragraph-like prose. Text *length* never
    # decides (interstitials carry ~5k characters of boilerplate); prose blocks
    # of >= 80 characters in their own text node are what an article has and
    # an interstitial does not (min_prose_blocks, measured on the captures).
    has_content = False
    login_form = False
    login_dialog = False
    app_form = False
    structured = q.maybe("structured")
    if forms is not None:
        for k, info in enumerate(forms.forms):
            fill = forms.fillable(k)
            if info.purpose == "login":
                if _in_dialog(doc, info.root):
                    login_dialog = True   # a sign-in modal over a page is an overlay, not a wall
                else:
                    login_form = True
            elif info.purpose == "application" and len(fill) >= 3:
                app_form = True
            if fill and (info.kind == "form" or len(fill) >= 2) and info.purpose != "unknown":
                has_content = True
        if any(is_apply_text(b.text) for b in forms.buttons):
            has_content = True
    if structured is not None and structured.postings:
        has_content = True
    if text.prose_blocks >= int(params["min_prose_blocks"]):
        has_content = True
    if not has_content:
        for a in doc.elements("a"):
            if is_apply_text(doc.accessible_name(a)):
                has_content = True
                break
    url_challenge = any(m in url_l for m in CHALLENGE_URL)
    if url_challenge:
        challenge = "gated"
        signals.append("challenge-url")
        vendors.update(v for m, v in VENDORS if m in url_l)
    elif iframe or widget or script:
        signals += [s for s, on in (("challenge-iframe", iframe), ("challenge-widget", widget),
                                    ("challenge-script", script)) if on]
        if not has_content:
            challenge = "gated"
        elif iframe or widget:
            challenge = "embedded"
        else:
            challenge = "clear"
    else:
        challenge = "clear"
    signals.append("page-content" if has_content else "no-page-content")
    # A login wall: a login URL, or a visible login form that is the page's only
    # way forward (no application form, no posting data). The page title is
    # never read: "Registered Nurse" is not a wall.
    file_ctrl = forms is not None and any(
        c.type == "file" and forms.forms[c.form].purpose != "login" for c in forms.controls)
    wall = login_url(q.obs.url) or (login_form and not app_form and not file_ctrl)
    if wall:
        signals.append("login-wall")
    folded = text.folded
    closed = _matched(folded, CLOSED)
    applied = _matched(folded, APPLIED)
    confirmed = _matched(folded, CONFIRMED)
    title_k = key(q.obs.title)
    error = _matched(folded[:4000], ERROR) + (["title-404"] if "404" in token_set(title_k) else [])
    if challenge == "gated":
        kind = "challenge"
    elif wall:
        kind = "login"
    elif error and not has_content:
        kind = "error"
    elif closed:
        kind = "closed"
    elif applied:
        kind = "applied"
    elif confirmed and not has_content:
        kind = "confirmation"
    else:
        kind = "content"
    # "consent" when a banner/dialog is in the observed tree; "consent-possible"
    # when only a consent manager's script is (its banner may live in a frame
    # or a closed shadow root this observation could not read).
    overlays: tuple[str, ...] = ("consent",) if consent_nodes else (
        ("consent-possible",) if consent_script else ())
    if dialogs:
        overlays += ("dialog",)
    if login_dialog:
        overlays += ("login",)
    phrases = tuple(f"closed:{p}" for p in closed) + tuple(f"applied:{p}" for p in applied) + \
        tuple(f"confirmed:{p}" for p in confirmed) + tuple(f"error:{p}" for p in error)
    ev = tuple(Evidence(s) for s in signals)
    return Ok(Verdict(kind, challenge, wall, overlays, tuple(sorted(vendors)), tuple(signals), phrases),
              evidence=ev)


TOOL = ToolSpec(
    id="verdict", ct_id="CT-T-006", version="0.1.0", run=_run, needs=("pagetext", "forms", "structured", "visibility"),
    params=(ParamSpec("min_prose_blocks", 6, 1, 1000,
                      doc="paragraph-like text blocks that make a page carry content"),),
    summary="challenge, login wall, consent, closed/applied/confirmation/error",
)

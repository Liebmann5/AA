"""The one answer to "is a human-verification challenge presented on this page?".

Single source of truth for challenge and login-wall verdicts (item 12A).

Why this module exists:
    The application-attempt path used to decide "CAPTCHA" with a substring
    search over the page source. Measured against 20 hand-triaged pages
    (2026-09-10) that verdict was wrong 12 times out of 20: every LinkedIn
    posting it flagged was an ordinary rendered job page whose only offence
    was the text "recaptcha" inside an HTML comment, and the real challenges
    were Cloudflare interstitials whose titles are localized and
    vendor-controlled. The login-wall check had the same defect in miniature:
    the title substring "register" made a posting titled "Registered Nurse"
    a login wall.

What the verdict reads (measured basis, not a keyword list):
    - Challenge markup in the RENDERED DOM: a challenge-vendor iframe (the
      anchor iframe only exists when a widget is actually rendering), widget
      markup (cf-turnstile / g-recaptcha / h-captcha attributes), or a
      challenge-platform script. A merely loaded vendor library is none of
      these.
    - Whether the page carries its own content, decided STRUCTURALLY: a
      form, or an apply-intent control. Measured on the 20 real pages:
      every interstitial had zero forms and no apply control — one
      population carried ~5k characters of non-script boilerplate, so
      visible-text length did not separate the populations and no longer
      decides anything. Every posting had 2-12 forms. Page byte size did
      not discriminate and is not used.
    - The URL path. The page TITLE IS DELIBERATELY NEVER READ: the one
      interstitial title measured ("Just a moment...") is localized, generic
      and vendor-controlled (ruling 2026-09-10), and the login-wall title
      scan is what produced "Registered Nurse".

    Text inside HTML comments and inside <script>/<style> bodies is not page
    content and is never matched: that is where every measured false
    positive lived.

Why a pure function:
    The verdict is a function of (url, title, html) alone, so it can be
    replayed over kept page copies (as --replay already does for the
    detectors) and graded against hand labels without a browser. The browser
    is only a snapshot taker.

Verdict vocabulary:
    "gated"    — the page IS a challenge or wall; there is nothing to fill.
    "embedded" — a challenge element is present inside a usable page (a
                 reCAPTCHA widget in a sign-in modal, say). The page can be
                 worked; the element only matters if a later step trips on it.
    "clear"    — no challenge evidence.

Vendor annotation:
    When challenge markup matches, the matched vendor is recorded on the
    assessment (``vendors``) as an annotation for research — which anti-bot
    system a site runs is access-equity evidence. It is never a verdict
    input, and nothing about it is persisted. This preserves, in pure
    form, the one unique capability of the retired evasion auditor.

Page kinds beyond challenge and login wall (application form, job
description, 404, ...) are composed from this engine by
domain/services/page_assessment.py — the ONE page verdict. This module
remains the single implementation of the challenge and login-wall answers.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlparse

from auto_apply.domain.services.apply_target import find_apply_controls

ChallengeVerdict = Literal["gated", "embedded", "clear"]

_CHALLENGE_URL_MARKERS: tuple[str, ...] = (
    "/sorry/",
    "/challenge/",
    "/human-challenge/",
    "/cdn-cgi/",
    "/checkpoint/",
    # Lifted from the retired evasion/detection.py after passing the 20-page
    # fixtures: an auth-flow verification page gates scraping exactly like a
    # challenge page. The same list's "blocked"/"denied" substrings were NOT
    # lifted — they match "/unblocked/" and job titles ("denied-claims").
    "/verify/",
    "geo.captcha-delivery.com",
)

_CHALLENGE_IFRAME_MARKERS: tuple[str, ...] = (
    "recaptcha",
    "hcaptcha",
    "turnstile",
    "funcaptcha",
    "arkose",
    "challenges.cloudflare.com",
)

_CHALLENGE_WIDGET_MARKERS: tuple[str, ...] = (
    "cf-turnstile",
    "g-recaptcha",
    "h-captcha",
    "cf-chl-widget",
    "challenge-form",
    # Lifted from the retired CloudflareDetectionStrategy after passing the
    # fixtures: the cf-spinner class only exists on Cloudflare challenge pages.
    "cf-spinner",
)

#: Public alias for the live-click probe in PageActionService, which refuses
#: to operate anything inside one of these markers. One list, two consumers,
#: so the verdict vocabulary cannot drift between detection and interaction.
CHALLENGE_WIDGET_MARKERS: tuple[str, ...] = _CHALLENGE_WIDGET_MARKERS

_CHALLENGE_SCRIPT_MARKERS: tuple[str, ...] = (
    "challenge-platform",
    "captcha-delivery",
    "challenges.cloudflare.com",
)

#: Marker substring → anti-bot vendor, matched against element attributes
#: (src, class, id, name) during the SAME single parse. Annotation only —
#: never a verdict input. Salvages the vendor probe of the retired
#: evasion/auditor.py at HTML level (page_source includes injected scripts).
_VENDOR_MARKERS: tuple[tuple[str, str], ...] = (
    ("captcha-delivery", "datadome"),
    ("challenges.cloudflare.com", "cloudflare"),
    ("cdn-cgi", "cloudflare"),
    ("challenge-platform", "cloudflare"),
    ("cf-turnstile", "cloudflare"),
    ("cf-chl", "cloudflare"),
    ("cf-spinner", "cloudflare"),
    ("g-recaptcha", "recaptcha"),
    ("recaptcha", "recaptcha"),
    ("h-captcha", "hcaptcha"),
    ("hcaptcha", "hcaptcha"),
    ("funcaptcha", "arkose"),
    ("arkose", "arkose"),
    ("px-captcha", "perimeterx"),
    ("perimeterx", "perimeterx"),
    ("akamai", "akamai"),
)

#: Login-wall URL markers, as WHOLE PATH SEGMENTS. Exact-segment matching
#: is the entire point: as substrings, "/register" sits inside
#: "/jobs/registered-nurse-123" and "/auth" inside "/author/..." — the same
#: substring class part A removed from the title, kept out of the URL.
_LOGIN_WALL_URL_MARKERS: tuple[tuple[str, ...], ...] = (
    ("login",),
    ("signin",),
    ("sign_in",),
    ("auth",),
    ("register",),
    ("signup",),
    ("account", "login"),
    ("users", "sign_in"),
    ("sso",),
)


def _login_url_matches(url: str) -> bool:
    """True when any marker matches consecutive WHOLE path segments."""
    try:
        path = urlparse(url or "").path.lower()
    except Exception:
        return False
    segments = [segment for segment in path.split("/") if segment]
    for marker in _LOGIN_WALL_URL_MARKERS:
        width = len(marker)
        for i in range(len(segments) - width + 1):
            if tuple(segments[i : i + width]) == marker:
                return True
    return False

#: Login-wall detection only: below this much visible text a page is too
#: thin to carry a posting. The challenge verdict deliberately does NOT use
#: text length — a measured interstitial population carried ~5k characters
#: of non-script boilerplate.
_MIN_CONTENT_TEXT_CHARS: int = 800

#: A page whose whole purpose is authentication does not host many forms.
_MAX_LOGIN_WALL_FORMS: int = 2

#: Cap on the visible text a probe keeps for phrase matching. Confirmation,
#: already-applied and closed language lives well inside the first 50k
#: characters of rendered text on every measured page.
_VISIBLE_TEXT_CAP: int = 50_000


@dataclass(frozen=True)
class ChallengeAssessment:
    """One verdict plus the signals that decided it.

    The signals travel with the outcome record (ApplicationEvidence.
    challenge_signals), so a disputed verdict says WHY, not just WHAT.
    """

    verdict: ChallengeVerdict
    signals: tuple[str, ...]
    detail: str
    #: Anti-bot vendors seen on the page, as an annotation for research.
    #: Never a verdict input; empty when none matched.
    vendors: tuple[str, ...] = ()


class _PageProbe(HTMLParser):
    """Structural facts about one page, collected in a single stdlib parse.

    Comments are never reported as data (HTMLParser routes them to
    handle_comment, which this class does not override), and script/style
    bodies are excluded from the visible-text count — the two places every
    measured false positive lived.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.form_count: int = 0
        self.password_input_count: int = 0
        self.challenge_iframe: bool = False
        self.challenge_widget: bool = False
        self.challenge_script: bool = False
        self.visible_text_chars: int = 0
        self.vendors: set[str] = set()
        self._text_parts: list[str] = []
        self._ignored_depth: int = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attr_text = " ".join(f"{name}={value}" for name, value in attrs).lower()
        for _marker, _vendor in _VENDOR_MARKERS:
            if _marker in attr_text:
                self.vendors.add(_vendor)
        if tag == "script":
            self._ignored_depth += 1
            src = (dict(attrs).get("src") or "").lower()
            if any(m in src for m in _CHALLENGE_SCRIPT_MARKERS):
                self.challenge_script = True
            return
        if tag == "style":
            self._ignored_depth += 1
            return
        if tag == "form":
            # A challenge's own form (Cloudflare's id="challenge-form") is the
            # challenge, not the page's content: it must not make an
            # interstitial look like a usable page.
            if not any(m in attr_text for m in _CHALLENGE_WIDGET_MARKERS):
                self.form_count += 1
        elif tag == "iframe":
            src = (dict(attrs).get("src") or "").lower()
            if any(m in src for m in _CHALLENGE_IFRAME_MARKERS):
                self.challenge_iframe = True
        elif tag == "input":
            if (dict(attrs).get("type") or "").lower() == "password":
                self.password_input_count += 1
        if tag in ("div", "input", "form", "section", "button"):
            if any(m in attr_text for m in _CHALLENGE_WIDGET_MARKERS):
                self.challenge_widget = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._ignored_depth > 0:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            chunk = data.strip()
            self.visible_text_chars += len(chunk)
            if chunk:
                self._text_parts.append(chunk)

    @property
    def visible_text(self) -> str:
        """The page's rendered visible text, lowercased, capped.

        Comments and <script>/<style> bodies are excluded — the two places
        every measured false positive lived. This is the ONLY text that
        phrase matchers may read.
        """
        return " ".join(self._text_parts).lower()[:_VISIBLE_TEXT_CAP]


def _probe(html: str) -> _PageProbe:
    """Parse one page into structural facts. A malformed page yields partial
    facts, which are still usable — this never raises."""
    probe = _PageProbe()
    try:
        probe.feed(html or "")
        probe.close()
    except Exception:
        pass
    return probe


def visible_page_text(html: str) -> str:
    """The page's rendered visible text, lowercased and capped.

    The one correct HTMLParser lives in this module; this is its public
    text accessor for the verdict's phrase matching. Comments and
    <script>/<style> bodies are never included. Never raises — a malformed
    page yields partial text.
    """
    return _probe(html).visible_text


def assess_challenge(*, url: str, title: str, html: str) -> ChallengeAssessment:
    """Decide whether a human-verification challenge is PRESENTED on this page.

    ``title`` is part of the snapshot signature and is DELIBERATELY never
    read — see the module docstring (ruling 2026-09-10). It is accepted so
    every caller passes the same three-value snapshot and no caller is
    tempted to "just check the title" locally.
    """
    del title  # deliberately unused: titles are localized and vendor-controlled
    url_l = (url or "").lower()
    if any(m in url_l for m in _CHALLENGE_URL_MARKERS):
        url_vendors = tuple(
            sorted({vendor for marker, vendor in _VENDOR_MARKERS if marker in url_l})
        )
        return ChallengeAssessment(
            verdict="gated",
            signals=("challenge-url",),
            detail=f"challenge URL marker in {url_l[:80]}",
            vendors=url_vendors,
        )

    probe = _probe(html)
    signals: list[str] = []
    if probe.challenge_iframe:
        signals.append("challenge-iframe")
    if probe.challenge_widget:
        signals.append("challenge-widget-markup")
    if probe.challenge_script:
        signals.append("challenge-script")

    # "The page carries its own content" is STRUCTURAL, never textual: a
    # form, or an apply-intent control. Measured on the 20 real pages
    # (probe_item12, 2026-09): every interstitial had 0 forms and no apply
    # control — including a population carrying ~5k characters of
    # non-script boilerplate that a text threshold misread as content;
    # every posting had 2-12 forms. Text length no longer decides anything;
    # it stays in the detail line as evidence only.
    try:
        has_apply_control = bool(find_apply_controls(url=url, html=html))
    except Exception:
        has_apply_control = False
    has_content = probe.form_count >= 1 or has_apply_control
    signals.append("page-content" if has_content else "no-page-content")
    detail = (
        f"forms={probe.form_count} "
        f"visible_text_chars={probe.visible_text_chars} "
        f"apply_control={has_apply_control} "
        f"iframe={probe.challenge_iframe} widget={probe.challenge_widget} "
        f"script={probe.challenge_script}"
    )

    if not (
        probe.challenge_iframe or probe.challenge_widget or probe.challenge_script
    ):
        return ChallengeAssessment(
            "clear", tuple(signals), detail, vendors=tuple(sorted(probe.vendors))
        )
    if not has_content:
        # Challenge markup and nothing else: the page IS the challenge,
        # whatever its title says and in whatever language.
        return ChallengeAssessment(
            "gated", tuple(signals), detail, vendors=tuple(sorted(probe.vendors))
        )
    if probe.challenge_iframe or probe.challenge_widget:
        # A rendered challenge element inside a usable page.
        return ChallengeAssessment(
            "embedded", tuple(signals), detail, vendors=tuple(sorted(probe.vendors))
        )
    # Only a challenge-platform SCRIPT on a content page: a loaded library
    # is not a presented challenge.
    return ChallengeAssessment(
        "clear", tuple(signals), detail, vendors=tuple(sorted(probe.vendors))
    )


def assess_login_wall(*, url: str, html: str) -> bool:
    """Structural login-wall verdict. The page title is never read.

    A wall is a page whose purpose is authentication: a login URL, or a
    password field on a page with at most a couple of forms and too little
    visible text to carry a posting. A posting page with a password field
    buried in a modal is not a wall, and a posting titled "Registered Nurse"
    is not a wall — that false positive is why no text matching survives here.
    """
    if _login_url_matches(url):
        return True
    probe = _probe(html)
    return (
        probe.password_input_count >= 1
        and probe.form_count <= _MAX_LOGIN_WALL_FORMS
        and probe.visible_text_chars < _MIN_CONTENT_TEXT_CHARS
    )

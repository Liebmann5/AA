"""Secondary adapter: PerceptionPort backed by BeautifulSoup static HTML parsing.

This adapter provides a zero-browser perception path for worst-case environments
where no Chrome/Firefox/Edge is available. It fetches pages via an injected
HTTPClientPort (stdlib urllib by default) and parses them with BeautifulSoup 4.

Limitations compared to the live-browser adapters:
  - No JavaScript execution — dynamic single-page applications are opaque.
  - No geometry — bounding-box-dependent logic is unavailable; all UIElements
    are returned with is_visible=True (conservative assumption).
  - No session cookies beyond what the HTTPClient carries — sites behind login
    walls cannot be accessed.
  - No interaction — this adapter implements PerceptionPort only; the
    ApplicationEngine still needs an InteractionPort to submit forms.

Despite these limits, the adapter is useful for:
  - Classifying static job description pages (CLOSED, ALREADY_APPLIED, etc.)
  - Extracting form structure from server-rendered ATS pages
  - Discovery via direct URL lists when no browser driver is present
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from auto_apply.domain.applications.fsm.states import ApplicationState
from auto_apply.domain.models.ui import UIElement, UIElementType, UIModel
from auto_apply.domain.ports.http_client_port import HTTPClientPort
from auto_apply.domain.ports.perception_port import PerceptionPort

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Graceful degradation: BS4 is a hard dependency per pyproject.toml, but
# we guard the import so a missing install degrades to empty scans rather
# than a crash at import time.
try:
    from bs4 import BeautifulSoup, Tag

    _BS4_AVAILABLE = True
except ImportError:  # pragma: no cover
    _BS4_AVAILABLE = False
    BeautifulSoup = None  # type: ignore[assignment,misc]
    Tag = None  # type: ignore[assignment,misc]


# ─────────────────────────────────────────────────────────────────────────────
# Keyword tables for ApplicationState classification (text-based, order matters)
# ─────────────────────────────────────────────────────────────────────────────

_TEXT_STATE_RULES: list[tuple[frozenset[str], ApplicationState]] = [
    (
        frozenset({"application sent", "application submitted", "you applied",
                   "successfully applied", "thank you for applying"}),
        ApplicationState.SUCCESS,
    ),
    (
        frozenset({"no longer accepting", "position has been filled",
                   "job is closed", "posting expired"}),
        ApplicationState.CLOSED,
    ),
    (
        frozenset({"you already applied", "you applied on", "already submitted"}),
        ApplicationState.ALREADY_APPLIED,
    ),
    (
        frozenset({"sign in to apply", "log in to apply", "login required",
                   "create an account to apply"}),
        ApplicationState.LOGIN_WALL,
    ),
    (
        frozenset({"upload resume", "upload cv", "attach resume",
                   "upload your resume"}),
        ApplicationState.UPLOAD_STEP,
    ),
    (
        frozenset({"review your application", "review and submit",
                   "confirm your application"}),
        ApplicationState.REVIEW_STEP,
    ),
    (
        frozenset({"browse all jobs", "view all jobs", "all jobs at",
                   "careers at", "job openings at", "open positions"}),
        ApplicationState.REDIRECT_TO_CAREERS_PAGE,
    ),
    (
        frozenset({"related jobs", "similar jobs", "jobs you might like",
                   "more jobs from"}),
        ApplicationState.INDEED_TAB_SWITCHED,
    ),
    (
        frozenset({"easy apply", "apply now", "quick apply", "1-click apply"}),
        ApplicationState.INITIAL_START,
    ),
]

# Tags whose type=hidden inputs should be skipped in scan_page.
_SKIP_INPUT_TYPES: frozenset[str] = frozenset({"hidden", "submit", "reset", "image"})

# HTML tags that represent interactable form elements.
_FORM_TAGS: tuple[str, ...] = ("input", "textarea", "select", "button")


class BS4PerceptionAdapter(PerceptionPort):
    """PerceptionPort backed by BeautifulSoup static HTML analysis.

    Fetches pages via an injected :class:`HTTPClientPort`, parses them with
    BeautifulSoup, and returns :class:`UIModel` / :class:`ApplicationState`
    without requiring any live browser.

    Args:
        http_client: An :class:`HTTPClientPort` implementation for fetching URLs.
    """

    def __init__(self, http_client: HTTPClientPort) -> None:
        self._http = http_client
        self._current_url: str = ""
        self._current_html: str = ""
        self._current_title: str = ""

    # ─────────────────────────────────────────────────────────────────────────
    # PerceptionPort interface
    # ─────────────────────────────────────────────────────────────────────────

    def navigate(self, url: str) -> None:
        """Fetches *url* and stores the response for subsequent scan/classify calls.

        Args:
            url: Fully-qualified URL to fetch.
        """
        resp = self._http.get(url)
        self._current_url = resp.url or url
        self._current_html = resp.text or ""

        if resp.status_code >= 400:
            logger.warning(
                "BS4PerceptionAdapter.navigate | status=%d url=%s",
                resp.status_code,
                self._current_url,
            )
            self._current_title = ""
            return

        self._current_title = self._extract_title(self._current_html)
        logger.debug(
            "BS4PerceptionAdapter.navigate | url=%s title=%r bytes=%d",
            self._current_url,
            self._current_title,
            len(self._current_html),
        )

    def scan_page(self) -> UIModel:
        """Parses the stored HTML and returns a UIModel of discovered form elements.

        Geometry-dependent fields (bounding boxes, pixel coordinates) are absent.
        All returned UIElements have ``is_visible=True`` as a conservative default.

        Returns:
            :class:`UIModel` describing every interactable element in the HTML.
        """
        if not _BS4_AVAILABLE:
            logger.warning(
                "bs4 not installed — scan_page returning empty UIModel. "
                "Install beautifulsoup4 for full BS4 perception."
            )
            return UIModel(url=self._current_url, title=self._current_title, elements=[])

        if not self._current_html:
            return UIModel(url=self._current_url, title=self._current_title, elements=[])

        soup = BeautifulSoup(self._current_html, "html.parser")
        elements: list[UIElement] = []

        for tag in soup.find_all(_FORM_TAGS):
            el = self._build_ui_element(tag, soup)
            if el is not None:
                elements.append(el)

        logger.debug(
            "BS4PerceptionAdapter.scan_page | url=%s elements=%d",
            self._current_url,
            len(elements),
        )
        return UIModel(
            url=self._current_url,
            title=self._current_title,
            elements=elements,
        )

    def get_current_state(self) -> ApplicationState:
        """Classifies the stored HTML into an ApplicationState value.

        Uses keyword matching over the visible page text, then structural
        element counts for redirect/modal detection.

        Returns:
            :class:`ApplicationState` for the current HTML content.
        """
        if not self._current_html:
            return ApplicationState.UNKNOWN

        # Fast path: keyword scan over lowercased visible text.
        page_text = self._visible_text(self._current_html).lower()

        for keywords, state in _TEXT_STATE_RULES:
            if any(kw in page_text for kw in keywords):
                return state

        if not _BS4_AVAILABLE:
            return ApplicationState.UNKNOWN

        soup = BeautifulSoup(self._current_html, "html.parser")

        # Structural: modal/dialog open.
        if soup.find(attrs={"role": "dialog"}) or soup.find(attrs={"role": "alertdialog"}):
            return ApplicationState.MODAL_OPEN

        # Structural: many job cards → listing page, not a single form.
        job_cards = soup.find_all(attrs={"data-job-id": True})
        if len(job_cards) > 3:
            return ApplicationState.REDIRECT_TO_LIST

        # Structural: multiple apply-style links → listing page.
        apply_links = [
            a for a in soup.find_all("a", href=True)
            if "apply" in (a.get_text(strip=True) or "").lower()
        ]
        if len(apply_links) > 3:
            return ApplicationState.REDIRECT_TO_LIST

        # Fallback: active form inputs present → generic form step.
        if soup.find("input") or soup.find("textarea"):
            return ApplicationState.FORM_STEP

        return ApplicationState.UNKNOWN

    def get_page_text(self) -> str:
        """Returns the visible text of the fetched HTML, script/style excluded.

        Works fully offline — this is the zero-browser leg of the canonical text
        path. Returns an empty string when no page has been fetched. Never raises.
        """
        if not self._current_html:
            return ""
        return self._visible_text(self._current_html).strip()

    # ─────────────────────────────────────────────────────────────────────────
    # Extra public method (not on PerceptionPort — used by tests and tooling)
    # ─────────────────────────────────────────────────────────────────────────

    def extract_full_dom_tree(self) -> Any | None:
        """Returns the BeautifulSoup tree for the stored HTML, or None.

        Callers that need direct DOM access beyond what the PerceptionPort
        interface provides (e.g., ATS-specific scrapers) can use this to
        work with the parsed tree directly.

        Returns:
            A :class:`bs4.BeautifulSoup` object, or ``None`` if BS4 is
            unavailable or no page has been fetched yet.
        """
        if not _BS4_AVAILABLE or not self._current_html:
            return None
        return BeautifulSoup(self._current_html, "html.parser")

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _build_ui_element(self, tag: Any, soup: Any) -> UIElement | None:
        """Converts a BeautifulSoup tag into a UIElement, or returns None."""
        try:
            tag_name: str = tag.name.lower()
            type_attr: str = (tag.get("type") or "").lower()

            # Skip hidden / non-visible inputs.
            if tag_name == "input" and type_attr in _SKIP_INPUT_TYPES:
                return None

            el_type = _classify_element(tag_name, type_attr, tag.get("role") or "")

            name = tag.get("name") or tag.get("id") or tag_name
            label = self._resolve_label(tag, soup)
            placeholder = tag.get("placeholder")
            is_required = tag.has_attr("required")
            pattern = tag.get("pattern")

            options: list[str] = []
            if el_type == UIElementType.SELECT:
                options = [
                    opt.get_text(strip=True)
                    for opt in tag.find_all("option")
                    if opt.get_text(strip=True)
                ]

            internal_id = f"{name}-{label}-{el_type.value}"

            return UIElement(
                id=internal_id,
                element_type=el_type,
                name=name,
                label=label,
                placeholder=placeholder,
                is_required=is_required,
                validation_pattern=pattern,
                options=options,
            )

        except Exception as exc:
            logger.debug("BS4: failed to build UIElement | error=%s", exc)
            return None

    def _resolve_label(self, tag: Any, soup: Any) -> str | None:
        """Resolves the human-readable label for an HTML element.

        Resolution order:
            1. ``aria-label`` attribute
            2. ``aria-labelledby`` → look up referenced element's text
            3. ``<label for="id">`` matching the element's ID
            4. Nearest ancestor ``<label>`` wrapping the element
            5. ``placeholder`` attribute
        """
        # 1. aria-label
        aria_label = (tag.get("aria-label") or "").strip()
        if aria_label:
            return aria_label

        # 2. aria-labelledby
        labelledby = tag.get("aria-labelledby")
        if labelledby:
            ref = soup.find(id=labelledby)
            if ref:
                text = ref.get_text(strip=True)
                if text:
                    return text

        # 3. <label for="id">
        el_id = tag.get("id")
        if el_id:
            lbl = soup.find("label", attrs={"for": el_id})
            if lbl:
                text = lbl.get_text(strip=True)
                if text:
                    return text

        # 4. Ancestor <label>
        for ancestor in tag.parents:
            if getattr(ancestor, "name", None) == "label":
                text = ancestor.get_text(separator=" ", strip=True)
                if text:
                    return text
                break

        # 5. Placeholder as last resort
        ph = (tag.get("placeholder") or "").strip()
        return ph or None

    @staticmethod
    def _visible_text(html: str) -> str:
        """Extracts visible text from raw HTML without importing BS4.

        Used as a fast path in get_current_state() before the full BS4 parse.
        Strips all tags via a simple regex-free approach — sufficient for the
        keyword-matching use case.
        """
        if not _BS4_AVAILABLE:
            # Minimal fallback: strip angle-bracket content.
            import re  # noqa: PLC0415

            return re.sub(r"<[^>]+>", " ", html)
        soup = BeautifulSoup(html, "html.parser")
        # Remove script/style blocks before extracting visible text.
        for tag in soup.find_all(["script", "style", "noscript"]):
            tag.decompose()
        return soup.get_text(separator=" ")

    @staticmethod
    def _extract_title(html: str) -> str:
        """Parses the <title> text from raw HTML."""
        if not _BS4_AVAILABLE:
            import re  # noqa: PLC0415

            m = re.search(r"<title[^>]*>([^<]*)</title>", html, re.IGNORECASE)
            return m.group(1).strip() if m else ""
        soup = BeautifulSoup(html, "html.parser")
        title_tag = soup.find("title")
        return title_tag.get_text(strip=True) if title_tag else ""


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _classify_element(
    tag_name: str,
    type_attr: str,
    role: str,
) -> UIElementType:
    """Maps an HTML tag + type + ARIA role to a UIElementType."""
    role = role.lower()

    if tag_name == "select" or role == "listbox":
        return UIElementType.SELECT
    if type_attr == "checkbox" or role == "checkbox":
        return UIElementType.CHECKBOX
    if type_attr == "radio" or role == "radio":
        return UIElementType.RADIO
    if type_attr == "file":
        return UIElementType.FILE_UPLOAD
    if tag_name == "textarea" or role == "textbox":
        return UIElementType.TEXT_AREA
    if tag_name == "button" or role == "button" or type_attr in ("submit", "button"):
        return UIElementType.BUTTON
    if tag_name == "a":
        return UIElementType.LINK
    return UIElementType.TEXT_INPUT
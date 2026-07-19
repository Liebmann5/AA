"""Secondary adapter: PerceptionPort backed by geometry-aware DOM extraction.

Wraps MathDOMAdapter to implement the full PerceptionPort contract.
scan_page() converts the DOMNode tree into a UIModel by selecting visible
interactable nodes based on bounding-box geometry. get_current_state()
classifies the page using keyword heuristics over the page's visible text.
"""

from __future__ import annotations

import logging

from auto_apply.adapters.secondary.perception.math_dom_adapter import MathDOMAdapter
from auto_apply.domain.applications.fsm.states import ApplicationState
from auto_apply.domain.models.math_dom import DOMNode
from auto_apply.domain.models.ui import UIElement, UIElementType, UIModel
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.ports.perception_port import PerceptionPort

logger = logging.getLogger(__name__)

_INTERACTABLE_TAGS = frozenset({"input", "textarea", "select", "button", "a"})
_INTERACTABLE_ROLES = frozenset({
    "button", "checkbox", "radio", "textbox", "combobox", "listbox", "link",
})

# Evaluated in order; first match wins.
_STATE_KEYWORDS: list[tuple[frozenset[str], ApplicationState]] = [
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
        frozenset({"sign in", "log in", "login required",
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

# CSS selectors used for structural state detection (not keyword-based).
_MODAL_SELECTOR = "[role='dialog'], [role='alertdialog'], .modal, .dialog"
_APPLY_BUTTON_SELECTOR = (
    "button[class*='apply'], a[class*='apply'], "
    "[data-job-id], [class*='job-card'], [class*='jobcard']"
)


class MathPerceptionAdapter(PerceptionPort):
    """PerceptionPort backed by geometry-aware DOM analysis.

    Uses MathDOMAdapter to obtain an immutable DOMNode tree with bounding-box
    geometry, then converts visible interactable nodes into UIElements.

    Args:
        browser: An initialized BrowserInterface.
        max_depth: Maximum DOM depth forwarded to MathDOMAdapter (default 50).
    """

    def __init__(self, browser: BrowserInterface, max_depth: int = 50) -> None:
        self._browser = browser
        self._math_adapter = MathDOMAdapter(browser, max_depth=max_depth)

    def navigate(self, url: str) -> None:
        self._browser.get(url)

    def scan_page(self) -> UIModel:
        root = self._math_adapter.extract_full_dom_tree()
        elements: list[UIElement] = []
        if root is not None:
            self._collect_interactables(root, elements)
        return UIModel(
            url=self._math_adapter.get_current_url(),
            title=self._math_adapter.get_page_title(),
            elements=elements,
        )

    def get_current_state(self) -> ApplicationState:
        try:
            raw = self._browser.execute_script("return document.body.innerText")
            page_text = (raw or "").lower()
        except Exception:
            return ApplicationState.UNKNOWN

        for keywords, state in _STATE_KEYWORDS:
            if any(kw in page_text for kw in keywords):
                return state

        try:
            modals = self._browser.find_elements("css selector", _MODAL_SELECTOR)
            if modals:
                return ApplicationState.MODAL_OPEN
        except Exception:
            pass

        try:
            cards = self._browser.find_elements("css selector", _APPLY_BUTTON_SELECTOR)
            if len(cards) > 3:
                return ApplicationState.REDIRECT_TO_LIST
        except Exception:
            pass

        try:
            inputs = self._browser.find_elements(
                "css selector", "input:not([type='hidden']), textarea"
            )
            if inputs:
                return ApplicationState.FORM_STEP
        except Exception:
            pass

        return ApplicationState.UNKNOWN

    def get_page_text(self) -> str:
        try:
            raw = self._browser.execute_script("return document.body.innerText")
        except Exception as exc:
            logger.debug("get_page_text failed: %s", exc)
            return ""
        return raw or ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_interactables(self, node: DOMNode, out: list[UIElement]) -> None:
        if _is_interactable(node) and _is_visible(node):
            ui_el = _to_ui_element(node)
            if ui_el is not None:
                out.append(ui_el)
        for child in node.children:
            self._collect_interactables(child, out)


# ------------------------------------------------------------------
# Module-level helpers (no instance state needed)
# ------------------------------------------------------------------

def _is_visible(node: DOMNode) -> bool:
    g = node.geometry
    return g is not None and g.width > 0 and g.height > 0


def _is_interactable(node: DOMNode) -> bool:
    if node.tag in _INTERACTABLE_TAGS:
        return True
    return node.get_attribute("role", "") in _INTERACTABLE_ROLES


def _to_ui_element(node: DOMNode) -> UIElement | None:
    try:
        el_type = _classify_node(node)
        name = (
            node.get_attribute("name")
            or node.get_attribute("id")
            or node.tag
        )
        label = (
            node.get_attribute("aria-label")
            or node.get_attribute("title")
            or node.text
            or None
        )
        return UIElement(
            id=f"{name}-{label}-{el_type.value}",
            element_type=el_type,
            name=name,
            label=label,
            placeholder=node.get_attribute("placeholder"),
            is_required=node.get_attribute("required") is not None,
            validation_pattern=node.get_attribute("pattern"),
        )
    except Exception as exc:
        logger.debug("Failed to convert DOMNode to UIElement: %s", exc)
        return None


def _classify_node(node: DOMNode) -> UIElementType:
    tag = node.tag
    role = node.get_attribute("role", "")
    input_type = node.get_attribute("type", "").lower()

    if tag == "select" or role == "listbox":
        return UIElementType.SELECT
    if input_type == "checkbox" or role == "checkbox":
        return UIElementType.CHECKBOX
    if input_type == "radio" or role == "radio":
        return UIElementType.RADIO
    if input_type == "file":
        return UIElementType.FILE_UPLOAD
    if tag == "textarea" or role == "textbox":
        return UIElementType.TEXT_AREA
    if tag == "button" or role == "button" or input_type == "submit":
        return UIElementType.BUTTON
    if tag == "a" or role == "link":
        return UIElementType.LINK
    return UIElementType.TEXT_INPUT
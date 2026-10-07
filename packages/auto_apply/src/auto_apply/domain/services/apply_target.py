"""Where does a posting's Apply control point — and is this page already a form?

Pure, replayable answers for the apply route (item 12B), in the same style
as domain/services/challenge_assessment.py: a stdlib parse of (url, html),
no browser, no host lists, no site-specific selectors. One parser answers
all three questions so the target LEARNED at vetting and the target
FOLLOWED at application can never be two different answers.

Measured basis (apply_targets.txt, 2026-09/10, 20 real job-board pages):
    - An offsite apply link is an <a> with an href, sometimes through a
      redirector. Buttons-only searches cannot see it.
    - Account-gated apply controls are <button>s with no navigable target;
      clicking one opens a sign-in dialog, not a form.
    - Postings always carry forms (search, sign-in, alerts) — measured at
      1 to 12 per page — so "has a <form>" cannot distinguish a posting
      from an application. What distinguishes them is a form SUBSTANTIAL
      enough to be the application: several fillable controls in one form,
      or a file upload.
    - Apply intent is matched on the ACCESSIBLE NAME (rendered text, then
      value / aria-label / title), English "apply" only — localization debt
      with a known shape, same as RV-9. Non-English apply controls are
      invisible until that debt is paid.

Nothing here reads HTML comments or unrendered page data: if a site does
not render an employer URL, AA does not go looking for one.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

_APPLY_LABEL_KEYWORDS: tuple[str, ...] = ("apply",)

#: A form with at least this many fillable controls (text inputs, selects,
#: textareas — not hidden/submit/button) is substantial enough to BE the
#: application. A posting's search box (1) and sign-in form (2) stay below.
_MIN_FORM_CONTROLS: int = 3


@dataclass(frozen=True)
class ApplyControl:
    """One apply-intent control found on a page.

    ``href`` is the resolved absolute URL, or "" when the control has no
    navigable target (the account-gated button shape). ``off_host`` is True
    when the href leaves the page's host — the route worth following.
    """

    label: str
    href: str
    off_host: bool
    tag: str


def is_apply_label(label: str) -> bool:
    """Apply intent in an accessible name. English-only (see module docstring)."""
    text = (label or "").lower()
    return any(k in text for k in _APPLY_LABEL_KEYWORDS)


class _ApplyProbe(HTMLParser):
    """Apply controls, form fillability and auth dialogs in a single parse."""

    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._page_url = page_url
        self._page_host = urlparse(page_url or "").netloc.lower()
        self.controls: list[ApplyControl] = []
        self.has_fillable_form: bool = False
        self.auth_dialog: bool = False
        self._open_controls: list[dict] = []
        self._form_stack: list[int] = []
        self._dialog_stack: list[str] = []

    # ------------------------------------------------------------------
    # HTMLParser hooks
    # ------------------------------------------------------------------

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attr = {name.lower(): (value or "") for name, value in attrs}
        role = attr.get("role", "").lower()
        aria_modal = attr.get("aria-modal", "").lower()

        if role == "dialog" or (aria_modal and aria_modal != "false"):
            self._dialog_stack.append(tag)

        if tag == "form":
            self._form_stack.append(0)

        if tag == "input":
            itype = attr.get("type", "text").lower()
            if itype == "password" and self._dialog_stack:
                self.auth_dialog = True
            if itype == "file":
                # A file upload is an application form by itself.
                self.has_fillable_form = True
            if self._form_stack and itype not in (
                "hidden",
                "submit",
                "button",
                "image",
                "reset",
            ):
                self._form_stack[-1] += 1
            if itype in ("submit", "button"):
                self._add_control(tag, attr, "")

        if tag in ("select", "textarea") and self._form_stack:
            self._form_stack[-1] += 1

        if tag in ("a", "button") or role == "button":
            self._open_controls.append({"tag": tag, "attr": attr, "text": []})

    def handle_data(self, data: str) -> None:
        for control in self._open_controls:
            control["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._dialog_stack and self._dialog_stack[-1] == tag:
            self._dialog_stack.pop()
        if tag == "form" and self._form_stack:
            if self._form_stack.pop() >= _MIN_FORM_CONTROLS:
                self.has_fillable_form = True
        # Finish the most recently opened control of this tag. Nested
        # controls of mixed tags are invalid HTML; stack order is good
        # enough for real pages.
        for i in range(len(self._open_controls) - 1, -1, -1):
            if self._open_controls[i]["tag"] == tag:
                self._finish_control(self._open_controls.pop(i))
                break

    # ------------------------------------------------------------------
    # Control assembly
    # ------------------------------------------------------------------

    def _finish_control(self, control: dict) -> None:
        text = " ".join("".join(control["text"]).split())
        self._add_control(control["tag"], control["attr"], text)

    def _add_control(self, tag: str, attr: dict, text: str) -> None:
        # Accessible name priority mirrors the live accessor in
        # ApplicationsWorkflow._control_label: rendered text, then value,
        # aria-label, title. The two must agree — a control the parser sees
        # and a control the browser sees are the same control.
        label = ""
        for candidate in (
            text,
            attr.get("value", ""),
            attr.get("aria-label", ""),
            attr.get("title", ""),
        ):
            if isinstance(candidate, str) and candidate.strip():
                label = candidate.strip()
                break

        href = ""
        raw_href = attr.get("href", "")
        if raw_href and not raw_href.lower().startswith(
            ("javascript:", "mailto:", "tel:", "#")
        ):
            resolved = urljoin(self._page_url, raw_href)
            if urlparse(resolved).scheme in ("http", "https"):
                href = resolved
        off_host = bool(href) and urlparse(href).netloc.lower() != self._page_host
        self.controls.append(
            ApplyControl(label=label, href=href, off_host=off_host, tag=tag)
        )


def _parse(url: str, html: str) -> _ApplyProbe:
    """Parse one page. A malformed page yields partial facts; never raises."""
    probe = _ApplyProbe(url)
    try:
        probe.feed(html or "")
        probe.close()
    except Exception:
        pass
    return probe


def find_apply_controls(*, url: str, html: str) -> tuple[ApplyControl, ...]:
    """Every control on the page whose accessible name carries apply intent."""
    return tuple(c for c in _parse(url, html).controls if is_apply_label(c.label))


def page_has_fillable_form(html: str) -> bool:
    """True when the page carries a form substantial enough to BE the
    application (>= _MIN_FORM_CONTROLS fillable controls in one form, or any
    file input). Checked BEFORE any apply-control search, so a real form
    whose submit button says "Apply" is never misread as a posting."""
    return _parse("", html).has_fillable_form


def auth_dialog_present(html: str) -> bool:
    """True when a modal dialog (role=dialog / aria-modal) contains a
    password field — the generic, accessible shape of "this site demands an
    account". The account-gated dialog is never rendered in the captured
    pre-click samples, so this deliberately targets the dialog shape, not
    any site's markup."""
    return _parse("", html).auth_dialog

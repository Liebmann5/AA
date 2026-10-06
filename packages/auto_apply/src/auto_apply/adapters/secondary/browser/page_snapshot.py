"""The browser as snapshot taker for the ONE page verdict.

assess_page (domain/services/page_assessment.py) is pure over
(url, title, html); the only thing any adapter may do with the live
browser is take that snapshot. One helper so the coercion rules are
written once: a driver that cannot answer degrades to empty strings, never
raises, and an empty snapshot is UNKNOWN to the verdict, never "clear".

The application layer keeps its own copy (ApplicationsWorkflow's
_page_snapshot): it may not import from adapters.
"""

from __future__ import annotations

from auto_apply.domain.ports.browser_port import BrowserInterface


def browser_page_snapshot(browser: BrowserInterface) -> tuple[str, str, str]:
    """(url, title, html) of the page the browser is on RIGHT NOW.

    Values are coerced defensively: a driver that cannot answer (or a test
    double whose attributes are not strings) degrades to empty strings
    rather than poisoning the parse.
    """
    snapshot: list[str] = []
    for attribute in ("current_url", "title", "page_source"):
        try:
            value = getattr(browser, attribute, "") or ""
        except Exception:
            value = ""
        snapshot.append(value if isinstance(value, str) else "")
    return snapshot[0], snapshot[1], snapshot[2]

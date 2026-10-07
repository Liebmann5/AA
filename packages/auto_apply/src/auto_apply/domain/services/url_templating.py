"""URL page templates — pure logic, no browser, fully testable.

A page number that lives in the URL is the cheapest, most deterministic
advance there is: no click, no control, no ambiguity. The template itself
is data (engine YAML, user-overridable through SelectorLoader); this module
is the only code that interprets it.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from auto_apply.domain.models.page_advance import UrlPageTemplate


def template_value(template: UrlPageTemplate, page_number: int) -> int:
    """The parameter value for a 1-based page number."""
    return template.first + template.step * (page_number - 1)


def next_page_url(
    template: UrlPageTemplate, current_url: str, page_number: int
) -> str | None:
    """current_url with the page parameter set to page_number's value.

    Existing parameters (and the fragment) are preserved; an existing page
    parameter is replaced, not duplicated. None for a malformed URL — the
    caller falls through to the next rung.
    """
    try:
        parts = urlsplit(current_url)
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k != template.param
    ]
    pairs.append((template.param, str(template_value(template, page_number))))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment)
    )


def url_template_from_config(config: object) -> UrlPageTemplate | None:
    """Parse the ``pagination.url_template`` section of an engine YAML dict.

    Anything malformed is a None (structural rungs take over), never an
    exception: YAML is user-editable data, and a typo must not kill discovery.
    """
    if not isinstance(config, dict):
        return None
    raw = config.get("url_template")
    if not isinstance(raw, dict):
        return None
    param = raw.get("param")
    first = raw.get("first")
    step = raw.get("step")
    if (
        not param
        or not isinstance(param, str)
        or not isinstance(first, int)
        or isinstance(first, bool)
        or not isinstance(step, int)
        or isinstance(step, bool)
        or step < 1
    ):
        return None
    return UrlPageTemplate(param=param, first=first, step=step)

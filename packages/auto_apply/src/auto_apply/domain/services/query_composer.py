"""Composes user-authored search queries from the search-surface catalog.

Pure: no I/O, no clock, no randomness, no browser, no network. The same
composer core serves the user-facing query builder (``compose``) and AA's
automated discovery (``build_automation_url``) — one capability model, one
composition path, so the two can never drift.

The composer never approximates. Anything a surface cannot express becomes a
plain-language note in the result, and content that cannot be expressed is
refused, never silently rewritten. A length limit is enforced by refusing to
write anything rather than by truncation.
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

from auto_apply.domain.models.search_query import (
    QueryNote,
    QueryRequest,
    QueryResult,
)
from auto_apply.domain.models.search_surface import (
    OFFERED_STATUSES,
    OperatorSpec,
    SearchSurfaceSpec,
    UrlOptionSpec,
    UrlTemplateSpec,
)

#: Typed operators the composer can emit today. The registry pins every
#: surface's offered operators to a subset of this set, so "offered" can
#: never outrun "composable".
EXPRESSIBLE_OPERATORS = frozenset({"phrase", "any_of", "exclude", "site", "intitle"})

_CONFUSABLES = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00a0": " ",
        "\u202f": " ",
        "\uff02": '"',
        "\uff07": "'",
    }
)

_SAFE_OPTION_VALUE = re.compile(r"[A-Za-z0-9._~\-]+")
_SITE_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def normalize_confusables(text: str) -> str:
    """Fold typographic quotes/dashes/spaces to ASCII and collapse whitespace."""
    return " ".join((text or "").translate(_CONFUSABLES).split())


def _clean_content(text: str) -> str:
    # '"' is dropped from content: the composer adds its own quoting, and a
    # nested quote would corrupt it. Apostrophes are kept.
    return normalize_confusables(text).replace('"', "")


def _clean_site(text: str) -> str:
    site = normalize_confusables(text)
    site = _SITE_SCHEME.sub("", site)
    return site.strip().rstrip("/")


def _info(topic: str, message: str) -> QueryNote:
    return QueryNote(severity="info", topic=topic, message=message)


def _refused(topic: str, message: str) -> QueryNote:
    return QueryNote(severity="refused", topic=topic, message=message)


def _offered_operators(spec: SearchSurfaceSpec) -> dict[str, OperatorSpec]:
    return {
        op.name: op
        for op in spec.operators
        if op.composable and op.status in OFFERED_STATUSES
    }


def _offered_url_options(spec: SearchSurfaceSpec) -> dict[str, UrlOptionSpec]:
    offered: dict[str, UrlOptionSpec] = {}
    for opt in spec.url_options:
        if opt.composable and opt.status in OFFERED_STATUSES:
            offered.setdefault(opt.option, opt)
    return offered


def _template_params(
    template: UrlTemplateSpec, query: str, location: str
) -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = []
    for p in template.parameters:
        if p.source == "query":
            params.append((p.name, query))
        elif p.source == "location":
            params.append((p.name, location or ""))
        else:
            params.append((p.name, p.value or ""))
    return params


def _format_option_value(opt: UrlOptionSpec, code: str) -> str:
    return opt.value_format.format(code=code) if "{code}" in opt.value_format else opt.value_format


def _compose_bar(
    request: QueryRequest,
    spec: SearchSurfaceSpec,
    ops: dict[str, OperatorSpec],
) -> tuple[str | None, list[QueryNote], bool]:
    """Returns (bar_text, notes, hard_stop). hard_stop means the URL must not
    be built either (a length refusal). A content refusal stops the bar but
    lets the link carry what the surface honestly can."""
    tq = spec.text_query
    notes: list[QueryNote] = []

    if request.site and "site" not in ops:
        return None, [_refused(
            "site",
            f"{spec.display_name} has no way to limit a typed search to one "
            "site, so no search text was written — writing one without the "
            "site limit would not be the search you asked for.",
        )], False
    if request.any_of and ("any_of" not in ops or not tq.or_token):
        return None, [_refused(
            "any_of",
            f"{spec.display_name} has no way to say 'any of these' in its "
            "search bar, so no search text was written.",
        )], False
    if request.exclude and "exclude" not in ops:
        return None, [_refused(
            "exclude",
            f"{spec.display_name} has no way to exclude words in its search "
            "bar, so no search text was written.",
        )], False
    if request.in_title and "intitle" not in ops:
        return None, [_refused(
            "intitle",
            f"{spec.display_name} has no title filter in its search bar, so "
            "no search text was written.",
        )], False

    quote = tq.phrase_quote
    subject_bits: list[str] = []
    if request.phrases and "phrase" not in ops:
        notes.append(_info(
            "phrase",
            f"{spec.display_name} has no exact-phrase quoting; your phrase "
            "was written without quotes.",
        ))
    for phrase in request.phrases:
        content = _clean_content(phrase)
        subject_bits.append(f"{quote}{content}{quote}" if "phrase" in ops else content)
    for term in request.required:
        subject_bits.append(normalize_confusables(term))
    if request.any_of:
        token = tq.or_token
        assert token is not None  # guaranteed by the refusal above
        if tq.or_uppercase:
            token = token.upper()
        alternatives = f" {token} ".join(
            f"{quote}{_clean_content(a)}{quote}" for a in request.any_of
        )
        # Own parentheses only beside other terms; alone, the subject
        # group's parentheses already enclose it.
        subject_bits.append(f"({alternatives})" if subject_bits else alternatives)

    parts: list[str] = []
    if request.site:
        parts.append(ops["site"].syntax.format(value=_clean_site(request.site)))
    if subject_bits:
        parts.append(tq.subject_group.format(content=" ".join(subject_bits)))
    for term in request.exclude:
        cleaned = _clean_content(term)
        if " " in cleaned:
            cleaned = f"{quote}{cleaned}{quote}"
        parts.append(ops["exclude"].syntax.format(value=cleaned))
    for term in request.in_title:
        cleaned = normalize_confusables(term)
        if " " in cleaned:
            cleaned = f"{quote}{cleaned}{quote}"
        parts.append(ops["intitle"].syntax.format(value=cleaned))

    bar = " ".join(parts)
    if not bar:
        return None, notes, False
    if tq.max_words is not None and len(bar.split()) > tq.max_words:
        source = f" ({tq.max_words_source})" if tq.max_words_source else ""
        notes.append(_refused(
            "length",
            f"That search is {len(bar.split())} words; {spec.display_name} "
            f"is reported to stop reading after {tq.max_words}{source}. "
            "Nothing was written — cutting it down would not be the search "
            "you asked for.",
        ))
        return None, notes, True
    return bar, notes, False


def _compose_url(
    request: QueryRequest,
    spec: SearchSurfaceSpec,
    bar: str | None,
    ops: dict[str, OperatorSpec],
    offered_options: dict[str, UrlOptionSpec],
) -> tuple[str | None, list[QueryNote]]:
    notes: list[QueryNote] = []
    template_name = request.template or spec.default_url or next(iter(spec.urls), None)
    if template_name is None:
        return None, notes
    template = spec.urls.get(template_name)
    if template is None:
        return None, [_refused(
            "template",
            f"{spec.display_name} has no link form called '{template_name}'. "
            f"Choices: {', '.join(spec.urls)}.",
        )]

    if bar is not None:
        query_value = bar
    else:
        # No bar (refused or never writable): the link carries the best form
        # the surface honestly offers, and every dropped part is named.
        bits: list[str] = []
        quote = spec.text_query.phrase_quote
        for phrase in request.phrases:
            content = _clean_content(phrase)
            bits.append(f"{quote}{content}{quote}" if "phrase" in ops else content)
        bits.extend(normalize_confusables(t) for t in request.required)
        dropped: list[str] = []
        if request.any_of:
            dropped.append("the 'any of these' part")
        if request.site:
            dropped.append("the site limit")
        if request.exclude:
            dropped.append("the exclusions")
        if request.in_title:
            dropped.append("the title filter")
        if dropped:
            notes.append(_info(
                "dropped",
                f"Only some of your search has a form on {spec.display_name}; "
                f"{', '.join(dropped)} "
                f"{'was' if len(dropped) == 1 else 'were'} left out of the link.",
            ))
        query_value = " ".join(bits)

    if not query_value:
        if request.options:
            notes.append(_refused(
                "options",
                "Settings without any search terms make no link, so they were "
                "not applied.",
            ))
        else:
            notes.append(_info("empty", "Nothing to build yet — add at least one term."))
        return None, notes

    params = _template_params(template, query_value, request.location)

    for key, value in request.options:
        opt = offered_options.get(key)
        if opt is None:
            known = next((o for o in spec.url_options if o.option == key), None)
            if known is not None:
                notes.append(_refused(
                    key,
                    f"{spec.display_name}'s '{key}' setting is not offered: "
                    f"{known.explanation}",
                ))
            else:
                notes.append(_refused(
                    key,
                    f"{spec.display_name} has no '{key}' setting, so it was left out.",
                ))
            continue
        if opt.free_form:
            cleaned = normalize_confusables(value)
            if not _SAFE_OPTION_VALUE.fullmatch(cleaned):
                notes.append(_refused(
                    key,
                    f"'{value}' is not a value {spec.display_name}'s '{key}' "
                    "setting can carry.",
                ))
                continue
            code = cleaned
        else:
            if opt.option_labels and value not in opt.option_labels:
                choices = ", ".join(opt.option_labels.values())
                notes.append(_refused(
                    key,
                    f"'{value}' is not offered for {opt.label}. Choices: {choices}.",
                ))
                continue
            looked_up = opt.codes.get(value)
            if looked_up is None:
                choices = ", ".join(
                    opt.option_labels.get(k, k) for k in opt.codes
                )
                notes.append(_refused(
                    key,
                    f"'{value}' is not a choice for {opt.label}. Choices: {choices}.",
                ))
                continue
            code = looked_up
        formatted = _format_option_value(opt, code)
        if opt.merge == "comma":
            for index, (pname, pvalue) in enumerate(params):
                if pname == opt.name:
                    params[index] = (pname, f"{pvalue},{formatted}")
                    break
            else:
                params.append((opt.name, formatted))
        else:
            params.append((opt.name, formatted))
        if opt.typed_equivalent and opt.typed_equivalent_note:
            notes.append(_info(
                key,
                f"{opt.label} cannot be typed into {spec.display_name}'s "
                f"search bar — the link carries it. {opt.typed_equivalent_note}",
            ))
        elif opt.channel == "url":
            notes.append(_info(
                key,
                f"{opt.label} cannot be typed into {spec.display_name}'s "
                "search bar — the link carries it.",
            ))

    return f"{template.base}?{urlencode(params)}", notes


def compose(request: QueryRequest, spec: SearchSurfaceSpec) -> QueryResult:
    """Compose the bar text and/or URL for one surface. Never raises on
    content; anything the surface cannot express becomes a note."""
    notes: list[QueryNote] = []
    ops = _offered_operators(spec)
    offered_options = _offered_url_options(spec)

    bar: str | None = None
    hard_stop = False
    if ops:
        bar, bar_notes, hard_stop = _compose_bar(request, spec, ops)
        notes.extend(bar_notes)
    elif any(
        (
            request.phrases,
            request.any_of,
            request.required,
            request.exclude,
            request.in_title,
            request.site,
        )
    ):
        notes.append(_info(
            "bar",
            f"{spec.display_name} has no typed search form AA can write for "
            "you — the link below is the way to use it.",
        ))

    url: str | None = None
    if not hard_stop and spec.urls:
        url, url_notes = _compose_url(request, spec, bar, ops, offered_options)
        notes.extend(url_notes)

    if bar is None and url is None and not notes:
        notes.append(_info("empty", "Nothing to build yet — add at least one term."))

    return QueryResult(
        surface=spec.name,
        display_name=spec.display_name,
        bar_text=bar,
        url=url,
        notes=tuple(notes),
    )


def build_automation_url(
    spec: SearchSurfaceSpec,
    *,
    query: str,
    location: str = "",
    date_range: str | None = None,
) -> str:
    """The URL AA's automated discovery sends.

    Byte-compatible with the pre-catalog engine strategies — pinned by
    tests/adapters/test_engine_url_byte_identity.py. Automation parameters
    come from the catalog's codes regardless of user-facing offer status:
    these are the parameters AA already sends in production. An unknown
    date_range is omitted (the pre-catalog behaviour), never invented.
    """
    if spec.automation_url is None:
        raise ValueError(f"{spec.name} has no automation URL template")
    template = spec.urls[spec.automation_url]
    params = _template_params(template, query, location)
    if date_range is not None and template.date_parameter is not None:
        option = next(
            (
                o
                for o in spec.url_options
                if o.name == template.date_parameter and o.option == "date"
            ),
            None,
        )
        if option is not None:
            code = option.codes.get(date_range)
            if code is not None:
                params.append((option.name, _format_option_value(option, code)))
    return f"{template.base}?{urlencode(params)}"

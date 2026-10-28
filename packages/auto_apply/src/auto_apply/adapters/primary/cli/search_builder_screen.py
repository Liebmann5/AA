"""The query-builder screen for the CLI (--search and the --search-* flags).

Composition stays in main.py; every print and every input lives here, so
main.py's pinned print-site count does not move (the consent-screen
precedent). The screen is offline by construction: the only outward call is
webbrowser.open, and only on an explicit user action.

Remembering is deliberate: a preview or a build writes nothing to the
device. Copy, open and keep are the only actions that remember a query, and
a platform or company query is remembered resolved — its site: restriction
folded in — so it replays identically as an engine query.
"""

from __future__ import annotations

import webbrowser

from auto_apply.application.services.i18n import get_text
from auto_apply.domain.models.search_query import (
    build_request,
    describe_request,
    format_result_lines,
    platform_display_text,
    resolve_and_remember,
)
from auto_apply.infrastructure.composition_root import build_query_builder

__all__ = ["run_search"]


class _Quit(Exception):
    """The person asked to stop."""


def _ask(prompt: str) -> str:
    """input() that treats EOF and Ctrl-C as "quit" — never an answer."""
    text = prompt.rstrip()
    if not text.endswith(":"):
        text += ":"
    try:
        return input(text + " ").strip()
    except (EOFError, KeyboardInterrupt):
        print()  # noqa: T201 — newline after ^C/^D
        raise _Quit from None


def _parse_options(raw: list[str] | None) -> tuple[tuple[str, str], ...]:
    """--search-option KEY=VALUE, repeatable; a malformed one is noted and
    skipped, never silently dropped."""
    options: list[tuple[str, str]] = []
    for item in raw or []:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            print(f"  {get_text('builder.bad_option')} {item}")  # noqa: T201
            continue
        options.append((key.strip(), value.strip()))
    return tuple(options)


def _render(result) -> None:
    """Print the result: labels and notes through the locale, with English
    sentences as fallbacks."""
    for line in format_result_lines(result, translate=get_text):
        print(line)  # noqa: T201


def _build(service, request, platform, company_url):
    """Build for the chosen target; returns None after printing the error."""
    try:
        if platform:
            return service.build_platform_query(platform, request)
        if company_url:
            return service.build_company_query(company_url, request)
        return service.build_query(request)
    except Exception as exc:  # noqa: BLE001 — the builder's message is the user-facing contract
        print(f"  {get_text('builder.error')}: {exc}")  # noqa: T201
        return None


def _remember(service, request, platform, company_url) -> None:
    """Remember via the shared resolve-then-remember step, so a query kept
    here replays identically to one kept from the GUI."""
    resolve_and_remember(
        service, request, platform=platform, company_url=company_url
    )


def _scripted(args, service) -> int:
    request = build_request(
        surface=args.search_surface or "google",
        terms=args.search_terms or "",
        any_of=args.search_any_of or "",
        exclude=args.search_exclude or "",
        in_title=args.search_in_title or "",
        location=args.search_location or "",
        options=_parse_options(args.search_option),
    )
    result = _build(service, request, args.search_platform, args.search_company)
    if result is None:
        return 2
    _render(result)
    if result.bar_text is None and result.url is None:
        return 1
    if args.search_keep or args.search_open:
        _remember(service, request, args.search_platform, args.search_company)
        print(f"  {get_text('builder.kept')}")  # noqa: T201
    if args.search_open:
        if result.url:
            webbrowser.open(result.url)
            print(f"  {get_text('builder.opened')}")  # noqa: T201
        else:
            print(f"  {get_text('builder.no_link')}")  # noqa: T201
    return 0


def _choose_named(prompt: str, names: list[str], display) -> str | None:
    """A picker that accepts a number or the name itself; q or Enter quits."""
    while True:
        print(f"  {prompt}")  # noqa: T201
        for index, name in enumerate(names, 1):
            print(f"    {index}) {display(name)}")  # noqa: T201
        raw = _ask(f"  {get_text('builder.choose')}")
        if raw.lower() in ("", "q", "quit"):
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(names):
            return names[int(raw) - 1]
        if raw in names:
            return raw
        print(f"  {get_text('builder.not_on_list')} {raw}")  # noqa: T201


def _choose_surface(service) -> str | None:
    offers = service.query_surfaces()
    names = [o.name for o in offers]
    display = {o.name: o.display_name for o in offers}
    return _choose_named(
        get_text("builder.surface_prompt"), names, lambda n: display[n]
    )


def _choose_target() -> str | None:
    options = (
        get_text("builder.target_surface"),
        get_text("builder.target_platform"),
        get_text("builder.target_company"),
    )
    while True:
        print(f"  {get_text('builder.target_prompt')}")  # noqa: T201
        for index, label in enumerate(options, 1):
            print(f"    {index}) {label}")  # noqa: T201
        raw = _ask(f"  {get_text('builder.choose')}")
        if raw.lower() in ("", "q", "quit"):
            return None
        if raw.isdigit() and 1 <= int(raw) <= 3:
            return ("surface", "platform", "company")[int(raw) - 1]
        print(f"  {get_text('builder.not_on_list')} {raw}")  # noqa: T201


def _choose_platform(service) -> str | None:
    offers = service.query_platforms()
    names = [o.name for o in offers]
    display = {o.name: platform_display_text(o) for o in offers}
    return _choose_named(
        get_text("builder.platform_prompt"), names, lambda n: display[n]
    )


def _collect_inputs(service, surface: str):
    defaults = service.query_defaults()
    terms_default = ", ".join(defaults.titles)
    if terms_default:
        print(f"  {get_text('builder.saved_note')} {terms_default}")  # noqa: T201
    terms = _ask(
        f"  {get_text('builder.terms_prompt')}"
        + (f" [{terms_default}]" if terms_default else "")
    )
    if not terms:
        terms = terms_default
    location_default = defaults.locations[0] if defaults.locations else ""
    location = _ask(
        f"  {get_text('builder.location_prompt')}"
        + (f" [{location_default}]" if location_default else "")
    )
    if not location:
        location = location_default
    any_of = _ask(f"  {get_text('builder.any_of_prompt')}")
    exclude = _ask(f"  {get_text('builder.exclude_prompt')}")
    in_title = _ask(f"  {get_text('builder.in_title_prompt')}")
    return build_request(
        surface=surface,
        terms=terms,
        any_of=any_of,
        exclude=exclude,
        in_title=in_title,
        location=location,
    )


def _actions(service, request, result, platform, company_url) -> str:
    """The post-preview loop. Returns "rebuild" or "quit"."""
    has_output = result.bar_text is not None or result.url is not None
    while True:
        print(f"  {get_text('builder.actions_line')}")  # noqa: T201
        choice = _ask(f"  {get_text('builder.choose')}").lower()
        if choice in ("", "q"):
            return "quit"
        if choice == "r":
            return "rebuild"
        if choice in ("c", "o", "k") and not has_output:
            print(f"  {get_text('builder.nothing_built')}")  # noqa: T201
            continue
        if choice == "c":
            if result.bar_text:
                print(f"  {result.bar_text}")  # noqa: T201
            if result.url:
                print(f"  {result.url}")  # noqa: T201
            _remember(service, request, platform, company_url)
            print(f"  {get_text('builder.kept')}")  # noqa: T201
        elif choice == "o":
            if not result.url:
                print(f"  {get_text('builder.no_link')}")  # noqa: T201
                continue
            webbrowser.open(result.url)
            _remember(service, request, platform, company_url)
            print(f"  {get_text('builder.opened')}")  # noqa: T201
        elif choice == "k":
            _remember(service, request, platform, company_url)
            print(f"  {get_text('builder.kept')}")  # noqa: T201
        else:
            print(f"  {get_text('builder.not_on_list')} {choice}")  # noqa: T201


def _interactive(service) -> int:
    print()  # noqa: T201
    print(f"  {get_text('builder.title')}")  # noqa: T201
    while True:
        surface = _choose_surface(service)
        if surface is None:
            return 0
        target = _choose_target()
        if target is None:
            return 0
        platform = company_url = None
        if target == "platform":
            platform = _choose_platform(service)
            if platform is None:
                return 0
        elif target == "company":
            company_url = _ask(f"  {get_text('builder.company_prompt')}")
            if not company_url:
                return 0
        while True:
            request = _collect_inputs(service, surface)
            result = _build(service, request, platform, company_url)
            if result is None:
                break
            _render(result)
            if _actions(service, request, result, platform, company_url) == "quit":
                return 0


def _recent(service) -> int:
    recent = service.recent_queries()
    if not recent:
        print(get_text("builder.recent_empty"))  # noqa: T201
        return 0
    print(get_text("builder.recent_title"))  # noqa: T201
    for request in recent:
        print(f"  {describe_request(request)}")  # noqa: T201
    return 0


def run_search(args, *, profile=None, builder=None) -> int:
    """Run the search builder. Returns the exit code.

    Args:
        args: the parsed CLI arguments (the --search-* flags).
        profile: the profile one-click defaults are read from (read-only).
        builder: a query-builder service; built pre-session when omitted.
    """
    service = builder if builder is not None else build_query_builder(profile)
    try:
        if args.search_clear_recent:
            service.clear_recent_queries()
            print(get_text("builder.recent_cleared"))  # noqa: T201
            return 0
        if args.search_recent:
            return _recent(service)
        scripted = any(
            (
                args.search_surface,
                args.search_platform,
                args.search_company,
                args.search_terms,
                args.search_any_of,
                args.search_exclude,
                args.search_in_title,
                args.search_location,
                args.search_option,
                args.search_open,
                args.search_keep,
            )
        )
        if scripted:
            return _scripted(args, service)
        return _interactive(service)
    except _Quit:
        return 0

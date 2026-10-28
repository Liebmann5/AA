"""Pins for the query builder's CLI screen and the shared domain helpers.

Label honesty per pin:
  TEETH — fail against the pre-change tree by construction: the screen, the
  helpers, the port methods and the service methods did not exist there.
  GUARD — hold behaviour this change must not break (the locale bundles'
  structure, the main-parser registration pattern, the screen's offline and
  GUI-free rules).
I have not executed these; each names the mutation it catches.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from auto_apply.adapters.primary.cli import search_builder_screen as screen
from auto_apply.adapters.secondary.discovery.ats_registry import ATSRegistry
from auto_apply.adapters.secondary.discovery.search_surface_registry import (
    list_surface_names,
    load_surface,
)
from auto_apply.application.agent.context import SessionStatistics
from auto_apply.application.services.i18n import get_text
from auto_apply.application.services.query_builder import QueryBuilderService
from auto_apply.application.services.session_controller import SessionController
from auto_apply.domain.exceptions import QueryBuilderError
from auto_apply.domain.models.search_query import (
    BuilderDefaults,
    PlatformOffer,
    QueryNote,
    QueryResult,
    build_request,
    describe_request,
    format_result_lines,
    platform_display_text,
    resolved_remember_request,
)
from auto_apply.domain.models.session_plan import SessionPlan

_PKG_ROOT = Path(__file__).resolve().parents[2]
_LOCALES = _PKG_ROOT / "src" / "auto_apply" / "resources" / "locales"


def _service(tmp_path: Path) -> QueryBuilderService:
    """A real service over a tmp recent file — real catalog, real registry."""
    return QueryBuilderService(
        profile=None,
        load_spec=load_surface,
        list_names=list_surface_names,
        ats_registry=ATSRegistry(),
        recent_path=tmp_path / "query_builder_recent.json",
    )


def _args(**over):
    base = dict(
        search=False,
        search_surface=None,
        search_platform=None,
        search_company=None,
        search_terms=None,
        search_any_of=None,
        search_exclude=None,
        search_in_title=None,
        search_location=None,
        search_option=None,
        search_open=False,
        search_keep=False,
        search_recent=False,
        search_clear_recent=False,
    )
    base.update(over)
    return SimpleNamespace(**base)


class _Script:
    """Scripted stdin; exhaustion is EOF, which the screen reads as quit."""

    def __init__(self, answers: list[str]) -> None:
        self._answers = iter(answers)

    def __call__(self, prompt: str = "") -> str:
        try:
            return next(self._answers)
        except StopIteration:
            raise EOFError from None


def _controller(builder) -> SessionController:
    plan = SessionPlan(session_id="qb-pin")
    registry = MagicMock()
    registry.get_session_plan.return_value = plan
    registry.get_active_profile.return_value = MagicMock()
    db = MagicMock()
    db.get_queue_stats.return_value = {
        "pending": 0, "in_progress": 0, "completed": 0,
        "failed": 0, "skipped": 0, "permanently_failed": 0,
    }
    orchestrator = MagicMock()
    orchestrator.session_plan = plan
    orchestrator.context = MagicMock()
    orchestrator.context.session_id = "qb-pin"
    orchestrator.context.stats = SessionStatistics()
    orchestrator.state_machine = MagicMock()
    orchestrator.task_queue = db
    return SessionController(
        registry=registry, db=db, orchestrator=orchestrator, query_builder=builder
    )


# ── Domain helpers ───────────────────────────────────────────────────────────

def test_build_request_maps_terms_to_phrases__teeth() -> None:
    """TEETH: comma-separated search words — typed, or one-click saved
    titles — map to phrases. Mutation caught: terms landing in `required`
    or `any_of`, or whitespace surviving."""
    request = build_request(surface="google", terms="Software Engineer, QA Lead")
    assert request.phrases == ("Software Engineer", "QA Lead")
    assert request.required == ()
    assert request.any_of == ()
    assert build_request(surface="google", terms="  ").phrases == ()


def test_build_request_shapes_the_rest_and_never_produces_required__teeth() -> None:
    """TEETH: the surfaces never produce `required` — the field stays in the
    model for the automated path. Mutation caught: a term string writing
    anywhere but its own field."""
    request = build_request(
        surface="bing",
        terms="x",
        any_of="a, b",
        exclude="c",
        in_title="d",
        location="Remote",
        site="example.com",
        options=(("date", "day"),),
    )
    assert request.required == ()
    assert request.any_of == ("a", "b")
    assert request.exclude == ("c",)
    assert request.in_title == ("d",)
    assert request.location == "Remote"
    assert request.site == "example.com"
    assert request.options == (("date", "day"),)


def test_describe_request_renders_terms_site_and_options__teeth() -> None:
    """TEETH: the recent list's one line. Mutation caught: a renderer that
    drops the site or the options."""
    request = build_request(
        surface="bing", terms="x", site="example.com", options=(("date", "day"),)
    )
    line = describe_request(request)
    assert line.startswith("bing: ")
    assert "x" in line and "site:example.com" in line and "date=day" in line


def test_platform_display_text_badge_rules__teeth() -> None:
    """TEETH: name only when no badge; name plus label when one exists.
    Mutation caught: badges on everything, or none ever."""
    bare = PlatformOffer(name="jobvite", status="measured", label="")
    assert platform_display_text(bare) == "jobvite"
    badged = PlatformOffer(name="workday", status="unverified", label="Unverified: x")
    shown = platform_display_text(badged)
    assert shown.startswith("workday") and "Unverified" in shown and shown != "workday"


def test_format_result_lines_injects_translator__teeth() -> None:
    """TEETH: the renderer's labels come from the injected translator, so
    the domain helper stays pure. Mutation caught: a hardcoded label."""
    result = QueryResult(
        surface="google", display_name="Google",
        bar_text='("x")', url="https://www.google.com/search?q=x", notes=(),
    )
    lines = format_result_lines(result, translate=lambda key: f"T:{key}")
    assert lines[0].startswith("T:builder.result.bar:")
    assert lines[1].startswith("T:builder.result.link:")
    default_lines = format_result_lines(result)
    assert default_lines[0].startswith("builder.result.bar:")


def test_format_result_lines_renders_refusal_notes_when_nothing_built__teeth() -> None:
    """TEETH (never a blank result): no bar, no link — the refusal notes
    still render. Mutation caught: notes dropped when both outputs are None."""
    result = QueryResult(
        surface="indeed", display_name="Indeed", bar_text=None, url=None,
        notes=(QueryNote(severity="refused", topic="site", message="no site limit exists"),),
    )
    lines = format_result_lines(result, translate=get_text)
    assert lines == ["  no site limit exists"]


def test_resolved_remember_request_folds_site_only__teeth() -> None:
    """TEETH (remembered platform/company queries are stored resolved).
    Mutation caught: folding anything but `site`, or folding an empty
    restriction."""
    request = build_request(surface="google", terms="x")
    folded = resolved_remember_request(request, "jobs.lever.co")
    assert folded.site == "jobs.lever.co"
    assert folded.phrases == request.phrases
    assert resolved_remember_request(request, "") is request
    assert resolved_remember_request(request, None) is request


# ── Service ──────────────────────────────────────────────────────────────────

def test_platform_offers_labels_unverified_only__teeth(tmp_path) -> None:
    """TEETH: unverified platforms carry the shared label; measured and
    vendor-verified carry none. Mutation caught: badges inverted or absent.
    Label text is compared against the locale lookup, not hardcoded."""
    offers = {o.name: o for o in _service(tmp_path).platform_offers()}
    assert offers["workday"].status == "unverified"
    assert offers["workday"].label == get_text("builder.platform.unverified")
    assert offers["workday"].label
    assert offers["jobvite"].status == "measured"
    assert offers["jobvite"].label == ""


def test_platform_offers_covers_the_registry__teeth(tmp_path) -> None:
    """TEETH: every registered platform with a host is offered — no second
    list. Mutation caught: a filtered or hardcoded subset."""
    names = {o.name for o in _service(tmp_path).platform_offers()}
    expected = {d.name for d in ATSRegistry().all_descriptors() if d.hosts}
    assert names == expected
    assert len(names) >= 30


def test_platform_restriction_for_platform_url_and_tenant__teeth(tmp_path) -> None:
    """TEETH: the one restriction resolver — platform, tenant URL, and
    platform+URL agree with the ATS data. Mutation caught: the slug ignored,
    or the shared path prefix dropped."""
    service = _service(tmp_path)
    assert service.platform_restriction_for("jobvite") == "jobs.jobvite.com"
    assert (
        service.platform_restriction_for(url="https://holisticai.bamboohr.com/careers/59")
        == "holisticai.bamboohr.com/careers"
    )
    assert (
        service.platform_restriction_for(
            "bamboohr", "https://holisticai.bamboohr.com/careers/59"
        )
        == "holisticai.bamboohr.com/careers"
    )


def test_platform_restriction_for_refuses_unknowns_loudly__teeth(tmp_path) -> None:
    """TEETH. Mutation caught: a quiet empty string where the answer should
    be a loud refusal."""
    service = _service(tmp_path)
    with pytest.raises(QueryBuilderError):
        service.platform_restriction_for("nonsense")
    with pytest.raises(QueryBuilderError):
        service.platform_restriction_for(url="https://example.org/jobs/1")
    with pytest.raises(QueryBuilderError):
        service.platform_restriction_for()


# ── Controller (the port's builder surface) ──────────────────────────────────

def test_controller_delegates_the_builder_methods__teeth() -> None:
    """TEETH: all nine port methods delegate to the injected service.
    Mutation caught: any one delegating to the wrong method or swallowing
    the result."""
    service = MagicMock()
    controller = _controller(service)
    request = build_request(surface="google", terms="x")

    assert controller.query_surfaces() is service.surfaces.return_value
    assert controller.query_platforms() is service.platform_offers.return_value
    assert controller.query_defaults() is service.defaults.return_value
    assert controller.build_query(request) is service.build.return_value
    assert (
        controller.build_platform_query("workday", request)
        is service.build_platform_search.return_value
    )
    assert (
        controller.build_company_query("https://x", request)
        is service.build_company_search.return_value
    )
    controller.remember_query(request)
    service.remember.assert_called_once_with(request)
    assert controller.recent_queries() is service.recent.return_value
    controller.clear_recent_queries()
    service.clear_recent.assert_called_once_with()


def test_controller_without_a_builder_defaults_and_raises__teeth() -> None:
    """TEETH (the no-builder ruling): queries degrade to empty answers; the
    three build calls raise a clear error. Mutation caught: a build that
    quietly returns a fake result."""
    controller = _controller(None)
    assert controller.query_surfaces() == ()
    assert controller.query_platforms() == ()
    assert controller.query_defaults() == BuilderDefaults()
    assert controller.recent_queries() == ()
    controller.clear_recent_queries()  # no-op, no raise
    request = build_request(surface="google", terms="x")
    with pytest.raises(QueryBuilderError):
        controller.build_query(request)
    with pytest.raises(QueryBuilderError):
        controller.build_platform_query("workday", request)
    with pytest.raises(QueryBuilderError):
        controller.build_company_query("https://x", request)


# ── Scripted CLI ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("jobvite", 'site:jobs.jobvite.com ("Software Engineer")'),
        ("bamboohr", 'site:bamboohr.com/careers ("Software Engineer")'),
        ("gusto", 'site:jobs.gusto.com/boards ("Software Engineer")'),
    ],
)
def test_three_queries_via_the_flag_path__teeth(tmp_path, capsys, platform, expected) -> None:
    """TEETH: the three known-good platform queries, through the CLI flags.
    Mutation caught: any one-character drift in the restriction or the
    composer's format."""
    code = screen.run_search(
        _args(search_platform=platform, search_terms="Software Engineer"),
        builder=_service(tmp_path),
    )
    assert code == 0
    out = capsys.readouterr().out
    assert expected in out
    assert "google.com/search" in out


def test_flag_refusal_renders_and_exits_nonzero__teeth(tmp_path, capsys) -> None:
    """TEETH: a restriction the surface cannot express is refused — rendered,
    non-zero, never a blank result. Mutation caught: exit 0, or silence."""
    code = screen.run_search(
        _args(search_surface="indeed", search_platform="workday", search_terms="x"),
        builder=_service(tmp_path),
    )
    out = capsys.readouterr().out
    assert code == 1
    assert out.strip(), "a refusal printed nothing — the user saw a blank result"

    code = screen.run_search(
        _args(search_platform="nonsense", search_terms="x"),
        builder=_service(tmp_path),
    )
    assert code == 2
    assert "nonsense" in capsys.readouterr().out


def test_open_calls_webbrowser_only_on_explicit_action__teeth(tmp_path) -> None:
    """TEETH: webbrowser.open fires only on --search-open. Mutation caught:
    opening on build or preview."""
    with patch.object(screen.webbrowser, "open") as mock_open:
        assert screen.run_search(
            _args(search_platform="jobvite", search_terms="x"),
            builder=_service(tmp_path),
        ) == 0
        mock_open.assert_not_called()

    with patch.object(screen.webbrowser, "open") as mock_open:
        assert screen.run_search(
            _args(search_platform="jobvite", search_terms="x", search_open=True),
            builder=_service(tmp_path),
        ) == 0
        mock_open.assert_called_once()
        assert "google.com/search" in mock_open.call_args.args[0]


def test_keep_remembers_resolved_and_replays_identically__teeth(tmp_path) -> None:
    """TEETH (copy/open/keep call remember — never build or preview; a
    remembered platform or company query replays identically). Mutation
    caught: remember on build, or a remembered query that builds to
    something else."""
    service = _service(tmp_path)
    assert screen.run_search(
        _args(search_platform="jobvite", search_terms="Software Engineer"),
        builder=service,
    ) == 0
    assert service.recent() == (), "a build with no action remembered something"

    assert screen.run_search(
        _args(search_platform="jobvite", search_terms="Software Engineer", search_keep=True),
        builder=service,
    ) == 0
    remembered = service.recent()
    assert len(remembered) == 1
    assert remembered[0].site == "jobs.jobvite.com"
    replayed = service.build(remembered[0])
    assert replayed.bar_text == 'site:jobs.jobvite.com ("Software Engineer")'

    assert screen.run_search(
        _args(
            search_company="https://holisticai.bamboohr.com/careers/59",
            search_terms="x",
            search_keep=True,
        ),
        builder=service,
    ) == 0
    remembered = service.recent()
    assert len(remembered) == 2
    company_entry = remembered[0]  # newest first
    assert company_entry.site == "holisticai.bamboohr.com/careers"
    assert service.build(company_entry).bar_text == 'site:holisticai.bamboohr.com/careers ("x")'


def test_recent_then_clear__teeth(tmp_path, capsys) -> None:
    """TEETH: --search-recent lists, --search-clear-recent forgets.
    Mutation caught: a list that writes, or a clear that leaves the file."""
    service = _service(tmp_path)
    screen.run_search(
        _args(search_platform="jobvite", search_terms="x", search_keep=True),
        builder=service,
    )
    capsys.readouterr()
    assert screen.run_search(_args(search_recent=True), builder=service) == 0
    out = capsys.readouterr().out
    assert "jobs.jobvite.com" in out
    assert screen.run_search(_args(search_clear_recent=True), builder=service) == 0
    assert service.recent() == ()


# ── Interactive CLI ──────────────────────────────────────────────────────────

def test_same_query_interactive_matches_the_flag_path__teeth(tmp_path, capsys, monkeypatch) -> None:
    """TEETH: the interactive screen builds the identical query from a
    scripted session. Mutation caught: the interactive path composing
    differently from the flag path."""
    monkeypatch.setattr("builtins.input", _Script([
        "google", "2", "jobvite", "Software Engineer", "", "", "", "", "q",
    ]))
    code = screen.run_search(_args(search=True), builder=_service(tmp_path))
    assert code == 0
    out = capsys.readouterr().out
    assert 'site:jobs.jobvite.com ("Software Engineer")' in out


def test_preview_never_remembers_and_copy_does__teeth(tmp_path, monkeypatch) -> None:
    """TEETH: preview and quit write nothing; copy remembers exactly once.
    Mutation caught: remember on preview, or copy forgetting."""
    service = _service(tmp_path)
    monkeypatch.setattr("builtins.input", _Script([
        "google", "1", "x", "", "", "", "", "q",
    ]))
    assert screen.run_search(_args(search=True), builder=service) == 0
    assert service.recent() == ()

    monkeypatch.setattr("builtins.input", _Script([
        "google", "1", "x", "", "", "", "", "c", "q",
    ]))
    assert screen.run_search(_args(search=True), builder=service) == 0
    remembered = service.recent()
    assert len(remembered) == 1
    assert remembered[0].phrases == ("x",)
    assert remembered[0].site is None


def test_interactive_quit_is_clean__teeth(tmp_path, monkeypatch) -> None:
    """TEETH: q at the first prompt exits 0 with nothing built and nothing
    remembered. Mutation caught: a quit that builds or writes."""
    service = _service(tmp_path)
    monkeypatch.setattr("builtins.input", _Script(["q"]))
    assert screen.run_search(_args(search=True), builder=service) == 0
    assert service.recent() == ()


# ── Static guarantees ────────────────────────────────────────────────────────

def test_screen_is_gui_free_and_offline__guard() -> None:
    """GUARD (rules: CLI is GUI-free and offline): no tkinter, no network
    library, no secondary-adapter import; webbrowser is the one allowed
    outward call. Mutation caught: any new import of those."""
    source = Path(screen.__file__).read_text(encoding="utf-8")
    banned = ("tkinter", "socket", "requests", "httpx", "selenium", "playwright", "urllib")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(banned), alias.name
                assert ".adapters.secondary" not in alias.name, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(banned), node.module
            assert ".adapters.secondary" not in node.module, node.module


def test_screen_carries_no_status_words__teeth() -> None:
    """TEETH (the surfaces carry no status words of their own): the
    verification vocabulary lives in the locale strings via the service,
    never in the screen. Mutation caught: a hardcoded badge in the screen."""
    source = Path(screen.__file__).read_text(encoding="utf-8").lower()
    for word in ("unverified", "third_party", "measured", "vendor"):
        assert word not in source, f"the CLI screen carries the status word {word!r}"


def test_builder_locale_key_sets_identical_en_es__guard() -> None:
    """GUARD (the locales rule): the en and es builder sections carry the
    same keys. Mutation caught: a key added to one locale only. (Whole-file
    equality is NOT asserted: es.json legitimately lags en.json elsewhere.)"""
    en = json.loads((_LOCALES / "en.json").read_text(encoding="utf-8"))
    es = json.loads((_LOCALES / "es.json").read_text(encoding="utf-8"))

    def _flat(section: dict) -> set[str]:
        out: set[str] = set()

        def walk(node: dict, prefix: str) -> None:
            for key, value in node.items():
                if isinstance(value, dict):
                    walk(value, f"{prefix}{key}.")
                else:
                    out.add(f"{prefix}{key}")

        walk(section, "")
        return out

    assert "builder" in en and "builder" in es
    assert _flat(en["builder"]) == _flat(es["builder"])


@pytest.mark.parametrize(
    "argv",
    [
        ["--search"],
        ["--search-recent"],
        ["--search-clear-recent"],
        ["--search-platform", "jobvite", "--search-terms", "x"],
        [
            "--search-surface", "google",
            "--search-company", "https://holisticai.bamboohr.com/careers/59",
            "--search-any-of", "a,b",
            "--search-exclude", "c",
            "--search-in-title", "d",
            "--search-location", "Remote",
            "--search-option", "date=day",
            "--search-open", "--search-keep",
        ],
    ],
)
def test_main_registers_and_dispatches_the_search_flags__teeth(monkeypatch, argv) -> None:
    """TEETH: every flag is registered (argparse exits 2 on an unregistered
    one) and any of them dispatches to the search handler before any session
    starts. Mutation caught: a flag added to the screen but never parsed, or
    a dispatch condition missing one."""
    import auto_apply.main as main_mod

    dispatched = {}

    def _fake_handle(args, repo):
        dispatched["args"] = args
        raise SystemExit(0)

    monkeypatch.setattr(main_mod, "setup_logging", lambda **kw: None)
    monkeypatch.setattr(main_mod, "build_session", lambda: MagicMock())
    monkeypatch.setattr(main_mod, "_handle_search", _fake_handle)
    monkeypatch.setattr("sys.argv", ["auto_apply", *argv])

    with pytest.raises(SystemExit) as exc:
        main_mod.main()
    assert exc.value.code == 0, (
        "the parse or dispatch did not complete — a flag is unregistered "
        "(argparse exits 2) or the dispatch condition missed it"
    )
    assert "args" in dispatched

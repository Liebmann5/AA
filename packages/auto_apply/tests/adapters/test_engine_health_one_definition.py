"""Pins: one engine health check, and a blocked engine is never retried another way.

Owner run, 2026-11-03 11:11 (log lines 266-276): Indeed answered with a
CAPTCHA, AA logged "no further requests will be sent to it", then opened
Indeed's home page to type the search in. Google's and Bing's health checks
were stubs that always answered "healthy" (``return True`` since 2c27af7);
only Indeed's asked the page verdict. Three definitions of one predicate.

Pins marked ``_teeth`` fail on the code before this change (``945d416``).
"""

from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace

from auto_apply.adapters.secondary.discovery.providers.base_provider import (
    BaseSearchProvider,
)
from auto_apply.adapters.secondary.discovery.strategies import navigators as nav
from auto_apply.adapters.secondary.discovery.strategies.navigators import (
    ResilientNavigator,
)
from auto_apply.domain.services import apply_target

_PROVIDERS = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src/auto_apply/adapters/secondary/discovery/providers"
)

_CAPTCHA = (
    "<html><head><title>Just a moment...</title></head><body>"
    "<div class='g-recaptcha' data-sitekey='x'></div>"
    "<script src='https://www.google.com/recaptcha/api.js'></script>"
    "</body></html>"
)


def test_no_provider_defines_its_own_health_check_teeth() -> None:
    """Single definition: only BaseSearchProvider defines _is_page_healthy."""
    owners = []
    for path in sorted(_PROVIDERS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_is_page_healthy":
                owners.append(path.name)
    assert owners == ["base_provider.py"], owners


class _Strategy:
    def __init__(self, name: str, log: list) -> None:
        self._name, self._log = name, log
        self.last_landing = None

    @property
    def name(self) -> str:
        return self._name

    def navigate(self, engine, instruction) -> bool:
        self._log.append(self._name)
        return True


class _Browser:
    current_url = "https://www.indeed.com/jobs?q=x"

    def get(self, url):
        self.current_url = url


def test_a_benched_engine_is_not_retried_through_another_route_teeth(monkeypatch) -> None:
    monkeypatch.setattr(nav.time, "sleep", lambda s: None)
    tried: list[str] = []
    navigator = ResilientNavigator(
        _Browser(), [_Strategy("DirectURL", tried), _Strategy("HumanSearch", tried)]
    )
    benched = {"now": False}

    def validator() -> bool:
        benched["now"] = True  # the health check benched the engine
        return False

    ok = navigator.navigate_with_fallback(
        SimpleNamespace(), SimpleNamespace(), validator, should_stop=lambda: benched["now"]
    )
    assert ok is False
    assert tried == ["DirectURL"]


def test_an_unblocked_failure_still_falls_back() -> None:
    """GUARD: a failure that did not bench the engine still tries the next
    route, as before (graceful degradation is kept, escalation is not)."""
    tried: list[str] = []
    navigator = ResilientNavigator(
        _Browser(), [_Strategy("DirectURL", tried), _Strategy("HumanSearch", tried)]
    )
    navigator.navigate_with_fallback(
        SimpleNamespace(), SimpleNamespace(), lambda: False, should_stop=lambda: False
    )
    assert tried == ["DirectURL", "HumanSearch"]


class _Detector:
    def __init__(self) -> None:
        self.benched: set[str] = set()

    def is_benched(self, name: str) -> bool:
        return name.lower() in self.benched

    def mark_blocked(self, name: str, reason: str) -> None:
        self.benched.add(name.lower())


class _GoogleLike(BaseSearchProvider):
    def run(self, instruction):  # pragma: no cover - not exercised
        return []


def _provider(html: str, url: str = "https://www.google.com/search?q=x") -> _GoogleLike:
    provider = _GoogleLike.__new__(_GoogleLike)
    provider.browser = SimpleNamespace(current_url=url, title="", page_source=html)
    provider._degradation_detector = _Detector()
    provider._research_observer = None
    return provider


def test_the_shared_check_benches_on_a_challenge_page_teeth() -> None:
    provider = _provider(_CAPTCHA)
    assert provider._is_page_healthy() is False
    assert provider._is_benched() is True


def test_the_shared_check_passes_an_ordinary_page() -> None:
    """GUARD"""
    provider = _provider("<html><body><p>results</p></body></html>")
    assert provider._is_page_healthy() is True
    assert provider._is_benched() is False


# ── A radio group is one question (Yahoo home page, owner capture) ─────────


def _form(inner: str) -> str:
    return f"<html><body><form>{inner}</form></body></html>"


def test_a_radio_group_counts_as_one_control_teeth() -> None:
    """A hidden 9-option feedback form made a search home page an
    "application form". Nine options of one question are one control."""
    nine = "".join(f"<input type='radio' name='reason' value='{i}'>" for i in range(9))
    assert apply_target.page_has_fillable_form(_form(nine)) is False


def test_three_questions_are_still_a_form() -> None:
    """GUARD: three radio questions (a screener step) remain a form."""
    three = "".join(
        f"<input type='radio' name='q{q}' value='y'><input type='radio' name='q{q}' value='n'>"
        for q in range(3)
    )
    assert apply_target.page_has_fillable_form(_form(three)) is True


def test_unnamed_options_are_each_counted() -> None:
    """GUARD: without a name there is no group to recognise; unchanged."""
    many = "".join("<input type='checkbox'>" for _ in range(3))
    assert apply_target.page_has_fillable_form(_form(many)) is True

"""Pins for URL page templates — pure logic, plus the engine YAML as data."""
from __future__ import annotations

from auto_apply.adapters.secondary.discovery.strategies.selector_loader import (
    SelectorLoader,
)
from auto_apply.domain.models.page_advance import UrlPageTemplate
from auto_apply.domain.services.url_templating import (
    next_page_url,
    template_value,
    url_template_from_config,
)

G = UrlPageTemplate(param="start", first=0, step=10)


def test_value_math_is_first_plus_step_times_page_minus_one():
    assert template_value(G, 1) == 0
    assert template_value(G, 2) == 10
    assert template_value(G, 5) == 40
    assert template_value(UrlPageTemplate(param="p", first=2, step=1), 3) == 4


def test_the_parameter_is_appended_to_a_bare_url():
    assert (
        next_page_url(G, "https://g.test/search", 2)
        == "https://g.test/search?start=10"
    )


def test_an_existing_page_parameter_is_replaced_not_duplicated():
    url = next_page_url(G, "https://g.test/s?q=jobs&start=0&hl=en", 3)
    assert url == "https://g.test/s?q=jobs&hl=en&start=20"


def test_existing_parameters_and_the_fragment_survive():
    url = next_page_url(G, "https://g.test/s?q=a+b&hl=en#frag", 2)
    assert url == "https://g.test/s?q=a+b&hl=en&start=10#frag"


def test_malformed_config_is_none_never_an_exception():
    for bad in (None, "x", {}, {"url_template": None},
                {"url_template": {"param": "start"}},
                {"url_template": {"param": "start", "first": 0, "step": 0}},
                {"url_template": {"param": "", "first": 0, "step": 1}},
                {"url_template": {"param": "p", "first": True, "step": 1}}):
        assert url_template_from_config(bad) is None
    assert url_template_from_config(
        {"url_template": {"param": "start", "first": 0, "step": 10}}
    ) == G


def test_the_bundled_google_yaml_carries_the_verified_template():
    """Google's start= is the one parameter the codebase already proves real."""
    config = SelectorLoader().load("google")
    template = url_template_from_config(config.get("pagination"))
    assert template == G


def test_bing_and_indeed_ship_no_invented_parameter():
    """Unverified vendor params are vendor fiction; structural rungs instead."""
    loader = SelectorLoader()
    for engine in ("bing", "indeed"):
        config = loader.load(engine)
        assert config, f"{engine}.yaml missing or unreadable"
        assert url_template_from_config(config.get("pagination")) is None


def test_a_user_override_can_add_a_template_without_a_release(tmp_path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "bing.yaml").write_text("engine: bing\n", encoding="utf-8")
    user = tmp_path / "user"
    user.mkdir()
    (user / "bing.yaml").write_text(
        "pagination:\n  url_template:\n    param: first\n    first: 1\n    step: 10\n",
        encoding="utf-8",
    )
    config = SelectorLoader(bundled_dir=bundled, user_override_dir=user).load("bing")
    assert url_template_from_config(config.get("pagination")) == UrlPageTemplate(
        param="first", first=1, step=10
    )

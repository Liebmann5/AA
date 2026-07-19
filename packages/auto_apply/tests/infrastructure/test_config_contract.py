"""Every setting the user can change must reach the code that would honour it.

The audit
---------
Same shape as the ``getattr`` sweep, one layer up. ``dict.get(key, default)``
cannot fail either: if ``key`` is absent, the default fires silently, forever.

93 config ``.get()`` sites in ``src/`` were checked against the real key
universe — ``runtime_defaults.yaml``'s 25 flat keys, its 5 nested sections, and
``ApplicationConfig``'s 8 fields (merged in via ``app_config.__dict__`` at
registry.py:348, because ``hasattr(user_profile, "settings")`` is always False —
``UserProfile`` has no ``settings`` field).

Browser provider reads were excluded: ``selenium_provider`` and
``playwright_provider`` read the *provider* dict built by
``browser_cascade._build_provider_config()``, not the effective config. Those
are correct.

What is left is not a scattering of typos. It is one contract, broken in three
places at once.

1. The GUI settings the user edits are merged and never read
------------------------------------------------------------
``ApplicationConfig`` has 8 fields. The settings editor writes them. The registry
merges them into the effective config. **Seven of the eight have no config
reader at all.** Only ``enable_behavior_humanization`` (registry.py:582) is read
back.

``use_proxies`` is referenced nowhere outside ``profile.py`` — not even the GUI.
Combined with the missing ``proxy_server`` field (see
``test_getattr_contracts.py``), the entire proxy feature is a checkbox wired to
nothing.

2. The same concept has two names on either side of the merge
--------------------------------------------------------------
The profile and the YAML each name the same settings differently, and the merge
puts both in the same flat dict without reconciling them::

    profile: run_headless        vs  YAML: headless_mode
    profile: preferred_browser   vs  YAML: preferred_browser_order

``RuntimeProfile`` reads ``headless_mode``. A user who toggles "run headless" in
the settings editor writes ``run_headless``, which lands in the effective config
and is read by nobody. The GUI control appears to work and changes nothing.

3. SessionPlan.from_config reads 15 keys; every one misses
----------------------------------------------------------
Not a subset — all of them::

    disc.get("max_results_per_query")        discovery has: max_pages_per_query,
    disc.get("max_queries_per_session")        max_concurrent_sources,
    disc.get("enable_company_page_mining")     between_provider_pause_{min,max}
    disc.get("use_ats_site_search")
    disc.get("date_range")
    disc.get("providers")
    apps.get("max_applications_per_session")  applications has: max_pages,
    apps.get("max_applications_per_company")    typing_wpm, thinking_pause_*, ...
    apps.get("list_only_mode")
    apps.get("enable_cover_letter_generation")
    browser.get("headless")                   browser has: mouse_* only
    browser.get("stealth_mode")
    config.get("research")                    section does not exist
    config.get("session")                     section does not exist
    config.get("linear_mode_platforms")       key does not exist

``timing.py`` has the same disease: ``browser.get("page_load_timeout_seconds")``
misses, while ``page_load_timeout_seconds`` sits in the YAML as a *flat* key.
``session_cfg.get("random_seed")`` reads a section that does not exist, which is
why ``--seed`` only works through the ``AA_RANDOM_SEED`` environment variable.

The shape of the fix
--------------------
Fifteen individually-wired fields would just re-create this. The defect is that
three writers (YAML, profile, admin policy) and many readers agree on a *flat
dict* and disagree about every key inside it, with ``.get(k, default)`` at every
boundary guaranteeing nobody ever finds out.

What is missing is a typed effective-settings object with one name per concept
that runtime code must read from, so a rename fails at import instead of
silently returning a default three years later.
"""

from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "auto_apply"


def _universe() -> tuple[set[str], dict[str, set[str]]]:
    from auto_apply.domain.models.profile import ApplicationConfig  # noqa: PLC0415

    y = list(SRC.rglob("runtime_defaults.yaml"))
    assert y, "runtime_defaults.yaml not found"
    d = yaml.safe_load(y[0].read_text(encoding="utf-8"))
    flat = {k for k, v in d.items() if not isinstance(v, dict)}
    sections = {k: set(v) for k, v in d.items() if isinstance(v, dict)}
    # registry.py:348 merges the profile's app_config in via __dict__
    return flat | set(sections) | set(ApplicationConfig.model_fields), sections


def test_profile_settings_reach_a_config_reader() -> None:
    """The settings editor writes these. Something must read them back."""
    import re  # noqa: PLC0415

    from auto_apply.domain.models.profile import ApplicationConfig  # noqa: PLC0415

    unread: list[str] = []
    for field in sorted(ApplicationConfig.model_fields):
        found = any(
            re.search(rf"""\.get\(\s*["']{field}["']""", py.read_text(encoding="utf-8", errors="replace"))
            for py in SRC.rglob("*.py")
        )
        if not found:
            unread.append(field)

    assert not unread, (
        f"ApplicationConfig fields are merged into the effective config "
        f"(registry.py:348) and never read back out: {unread}. The settings "
        f"editor writes them, the registry merges them, and no runtime consumer "
        f"looks them up. Every one of those GUI controls appears to work and "
        f"changes nothing."
    )


def test_no_duplicate_names_for_one_concept_across_the_merge() -> None:
    """One concept, one canonical name — reconciled, not two dead-writing aliases.

    Structural replacement for the original diagnostic (which only asserted the two
    known collisions were absent). This asserts the *fix* is in place:

      * headless is one canonical name (``headless_mode``); the old ``run_headless``
        profile field is gone, folded into it via a back-compat validation alias.
      * the browser pick (``preferred_browser``) is a declarative INPUT that
        ``_merge_config`` RESOLVES into the front of ``preferred_browser_order``
        (the resolved state the cascade reads) — input -> resolution -> resolved.

    Teeth (must FAIL against pre-6d code): before 6d, ``run_headless`` is still a
    field, and ``_merge_config`` has no browser resolution so the pick never reaches
    the order — both assertions fail.
    """
    from auto_apply.domain.models.profile import ApplicationConfig  # noqa: PLC0415
    from auto_apply.infrastructure.registry import CapabilitiesRegistry  # noqa: PLC0415

    fields = set(ApplicationConfig.model_fields)
    assert "run_headless" not in fields, (
        "run_headless still exists as a profile field alongside the canonical "
        "headless_mode — two names for one concept. RuntimeProfile reads "
        "headless_mode, so the run_headless GUI toggle is a dead-write."
    )
    assert "headless_mode" in fields, (
        "the canonical headless_mode field is missing from ApplicationConfig."
    )

    merged = CapabilitiesRegistry._merge_config(
        runtime_defaults={
            "headless_mode": False,
            "preferred_browser_order": ["chrome", "firefox", "edge"],
        },
        user_settings={"preferred_browser": "firefox"},
        admin_policy=None,
        is_low_resource=False,
    )
    order = merged.get("preferred_browser_order", [])
    assert order and order[0] == "firefox", (
        "preferred_browser (the user's pick) is not folded to the front of "
        f"preferred_browser_order (got {order!r}). The browser choice is a "
        "dead-write: written to the profile, merged, and read by nobody."
    )


def test_session_plan_sources_config_from_typed_effective_config() -> None:
    """SessionPlan.from_config must source config values from the typed
    EffectiveConfig, not raw dict.get().

    Structural successor to the two diagnostic pins that hardcoded a mirror of
    from_config's broken nested reads (this one and, in the sibling file,
    test_yaml_provides_every_section_from_config_reads). Those could only check
    a fixed list of keys and described reads that no longer exist. This holds for
    the whole method at once: every config value flows through a field that
    provably exists, so a renamed or dropped key fails here instead of silently
    defaulting. Verified to fail against the pre-migration from_config.
    """
    import ast  # noqa: PLC0415
    import inspect  # noqa: PLC0415
    import textwrap  # noqa: PLC0415

    from auto_apply.domain.models.effective_config import EffectiveConfig  # noqa: PLC0415
    from auto_apply.domain.models.session_plan import SessionPlan  # noqa: PLC0415

    tree = ast.parse(textwrap.dedent(inspect.getsource(SessionPlan.from_config)))

    settings_reads = {
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "settings"
    }
    assert settings_reads, (
        "SessionPlan.from_config does not read from a typed EffectiveConfig; it "
        "still uses raw dict.get(), which silently defaults on a missing key."
    )

    unknown = sorted(settings_reads - set(EffectiveConfig.model_fields))
    assert not unknown, (
        f"from_config reads settings.{unknown}, which are not EffectiveConfig "
        f"fields — a renamed field would silently vanish."
    )

    # execution_mode is an admin grant injected under a 'session' section, not a
    # YAML knob, so those are the only raw dict reads permitted to remain.
    raw_get_keys = {
        n.args[0].value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "get"
        and n.args
        and isinstance(n.args[0], ast.Constant)
        and isinstance(n.args[0].value, str)
    }
    stray = sorted(raw_get_keys - {"session", "execution_mode"})
    assert not stray, (
        f"from_config still reads raw config keys {stray} instead of the typed "
        f"EffectiveConfig — each is a dict.get that can silently default."
    )


def test_behavior_parameters_sources_config_from_typed_effective_config() -> None:
    """BehaviorParameters.from_config must source timing values from the typed
    EffectiveConfig, not raw dict.get().

    Structural successor to the diagnostic pin that hardcoded from_config's
    browser.* reads (page_load_timeout_seconds lived at the YAML top level, not
    in the browser section, so the configured value was silently replaced by a
    hardcoded default). Every timing value now flows through a field that
    provably exists. random_seed is a session-level value (env var or an
    admin-injected 'session' section), the only raw config read permitted to
    remain. Verified to fail against the pre-migration from_config.
    """
    import ast  # noqa: PLC0415
    import inspect  # noqa: PLC0415
    import textwrap  # noqa: PLC0415

    from auto_apply.domain.models.effective_config import EffectiveConfig  # noqa: PLC0415
    from auto_apply.domain.models.timing import BehaviorParameters  # noqa: PLC0415

    tree = ast.parse(textwrap.dedent(inspect.getsource(BehaviorParameters.from_config)))

    settings_reads = {
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "settings"
    }
    assert settings_reads, (
        "BehaviorParameters.from_config does not read from a typed EffectiveConfig; "
        "it still uses raw dict.get(), which silently defaults on a missing key."
    )

    unknown = sorted(settings_reads - set(EffectiveConfig.model_fields))
    assert not unknown, (
        f"from_config reads settings.{unknown}, which are not EffectiveConfig "
        f"fields — a renamed field would silently vanish."
    )

    # random_seed comes from the env var or an admin-injected 'session' section,
    # not a YAML knob, so those are the only raw dict reads permitted to remain.
    raw_get_keys = {
        n.args[0].value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "get"
        and n.args
        and isinstance(n.args[0], ast.Constant)
        and isinstance(n.args[0].value, str)
    }
    stray = sorted(raw_get_keys - {"session", "random_seed", "AA_RANDOM_SEED"})
    assert not stray, (
        f"from_config still reads raw config keys {stray} instead of the typed "
        f"EffectiveConfig — each is a dict.get that can silently default."
    )

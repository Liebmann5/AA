"""getattr() with a default must not stand in for a contract.

The pattern
-----------
``getattr(obj, "some_field", fallback)`` cannot fail. If ``some_field`` does not
exist on ``obj``, Python returns ``fallback`` — silently, forever, on every run.
A plain ``obj.some_field`` would have raised ``AttributeError`` on the first
execution and been fixed the same day.

An audit of all 150 ``getattr(x, "literal", default)`` sites in ``src/`` found
five that read a field which does not exist on the target model. Most of the
other 145 are legitimate duck-typing over browser adapters or genuinely optional
attributes; these five are contracts that silently evaporated.

What each one costs
-------------------
``serp_strategy.py:147`` — ``JobSearchPreferences.max_search_results``
    ``MAX_TOTAL_JOBS`` is 30 on every machine regardless of config, admin policy
    or the low-resource clamp. Covered separately in
    ``test_low_resource_clamps.py``.

``browser_cascade.py:209`` — ``ApplicationConfig.proxy_server``
    The provider config's ``"proxy"`` key is always ``None``. ``ApplicationConfig``
    *does* have ``use_proxies`` — a user can switch proxies on, and there is no
    field to say which proxy, so the browser launches direct. A user who enables
    proxies and believes their traffic is routed is wrong, and nothing tells
    them. That is a privacy failure, not a feature gap.

``browser_cascade.py:212`` — ``ApplicationConfig.rotate_user_agent``
    Always ``False``. User-agent rotation never happens in production.

``browser_cascade.py:213`` — ``ApplicationConfig.user_agent``
    Always ``None``. A custom UA can never be set.

``rule_based_adapter.py:242`` — ``LegalInfo.has_security_clearance``
    ``LegalInfo`` has ``has_work_authorization``, ``requires_sponsorship`` and
    ``non_compete_agreements`` — no clearance field. So the reasoning adapter
    answers "do you hold a security clearance?" with ``False`` for every user,
    including users who hold one. The user cannot express the truth and AA
    answers anyway.

    Every answer must be attributable to the authorized user profile, an explicit
    user response, a deterministic policy, or a validated transformation of
    authorized data. ``False`` from a getattr fallback is none of those. It is a
    fabricated answer submitted on a real person's behalf, and it loses them
    cleared roles they qualify for.

Why the tests did not catch the UA one
--------------------------------------
``test_reproducibility.py`` exercises ``_get_user_agent`` against a hand-built
dict ``{"rotate_user_agent": True, ...}``. The function works. The tests pass.
But ``browser_cascade`` is the only thing that builds that dict in production,
and it always writes ``rotate_user_agent: False``. The unit under test is
correct and unreachable — a test proving a mechanism works while nothing feeds
it real input.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "auto_apply"


def _model_fields(name: str) -> set[str]:
    from auto_apply.domain.models import profile as profile_mod  # noqa: PLC0415

    model = getattr(profile_mod, name)
    return set(model.model_fields)


@pytest.mark.parametrize(
    ("site", "model", "attr", "cost"),
    [
        # Live getattr-into-config sites that must resolve to a real field. Entries
        # are removed as their getattr is eliminated or their field is added:
        #   * serp_strategy max_search_results  -> getattr deleted (cap now threaded
        #     via SearchInstruction.max_results); no longer a getattr site.
        #   * rotate_user_agent / user_agent    -> fields added to ApplicationConfig;
        #     the feature was already wired in selenium_provider._get_user_agent.
        (
            "infrastructure/browser_cascade.py:209",
            "ApplicationConfig",
            "proxy_server",
            "provider config 'proxy' is always None, so use_proxies=true launches direct",
        ),
    ],
)
def test_getattr_target_field_exists(site: str, model: str, attr: str, cost: str) -> None:
    assert attr in _model_fields(model), (
        f"{site} reads getattr(..., {attr!r}, <default>) but {model} has no such "
        f"field, so the default fires on every run. Cost: {cost}. Either add the "
        f"field to {model} or delete the read — do not leave a getattr default "
        f"standing in for a contract."
    )


def test_no_new_getattr_defaults_on_profile_models() -> None:
    """Enforcement against reintroduction.

    Walks every ``getattr(x, "literal", default)`` whose attribute name matches
    no field on any profile model and no known duck-typed interface. New dead
    reads fail here rather than surviving three more years.
    """
    from auto_apply.domain.models import profile as profile_mod  # noqa: PLC0415

    known: set[str] = set()
    for name in dir(profile_mod):
        obj = getattr(profile_mod, name)
        if hasattr(obj, "model_fields"):
            known |= set(obj.model_fields)

    # Targets whose type we can name with confidence from the call site.
    typed_targets = {
        "self.prefs", "prefs", "self._profile.legal_info", "app_config",
        "self.profile.legal_info",
    }

    offenders: list[str] = []
    for py in SRC.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if not (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "getattr"
                and len(n.args) == 3
                and isinstance(n.args[1], ast.Constant)
                and isinstance(n.args[1].value, str)
            ):
                continue
            try:
                target = ast.unparse(n.args[0])
            except Exception:  # noqa: BLE001
                continue
            if target not in typed_targets:
                continue
            attr = n.args[1].value
            if attr not in known:
                offenders.append(
                    f"{py.relative_to(SRC).as_posix()}:{n.lineno} "
                    f"getattr({target}, {attr!r}, ...)"
                )

    assert not offenders, (
        "getattr() reads a field that exists on no profile model. The default will "
        f"fire on every run and nothing will ever raise: {offenders}"
    )

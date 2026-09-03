"""Pins for the Q3 port-contract clusters (Stage S-6b).

  * find_best_match is declared on TextSimilarityPort and TextMatcher satisfies it.
  * The raw-driver capability probe is getattr, never isinstance — the probe
    pin's docstring records why (inspect.getattr_static does not invoke
    __getattr__ on Python 3.12+).
  * RegistryPort declares the enforcement surface PolicyEnforcement needs.
  * PolicyEnforcement never touches the registry's private _effective_config.
  * apply_config_override round-trips through get_effective_config.
  * raw_driver_port.py remains as a documentation/type marker only.
"""

import pathlib
from unittest.mock import MagicMock

from auto_apply.application.services.text_matching import TextMatcher
from auto_apply.domain.ports.registry_port import RegistryPort
from auto_apply.domain.ports.text_similarity_port import TextSimilarityPort
from auto_apply.infrastructure.registry import CapabilitiesRegistry


def test_text_similarity_port_declares_find_best_match() -> None:
    assert hasattr(TextSimilarityPort, "find_best_match")


def test_text_matcher_satisfies_the_widened_port() -> None:
    matcher = TextMatcher()
    assert isinstance(matcher, TextSimilarityPort)


def test_raw_driver_probe_is_getattr_not_isinstance() -> None:
    """The runtime capability probe must be getattr, never isinstance.

    Since Python 3.12, runtime_checkable protocol isinstance is evaluated
    with inspect.getattr_static, which does NOT invoke __getattr__.
    ResilientDriver only forwards get_raw_driver through __getattr__, so
    isinstance(resilient, SupportsRawDriver) returns False in production and
    silently disabled tab switching, CDP extraction, and console-log
    auditing — the regression this pin exists to keep out. A getattr probe
    goes through the forwarder and finds the method; for an adapter that
    genuinely lacks it, getattr returns None, the intended degradation.
    """
    from auto_apply.adapters.secondary.browser.selenium_adapter import SeleniumAdapter
    from auto_apply.infrastructure.resilient_driver import ResilientDriver

    resilient = ResilientDriver(SeleniumAdapter(MagicMock()))
    getter = getattr(resilient, "get_raw_driver", None)
    assert callable(getter), (
        "getattr must find get_raw_driver through ResilientDriver.__getattr__"
    )

    class _NoRaw:
        pass

    assert getattr(_NoRaw(), "get_raw_driver", None) is None, (
        "the probe must degrade to None when the method genuinely does not exist"
    )


def test_raw_driver_port_remains_as_documentation_marker() -> None:
    """raw_driver_port.py is kept for typing/documentation, not as a runtime check."""
    from auto_apply.domain.ports import raw_driver_port

    assert hasattr(raw_driver_port, "SupportsRawDriver")
    assert hasattr(raw_driver_port, "SupportsRawPage")


def test_registry_port_declares_enforcement_surface() -> None:
    for name in ("get_admin_policy", "get_environment_capabilities", "apply_config_override"):
        assert hasattr(RegistryPort, name), f"RegistryPort is missing {name}"


def test_policy_enforcement_never_touches_private_config() -> None:
    src = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src" / "auto_apply" / "adapters" / "secondary" / "security" / "policy_enforcement.py"
    ).read_text(encoding="utf-8")
    assert "registry._effective_config" not in src, (
        "PolicyEnforcement reads the registry's private config attribute"
    )
    assert "self._config" not in src, (
        "PolicyEnforcement still holds a direct reference to the private config dict"
    )


def test_apply_config_override_round_trips() -> None:
    registry = CapabilitiesRegistry.__new__(CapabilitiesRegistry)
    registry._effective_config = {}
    registry.apply_config_override("headless_mode", True)
    assert registry.get_effective_config("headless_mode") is True

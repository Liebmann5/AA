"""The lint gate — closing the used-but-never-defined bug class (Stage 6a).

Three times this arc a symbol was used and never imported: ``time`` in the DOM
observer, ``ApplicationError`` in the workflow, ``InteractionType`` in the
strategic pass. Each was harmless only because no test reached the line. Live
runs reach the lines.

A linter closes the whole class at once, and it found a fourth immediately —
one I shipped: ``composition_root`` used ``_extraction_observer`` at line 168
and defined it at 366. With a driver present that raised ``NameError`` into a
bare ``except``, so the Math perception adapter silently failed to build on
every real browser run since Stage 5a. 905 passing tests never saw it, because
every orchestrator test runs with ``driver=None``.

So two pins: the linter itself, and the driver-present build that would have
caught this one specifically.
"""
import pathlib
import subprocess
import sys

import pytest
from unittest.mock import MagicMock, patch

PACKAGE = pathlib.Path(__file__).resolve().parent.parent.parent
SRC = PACKAGE / "src"


def _run_ruff(*args) -> subprocess.CompletedProcess:
    """Invoke ruff, preferring the interpreter running the tests."""
    for command in ([sys.executable, "-m", "ruff"], ["ruff"]):
        try:
            return subprocess.run(
                [*command, *args],
                capture_output=True,
                text=True,
                cwd=str(PACKAGE),
                timeout=180,
            )
        except (FileNotFoundError, OSError):
            continue
    pytest.fail(
        "ruff is not available, so the lint gate cannot run. It is a declared "
        "dev dependency; install it with `pip install ruff`. This pin fails "
        "rather than skips on purpose — a check that silently does nothing is "
        "the exact failure mode it exists to prevent."
    )
    # pytest.fail is terminal at runtime. The raise below never executes; it
    # exists so the fall-through is provably terminal in every mypy resolution
    # regime — including follow_imports = "skip" (PKG-1), under which
    # pytest.fail resolves as Any rather than NoReturn. Same idiom as
    # _gates_job in test_ci_workflow.py.
    raise AssertionError("unreachable")


def test_no_undefined_names_anywhere_in_src():
    """F821 must be zero. This is the rule that catches the whole class.

    Every one of the four bugs above is an F821: a name used at runtime that
    nothing defines or imports in scope.
    """
    result = _run_ruff(
        "check", "src", "--select", "F821", "--output-format", "concise"
    )

    assert result.returncode == 0, (
        "undefined names found — these are runtime NameErrors waiting for the "
        f"first live run to reach them:\n{result.stdout}{result.stderr}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# THE TEST GAP THAT LET THE FOURTH BUG THROUGH
# ─────────────────────────────────────────────────────────────────────────────


def test_the_math_perception_adapter_is_actually_built_with_a_driver():
    """Every other orchestrator test runs with driver=None.

    That is why a NameError on the driver-present branch survived 905 passing
    tests, and closing that coverage gap is this pin's job.

    Being accurate about its strength: it is a COVERAGE pin, not a
    discriminator for the specific bug. Measured against the buggy tree it still
    passes, because the NameError is swallowed by a bare ``except`` and a later
    construction site builds the adapter anyway. The pins that actually catch
    that bug are the F821 gate and the definition-order guard below.
    """
    from auto_apply.infrastructure.composition_root import build_orchestrator
    from auto_apply.infrastructure.registry import CapabilitiesRegistry

    from tests.infrastructure.test_reproducibility import _minimal_profile

    registry = CapabilitiesRegistry.build(user_profile=_minimal_profile())

    driver = MagicMock()
    driver.page_source = "<html></html>"
    driver.current_url = "https://example.test"

    with patch(
        "auto_apply.infrastructure.composition_root.BrowserCascade.acquire_driver",
        return_value=driver,
    ), patch(
        "auto_apply.adapters.secondary.perception.math_dom_adapter.MathDOMAdapter"
    ) as math_adapter:
        orchestrator = build_orchestrator(registry)

    assert orchestrator is not None
    assert math_adapter.called, (
        "MathDOMAdapter was never constructed on the driver-present path — "
        "the Math perception subsystem is silently disabled"
    )


def test_the_audit_observer_is_defined_before_its_first_use():
    """Specific guard on the shipped bug, so it cannot come back quietly."""
    source = (
        SRC / "auto_apply" / "infrastructure" / "composition_root.py"
    ).read_text(encoding="utf-8", errors="ignore")

    definition = source.index("_extraction_observer = DiscoveryMathAuditor()")
    first_use = source.index("observer=_extraction_observer")

    assert definition < first_use, (
        "_extraction_observer is used before it is defined; with a driver "
        "present that is a NameError swallowed by a bare except"
    )


def test_the_observer_is_defined_exactly_once():
    source = (
        SRC / "auto_apply" / "infrastructure" / "composition_root.py"
    ).read_text(encoding="utf-8", errors="ignore")

    assert source.count("_extraction_observer = DiscoveryMathAuditor()") == 1

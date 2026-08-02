
"""Pins for composition-root construction of the PageActionService tool (Stage 1).

``PageActionService`` is 876 lines of port-only, config-driven, seeded browser
interaction that nothing in production ever constructed — its only callers were
two test modules, so the ``navigation_retries``, ``warmup_pause`` and
``min_action_delay_ms`` work from earlier sessions all landed on a dead branch.

These pins hold the tool on the live path:

    * the composition root builds it whenever there is a driver,
    * it receives a namespaced seeded RNG (never a bare ``random.Random()``),
    * it is handed to the ``InteractionExecutor`` that every engine already
      receives as ``interaction_port``,
    * and its absence in static (no-driver) mode is still a clean build.
"""
import ast
import pathlib

SRC = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "src"
    / "auto_apply"
    / "infrastructure"
    / "composition_root.py"
)


def _source() -> str:
    return SRC.read_text(encoding="utf-8", errors="ignore")


def test_composition_root_imports_the_page_action_tool():
    """The tool is referenced by the only module allowed to wire concretes."""
    src = _source()
    assert "PageActionService" in src, (
        "composition_root.py never mentions PageActionService — the interaction "
        "tool is still orphaned."
    )


def test_composition_root_seeds_the_tool_with_a_named_rng_namespace():
    """Determinism: the tool's pacing stream is namespaced and reproducible."""
    assert 'make_rng("interaction.pacing")' in _source(), (
        'composition_root.py must allocate make_rng("interaction.pacing") so '
        "the tool's pacing is reproducible under a session seed."
    )


def test_the_rng_namespace_is_allocated_unconditionally():
    """The namespace is reserved in every mode, so seeded streams do not shift.

    Allocating it only inside the ``driver is not None`` branch would make
    stream allocation depend on execution mode and would leave the existing
    namespace contract test (test_reproducibility) unable to observe it.
    """
    src = _source()
    target = 'make_rng("interaction.pacing")'
    assert target in src, (
        "the namespace is not allocated at all — this pin cannot pass vacuously"
    )

    tree = ast.parse(src)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.If, ast.While, ast.For, ast.Try)):
            continue
        body_src = "\n".join(ast.unparse(child) for child in node.body)
        # ast.unparse normalises quotes to single quotes.
        if target.replace('"', "'") in body_src:
            raise AssertionError(
                "make_rng(\"interaction.pacing\") is allocated inside a "
                "conditional block; it must be allocated unconditionally."
            )


def test_the_tool_is_injected_into_the_interaction_executor():
    """The executor every engine receives is the one holding the tool."""
    src = _source()
    assert "page_action=" in src, (
        "InteractionExecutor is still constructed without the page_action tool, "
        "so interaction_port.click() has nothing to delegate to."
    )


def test_static_mode_builds_without_a_tool_and_without_raising():
    """Worst-case degradation: no driver → no tool, no crash, no browser calls.

    ``interaction_port`` is already None without a driver; this pin proves the
    new construction does not introduce a driver assumption into the static
    (zero-browser) path that worst-case users depend on.
    """
    from unittest.mock import patch

    from auto_apply.infrastructure.composition_root import build_orchestrator
    from auto_apply.infrastructure.registry import CapabilitiesRegistry

    from tests.infrastructure.test_reproducibility import _minimal_profile

    registry = CapabilitiesRegistry.build(user_profile=_minimal_profile())

    with patch(
        "auto_apply.infrastructure.composition_root.BrowserCascade.acquire_driver",
        return_value=None,
    ):
        orchestrator = build_orchestrator(registry)

    assert orchestrator is not None

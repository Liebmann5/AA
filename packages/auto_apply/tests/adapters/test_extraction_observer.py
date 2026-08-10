
"""Pins for the extraction observer port (Stage 5a).

Auditing is observation: it records what extraction saw and must never change
what extraction produces. That is exactly why it belongs behind a port — the
adapters emitting audit records were reaching up into the application layer to
find them, which is four of the fifteen remaining boundary violations.

The refactor is pure indirection, and these pins hold it to that:

    * what the auditor records is byte-for-byte identical through the port;
    * the port's methods ARE the auditor's methods, not reimplementations;
    * the four violations actually drop, recomputed with the boundary test's
      own AST logic rather than by eye;
    * nothing wired degrades to silence, never to an exception — discovery must
      not be able to fail because nobody was watching.
"""
import ast
import logging
import pathlib

import pytest
from unittest.mock import MagicMock

from auto_apply.application.services.auditing.discovery_math_auditor import (
    DiscoveryMathAuditor,
)
from auto_apply.domain.ports.extraction_observer_port import (
    ExtractionObserverPort,
    NullAuditReporter,
    NullExtractionObserver,
    PageAuditReporterPort,
)

AUDIT_METHODS = (
    "audit_candidate_containers",
    "audit_structural_hash_groups",
    "audit_extraction_attempt",
    "audit_geometry_cluster",
    "audit_validation_error",
    "audit_final_job_list",
    "audit_text_extraction",
)

SRC_ROOT = (
    pathlib.Path(__file__).resolve().parent.parent.parent / "src" / "auto_apply"
)


# ─────────────────────────────────────────────────────────────────────────────
# PURE INDIRECTION
# ─────────────────────────────────────────────────────────────────────────────


def test_the_observer_methods_are_the_auditors_own_methods():
    """Not a wrapper, not a reimplementation — the same function objects.

    This is the strongest available proof that the port cannot drift from what
    it fronts: there is nothing in between to drift.
    """
    observer = DiscoveryMathAuditor()

    for name in AUDIT_METHODS:
        assert getattr(observer, name) is getattr(DiscoveryMathAuditor, name), (
            f"{name} is no longer the auditor's own method"
        )


def test_the_enabled_flag_reads_the_same_class_state_as_before():
    """The gate the Math DOM adapter used to read directly."""
    observer = DiscoveryMathAuditor()
    assert observer.enabled == bool(DiscoveryMathAuditor._ENABLED)


def test_the_real_auditor_satisfies_the_port():
    assert isinstance(DiscoveryMathAuditor(), ExtractionObserverPort)


def test_the_nulls_satisfy_their_ports():
    assert isinstance(NullExtractionObserver(), ExtractionObserverPort)
    assert isinstance(NullAuditReporter(), PageAuditReporterPort)


# ─────────────────────────────────────────────────────────────────────────────
# BYTE-FOR-BYTE AUDIT OUTPUT
# ─────────────────────────────────────────────────────────────────────────────


def _records(caplog, call):
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        call()
    return [(r.levelno, r.getMessage()) for r in caplog.records]


@pytest.mark.parametrize(
    "name,args",
    [
        ("audit_candidate_containers", ([MagicMock()], "SrcA")),
        ("audit_structural_hash_groups", ({"h1": [MagicMock()]}, "SrcA")),
        ("audit_extraction_attempt", ({"title": "T"}, False, "reason")),
        ("audit_geometry_cluster", (["a", "b"], "Page Title")),
        ("audit_validation_error", ({"title": "T"}, "bad url")),
        ("audit_final_job_list", ([MagicMock()], "SrcA")),
    ],
)
def test_audit_output_is_identical_through_the_port(caplog, name, args):
    """Same records, same levels, same order — static call vs port call."""
    observer = DiscoveryMathAuditor()

    direct = _records(caplog, lambda: getattr(DiscoveryMathAuditor, name)(*args))
    through_port = _records(caplog, lambda: getattr(observer, name)(*args))

    assert direct == through_port


def test_a_null_observer_records_nothing_at_all(caplog):
    """Silence, not noise — and not an exception."""
    null = NullExtractionObserver()

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        null.audit_candidate_containers([MagicMock()], "SrcA")
        null.audit_extraction_attempt({}, False, "reason")
        null.audit_final_job_list([MagicMock()], "SrcA")

    assert caplog.records == []
    assert null.enabled is False


# ─────────────────────────────────────────────────────────────────────────────
# DEGRADATION — nothing wired must never raise
# ─────────────────────────────────────────────────────────────────────────────


def test_every_null_method_is_callable_and_returns_none():
    null = NullExtractionObserver()
    for name in AUDIT_METHODS:
        assert getattr(null, name) is not None

    assert null.audit_candidate_containers([], "s") is None
    assert null.audit_text_extraction(MagicMock(), "", "s") is None

    reporter = NullAuditReporter()
    assert reporter.log_state("ctx") is None
    assert reporter.log_item_rejection(MagicMock(), "why", {}) is None


def test_the_miner_defaults_to_a_null_observer():
    from auto_apply.adapters.secondary.discovery.components.miner import SemanticMiner

    miner = SemanticMiner(
        browser=MagicMock(),
        title_parser=MagicMock(),
        url_parser=MagicMock(),
        company_parser=MagicMock(),
    )
    assert isinstance(miner._observer, NullExtractionObserver)


def test_the_math_dom_adapter_defaults_to_a_null_observer():
    from auto_apply.adapters.secondary.perception.math_dom_adapter import MathDOMAdapter

    adapter = MathDOMAdapter(browser=MagicMock())
    assert isinstance(adapter._observer, NullExtractionObserver)
    assert adapter._observer.enabled is False


def test_the_serp_strategy_defaults_to_null_observer_and_reporter():
    from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
        GenericSERPStrategy,
    )

    strategy = GenericSERPStrategy(
        browser=MagicMock(), search_prefs=None, source_tag="T"
    )
    assert isinstance(strategy._observer, NullExtractionObserver)
    assert isinstance(strategy.auditor, NullAuditReporter)

    # The page-state call the strategy makes on every scrape must be safe.
    assert strategy.auditor.log_state("T - Pre-Scrape") is None


# ─────────────────────────────────────────────────────────────────────────────
# THE VIOLATIONS ACTUALLY DROP
# ─────────────────────────────────────────────────────────────────────────────


def _violations():
    """Recompute boundary violations with the architecture test's own logic."""
    from tests.test_architecture import _file_layer, _imported_layer, _is_allowed

    found = []
    for py_file in SRC_ROOT.rglob("*.py"):
        layer = _file_layer(py_file)
        if layer is None:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                if node.module and node.module != "__future__":
                    modules = [node.module]
            for module in modules:
                imported = _imported_layer(module)
                if imported and not _is_allowed(layer, imported):
                    found.append(
                        (str(py_file.relative_to(SRC_ROOT)).replace("\\", "/"), module)
                    )
    return found


@pytest.mark.parametrize(
    "path,module",
    [
        (
            "adapters/secondary/discovery/components/miner.py",
            "auto_apply.application.services.auditing.discovery_math_auditor",
        ),
        (
            "adapters/secondary/perception/math_dom_adapter.py",
            "auto_apply.application.services.auditing.discovery_math_auditor",
        ),
        (
            "adapters/secondary/discovery/strategies/serp_strategy.py",
            "auto_apply.application.services.auditing.discovery_math_auditor",
        ),
        (
            "adapters/secondary/discovery/strategies/serp_strategy.py",
            "auto_apply.application.services.auditing.reporter",
        ),
    ],
)
def test_each_retired_violation_is_gone(path, module):
    assert (path, module) not in _violations()


# The descent, so a future reader can see the direction of travel:
#   15 -> 11 (earlier stages)
#   11 ->  4 (ports stage: EventPublisherPort, LivenessPort,
#             ProfileRepositoryPort, RegistryPort.get_environment_capabilities)
#    4 ->  0 (relocation stage: interruption/pagination/classifier moved from
#             application/services/ to adapters/secondary/ — they drive a
#             browser, so they were secondary adapters filed in the wrong
#             layer; ConsentRecord/ConsentRepositoryPort moved to domain)
#
# Zero. This must never rise. test_hexagonal_import_boundaries asserts the
# empty list; this asserts the count, so a violation that the list-based pin
# somehow tolerates still shows up here as a number that moved.
_BOUNDARY_VIOLATION_CEILING = 0


def test_the_total_violation_count_does_not_rise():
    """A ratchet, checked by the same AST logic the main boundary pin uses.

    Equality, not <=, on purpose: a stage that retires one violation while
    introducing another nets to zero under <= and would pass silently. Equality
    forces the number to be restated deliberately every time it moves, which is
    the only reason a count pin earns its place alongside the pin that asserts
    the list itself.
    """
    total = len(_violations())
    assert total == _BOUNDARY_VIOLATION_CEILING, (
        f"expected {_BOUNDARY_VIOLATION_CEILING} boundary violations, found "
        f"{total}. If you retired one, lower the ceiling in the same commit. "
        f"If this went up, an adapter started reaching across a layer."
    )

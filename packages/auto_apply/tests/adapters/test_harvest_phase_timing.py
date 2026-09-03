"""Teeth: harvest phases are reported, on both the math and the miner routes.

Stage 3 of Batch 2 adds DEBUG phase lines so the next live run can show
which phase of a harvest grows (script / build / stitch / analyze on the
math route; candidate scan / extraction on the fallback miner). On the
pre-stage tree both assertions fail with ``AssertionError: assert False``.
"""

import logging
from typing import Any
from unittest.mock import Mock

from auto_apply.adapters.secondary.discovery.components.miner import SemanticMiner
from auto_apply.adapters.secondary.perception.math_dom_adapter import MathDOMAdapter

_TREE: dict[str, Any] = {
    "tag": "body",
    "attributes": {},
    "text": "",
    "geometry": None,
    "children": [
        {
            "tag": "div",
            "attributes": {"role": "heading"},
            "text": "Software Engineer",
            "geometry": {"x": 10, "y": 20, "width": 300, "height": 40},
            "children": [],
        }
    ],
}


class _StubExtractor:
    def __init__(self, value: str) -> None:
        self._value = value

    def extract(self, element: Any) -> str:
        return self._value


def test_math_dom_extraction_reports_phase_timing(caplog) -> None:
    browser = Mock()
    browser.execute_script.return_value = _TREE
    browser.find_elements.return_value = []  # no iframes

    adapter = MathDOMAdapter(browser=browser)

    with caplog.at_level(logging.DEBUG):
        root = adapter.extract_full_dom_tree()

    assert root is not None
    phase_lines = [
        r.getMessage() for r in caplog.records if "MathDOM extraction:" in r.getMessage()
    ]
    assert phase_lines, "expected one phase-timing line from extract_full_dom_tree"
    line = phase_lines[0]
    assert "script=" in line
    assert "build=" in line
    assert "stitch=" in line
    assert "nodes=2" in line
    assert "bytes=" in line


def test_semantic_miner_reports_phase_timing(caplog) -> None:
    # SemanticMiner._score_and_extract requires at least TWO children before it
    # will treat a container as a job list ("if child_count < 2: return 0, []").
    # A single child scores zero and extracts nothing, which is what made the
    # first version of this test assert 0 == 1.
    browser = Mock()
    container = Mock()
    first_child = Mock()
    second_child = Mock()
    first_child.get_size.return_value = (100, 100)
    second_child.get_size.return_value = (100, 100)
    container.find_elements.return_value = [first_child, second_child]
    browser.find_elements.return_value = [container]

    miner = SemanticMiner(
        browser=browser,
        title_parser=_StubExtractor("Software Engineer"),
        url_parser=_StubExtractor("https://jobs.example/1"),
        company_parser=_StubExtractor("ExampleCo"),
    )

    with caplog.at_level(logging.DEBUG):
        jobs = miner.mine_jobs(source_name="Indeed")

    assert len(jobs) == 2
    miner_lines = [
        r.getMessage()
        for r in caplog.records
        if "miner:" in r.getMessage() and "candidates" in r.getMessage()
    ]
    assert miner_lines, "expected one per-harvest phase line from SemanticMiner"
    assert "1 candidates scanned" in miner_lines[0]
    assert "2 jobs extracted" in miner_lines[0]

    container_lines = [
        r.getMessage()
        for r in caplog.records
        if "miner container:" in r.getMessage()
    ]
    assert container_lines, "expected one per-container phase line"
    assert "2 children, 2 jobs" in container_lines[0]

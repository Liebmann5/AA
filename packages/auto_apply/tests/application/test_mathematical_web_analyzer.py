"""Tests for MathematicalWebAnalyzer.

All DOMNode trees are constructed in memory; a MathematicalPerceptionPort
mock is used instead of a real browser adapter.
"""

import pytest
from unittest.mock import MagicMock

from auto_apply.application.services.mathematical_web_analyzer import (
    MathematicalWebAnalyzer,
)
from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.parsed_job_description import ParsedJobDescription
from auto_apply.domain.models.math_webpage import WebpageStructure


@pytest.fixture
def mock_perception_port():
    """A MinimalMathematicalPerceptionPort mock that returns canned data."""
    import auto_apply.domain.ports.math_perception_port as mp
    spec = MagicMock(spec_set=mp.MathematicalPerceptionPort)
    spec.extract_full_dom_tree.return_value = None
    spec.get_current_url.return_value = "https://example.com"
    spec.get_page_title.return_value = "Apply Now"
    return spec


def _build_card(title: str, company: str, url: str) -> DOMNode:
    return DOMNode(
        tag="div",
        attributes=(("class", "job-card"),),
        geometry=Geometry(0, 0, 220, 100),
        depth=1,
        children=(
            DOMNode(
                tag="h2",
                text=title,
                geometry=Geometry(10, 10, 200, 20),
                depth=2,
            ),
            DOMNode(
                tag="p",
                text=company,
                geometry=Geometry(10, 40, 200, 20),
                depth=2,
            ),
            DOMNode(
                tag="a",
                attributes=(("href", url),),
                text="Apply",
                geometry=Geometry(10, 70, 50, 20),
                depth=2,
            ),
        ),
    )


class TestExtractJobListings:
    def test_no_cards_returns_empty(self, mock_perception_port):
        root = DOMNode(tag="body", depth=0)
        mock_perception_port.extract_full_dom_tree.return_value = root
        analyzer = MathematicalWebAnalyzer(mock_perception_port)
        jobs = analyzer.extract_job_listings()
        assert jobs == []

    def test_single_card_extracts_job(self, mock_perception_port):
        card = _build_card("Software Engineer", "Acme Inc", "https://acme.com/jobs/1")
        body = DOMNode(tag="body", depth=0, children=(card, card))
        mock_perception_port.extract_full_dom_tree.return_value = body
        analyzer = MathematicalWebAnalyzer(mock_perception_port)
        jobs = analyzer.extract_job_listings()
        assert len(jobs) == 1
        assert isinstance(jobs[0], Job)
        assert jobs[0].title == "Software Engineer"
        assert jobs[0].company == "Acme Inc"
        assert jobs[0].url == "https://acme.com/jobs/1"


class TestAnalyzeJobDescription:
    def test_extracts_main_content(self, mock_perception_port):
        main_node = DOMNode(
            tag="div",
            text="Job Title: Senior Engineer Location: Remote",
            geometry=Geometry(0, 0, 800, 600),
            depth=1,
        )
        body = DOMNode(tag="body", depth=0, children=(main_node,))
        mock_perception_port.extract_full_dom_tree.return_value = body
        analyzer = MathematicalWebAnalyzer(mock_perception_port)
        result = analyzer.analyze_job_description()
        assert isinstance(result, ParsedJobDescription)
        assert result.is_remote is True

    def test_parsed_fields_are_model_fields_only(self, mock_perception_port):
        main_node = DOMNode(
            tag="div",
            text="We work fully remote. Great team.",
            geometry=Geometry(0, 0, 800, 600),
            depth=1,
        )
        body = DOMNode(tag="body", depth=0, children=(main_node,))
        mock_perception_port.extract_full_dom_tree.return_value = body
        analyzer = MathematicalWebAnalyzer(mock_perception_port)
        result = analyzer.analyze_job_description()
        assert isinstance(result, ParsedJobDescription)
        assert result.is_remote is True
        assert result.locations == []
        assert result.organizations == []
        for absent in ("title", "salary", "description"):
            assert absent not in result.model_dump()


class TestDetectJobCardsGuard:
    def _card(self) -> DOMNode:
        return DOMNode(
            tag="div",
            geometry=Geometry(0, 0, 220, 100),
            depth=1,
            children=(
                DOMNode(tag="h2", text="Engineer", geometry=Geometry(5, 5, 100, 20), depth=2),
                DOMNode(
                    tag="a",
                    attributes=(("href", "/j/1"),),
                    text="Apply",
                    geometry=Geometry(5, 40, 60, 20),
                    depth=2,
                ),
            ),
        )

    def test_looks_like_card_accepts_real_card(self):
        from auto_apply.domain.services.structural_hashing import is_card_like
        assert is_card_like(self._card()) is True

    def test_looks_like_card_rejects_missing_geometry(self):
        from auto_apply.domain.services.structural_hashing import is_card_like
        node = DOMNode(
            tag="div",
            depth=1,
            children=(
                DOMNode(
                    tag="a",
                    text="x",
                    attributes=(("href", "/"),),
                    depth=2,
                ),
            ),
        )
        assert is_card_like(node) is False

    def test_looks_like_card_rejects_tiny_area(self):
        from auto_apply.domain.services.structural_hashing import is_card_like
        node = DOMNode(
            tag="li",
            geometry=Geometry(0, 0, 30, 10),
            depth=1,
            children=(
                DOMNode(
                    tag="a",
                    text="Home",
                    attributes=(("href", "/"),),
                    depth=2,
                ),
            ),
        )
        assert is_card_like(node) is False

    def test_looks_like_card_rejects_no_link(self):
        from auto_apply.domain.services.structural_hashing import is_card_like
        node = DOMNode(
            tag="div",
            geometry=Geometry(0, 0, 220, 100),
            depth=1,
            children=(
                DOMNode(
                    tag="span",
                    text="just text",
                    geometry=Geometry(5, 5, 80, 20),
                    depth=2,
                ),
            ),
        )
        assert is_card_like(node) is False

    def test_detect_job_cards_filters_repeated_navlinks(self, mock_perception_port):
        nav_items = [
            DOMNode(
                tag="li",
                geometry=Geometry(0, i * 12, 40, 10),
                depth=2,
                children=(
                    DOMNode(
                        tag="a",
                        text="Nav",
                        attributes=(("href", f"/{i}"),),
                        geometry=Geometry(0, i * 12, 40, 10),
                        depth=3,
                    ),
                ),
            )
            for i in range(4)
        ]
        nav = DOMNode(tag="ul", depth=1, children=tuple(nav_items))
        cards = [self._card(), self._card()]
        body = DOMNode(tag="body", depth=0, children=(nav, *cards))

        analyzer = MathematicalWebAnalyzer(mock_perception_port)
        analyzed = analyzer._detect_job_cards(body)

        assert analyzed
        assert all(d.tag == "div" for d in analyzed)


class TestAnalyzeForm:
    def test_delegates_to_form_analyzer(self, mock_perception_port):
        mock_perception_port.get_current_url.return_value = "https://example.com"
        mock_perception_port.get_page_title.return_value = "Apply Form"
        root = DOMNode(tag="body", depth=0)
        mock_perception_port.extract_full_dom_tree.return_value = root

        mock_structure = WebpageStructure(
            url=mock_perception_port.get_current_url(),
            title=mock_perception_port.get_page_title(),
            dom_root=root,
        )
        analyzer = MathematicalWebAnalyzer(mock_perception_port)
        analyzer._form_analyzer.analyze = MagicMock(return_value=mock_structure)
        result = analyzer.analyze_form()
        assert result is mock_structure
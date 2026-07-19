"""Unit tests for MathPageUnderstandingAdapter.

Uses mocked MathDOMAdapter and MathFormUnderstandingService.  No real
browser or network I/O required.
"""

from unittest.mock import MagicMock

import pytest

from auto_apply.adapters.secondary.perception.math_dom_adapter import (
    MathPageUnderstandingAdapter,
)
from auto_apply.domain.models.math_dom import DOMNode, Geometry
from auto_apply.domain.models.math_webpage import (
    FieldType,
    FormRegion,
    LabeledField,
    WebpageStructure,
)
from auto_apply.domain.ports.page_understanding_port import (
    PageContext,
    SERPStructure,
    FormStructure,
    JobListingStructure,
)


def _mock_dom_adapter(return_root=None):
    dom = MagicMock()
    dom.extract_full_dom_tree.return_value = return_root
    return dom


def _mock_form_service(return_structure=None):
    svc = MagicMock()
    svc.analyze.return_value = return_structure or WebpageStructure(
        url="", title="", dom_root=None
    )
    return svc


DUMMY_PAGE_CONTEXT = PageContext(
    url="https://example.com/jobs",
    html_source="<html></html>",
    page_title="Jobs at Example",
)


def _make_job_card_node(title="Engineer", company="Acme", url="/jobs/1"):
    """Build a minimal DOMNode representing a job card."""
    card_children = [
        DOMNode(
            tag="h3",
            text=title,
            geometry=Geometry(0, 0, 100, 20),
            depth=1,
        ),
        DOMNode(
            tag="p",
            text=company,
            geometry=Geometry(0, 20, 100, 20),
            depth=1,
        ),
        DOMNode(
            tag="a",
            attributes=(("href", url),),
            text="Apply",
            geometry=Geometry(0, 40, 50, 20),
            depth=1,
        ),
    ]
    return DOMNode(
        tag="div",
        geometry=Geometry(0, 0, 200, 80),
        depth=0,
        children=tuple(card_children),
    )


# ─────────────────────────────────────────────────────────────────────────────


def test_analyze_serp_extracts_job_cards():
    """When the math subsystem returns job_listings, they appear as cards."""
    card = _make_job_card_node(
        title="Software Engineer", company="Acme Corp", url="/jobs/123"
    )
    # Build a dummy root containing the card so that extract_full_dom_tree()
    # can return it, but the service's analyze() is mocked anyway.
    dom_root = DOMNode(tag="body", depth=0, children=(card,))

    dom_adapter = _mock_dom_adapter(return_root=dom_root)

    structure = WebpageStructure(
        url="https://example.com/jobs",
        title="Jobs at Example",
        dom_root=dom_root,
        job_listings=[card],   # the service returns this card
    )
    form_service = _mock_form_service(return_structure=structure)

    adapter = MathPageUnderstandingAdapter(dom_adapter, form_service)
    result = adapter.analyze_serp(DUMMY_PAGE_CONTEXT)

    assert isinstance(result, SERPStructure)
    assert len(result.job_cards) == 1
    card_info = result.job_cards[0]
    assert card_info.title == "Software Engineer"
    assert card_info.company == "Acme Corp"
    assert "123" in card_info.url


def test_analyze_serp_empty_when_extraction_fails():
    """Return empty SERPStructure when DOM extraction returns None."""
    dom_adapter = _mock_dom_adapter(return_root=None)
    form_service = _mock_form_service()

    adapter = MathPageUnderstandingAdapter(dom_adapter, form_service)
    result = adapter.analyze_serp(DUMMY_PAGE_CONTEXT)

    assert isinstance(result, SERPStructure)
    assert len(result.job_cards) == 0


def test_analyze_form_returns_form_fields():
    """Ensure that form regions are translated into FormFieldInfo."""
    # Create a minimal form region with one field
    input_node = DOMNode(
        tag="input",
        attributes=(("name", "email"), ("type", "text")),
        geometry=Geometry(0, 0, 200, 30),
        depth=1,
    )
    label_node = DOMNode(
        tag="label",
        text="Email",
        geometry=Geometry(0, 20, 50, 20),
        depth=1,
    )
    from auto_apply.domain.models.math_webpage import LabeledField

    field = LabeledField(
        input_node=input_node,
        label_node=label_node,
        label_text="Email",
        inferred_type=FieldType.EMAIL,
        is_required=True,
        is_honeypot=False,
    )

    form_region = FormRegion(
        root_node=DOMNode(tag="form", depth=0),
        clusters=[],
    )
    # We need to attach the field to a cluster inside the form region.
    # The easiest way is to use all_fields property which is derived.
    # Since FormRegion is frozen, we can't mutate. Instead, we can construct
    # a WebpageStructure manually and then mock the service.
    # We'll inject a structure that contains a form with fields.

    # Build a simple WebpageStructure with one form containing that field.
    # To do this without violating frozenness, we can build via the
    # MathFormUnderstandingService mock. Just return a WebpageStructure
    # that has the form region with that field.
    # We'll construct the FormRegion with a cluster that contains the field.

    from auto_apply.domain.models.math_webpage import FieldCluster

    cluster = FieldCluster(fields=[field])
    form_region = FormRegion(
        root_node=DOMNode(tag="form", depth=0),
        clusters=[cluster],
    )

    structure = WebpageStructure(
        url="https://example.com/apply",
        title="Apply",
        dom_root=DOMNode(tag="body", depth=0),
        forms=[form_region],
    )

    dom_adapter = _mock_dom_adapter(return_root=structure.dom_root)
    form_service = _mock_form_service(return_structure=structure)

    adapter = MathPageUnderstandingAdapter(dom_adapter, form_service)
    result = adapter.analyze_form(DUMMY_PAGE_CONTEXT)

    assert isinstance(result, FormStructure)
    assert len(result.fields) == 1
    assert result.fields[0].label_text == "Email"
    assert result.fields[0].is_required is True
    assert result.confidence > 0.0


def test_analyze_form_empty_when_root_is_none():
    """Return empty FormStructure when DOM extraction fails."""
    dom_adapter = _mock_dom_adapter(return_root=None)
    form_service = _mock_form_service()

    adapter = MathPageUnderstandingAdapter(dom_adapter, form_service)
    result = adapter.analyze_form(DUMMY_PAGE_CONTEXT)

    assert isinstance(result, FormStructure)
    assert len(result.fields) == 0
    assert result.confidence == 0.0


def test_analyze_job_listing_extracts_details():
    """A single listing page yields a populated JobListingStructure."""
    card = _make_job_card_node(
        title="Data Scientist", company="DataCorp", url="/apply/ds123"
    )
    dom_root = DOMNode(tag="body", depth=0, children=(card,))

    structure = WebpageStructure(
        url="https://example.com/job",
        title="Data Scientist at DataCorp",
        dom_root=dom_root,
        job_listings=[card],
    )

    dom_adapter = _mock_dom_adapter(return_root=dom_root)
    form_service = _mock_form_service(return_structure=structure)

    adapter = MathPageUnderstandingAdapter(dom_adapter, form_service)
    result = adapter.analyze_job_listing(DUMMY_PAGE_CONTEXT)

    assert isinstance(result, JobListingStructure)
    assert "Data Scientist" in result.title
    assert result.company == "DataCorp"
    assert "/apply/ds123" in result.apply_url
    assert result.apply_button_present is True
    assert result.full_text != ""  # should contain visible text from the page


def test_analyze_job_listing_empty_when_extraction_fails():
    """Return empty structure when no DOM root available."""
    dom_adapter = _mock_dom_adapter(return_root=None)
    form_service = _mock_form_service()

    adapter = MathPageUnderstandingAdapter(dom_adapter, form_service)
    result = adapter.analyze_job_listing(DUMMY_PAGE_CONTEXT)

    assert isinstance(result, JobListingStructure)
    assert result.title == ""
    assert result.company == ""
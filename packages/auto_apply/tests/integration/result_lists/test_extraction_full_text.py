"""Real-browser pins for the extraction script's text (slice S1, defect 4).

Before S1 the script kept only an element's own text nodes, so
``<h3><span>Title</span></h3>`` gave the heading no text and every such card
was dropped for "no title". These pins run the script itself in Chrome.
"""

from __future__ import annotations

import pytest

from auto_apply.domain.models import math_dom

TEXT_CAP = getattr(math_dom, "TEXT_CAP", 256)

pytestmark = pytest.mark.browser

_PAGE = """<!DOCTYPE html><html><body>
<h3 id="t1"><span>Engineer 1</span></h3>
<h2><a id="lnk" href="/job/2"><strong>Soft</strong>ware Engineer<span aria-hidden="true"> *</span><span style="display:none"> HIDDEN</span></a></h2>
<button aria-label="Close dialog">X</button>
<div role="link" aria-labelledby="t1">ignored</div>
<a href="/img"><img alt="Company logo" src="data:,"></a>
<h4>{long}</h4>
<script>var leaked = "never text";</script>
</body></html>"""


def _tree(chrome, page_server):
    from auto_apply.adapters.secondary.browser.selenium_adapter import SeleniumAdapter
    from auto_apply.adapters.secondary.perception.math_dom_adapter import MathDOMAdapter

    page_server(chrome, "/fulltext", _PAGE.replace("{long}", "word " * TEXT_CAP))
    root, facts = MathDOMAdapter(SeleniumAdapter(chrome)).extract_observation()
    assert root is not None and facts is not None
    return root, facts


def _first(root, tag, **attrs):
    for node in root.iter_nodes():
        if node.tag == tag and all(node.get_attribute(k) == v for k, v in attrs.items()):
            return node
    raise AssertionError(f"no <{tag}> {attrs}")


def test_nested_heading_text_is_read_teeth(chrome, page_server) -> None:
    root, _ = _tree(chrome, page_server)
    h3 = _first(root, "h3")
    assert h3.text == ""  # direct text is unchanged
    assert h3.full_text == "Engineer 1"
    assert h3.accessible_name == "Engineer 1"


def test_inline_markup_joins_and_hidden_text_is_excluded(chrome, page_server) -> None:
    root, _ = _tree(chrome, page_server)
    link = _first(root, "a", id="lnk")
    assert link.full_text == "Software Engineer *"  # visible text, aria-hidden is visible
    assert link.accessible_name == "Software Engineer"  # aria-hidden excluded from the name
    assert "HIDDEN" not in link.full_text


def test_accessible_name_sources(chrome, page_server) -> None:
    root, _ = _tree(chrome, page_server)
    assert _first(root, "button").accessible_name == "Close dialog"
    assert _first(root, "div", role="link").accessible_name == "Engineer 1"
    assert _first(root, "a", href="/img").accessible_name == "Company logo"
    body_text = root.full_text
    assert "never text" not in body_text


def test_text_cap_truncates_and_flags(chrome, page_server) -> None:
    root, facts = _tree(chrome, page_server)
    h4 = _first(root, "h4")
    assert len(h4.full_text) == TEXT_CAP and h4.text_truncated is True
    assert ("text_cap", facts.text_capped) in facts.truncations() and facts.text_capped >= 2
    assert not facts.text_budget_hit and facts.node_count >= 10

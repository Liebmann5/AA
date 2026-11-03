"""Real-browser fixtures for the form pins (slice S4).

The browser and the page server are the ones the result-list pins use
(``tests/integration/result_lists/conftest.py``), loaded from that file so
there is one copy. A machine without Chrome or Selenium skips cleanly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_SHARED = Path(__file__).parent.parent / "result_lists" / "conftest.py"
_spec = importlib.util.spec_from_file_location("_s1_browser_fixtures", _SHARED)
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)

chrome = _shared.chrome
page_server = _shared.page_server


# ── Run a page through AA's real extraction and form reader ──────────────


def read_page(chrome, page_server, path: str, html: str | None = None):
    from auto_apply.adapters.secondary.browser.selenium_adapter import SeleniumAdapter
    from auto_apply.adapters.secondary.perception.math_dom_adapter import MathDOMAdapter
    from auto_apply.domain.services.dom_segmentation import MathFormUnderstandingService

    page_server(chrome, path, html)
    root = MathDOMAdapter(SeleniumAdapter(chrome)).extract_full_dom_tree()
    assert root is not None
    return MathFormUnderstandingService().analyze(root, url="http://fixture" + path)


def fields_of(structure):
    return [f for form in structure.forms for f in form.all_fields]


def by_name(fields, name: str):
    for field in fields:
        if field.input_node.get_attribute("name") == name:
            return field
    raise AssertionError(f"no field named {name!r}: {[f.input_node.get_attribute('name') for f in fields]}")


@pytest.fixture
def forms(chrome, page_server):
    """``forms.read(path, html)`` returns the analysed structure."""
    return SimpleNamespace(
        read=lambda path, html=None: read_page(chrome, page_server, path, html),
        fields_of=fields_of,
        by_name=by_name,
    )

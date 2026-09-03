"""Pins for the None-attribute guard cluster (Stage S-6a).

``get_attribute`` returns ``str | None`` per the BrowserInterface port. On
real pages, odd elements answer None, and five call sites called ``.lower()``
(or ``.text``) on that result unguarded. The AttributeError that followed was
then swallowed by broad ``except Exception`` handlers — a silent fill failure
on a real application, with no log and no evidence. These pins drive each
formerly-crashing site with an element whose attribute reads all return None
and assert the guard holds.

Pin labels:
    teeth (4)    — verified to raise AttributeError on the pre-fix tree.
    coverage (1) — documents the None-return contract; the site's result is
                   externally identical pre/post, so the fix is type-level.
"""

from unittest.mock import MagicMock

from auto_apply.adapters.secondary.interaction.handlers.select import SelectInputHandler
from auto_apply.adapters.secondary.interaction.handlers.file import FileInputHandler
from auto_apply.adapters.secondary.interaction.human_like_adapter import UnifiedInteractor
from auto_apply.adapters.secondary.perception.dom_adapter import DOMScanner
from auto_apply.domain.models.ui import UIElementType


def _none_element() -> MagicMock:
    """An element whose every attribute read returns None."""
    element = MagicMock()
    element.get_attribute.side_effect = lambda name: None
    return element


def test_select_handler_completes_with_none_tag_name() -> None:
    """TEETH: tagName -> None must not crash the dispatch.

    Pre-fix the guard line raised AttributeError out of handle() and the field
    went silently unfilled. Post-fix the tag degrades to "" and the combobox
    fallback completes (it sends keys to the element).
    """
    browser = MagicMock()
    browser.find_elements.return_value = []
    element = _none_element()

    handler = SelectInputHandler(browser)
    handler.handle(element, "Mathematics")

    element.send_keys.assert_called()


def test_file_handler_completes_with_none_tag_name(tmp_path) -> None:
    """TEETH: tagName -> None must route to the associated-input search.

    Pre-fix the guard line raised before _find_associated_file_input ran;
    browser.find_elements was never called.
    """
    dummy = tmp_path / "resume.pdf"
    dummy.write_text("x", encoding="utf-8")

    element = _none_element()
    element.find_elements.return_value = []
    browser = MagicMock()
    browser.find_elements.return_value = []

    handler = FileInputHandler(browser)
    handler.handle(element, str(dummy))

    browser.find_elements.assert_called()


def test_fill_input_actually_fills_with_none_attributes() -> None:
    """TEETH: fill_input must reach the text handler and type the value.

    The dispatch line is inside a try/except that logs and swallows, so the
    pre-fix failure never raised — the value simply never reached the element.
    That silent skip is the bug this pin proves is gone.
    """
    element = _none_element()
    interactor = UnifiedInteractor(browser=MagicMock())

    interactor.fill_input(element, "Jane")

    typed = [c.args[0] for c in element.send_keys.call_args_list if c.args]
    assert "Jane" in typed, (
        f"value never reached the element — the fill was silently skipped. "
        f"send_keys calls: {typed}"
    )


def test_determine_type_survives_none_tag_name() -> None:
    """TEETH: tagName -> None must fall through to TEXT_INPUT."""
    scanner = DOMScanner(MagicMock())
    element = _none_element()

    assert scanner._determine_type(element) == UIElementType.TEXT_INPUT


def test_resolve_label_returns_none_for_parentless_element() -> None:
    """COVERAGE: with no parent element, _resolve_label returns None.

    Pre-fix reached the same result by crashing internally and catching it;
    post-fix reaches it via an explicit None check. Externally identical —
    labelled coverage, not teeth.
    """
    scanner = DOMScanner(MagicMock())
    element = _none_element()
    element.find_element.return_value = None

    assert scanner._resolve_label(element) is None

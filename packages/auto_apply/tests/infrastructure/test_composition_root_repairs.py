"""Pins for the S-6c composition_root repairs.

Verified by inspection: all three pins fail on the pre-fix tree —
DOMScanner was not a PerceptionPort (isinstance False), get_page_text raised
AttributeError, and DatabaseManager did not nominally subclass WorkQueuePort
(the ABC at domain/ports/work_queue_port.py).
"""

from unittest.mock import MagicMock

from auto_apply.adapters.secondary.persistence.database import DatabaseManager
from auto_apply.adapters.secondary.perception.dom_adapter import DOMScanner
from auto_apply.domain.ports.perception_port import PerceptionPort
from auto_apply.domain.ports.work_queue_port import WorkQueuePort


def test_dom_scanner_is_a_full_perception_port() -> None:
    scanner = DOMScanner(MagicMock())
    assert isinstance(scanner, PerceptionPort), (
        "DOMScanner must implement navigate, scan_page, get_current_state, "
        "and get_page_text to stand in as a perception adapter"
    )


def test_dom_scanner_serves_vetting_text_path() -> None:
    """VettingWorkflow._fetch_job_description calls navigate + get_page_text.

    On the DOMScanner path this previously raised AttributeError and silently
    degraded vetting to title-only.
    """
    browser = MagicMock()
    browser.execute_script.return_value = "Senior Engineer — 5 years experience"
    scanner = DOMScanner(browser)
    assert scanner.get_page_text() == "Senior Engineer — 5 years experience"


def test_database_manager_nominally_implements_work_queue_port() -> None:
    assert issubclass(DatabaseManager, WorkQueuePort), (
        "WorkQueuePort is an ABC — mypy requires nominal subtyping, and the "
        "orchestrator's task_queue argument must satisfy it"
    )

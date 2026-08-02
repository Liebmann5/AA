"""Unit tests for SessionController task seeding with multi‑location support."""

from unittest.mock import MagicMock

import pytest

from auto_apply.application.services.session_controller import SessionController
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.task_priority import TaskPriority
from auto_apply.domain.models.work_unit import TaskType


def test_seed_discovery_tasks_uses_title_location_pairs():
    """A profile with 2 titles × 3 locations should produce 6 tasks."""
    # Build a minimal UserProfile via model_validate (Pydantic v2).
    profile = UserProfile.model_validate({
        "profile_name": "test",
        "personal_info": {
            "first_name": "T",
            "last_name": "U",
            "email": "t@example.com",
            "phone_number": "000",
            "street_address": "",
            "city": "",
            "state": "",
            "zip_code": "",
        },
        "links": {},
        "career_summary": "A test summary for validation purposes, written to satisfy the fifty character minimum length requirement.",
        "search_preferences": {
            "desired_job_titles": ["Title1", "Title2"],
            "preferred_locations": ["LocA", "LocB", "LocC"],
        },
        "politeness_settings": {},
    })

    # Mocks
    registry = MagicMock()
    registry.get_active_profile.return_value = profile

    db = MagicMock()
    db.queue_task = MagicMock()

    orchestrator = MagicMock()

    controller = SessionController(registry=registry, db=db, orchestrator=orchestrator)

    count = controller._seed_discovery_tasks("")

    assert count == 6
    assert db.queue_task.call_count == 6

    # Verify that each task has the expected payload structure
    for call_args in db.queue_task.call_args_list:
        task = call_args[0][0]
        assert task.task_type == TaskType.DISCOVER
        assert task.priority == TaskPriority.DISCOVER
        assert "query" in task.payload
        assert "location" in task.payload
        # The title/location are derived from the cross product, so we don't
        # check exact values, just that they are populated.
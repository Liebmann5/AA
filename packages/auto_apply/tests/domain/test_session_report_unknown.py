"""UNKNOWN attempts must be reported, not silently dropped from every count.

Planned at the end of the P0-2 fix turn and not emitted then; without this
file, an attempt whose outcome AA cannot tell appeared in no saved count.
"""

from __future__ import annotations

import json

from auto_apply.domain.models.session_report import ApplicationRecord, SessionReport


def _record(outcome: str) -> ApplicationRecord:
    return ApplicationRecord(
        job_url="u",
        job_title="t",
        company="c",
        ats_platform=None,
        outcome=outcome,
        confidence=0.5,
        fields_filled=0,
        pages_navigated=0,
        used_gpt4all=False,
    )


def test_unknown_attempts_are_counted_somewhere():
    """UNKNOWN is its own count: not submitted, not failed, never absent."""
    report = SessionReport(session_id="s", profile_name="p")
    report.applications.append(_record("UNKNOWN"))
    report.applications.append(_record("SUBMITTED"))
    report.applications.append(_record("ERROR"))
    assert report.applications_unknown == 1
    assert report.applications_submitted == 1
    assert report.applications_failed == 1
    assert report.applications_completed == 3


def test_unknown_is_in_the_saved_json(tmp_path):
    """The saved report carries applications.unknown for an UNKNOWN attempt."""
    report = SessionReport(session_id="s", profile_name="p")
    report.applications.append(_record("UNKNOWN"))
    report.finalize(1.0)
    path = report.save(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["applications"]["unknown"] == 1
    assert data["applications"]["failed"] == 0

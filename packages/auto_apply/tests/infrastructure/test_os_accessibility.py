"""Pins for the run's assistive-technology signals (os_accessibility)."""

from __future__ import annotations

from auto_apply.infrastructure.os_accessibility import (
    environment_requests_screen_reader,
    presentation_settings,
    screen_reader_running,
)


def test_the_environment_switch() -> None:
    assert environment_requests_screen_reader({"AA_SCREEN_READER": "1"})
    assert environment_requests_screen_reader({"AA_SCREEN_READER": " Yes "})
    assert not environment_requests_screen_reader({"AA_SCREEN_READER": "0"})
    assert not environment_requests_screen_reader({})


def test_the_os_hint_turns_it_on_only_when_the_person_has_not_chosen() -> None:
    on = presentation_settings({"screen_reader_mode": False}, env={}, detect=lambda: True)
    assert on["screen_reader_mode"] is True
    kept_off = presentation_settings({"screen_reader_mode": False},
                                     explicit_screen_reader=False, env={},
                                     detect=lambda: True)
    assert kept_off["screen_reader_mode"] is False


def test_the_environment_wins_for_the_run() -> None:
    out = presentation_settings({}, explicit_screen_reader=False,
                                env={"AA_SCREEN_READER": "1"}, detect=lambda: None)
    assert out["screen_reader_mode"] is True


def test_no_signal_changes_nothing() -> None:
    section = {"screen_reader_mode": False, "font_scale": 1.5}
    assert presentation_settings(section, env={}, detect=lambda: None) == section


def test_detection_never_raises() -> None:
    assert screen_reader_running() in (True, False, None)

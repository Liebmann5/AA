"""Round-trip pin for portable document paths (R2).

The profile model stores document paths as portable STRINGS — relative to
PROFILES_DIR when the file lives under it — so a profile JSON works on any
machine and any USB drive letter. These tests pin that claim end to end,
including relocation of the profiles root (a different simulated drive).

Teeth: on the pre-stage tree, writers stored absolute Path objects and
``get_resolved_resume_path()`` returned None for a relative-looking stored
string whenever PROFILES_DIR pointed elsewhere.
"""

from pathlib import Path

import pytest

from auto_apply.domain.models.profile import PersonalInfo, make_portable_path


def _info(resume_path: str | None) -> PersonalInfo:
    return PersonalInfo(
        first_name="A",
        last_name="B",
        email="a@b.com",
        phone_number="555-0100",
        street_address="1 Main St",
        city="Town",
        state="ST",
        zip_code="00000",
        resume_path=resume_path,
    )


def test_store_absolute_under_profiles_dir_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEETH (round-trip): absolute file under PROFILES_DIR → stored relative
    → reloaded → resolved back to the real file."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    resume = profiles / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("auto_apply.domain.config.PROFILES_DIR", profiles)

    stored = make_portable_path(resume)
    assert stored == "resume.pdf"

    info = _info(stored)
    assert info.get_resolved_resume_path() == resume


def test_absolute_outside_profiles_dir_stays_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Coverage: a file outside PROFILES_DIR is stored absolute and still resolves."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    resume = elsewhere / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("auto_apply.domain.config.PROFILES_DIR", profiles)

    stored = make_portable_path(resume)
    assert stored == str(resume)

    info = _info(stored)
    assert info.get_resolved_resume_path() == resume


def test_relative_path_survives_relocation_of_profiles_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DIFFERENTIAL (the portability claim): the same stored string resolves
    correctly after PROFILES_DIR is re-rooted to a DIFFERENT simulated drive —
    the E: → F: USB-stick scenario the docstring only asserted before."""
    first = tmp_path / "drive_e" / "profiles"
    first.mkdir(parents=True)
    resume = first / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("auto_apply.domain.config.PROFILES_DIR", first)

    stored = make_portable_path(resume)
    assert stored == "resume.pdf"

    # Simulate mounting the stick on a different machine / drive letter.
    second = tmp_path / "drive_f" / "profiles"
    second.mkdir(parents=True)
    moved = second / "resume.pdf"
    moved.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("auto_apply.domain.config.PROFILES_DIR", second)

    info = _info(stored)
    assert info.get_resolved_resume_path() == moved

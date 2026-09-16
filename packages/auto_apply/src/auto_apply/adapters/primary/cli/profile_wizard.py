"""Interactive profile creation wizard for first-time users.

Called when PROFILES_DIR contains no user-created .json files (only the
bundled default_profile template). Guides the user through creating a
minimal working profile with the fields AA needs for form filling.

Validation contract:
    The collected answers are validated through UserProfile — the SAME
    model the ProfileRepository will later use to reject the file — BEFORE
    anything is persisted. If pydantic objects to a field, that field (and
    only that field) is re-prompted with the validation message; every other
    answer is kept. The "Profile saved" message is printed only after the
    complete profile validates and the write succeeds, so the message is
    always true.

Persistence contract:
    When a ``save`` callable is supplied (in practice
    ``ProfileRepository.save_profile``, passed through the
    ProfileRepositoryPort interface), the wizard hands the validated
    UserProfile to it and uses the returned value to locate the written
    file. Persistence then belongs to the repository: it owns atomic writes
    and, when a master password is active, vault encryption. This matters
    for the repair flow — writing plaintext over an encrypted profile is a
    silent downgrade the user is never told about, and it is exactly what
    happens if the wizard writes bytes itself while a vault is live. The
    wizard deliberately contains no encryption logic and no
    ProfileRepository import; the callable keeps that dependency out of
    this module.

    Type note: ProfileRepositoryPort.save_profile declares its return as
    ``object`` by deliberate design (its docstring says the signature is
    still in flux), while the concrete implementation returns a ``Path``.
    The wizard therefore annotates ``save`` against the port's honest
    promise and narrows the result at runtime — see the narrowing comment
    in run_profile_wizard.

    When ``save`` is None, the wizard falls back to a direct atomic
    plaintext write so it stays usable standalone (no repository in scope).
    Plaintext is correct on that path precisely because no vault context
    can exist there.

Repair contract:
    run_profile_wizard() accepts an optional ``prefill`` dict (a broken
    profile's parsed JSON) and ``target_path`` (the file to overwrite).
    Every prompt shows the prefill value as its default, all sections of the
    file the wizard does not own (education, work_experience, legal_info,
    app_config, ...) are preserved verbatim, and the user only has to fix
    the field that failed validation. This is how a broken profile can be
    repaired without leaving AA or hand-editing JSON.

Resume path:
    Existence is checked at entry as a WARNING, not a block. A user may
    legitimately be creating the profile before copying the file onto the
    machine (the wizard's own next-steps text tells them to do that after),
    so blocking would forbid a legitimate order of operations. The message
    states plainly whether a check found the file or not — it never implies
    a check that did not happen.
"""

from __future__ import annotations

import copy
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from auto_apply.domain.models.profile import UserProfile


class _WizardCancelled(Exception):
    """Internal signal: the user interrupted a repair re-prompt."""


def prompt(question: str, default: str = "", required: bool = False) -> str:
    """Ask one question; returns the answer, the default, or "" on Ctrl+C.

    Module-level so the validation-repair handlers below can re-prompt
    failing fields with identical behaviour to the main collection.
    """
    suffix = f" [{default}]" if default else " (required)" if required else ""
    while True:
        try:
            answer = input(f"  {question}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()  # noqa: T201
            return ""
        if answer:
            return answer
        if default:
            return default
        if not required:
            return ""
        print("  This field is required.")  # noqa: T201


def _resume_path_exists(resume_path: str, profiles_dir: Path) -> bool:
    """Mirrors the resolution rule the model uses: absolute as-is, else under profiles_dir.

    This deliberately does NOT import PersonalInfo's resolver — that helper
    is instance-bound and its validator intentionally skips existence, so a
    two-line local mirror is the honest way to check before the model exists.
    """
    candidate = Path(resume_path)
    check = candidate if candidate.is_absolute() else profiles_dir / candidate
    return check.exists()


# ─────────────────────────────────────────────────────────────────────────────
# Validation-repair handlers: one per field the wizard knows how to re-prompt.
# Each prints the pydantic message, re-prompts ONLY that field, and patches
# the profile dict in place. Everything else the user entered is untouched.
# ─────────────────────────────────────────────────────────────────────────────

def _repair_first_name(profile: dict, msg: str) -> None:
    print(f"\n  ✗ First name was rejected: {msg}")  # noqa: T201
    value = prompt("First name", default=profile["personal_info"].get("first_name", ""), required=True)
    if not value:
        raise _WizardCancelled
    profile["personal_info"]["first_name"] = value


def _repair_last_name(profile: dict, msg: str) -> None:
    print(f"\n  ✗ Last name was rejected: {msg}")  # noqa: T201
    value = prompt("Last name", default=profile["personal_info"].get("last_name", ""), required=True)
    if not value:
        raise _WizardCancelled
    profile["personal_info"]["last_name"] = value


def _repair_email(profile: dict, msg: str) -> None:
    print(f"\n  ✗ Email address was rejected: {msg}")  # noqa: T201
    value = prompt("Email address", default=profile["personal_info"].get("email", ""), required=True)
    if not value:
        raise _WizardCancelled
    profile["personal_info"]["email"] = value


def _repair_phone(profile: dict, msg: str) -> None:
    print(f"\n  ✗ Phone number was rejected: {msg}")  # noqa: T201
    value = prompt("Phone number (optional)", default=profile["personal_info"].get("phone_number", ""))
    # Optional field: an interrupt or empty answer clears it, which is valid.
    profile["personal_info"]["phone_number"] = value


def _repair_resume_path(profile: dict, msg: str) -> None:
    print(f"\n  ✗ Resume path was rejected: {msg}")  # noqa: T201
    current = str(profile["personal_info"].get("resume_path") or "resume.pdf")
    value = prompt("Path to your resume PDF", default=current)
    # Optional field: an interrupt clears it, which the model accepts (str | None).
    profile["personal_info"]["resume_path"] = value or None


def _repair_linkedin(profile: dict, msg: str) -> None:
    print(f"\n  ✗ LinkedIn URL was rejected: {msg}")  # noqa: T201
    print("    Use the full address, e.g. https://www.linkedin.com/in/yourname")  # noqa: T201
    links = profile.setdefault("links", {})
    current = links.get("linkedin") or links.get("linkedin_url") or ""
    value = prompt("LinkedIn URL (optional)", default=current)
    if value:
        links["linkedin"] = value
    else:
        # Optional field: dropping it is valid and unblocks the profile.
        links.pop("linkedin", None)


def _repair_career_summary(profile: dict, msg: str) -> None:
    print(f"\n  ✗ Career summary was rejected: {msg}")  # noqa: T201
    value = prompt("Career summary (2-3 sentences about your background)", required=True)
    if not value:
        raise _WizardCancelled
    profile["career_summary"] = value


def _repair_job_titles(profile: dict, msg: str) -> None:
    print(f"\n  ✗ Job titles were rejected: {msg}")  # noqa: T201
    current = ", ".join(profile.get("search_preferences", {}).get("desired_job_titles", []))
    value = prompt("Job titles to search for (comma-separated)", default=current, required=True)
    if not value:
        raise _WizardCancelled
    profile["search_preferences"]["desired_job_titles"] = [
        t.strip() for t in value.split(",") if t.strip()
    ]


def _repair_locations(profile: dict, msg: str) -> None:
    print(f"\n  ✗ Preferred location was rejected: {msg}")  # noqa: T201
    current = (profile.get("search_preferences", {}).get("preferred_locations") or ["Remote"])[0]
    value = prompt("Preferred location (or 'Remote')", default=current)
    profile["search_preferences"]["preferred_locations"] = [value] if value else []


_FIELD_REPAIRS = {
    ("personal_info", "first_name"): _repair_first_name,
    ("personal_info", "last_name"): _repair_last_name,
    ("personal_info", "email"): _repair_email,
    ("personal_info", "phone_number"): _repair_phone,
    ("personal_info", "resume_path"): _repair_resume_path,
    ("links", "linkedin"): _repair_linkedin,
    ("career_summary",): _repair_career_summary,
    ("search_preferences", "desired_job_titles"): _repair_job_titles,
    ("search_preferences", "preferred_locations"): _repair_locations,
}


def _reprompt_failed_fields(profile: dict, exc: ValidationError) -> bool:
    """Re-prompt every field pydantic rejected. Returns False if any error is
    outside the fields this wizard knows how to fix."""
    handled_all = True
    seen: set[tuple] = set()
    for err in exc.errors():
        # Strip list indices from the location so ("search_preferences",
        # "desired_job_titles", 0) maps to its field handler.
        loc = tuple(part for part in err["loc"] if not isinstance(part, int))
        if loc in seen:
            continue
        seen.add(loc)
        handler = _FIELD_REPAIRS.get(loc)
        if handler is None:
            loc_str = " → ".join(str(p) for p in err["loc"]) or "(top of file)"
            print(f"\n  ✗ Cannot be fixed by this wizard: {loc_str} — {err['msg']}")  # noqa: T201
            handled_all = False
            continue
        handler(profile, err["msg"])
    return handled_all


def run_profile_wizard(
    profiles_dir: Path,
    prefill: dict | None = None,
    target_path: Path | None = None,
    save: Callable[[UserProfile, Path | None], object] | None = None,
) -> Path | None:
    """Interactively create or repair a user profile. Returns the saved path.

    Args:
        profiles_dir: Directory where the profile JSON is saved.
        prefill: Optional parsed dict of an existing (broken) profile. Every
            prompt shows these values as defaults, and sections the wizard
            does not collect are preserved verbatim.
        target_path: Optional exact output path (used when repairing so the
            original filename is kept). Derived from the user's name otherwise.
        save: Optional persistence callable matching the shape the
            ProfileRepositoryPort actually promises: it accepts a UserProfile
            and an optional target path, and returns ``object`` (the port's
            declared return type — the concrete implementation returns a
            ``Path``). When supplied, the validated UserProfile is handed to
            it and the returned value locates the written file. When None,
            the wizard falls back to a direct atomic plaintext write
            (standalone use; no vault context can exist there, so plaintext
            is correct).

    Returns:
        Absolute Path to the saved profile file, or None if the user
        cancelled, validation could not be completed, or the write failed.
        Nothing is persisted unless the whole profile validates and the
        write succeeds.
    """
    print("\n" + "═" * 60)  # noqa: T201
    if prefill is not None:
        print(f"  Repairing profile '{prefill.get('profile_name', 'unknown')}'")  # noqa: T201
        print("  Press Enter to keep the value shown in [brackets];")  # noqa: T201
        print("  type a new value to change it. Ctrl+C cancels without saving.")  # noqa: T201
    else:
        print("  Welcome to AutoApply!")  # noqa: T201
        print("  No profile found. Let's create one now.")  # noqa: T201
        print("  (Press Ctrl+C at any time to exit)")  # noqa: T201
    print("═" * 60 + "\n")  # noqa: T201

    pf_personal = (prefill or {}).get("personal_info", {}) or {}
    pf_links = (prefill or {}).get("links", {}) or {}
    pf_search = (prefill or {}).get("search_preferences", {}) or {}

    print("── Personal Information ─────────────────────────────────────")  # noqa: T201
    first_name = prompt(
        "First name",
        default=str(pf_personal.get("first_name", "")),
        required=True,
    )
    if not first_name:
        print("  Profile creation cancelled.")  # noqa: T201
        return None

    last_name = prompt(
        "Last name",
        default=str(pf_personal.get("last_name", "")),
        required=True,
    )
    if not last_name:
        print("  Profile creation cancelled.")  # noqa: T201
        return None

    email = prompt(
        "Email address",
        default=str(pf_personal.get("email", "")),
        required=True,
    )
    if not email:
        print("  Profile creation cancelled.")  # noqa: T201
        return None

    phone = prompt("Phone number", default=str(pf_personal.get("phone_number", "")))

    linkedin_url = prompt(
        "LinkedIn URL (optional)",
        default=str(pf_links.get("linkedin") or pf_links.get("linkedin_url") or ""),
    )

    # ── Resume path: existence warning, not a block ──────────────────────────
    pf_resume = str(pf_personal.get("resume_path") or "")
    resume_path: str | None = prompt(
        "Path to your resume PDF",
        default=pf_resume or "resume.pdf",
    )
    if not resume_path:
        resume_path = pf_resume or "resume.pdf"

    while True:
        if resume_path == "resume.pdf":
            candidate = profiles_dir / resume_path
            if candidate.exists():
                print(f"  ✓ Found your resume: {candidate}")  # noqa: T201
            else:
                print(f"  → No resume found there yet. Copy your PDF to: {candidate}")  # noqa: T201
                print("    (The file is NOT required to finish this profile.)")  # noqa: T201
            break
        if _resume_path_exists(resume_path, profiles_dir):
            break
        candidate = Path(resume_path)
        check = candidate if candidate.is_absolute() else profiles_dir / candidate
        print(f"\n  ⚠ No file found at: {check}")  # noqa: T201
        print("    You can keep this path and copy the file there later,")  # noqa: T201
        print("    or enter a different path now.")  # noqa: T201
        try:
            keep = input("  Keep this path anyway? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()  # noqa: T201
            keep = ""
        if keep not in ("n", "no"):
            break
        resume_path = prompt("Path to your resume PDF", default="resume.pdf", required=True)
        if not resume_path:
            print("  Profile creation cancelled.")  # noqa: T201
            return None

    print()  # noqa: T201
    print("── Job Search Preferences ───────────────────────────────────")  # noqa: T201
    pf_titles = ", ".join(pf_search.get("desired_job_titles", []) or [])
    job_titles_raw = prompt(
        "Job titles to search for (comma-separated)",
        default=pf_titles or "Software Engineer",
    )
    job_titles = [t.strip() for t in job_titles_raw.split(",") if t.strip()]
    pf_locations = pf_search.get("preferred_locations", []) or []
    location = prompt(
        "Preferred location (or 'Remote')",
        default=pf_locations[0] if pf_locations else "Remote",
    )

    print()  # noqa: T201
    print("── Career Summary ──────────────────────────────────────────")  # noqa: T201
    print("  Write 2-3 sentences about your background.")  # noqa: T201
    print("  This is used for open-ended form questions.")  # noqa: T201
    career_summary = prompt(
        "Career summary",
        default=str((prefill or {}).get("career_summary", "")),
        required=True,
    )
    if not career_summary:
        print("  Profile creation cancelled.")  # noqa: T201
        return None

    # ── Assemble the profile dict (prefill preserved verbatim where present) ──
    if prefill is not None:
        profile: dict[str, Any] = copy.deepcopy(prefill)
    else:
        profile = {
            "personal_info": {},
            "links": {},
            "education": [],
            "work_experience": [],
            "references": [],
            "legal_info": {},
            "search_preferences": {},
            "application_preferences": {},
            "app_config": {},
            "politeness_settings": {},
            "custom_answer_templates": [],
        }

    profile["profile_name"] = (
        (prefill or {}).get("profile_name") or f"{first_name} {last_name}"
    )

    personal = profile.setdefault("personal_info", {})
    personal["first_name"] = first_name
    personal["last_name"] = last_name
    personal["email"] = email
    if phone:
        personal["phone_number"] = phone
    else:
        personal.setdefault("phone_number", "")
    personal["resume_path"] = resume_path
    personal.setdefault("street_address", "")
    personal.setdefault("city", "")
    personal.setdefault("state", "")
    personal.setdefault("zip_code", "")
    personal.setdefault("country", "United States")

    links = profile.setdefault("links", {})
    if linkedin_url:
        links["linkedin"] = linkedin_url

    profile["career_summary"] = career_summary

    search = profile.setdefault("search_preferences", {})
    search["desired_job_titles"] = job_titles
    search["preferred_locations"] = [location] if location else []
    search.setdefault("employment_types", ["full-time"])
    search.setdefault("workplace_types", ["remote", "hybrid"])
    search.setdefault("skills", [])

    legal = profile.setdefault("legal_info", {})
    legal.setdefault("requires_sponsorship", False)
    legal.setdefault("has_work_authorization", True)
    legal.setdefault("non_compete_agreements", [])

    app_config = profile.setdefault("app_config", {})
    app_config.setdefault("preferred_browser", "any")
    app_config.setdefault("headless_mode", False)
    app_config.setdefault("daily_application_limit", 50)
    app_config.setdefault("enable_behavior_humanization", True)

    politeness = profile.setdefault("politeness_settings", {})
    politeness.setdefault("respect_robots_txt", True)
    politeness.setdefault("default_delay", 2.0)

    profile.setdefault("application_preferences", {})
    profile.setdefault("custom_answer_templates", [])
    profile.setdefault("education", [])
    profile.setdefault("work_experience", [])
    profile.setdefault("references", [])

    # ── Validate through the SAME model the repository will use later ────────
    while True:
        try:
            model = UserProfile(**profile)
            break
        except ValidationError as exc:
            try:
                handled = _reprompt_failed_fields(profile, exc)
            except _WizardCancelled:
                print("\n  Profile creation cancelled. Nothing was written.")  # noqa: T201
                return None
            if not handled:
                print("\n  Profile was NOT saved — nothing has been written to disk.")  # noqa: T201
                print("  You can edit the JSON by hand, or delete the file and start again.")  # noqa: T201
                return None

    # ── Persist, only after full validation ──────────────────────────────────
    profiles_dir.mkdir(parents=True, exist_ok=True)
    if target_path is not None:
        profile_path = target_path
    else:
        filename = f"{first_name.lower()}_{last_name.lower()}_profile.json"
        profile_path = profiles_dir / filename

    if save is not None:
        # Persistence is delegated to the caller's save callable (in practice
        # ProfileRepository.save_profile, passed through the port): it owns
        # atomic writes and, when a master password is active, vault
        # encryption. The wizard never writes bytes itself on this path, so
        # it cannot downgrade an encrypted file to plaintext.
        try:
            saved = save(model, profile_path)
        except Exception as exc:
            print(f"\n  ✗ Could not save the profile: {exc}")  # noqa: T201
            print("    Nothing was written.")  # noqa: T201
            return None

        # The port (ProfileRepositoryPort.save_profile) declares its return
        # as `object` by deliberate design — its docstring says the signature
        # is still in flux — while the concrete ProfileRepository
        # implementation returns a Path. Narrowing here is a REAL boundary,
        # not defensive noise: the wizard needs a Path for its follow-up
        # messages, the type system cannot promise one, and a future reader
        # must not "simplify" this into assuming the return is always a Path.
        if isinstance(saved, Path):
            profile_path = saved
        elif isinstance(saved, str) and saved:
            profile_path = Path(saved)
        # Anything else (including None): fall back to profile_path, the
        # destination the wizard requested — the repository honours
        # target_path, so the file is where we asked it to be.
    else:
        # Standalone fallback: direct atomic plaintext write, used only when
        # no save callable was supplied. Plaintext is correct here precisely
        # because no vault context can exist on this path.
        tmp_path = profile_path.with_name(profile_path.name + ".tmp")
        try:
            tmp_path.write_text(
                model.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
            )
            os.replace(tmp_path, profile_path)
        except OSError as exc:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            print(f"\n  ✗ Could not write the profile file: {exc}")  # noqa: T201
            print("    Nothing was saved.")  # noqa: T201
            return None

    print()  # noqa: T201
    if prefill is not None:
        print(f"  ✓ Profile repaired and saved: {profile_path}")  # noqa: T201
        print()  # noqa: T201
        print("  Run AutoApply again to use it.")  # noqa: T201
    else:
        print(f"  ✓ Profile saved: {profile_path}")  # noqa: T201
        print()  # noqa: T201
        print("  Next steps:")  # noqa: T201
        if not _resume_path_exists(resume_path, profiles_dir):
            print(f"  1. Copy your resume to: {profiles_dir / resume_path}")  # noqa: T201
            print(f"  2. Edit {profile_path.name} to add work experience and skills")  # noqa: T201
            print("  3. Run AutoApply again to start searching")  # noqa: T201
        else:
            print(f"  1. Edit {profile_path.name} to add work experience and skills")  # noqa: T201
            print("  2. Run AutoApply again to start searching")  # noqa: T201
    print()  # noqa: T201

    return profile_path

"""Pins for the first-run identity defect and the Settings layout contract:
the GUI must never save a profile it did not ask the user for, the validator
must catch template identity wherever it survives without blocking honest
users, the GUI must always be able to repair it — and the Save button must
stay visible while it happens.

Pin labels are stated honestly in each docstring:

  TEETH       — verified to fail against the pre-fix tree for the reason given.
  GUARD       — passes on both trees; freezes behaviour a future "fix" must
                not silently change (characterisation).
  COVERAGE    — pins behaviour of code introduced by this change; failure on
                the old tree only proves the feature was absent, so it is
                labelled coverage, not teeth.
  SOURCE PIN  — asserts structure in source text. It CANNOT prove rendered
                layout. Each source pin says exactly what it does and does
                not catch.

The two-template reality this file encodes: resources/templates/default_profile.json
does NOT parse as a UserProfile (requires_sponsorship: "None" violates the
model — it is now valid JSON, but not model-valid), while
resources/templates/template_profile.json DOES parse as a UserProfile and is
what ProfileRepository seeds into PROFILES_DIR/default_profile.json. The
contamination check must therefore read every *.json in the templates
directory — pin 11 locks that in.

A second reality: _walk_leaves produces FULLY DOTTED leaf paths —
education[0].school comes out as "education.school", not bare "education" —
and the assertions here match that measured behaviour.

A third reality, owned plainly: _string_constants EXCLUDES docstrings (see
the helper's docstring). The two pins that use it mean "no string literal
used as a VALUE" — prose is deliberately not evidence.
"""

from __future__ import annotations

import ast
import json
from importlib import resources as importlib_resources
from pathlib import Path

import pytest

from auto_apply.application.services.profile_validator import (
    find_template_contamination,
    validate_profile,
)
from auto_apply.application.services.ui_schema import build_ui_schema
from auto_apply.domain.models.profile import UserProfile, make_portable_path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "auto_apply"
GUI_APP = SRC_ROOT / "adapters" / "primary" / "gui" / "app.py"
SETTINGS_EDITOR = SRC_ROOT / "adapters" / "primary" / "gui" / "settings_editor.py"
CLI_WIZARD = SRC_ROOT / "adapters" / "primary" / "cli" / "profile_wizard.py"


def _template_doc(name: str) -> dict:
    return json.loads(
        (importlib_resources.files("auto_apply.resources.templates") / name).read_text(
            encoding="utf-8"
        )
    )


def _string_constants(path: Path) -> list[str]:
    """String literals used as VALUES in *path*, with docstrings excluded.

    A docstring is the first statement of a Module, ClassDef, FunctionDef or
    AsyncFunctionDef body when that statement is a bare string Constant.
    Prose is deliberately NOT evidence: the pins that consume this helper
    assert "the template name is never used as a value", not "the template
    name is never mentioned in a comment". (An earlier version of this
    helper collected docstrings too and fired on profile_wizard.py's own
    module docstring — measured, not inferred.)
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstring_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
            ):
                docstring_nodes.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstring_nodes
    ]


def _clean_values() -> dict[str, str]:
    """Sample onboarding answers that share NOTHING distinctive with templates."""
    return {
        "profile_name": "ada-dev",
        "personal_info.first_name": "Ada",
        "personal_info.last_name": "Lovelace",
        "personal_info.email": "ada@example.com",
        "personal_info.phone_number": "555-0100",
        "personal_info.street_address": "12 Analytical Way",
        "personal_info.city": "Austin",
        "personal_info.state": "TX",
        "personal_info.zip_code": "78701",
        "personal_info.resume_path": "",
        "career_summary": (
            "Backend developer with four years building data pipelines and "
            "internal tools. I like small, well-tested systems."
        ),
        "search_preferences.desired_job_titles": "Data Scientist",
    }


# ─────────────────────────────────────────────────────────────────────────────
# TEETH: onboarding must not touch the template — source level
# ─────────────────────────────────────────────────────────────────────────────


def test_onboarding_source_has_no_template_reference() -> None:
    """TEETH: gui/app.py must not use the template profile's name as a value.

    Fails on the pre-fix tree: _show_onboarding loads the template and saves
    its identity. The literal now lives only in
    profile_validator.TEMPLATE_PROFILE_NAME, which app.py imports for the
    bootstrap filter. Prose is deliberately NOT evidence here — a docstring
    mentioning the template's history is fine; what is pinned is that no
    string literal carrying the template name is used as a value.
    """
    constants = _string_constants(GUI_APP)
    assert not any("default_profile" in c for c in constants), (
        "gui/app.py uses the template profile name as a value — onboarding "
        "must build a profile from user input only"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEETH: the template profile fails validation, naming the email field
# ─────────────────────────────────────────────────────────────────────────────


def test_template_profile_fails_validation_naming_email() -> None:
    """TEETH: a template-copied profile must fail, naming personal_info.email.

    Fails on the pre-fix tree: validate_profile only checked presence, so
    the placeholder identity validated clean. Uses template_profile.json —
    the file that actually seeds PROFILES_DIR and parses as a UserProfile.
    It trips on MANY distinctive identity fields at once (email, phone,
    address, resume path, links, career summary, work description), which is
    exactly the >= 2 match rate the severity rule blocks on.
    """
    profile = UserProfile(**_template_doc("template_profile.json"))
    result = validate_profile(profile)
    assert not result.is_valid, "the template identity validated clean"
    joined = "\n".join(result.errors)
    assert "personal_info.email" in joined, (
        f"the contamination error must name personal_info.email; got: {joined}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEETH: the check reaches references and work history, not just personal_info
# ─────────────────────────────────────────────────────────────────────────────


def test_contamination_check_flags_reference_email_and_work_history() -> None:
    """TEETH: template values in references/work_experience are caught too.

    Fails on the pre-fix tree: nothing looked past personal_info. Carries
    the template's reference NAME ("Steve Harris", 12 chars, distinctive)
    and phone_number ("911-555-1234", phone-shaped, distinctive) from
    resources/templates/default_profile.json into a VALID profile — its own
    reference email is replaced with a valid one, because that file's
    reference email ("steve..harry.harris@hotmail.com", two consecutive
    periods) is rejected by EmailStr. The pin's point stands: references are
    walked, and a match anywhere in them is caught.
    """
    data = _template_doc("template_profile.json")
    data["references"] = [
        {
            "name": "Steve Harris",
            "job_title": "Bandmate",
            "company": "RealCo",
            "email": "steve.harris@example.com",
            "phone_number": "911-555-1234",
        }
    ]
    data["work_experience"][0]["description"] = (
        _template_doc("default_profile.json")["work_experience"][0]["description"]
    )
    profile = UserProfile(**data)

    contaminated = find_template_contamination(profile)
    assert any(p.startswith("references") for p in contaminated), (
        f"reference name/phone not flagged: {contaminated}"
    )
    assert any(p.startswith("work_experience") for p in contaminated), (
        f"work-history description not flagged: {contaminated}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# COVERAGE: onboarding-built profiles contain no template identity at all
# ─────────────────────────────────────────────────────────────────────────────


def test_onboarding_build_profile_contains_no_template_values() -> None:
    """COVERAGE: a profile built by GUI onboarding carries zero template data.

    Labelled coverage, not teeth: the pre-fix tree never copied references
    or legal_info, because template_profile.json — the file that actually
    seeds PROFILES_DIR — contains neither block. What the pre-fix tree DID
    copy verbatim was work_experience (Iron Maiden), education (Queen Mary),
    career_summary and links, and it saved legal declarations from the
    model's defaults without ever asking. The new builder creates
    references/work_experience/education empty and takes legal answers only
    from the user's explicit radio choices.
    """
    from auto_apply.adapters.primary.gui.app import _build_profile_from_onboarding

    profile = _build_profile_from_onboarding(
        _clean_values(),
        {"has_work_authorization": True, "requires_sponsorship": False},
    )

    assert profile.references == [], "references must start empty, not copied"
    assert profile.work_experience == [], "work history must start empty"
    assert profile.legal_info.has_work_authorization is True
    assert profile.legal_info.requires_sponsorship is False
    assert find_template_contamination(profile) == [], (
        "onboarding produced a profile the contamination check rejects"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEETH: every required schema field has a GUI write path
# ─────────────────────────────────────────────────────────────────────────────


def test_all_required_schema_fields_have_gui_write_path() -> None:
    """TEETH: required fields must be collectible at creation AND repairable.

    Fails on the pre-fix tree: onboarding collected 2 fields and no GUI
    screen could edit name/email/phone/address. Behavioural pin, not a
    source-grep: it calls the same schema-driven helpers the wizard and the
    About-you tab render from, so it cannot be satisfied by hardcoded lists.
    """
    from auto_apply.adapters.primary.gui.app import _onboarding_schema_fields
    from auto_apply.adapters.primary.gui.settings_editor import _about_you_field_keys

    required = {f.key for f in build_ui_schema(UserProfile, "en") if f.required}
    onboarding = {f.key for f in _onboarding_schema_fields()}
    about_you = set(_about_you_field_keys())

    missing_everywhere = required - (onboarding | about_you)
    assert not missing_everywhere, (
        f"required fields with no write path anywhere in the GUI: "
        f"{sorted(missing_everywhere)}"
    )

    # The repair path must cover every identity field validation can flag.
    # profile_name is intentionally creation-only (renaming changes the
    # on-disk filename; the tab shows it read-only).
    missing_repair = (required - {"profile_name"}) - about_you
    assert not missing_repair, (
        f"required identity fields the About-you tab cannot repair: "
        f"{sorted(missing_repair)}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEETH (new feature): About you is the first tab of the settings editor
# ─────────────────────────────────────────────────────────────────────────────


def test_about_you_tab_is_first_in_settings_editor() -> None:
    """TEETH (new feature presence): About you is built before Browser Engine.

    Fails on the pre-fix tree because the tab did not exist. Ordered first so
    the repair path is the first thing a user sees when they open Settings.
    """
    source = SETTINGS_EDITOR.read_text(encoding="utf-8")
    about_idx = source.index("self._build_about_you_tab(notebook)")
    browser_idx = source.index("self._build_browser_tab(notebook)")
    assert about_idx < browser_idx, "About you must be the first tab built"


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE PIN: Save/Cancel buttons pack BEFORE the notebook
# ─────────────────────────────────────────────────────────────────────────────


def test_save_buttons_pack_before_notebook_source_pin() -> None:
    """SOURCE PIN: btn_frame.pack must precede notebook.pack in the source.

    The rendered-layout defect this guards: Tk's packer allocates in order
    and expand=True children get only leftover space, so notebook-first
    packing allocates the button frame zero height and the Save button
    vanishes — measured on the applied tree, invisible to this suite at the
    time. This pin catches a revert of that two-line order. It CANNOT prove
    rendered layout: it would not catch a different pack-order bug, a Tk
    version behaviour change, or a geometry miscalculation elsewhere.
    """
    source = SETTINGS_EDITOR.read_text(encoding="utf-8")
    btn_idx = source.index("btn_frame.pack(")
    notebook_idx = source.index("notebook.pack(")
    assert btn_idx < notebook_idx, (
        "the Save/Cancel frame must pack BEFORE the notebook so the packer "
        "reserves its height — notebook-first packing makes it vanish"
    )


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE PIN: the About-you tab is built inside a scrolling canvas
# ─────────────────────────────────────────────────────────────────────────────


def test_about_you_tab_is_scrollable_source_pin() -> None:
    """SOURCE PIN: About-you content must be built via the scrolling helper.

    Twelve label+entry rows do not fit a 1366x768 laptop screen — AA's
    worst-case user — so the tab's content frame must come from
    _build_scrollable_tab, which constructs a Canvas with an inner Frame and
    a vertical Scrollbar. This pin catches removal of the scroll wrapper. It
    CANNOT prove rendered layout: it would not catch a broken scrollregion
    update, a mousewheel binding that never fires, or content that still
    overflows for other reasons.
    """
    source = SETTINGS_EDITOR.read_text(encoding="utf-8")
    about_src = source[
        source.index("def _build_about_you_tab") : source.index(
            "def _resolve_profile_value"
        )
    ]
    assert "_build_scrollable_tab(" in about_src, (
        "the About-you tab must build its content frame via the scrolling "
        "helper, not a fixed-height frame"
    )
    assert "tk.Canvas(" in source and "ttk.Scrollbar(" in source, (
        "the scrolling helper must construct a Canvas and a vertical Scrollbar"
    )


# ─────────────────────────────────────────────────────────────────────────────
# GUARD (characterisation): make_portable_path on a relative input is stable
# ─────────────────────────────────────────────────────────────────────────────


def test_make_portable_path_relative_input_unchanged(tmp_path, monkeypatch) -> None:
    """GUARD (characterisation): relative input returns unchanged from any CWD.

    Passes today. Explicitly NOT a defect — the except ValueError branch in
    make_portable_path returns the original string, and this pin exists so a
    future "fix" cannot silently change that contract.
    """
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setattr("auto_apply.domain.config.PROFILES_DIR", profiles)
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)

    assert make_portable_path("resume.pdf") == "resume.pdf"


# ─────────────────────────────────────────────────────────────────────────────
# GUARD: the CLI profile wizard must never touch the template
# ─────────────────────────────────────────────────────────────────────────────


def test_cli_profile_wizard_never_touches_template() -> None:
    """GUARD: the CLI wizard uses no template value — prose is not evidence.

    Owned plainly: I labelled this pin "passes today" without running it;
    measured, the first version failed because _string_constants collected
    the module's own docstring ("bundled default_profile template"). The
    helper now excludes docstrings, so this pin means what it always should
    have meant: no string literal carrying the template name is used as a
    VALUE anywhere in the CLI wizard. A docstring mentioning the template's
    history remains fine.
    """
    constants = _string_constants(CLI_WIZARD)
    assert not any("default_profile" in c for c in constants), (
        "cli/profile_wizard.py uses the template profile name as a value"
    )


# ─────────────────────────────────────────────────────────────────────────────
# GUARD (collision safety): a real user's profile passes validation
# ─────────────────────────────────────────────────────────────────────────────


def test_clean_profile_passes_validation() -> None:
    """GUARD: a normal profile with zero template values validates clean.

    Passes on both trees — the contamination check must not break the
    legitimate path it now guards.
    """
    from auto_apply.adapters.primary.gui.app import _build_profile_from_onboarding

    profile = _build_profile_from_onboarding(
        _clean_values(),
        {"has_work_authorization": True, "requires_sponsorship": False},
    )
    result = validate_profile(profile)
    assert result.is_valid, f"clean profile rejected: {result.errors}"


# ─────────────────────────────────────────────────────────────────────────────
# GUARD (collision rule): benign collisions can never trip the check
# ─────────────────────────────────────────────────────────────────────────────


def test_contamination_ignores_booleans_none_and_enum_values() -> None:
    """GUARD: shared booleans/enum values/geo strings are not contamination.

    Passes on both trees. The profile below shares has_work_authorization,
    requires_sponsorship, gender, race, workplace types, city and country
    with the template — all of which a real user may legitimately hold —
    while its distinctive identity fields (email, phone, address, resume
    path, links, career summary, education school, work description) are its
    own. The education school and work-history description ARE replaced here:
    leaving the template's values in those two fields would be two matches,
    which under the severity rule is a blocking error — that is a different
    pin (pin 12 covers the single-match case). If the check ever starts
    flagging the benign collisions kept here, most real users would be
    accused of contamination.
    """
    data = _template_doc("template_profile.json")
    info = data["personal_info"]
    info.update(
        {
            "first_name": "Grace",
            "last_name": "Hopper",
            "email": "grace@example.com",
            "phone_number": "555-0199",
            "street_address": "1 Compiler Lane",
            "resume_path": None,
        }
    )
    data["career_summary"] = (
        "Computer scientist and rear admiral. I write compilers and teach."
    )
    data["links"] = {}
    data["education"][0]["school"] = "University of Cambridge"
    data["work_experience"][0]["description"] = (
        "Built one of the first compilers and led early standardisation work."
    )
    # city stays "London", country stays "United Kingdom", gender "Male",
    # legal bools stay as the template's — those are the exact benign
    # collisions under test, and they must NOT be flagged.
    profile = UserProfile(**data)
    assert find_template_contamination(profile) == [], (
        f"benign collisions flagged: {find_template_contamination(profile)}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# COVERAGE (new behaviour): the template value set covers BOTH template files
# ─────────────────────────────────────────────────────────────────────────────


def test_contamination_check_reads_all_template_files() -> None:
    """COVERAGE: values unique to EACH template file are evidence.

    New-code pin: the old tree has no template-value machinery at all. This
    locks in the two-template reality — one file is not model-valid, the
    other seeds PROFILES_DIR — so the check cannot rely on either file
    alone. It also depends on default_profile.json being loadable JSON.
    """
    from auto_apply.application.services import profile_validator

    values = profile_validator._template_value_set()
    default_doc = _template_doc("default_profile.json")
    template_doc = _template_doc("template_profile.json")

    assert default_doc["references"][0]["email"] in values, (
        "the reference email unique to default_profile.json is not evidence"
    )
    assert template_doc["links"]["github"] in values, (
        "the GitHub URL unique to template_profile.json is not evidence"
    )


# ─────────────────────────────────────────────────────────────────────────────
# COVERAGE (severity rule): a single template match warns but does not block
# ─────────────────────────────────────────────────────────────────────────────


def test_single_template_match_warns_but_does_not_block() -> None:
    """COVERAGE: a profile whose ONLY template match is its own school passes.

    The severity rule: exactly 1 match -> warning, session proceeds; 2+
    matches -> blocking error. This pin is coverage, not teeth: on the
    pre-fix tree no contamination machinery existed, so this profile would
    pass for the wrong reason (nothing checked at all) — the assertion that
    fails pre-fix is the WARNING naming education, i.e. the feature that did
    not exist. The case under test is the canonical false positive the rule
    exists to prevent: a genuine graduate of the template's school typing
    their own education must not be blocked and accused of template data.

    The assertion uses the measured leaf path "education.school" — the walk
    descends into list items' dicts and reports the full dotted path.
    """
    data = _template_doc("template_profile.json")
    info = data["personal_info"]
    info.update(
        {
            "first_name": "Grace",
            "last_name": "Hopper",
            "email": "grace@example.com",
            "phone_number": "555-0199",
            "street_address": "1 Compiler Lane",
            "resume_path": None,
        }
    )
    data["career_summary"] = (
        "Computer scientist and rear admiral. I write compilers and teach."
    )
    data["links"] = {}
    data["work_experience"][0]["description"] = (
        "Built one of the first compilers and led early standardisation work."
    )
    # education is left EXACTLY as the template's — "Queen Mary University of
    # London" — the single deliberate match.
    profile = UserProfile(**data)

    assert find_template_contamination(profile) == ["education.school"], (
        f"expected exactly one match (education.school); got "
        f"{find_template_contamination(profile)}"
    )

    result = validate_profile(profile)
    assert result.is_valid, (
        f"a single honest collision blocked the session: {result.errors}"
    )
    assert any("education" in w for w in result.warnings), (
        f"the single match must surface as a warning naming the field; "
        f"warnings were: {result.warnings}"
    )

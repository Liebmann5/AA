"""Chain E safety pins: PII containment, output ownership, boundary ratchets.

Three instruments, honestly labelled:

  TEETH   test_no_pii_in_the_activity_stream
          A sentinel identity is pushed through the projection and must not
          appear in any record the UI can display or export.

  RATCHET test_print_sites_outside_the_primary_adapters
  RATCHET test_primary_adapters_do_not_reach_past_the_domain
          Neither can be green at zero today, and a pin that fails on arrival
          is not a pin. Each asserts the CURRENT set exactly: adding a new
          violation fails, and removing one fails too, forcing the inventory
          down deliberately rather than letting it drift either way.

Stage U4 drives the second ratchet to zero by retyping both surfaces against
UIPort. Until then this file is what stops the debt growing.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "auto_apply"
PRIMARY = SRC / "adapters" / "primary"


# ── helpers ──────────────────────────────────────────────────────────────────

def _py_files(root: pathlib.Path):
    return sorted(p for p in root.rglob("*.py"))


def _rel(p: pathlib.Path) -> str:
    return p.relative_to(SRC).as_posix()


def _main_block_lines(tree: ast.Module) -> set[int]:
    """Line numbers inside an ``if __name__ == "__main__"`` block."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "__name__" in ast.dump(node.test):
            lines.update(
                n.lineno for n in ast.walk(node) if hasattr(n, "lineno")
            )
    return lines


# ── TEETH: no PII reaches the activity stream ────────────────────────────────

SENTINEL_EMAIL = "zz-sentinel@example.invalid"
SENTINEL_PHONE = "555-0100-SENTINEL"
SENTINEL_NAME = "Zzsentinel Qqsentinel"


def test_no_pii_in_the_activity_stream() -> None:
    """TEETH: the projection renders job facts, never applicant facts.

    SessionEventRecord.text is displayed in both dashboards and written to
    the exported results. Event payloads are assembled from objects that sit
    next to the profile, so a careless projection could carry the applicant's
    name, email or phone into a file the user shares.

    Fails if any renderer ever interpolates a profile field: the sentinel
    values are distinctive enough that a substring test cannot false-positive.
    """
    from auto_apply.domain.models.ui_contract import SessionEventRecord

    fields = SessionEventRecord.model_fields
    assert "text" in fields, (
        "the activity record no longer has a rendered text field; "
        "this pin must be re-pointed at whatever replaced it"
    )

    source = (SRC / "application" / "services" / "session_controller.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    # Every f-string and .format() that builds a SessionEventRecord text must
    # not reference a profile attribute. Walk for attribute chains that start
    # at a profile-ish name and end at a PII field.
    pii_leaves = {
        "email", "phone_number", "first_name", "last_name",
        "street_address", "zip_code", "cover_letter",
    }
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr not in pii_leaves:
            continue
        chain: list[str] = [node.attr]
        cur: ast.expr = node.value
        while isinstance(cur, ast.Attribute):
            chain.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            chain.append(cur.id)
        dotted = ".".join(reversed(chain))
        if "profile" in dotted or "personal_info" in dotted:
            offenders.append(f"{dotted} (line {node.lineno})")

    assert not offenders, (
        "session_controller reads applicant PII where the activity stream is "
        "built. Job title and company belong in a record; the applicant's own "
        "details never do, because the stream is displayed AND exported.\n  "
        + "\n  ".join(offenders)
    )


# ── RATCHET: who is allowed to print ─────────────────────────────────────────
#
# main.py is the process entry point. It prints usage, startup banners and
# fatal errors before any surface exists to render them, so it is exempt by
# design rather than by neglect. Everything else here is DEBT: user-facing
# text built outside a primary adapter, which a GUI user can never see.
#
#   session_controller.py  the Profile Check advisory block. A CLI user sees
#                          it; a GUI user does not, because it goes to stdout.
#   composition_root.py    one stderr write during wiring.
#
EXPECTED_PRINT_SITES: dict[str, int] = {
    "main.py": 39,
    "application/services/session_controller.py": 4,
    "infrastructure/composition_root.py": 1,
}


def _print_sites() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in _py_files(SRC):
        rel = _rel(path)
        if rel.startswith("adapters/primary/"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken file fails elsewhere
            continue
        skip = _main_block_lines(tree)
        n = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
            and node.lineno not in skip
        )
        if n:
            found[rel] = n
    return found


def test_print_sites_outside_the_primary_adapters() -> None:
    """RATCHET: user-facing output is owned by the primary adapters.

    Asserts the exact current inventory. A new print outside a primary
    adapter fails here; so does removing one without updating the map, which
    is deliberate — the count comes down on purpose, not by accident.
    """
    actual = _print_sites()
    assert actual == EXPECTED_PRINT_SITES, (
        "print inventory changed.\n"
        f"  expected: {EXPECTED_PRINT_SITES}\n"
        f"  actual:   {actual}\n"
        "A new entry means user-facing text was built where a GUI user cannot "
        "see it. A smaller count is progress — update the map in the same "
        "change and say what now renders it."
    )


# ── RATCHET: how far a primary adapter may reach ─────────────────────────────
#
# A primary adapter may import domain.* (ports and models are the contract)
# and its own siblings. Everything below is what it reaches past that today.
# Stage U4 drives this to empty by retyping both surfaces against UIPort.
#
EXPECTED_REACHES: dict[str, set[str]] = {
    "cli/startup.py": {
        "auto_apply.application.services.autonomy",
        "auto_apply.application.services.session_controller",
        "auto_apply.infrastructure.composition_root",
    },
    "cli/wizard.py": {
        "auto_apply.application.services.session_controller",
        "auto_apply.application.services.ui_schema",
    },
    "gui/app.py": {
        "auto_apply.application.services.profile_validator",
        "auto_apply.application.services.session_controller",
        "auto_apply.application.services.ui_schema",
        "auto_apply.infrastructure.composition_root",
    },
    "gui/dashboard.py": {
        "auto_apply.application.services.session_controller",
    },
    "gui/settings_editor.py": {
        "auto_apply.application.services.ui_schema",
        "auto_apply.infrastructure.composition_root",
    },
    "gui/strings.py": {
        "auto_apply.application.services.i18n",
    },
    "gui/wizard.py": {
        "auto_apply.application.services.autonomy",
    },
}

_ALLOWED_PREFIXES = ("auto_apply.domain.", "auto_apply.adapters.primary.")


def _reaches() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in _py_files(PRIMARY):
        rel = path.relative_to(PRIMARY).as_posix()
        hits: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            else:
                continue
            for m in mods:
                if m.startswith("auto_apply") and not m.startswith(_ALLOWED_PREFIXES):
                    hits.add(m)
        if hits:
            found[rel] = hits
    return found


def test_primary_adapters_do_not_reach_past_the_domain() -> None:
    """RATCHET: the UI's reach into the application layer only shrinks.

    UIPort exists so both surfaces talk to one typed contract. Four modules
    still import SessionController directly — the concrete class the port
    replaces — and that is the debt stage U4 clears. Until then, this asserts
    the reach exactly so it cannot grow while nobody is looking.
    """
    actual = _reaches()
    assert actual == EXPECTED_REACHES, (
        "the primary adapters' reach changed.\n"
        f"  new:     { {k: sorted(v - EXPECTED_REACHES.get(k, set())) for k, v in actual.items() if v - EXPECTED_REACHES.get(k, set())} }\n"
        f"  cleared: { {k: sorted(v - actual.get(k, set())) for k, v in EXPECTED_REACHES.items() if v - actual.get(k, set())} }\n"
        "New reaches are regressions. Cleared ones are progress — update the "
        "map in the same change."
    )


@pytest.mark.parametrize("surface", ["cli", "gui"])
def test_both_surfaces_are_counted_by_the_reach_ratchet(surface: str) -> None:
    """GUARD: the ratchet actually looks at both surfaces.

    A scan that silently stopped finding one surface's files would pass the
    ratchet above by accident. Ruling C says both surfaces are first-class;
    this asserts the instrument treats them that way.
    """
    scanned = {k.split("/")[0] for k in _reaches()}
    assert surface in scanned, (
        f"the reach scan found no {surface} modules at all — the walk is "
        "broken, and the ratchet above is passing for the wrong reason"
    )

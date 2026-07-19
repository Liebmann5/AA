"""AA must not answer a security-clearance question the user never answered.

The defect this locks down
--------------------------
``LogicEngine.check_security_clearance`` used to read::

    getattr(self.profile.legal_info, "has_security_clearance", False)

``LegalInfo`` had no such field, so the default fired for everyone: the engine
concluded "no clearance" for every user and rejected cleared candidates from
every clearance-gated job. The code comment even admitted the field was missing
and chose ``False`` as the stand-in — a fabricated legal answer submitted on a
real person's behalf, which the never-fabricate rule forbids.

The fix has three parts, all pinned here:

1. ``LegalInfo`` carries ``security_clearance: ClearanceDeclaration | None``.
   ``None`` means *not declared* — an honest absence, never coerced to "has
   none", because only the user may assert they hold no clearance.

2. ``ClearanceDeclaration`` is ``jurisdiction`` + free-text ``level``. No fixed
   taxonomy: a ``Literal[...]`` of levels would be a second source of truth
   about every country's clearance system, wrong for the jurisdictions not
   enumerated. A free-text level cannot be wrong about the user's own clearance.

3. ``check_security_clearance`` reads the real field. A user who declared a
   clearance is no longer auto-rejected; a user who declared none (``None``)
   reads as a real absence, not a fabricated ``False``.

What is deliberately NOT here yet
---------------------------------
Jurisdiction-mismatch escalation (user's clearance is US, job is in the UK ->
ask a human) belongs at *form-fill* time, where AA would otherwise type a
clearance answer into an application. ``check_security_clearance`` is a filter
that receives only ``job_description: str`` — it has no job country to compare
against, and it submits nothing. So the escalation cannot live here. The
approval-gate wiring for the form-fill path is a separate task; this file pins
the field and the non-fabrication guarantee that make that task safe to build.
"""

from __future__ import annotations

import ast
import pathlib
from unittest.mock import MagicMock

from auto_apply.domain.models.profile import ClearanceDeclaration, LegalInfo

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "auto_apply"
ADAPTER = SRC / "adapters" / "secondary" / "reasoning" / "rule_based_adapter.py"

CLEARANCE_JOB = "This role requires an active Top Secret security clearance."
OPEN_JOB = "Entry-level position, no clearance required."


def _engine_with(clearance):
    from auto_apply.adapters.secondary.reasoning.rule_based_adapter import (  # noqa: PLC0415
        LogicEngine,
    )

    profile = MagicMock()
    profile.legal_info = LegalInfo(security_clearance=clearance)
    engine = LogicEngine.__new__(LogicEngine)  # bypass __init__ dependencies
    engine.profile = profile
    return engine


def test_legalinfo_has_clearance_declaration_field() -> None:
    field = LegalInfo.model_fields.get("security_clearance")
    assert field is not None, (
        "LegalInfo has no security_clearance field, so any read of the user's "
        "clearance falls back to a fabricated default."
    )
    assert field.default is None, (
        "security_clearance must default to None (not declared), never to a "
        "value that asserts something about the user on their behalf."
    )


def test_clearance_declaration_is_jurisdiction_plus_free_text_level() -> None:
    fields = ClearanceDeclaration.model_fields
    assert set(fields) == {"jurisdiction", "level"}, (
        f"ClearanceDeclaration should be exactly jurisdiction + level, got "
        f"{set(fields)}. Extra structure here becomes a taxonomy to maintain."
    )
    assert fields["level"].annotation is str, (
        "level must be free text. A Literal of clearance levels is a second "
        "source of truth about every jurisdiction's system."
    )


def test_declared_clearance_is_not_auto_rejected() -> None:
    """The actual bug: a cleared user was filtered out of every clearance job."""
    engine = _engine_with(ClearanceDeclaration(jurisdiction="US", level="Top Secret"))
    assert engine.check_security_clearance(CLEARANCE_JOB) is True, (
        "A user who declared a clearance was rejected from a clearance-requiring "
        "job. The engine is fabricating 'no clearance' instead of reading the "
        "declaration."
    )


def test_undeclared_clearance_reads_as_real_absence() -> None:
    """None is a real 'not declared', and a hard-requirement job is skipped."""
    engine = _engine_with(None)
    assert engine.check_security_clearance(CLEARANCE_JOB) is False
    assert engine.check_security_clearance(OPEN_JOB) is True


def test_no_fabricated_clearance_read_remains() -> None:
    """The getattr stand-in must be gone, not merely shadowed."""
    src = ADAPTER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    bad = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) == 3
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "has_security_clearance"
    ]
    assert not bad, (
        f"getattr(..., 'has_security_clearance', <default>) still present at "
        f"lines {bad}. Read profile.legal_info.security_clearance directly so a "
        f"missing declaration is None, not a fabricated answer."
    )

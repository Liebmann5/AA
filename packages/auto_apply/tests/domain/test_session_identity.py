"""Session identity must be unique, opaque, and singular.

The defect this pins
--------------------
``registry.py`` built the plan with::

    session_id="unset",  # will be overwritten by the orchestrator

Three things were wrong with that line.

1. ``SessionPlan`` is ``frozen=True``. The orchestrator *cannot* overwrite it;
   assignment raises ``ValidationError``. The comment described an impossibility.
2. The orchestrator never tried. It minted a *second*, unrelated identity in
   ``__init__``::

       session_id=f"session_{int(time.time())}"

   So ``plan.session_id`` stayed the literal string ``"unset"`` for every run
   AA has ever performed, and a parallel identity did the real work — the second
   source of truth the engineering philosophy forbids.
3. ``SessionPlan``'s own docstring promises "Unique identifier for this run
   (UUID)". A Unix-second timestamp is neither a UUID nor unique.

Why the collision matters
-------------------------
``int(time.time())`` has one-second resolution. Sessions started in the same
second share an identity. ``CheckpointManager._checkpoint_path()`` keys
checkpoints by session id, so a collision means one session restores another's
saved state.

The worst case is not a race — it is AA's target hardware. An old laptop with a
dead CMOS battery reports the same epoch on every single boot. Every session on
that machine would receive an identical ``session_id`` forever: checkpoints
overwrite each other, and research records from separate runs silently merge
into one.

A timestamp identity also leaks wall-clock time into every research record and
log line, which is a re-identification vector in a corpus that claims PII
minimisation.
"""

from __future__ import annotations

import uuid

from auto_apply.domain.models.session_plan import SessionPlan


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def test_session_plan_is_frozen() -> None:
    """Pins the premise: nothing can 'overwrite it later'."""
    plan = SessionPlan(session_id=str(uuid.uuid4()))
    assert plan.model_config.get("frozen") is True, (
        "SessionPlan is no longer frozen — the 'assembled at startup, never "
        "changes during a run' guarantee has been lost."
    )


def test_registry_assigns_a_real_uuid_not_a_placeholder() -> None:
    """The plan must arrive with a usable identity, not 'unset'."""
    from auto_apply.infrastructure import registry as registry_mod

    src = registry_mod.__file__
    with open(src, encoding="utf-8") as fh:
        text = fh.read()

    assert 'session_id="unset"' not in text, (
        "registry.py still builds SessionPlan with session_id='unset'. Because "
        "SessionPlan is frozen, that placeholder is permanent for the whole run."
    )
    assert "will be overwritten by the orchestrator" not in text, (
        "registry.py still carries the comment claiming the orchestrator "
        "overwrites session_id. It cannot: the model is frozen."
    )


def test_orchestrator_does_not_mint_a_second_identity() -> None:
    """Session identity has exactly one source: the SessionPlan."""
    from auto_apply.application.agent import orchestrator as orch_mod

    with open(orch_mod.__file__, encoding="utf-8") as fh:
        text = fh.read()

    assert 'f"session_{int(time.time())}"' not in text, (
        "orchestrator still mints its own timestamp session_id, creating a "
        "second source of truth alongside plan.session_id and colliding for "
        "any two sessions started in the same second."
    )


def test_session_ids_are_unique_across_rapid_construction() -> None:
    """Two sessions started back-to-back must not share an identity."""
    from auto_apply.infrastructure.registry import _new_session_id

    ids = {_new_session_id() for _ in range(1000)}
    assert len(ids) == 1000, (
        f"session id generator produced {len(ids)} unique values out of 1000 — "
        f"checkpoints are keyed by this, so collisions restore the wrong state."
    )
    assert all(_is_uuid(i) for i in ids), (
        "session ids are not UUIDs, contradicting SessionPlan's own docstring."
    )


def test_session_id_does_not_encode_wall_clock_time() -> None:
    """A clock-derived id leaks run time into every research record."""
    from auto_apply.infrastructure.registry import _new_session_id

    import time as _time

    before = int(_time.time())
    sid = _new_session_id()
    assert str(before) not in sid and str(before - 1) not in sid, (
        f"session_id {sid!r} embeds the current epoch. On a machine with a dead "
        f"RTC this is constant across boots, and in research exports it is a "
        f"re-identification vector."
    )

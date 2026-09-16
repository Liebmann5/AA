"""The autonomy write: configure a profile's submission-review policy.

Autonomy is the user's choice to let AA submit each completed application
without pausing for per-submission review. The BACKEND has honoured the
choice since the fail-closed authoriser was written
(``applications_workflow._authorize_submission``): removing
``BEFORE_FORM_SUBMIT`` from the profile's checkpoint list authorises
autonomous submission, and keeping it forces a review prompt. This module is
the WRITE side of that contract — the control both surfaces (CLI startup,
GUI session wizard) and the port method (``SessionController.set_autonomy``)
use to change the choice. The fail-closed authoriser itself is untouched and
remains the single decision point for every submission.

Placement rationale — application layer, not domain. The write persists
through ``ProfileRepositoryPort``, and persistence does not belong in the
domain layer. It is module-level, not only a controller method, because the
CLI must apply it AFTER the wizard but BEFORE ``build_session_controller`` —
and building the controller launches a browser (the cascade in
``build_orchestrator``), which must not happen before the user has even
chosen what to do.

Immutability contract: ``apply_autonomy`` writes the profile object AND
persists it to disk. It never touches a ``ProfileBasedInterruptPolicy``
already constructed for a session. A session's policy is frozen at
composition — see ``SessionController.autonomy()`` (the construction-time
snapshot) and the AST guards in ``tests/application/test_autonomy.py`` — so
a change written here applies to the NEXT session built from this profile
object. In both real flows that is the imminent run: the CLI builds its
controller immediately after this call; the GUI builds a new controller on
every Start.
"""

from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.ports.interrupt_policy_port import (
    Checkpoint,
    ProfileBasedInterruptPolicy,
)
from auto_apply.domain.ports.profile_repository_port import ProfileRepositoryPort


# Checkpoint value sets, derived from the policy itself so they cannot drift
# from it: the policy is the single source of truth for what the review
# default MEANS. Sorted for deterministic reads and pins.
_REVIEW_CHECKPOINTS: list[str] = sorted(
    checkpoint.name for checkpoint in ProfileBasedInterruptPolicy.DEFAULT_CHECKPOINTS
)
_AUTONOMOUS_CHECKPOINTS: list[str] = [Checkpoint.ON_SUSPICIOUS_REDIRECT.name]


def autonomy_enabled_for_profile(profile: UserProfile) -> bool:
    """True when this profile is configured to submit without asking.

    Delegates to the policy's own parse, so the fallback rule (an empty or
    unparseable checkpoint list falls back to the review default) is answered
    identically everywhere — a typo must never read as autonomy. Anything
    that is not a list/tuple of checkpoint names is coerced to None first,
    which resolves to the review default (False).
    """
    checkpoints = getattr(
        getattr(profile, "app_config", None), "human_review_checkpoints", None
    )
    # A tuple is not a list, and is_autonomous declares list[str] | None.
    # Coerce rather than widening the port: the narrower contract is correct.
    names: list[str] | None = (
        [str(c) for c in checkpoints]
        if isinstance(checkpoints, (list, tuple))
        else None
    )
    return ProfileBasedInterruptPolicy.is_autonomous(names)


def apply_autonomy(
    profile: UserProfile,
    profile_repo: ProfileRepositoryPort,
    enabled: bool,
    acknowledgements: tuple[str, ...] = (),
) -> bool:
    """Configure a profile's submission-review policy and persist it.

    Enabling REQUIRES two acknowledgements — the surface shows two
    differently-worded warnings and passes one acknowledgement per
    confirmation. With fewer than two, this returns False and changes
    nothing, so no surface can skip a warning by construction. Disabling
    requires none: turning autonomy off is always safe.

    The write updates the in-memory profile object AND persists via the
    repository (which owns atomic writes and vault encryption). It never
    rebuilds a policy already constructed for a session — see the module
    docstring's immutability contract.

    Returns:
        True when the choice was applied and persisted; False when it was
        refused (missing acknowledgements).

    Raises:
        RuntimeError: When no repository is available to persist through —
            an in-memory-only change would vanish on restart.
    """
    if profile_repo is None:
        raise RuntimeError(
            "apply_autonomy cannot persist: no profile repository was "
            "supplied. Wire the profile repository (ProfileRepositoryPort)."
        )
    if enabled and len(acknowledgements) < 2:
        return False

    profile.app_config.human_review_checkpoints = (
        list(_AUTONOMOUS_CHECKPOINTS) if enabled else list(_REVIEW_CHECKPOINTS)
    )
    profile_repo.save_profile(profile)
    return True

"""How long AA waits for the person. Pure. WCAG 2.2 SC 2.2.1 Timing Adjustable.

Every question AA puts to the person — an approval, a form question it
cannot answer, a challenge only a person can solve, a sign-in only they may
do — waits a limited time and then moves on without them, so that an
unattended session does not stall for ever. Those limits are AA's own, so
AA must let the person change them before they meet them. WCAG 2.2 SC 2.2.1
(Level A) is satisfied by any one of: turning the limit off, adjusting it
over a range of at least ten times the default, or extending it on warning.
AA offers the first two, as one setting (``accessibility.time_limits``):

* ``1x``  — the standard limits (the default);
* ``3x``  — three times as long;
* ``10x`` — ten times as long (the range WCAG names);
* ``20x`` — twenty times as long;
* ``off`` — no limit: AA waits until the person answers or stops the session.

The one place every question passes through applies it
(``SessionController.request_approval``), so no prompt can be missed, and a
stopped session releases every open question, so "off" can never trap the
session. Time limits set by websites themselves are outside AA's control;
AA records them as barriers where it can see them.
"""

from __future__ import annotations

#: Multiplier per setting value; None means no limit.
TIME_LIMIT_SCALES: dict[str, float | None] = {
    "1x": 1.0,
    "3x": 3.0,
    "10x": 10.0,
    "20x": 20.0,
    "off": None,
}
DEFAULT_TIME_LIMITS = "1x"


def known_mode(mode: object) -> bool:
    """Is ``mode`` one of the setting's values?"""
    return isinstance(mode, str) and mode.strip().lower() in TIME_LIMIT_SCALES


def person_timeout(base_s: float | None, mode: object) -> float | None:
    """The wait for one question: ``base_s`` scaled by the person's setting.

    None means wait without limit. An unknown setting value is read as the
    standard limits (the caller reports it), never as "off": a typo must not
    make an unattended session wait for ever.
    """
    if base_s is None:
        return None
    key = mode.strip().lower() if isinstance(mode, str) else DEFAULT_TIME_LIMITS
    scale = TIME_LIMIT_SCALES.get(key, 1.0)
    if scale is None:
        return None
    return max(0.0, float(base_s)) * scale


__all__ = ["DEFAULT_TIME_LIMITS", "TIME_LIMIT_SCALES", "known_mode", "person_timeout"]

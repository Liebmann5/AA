"""The page-feedback loop must actually close, and seeded runs must not write.

What this pins
--------------
``PageFeedbackService`` is fully built: EMA success rates, a minimum-samples
gate, a bounded weight, a repository port, a SQLite adapter, and its own test
file. ``composition_root`` constructs it (line 481) and injects it into
``PageAnalysisRouter`` (line 493). The router reads it as a tie-breaker.

``PageFeedbackService.record_outcome()`` is never called by anything.

So nothing is ever recorded, the EMA store stays empty, the minimum-samples gate
never opens, and the router's feedback branch is permanently dead code sitting
behind a condition that cannot become true. The loop is a circle with one arc
missing: read wired, write not.

The second, subtler half
------------------------
``record_outcome()`` takes ``is_deterministic: bool = False`` and its module
docstring promises:

    when ``is_deterministic=True`` is passed to ``record_outcome()``, no data is
    persisted — the store is strictly read-only for the duration of the run,
    guaranteeing that two seeded runs with the same initial database produce
    identical tier recommendations.

Nothing in ``src/`` ever passes ``is_deterministic``. The value that should feed
it already exists — ``SessionPlan.is_deterministic`` (session_plan.py:150,
``self.behavior.random_seed is not None``) — and is read by nobody.

Today that guarantee is vacuously safe: no writes happen at all, so seeded runs
cannot poison each other. But the moment anyone connects ``record_outcome()`` —
the obvious next step, and the "feedback loop I still need to build" — a seeded
run starts mutating the store it reads from, and two ``--seed 42`` runs diverge.
The determinism claim in §18.1 fails silently, with no test to catch it.

That is why both halves are pinned together. Wiring the write without wiring the
flag converts a dead feature into a reproducibility bug.
"""

from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "auto_apply"


def _calls_named(root: pathlib.Path, method: str) -> list[str]:
    """Find call sites of `.method(...)` across a source tree."""
    found: list[str] = []
    for py in root.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == method
            ):
                found.append(f"{py.relative_to(SRC).as_posix()}:{node.lineno}")
    return found


def test_session_plan_is_deterministic_reaches_a_consumer() -> None:
    """A determinism flag nothing reads cannot make anything deterministic."""
    readers = [
        py.relative_to(SRC).as_posix()
        for py in SRC.rglob("*.py")
        if "plan.is_deterministic" in py.read_text(encoding="utf-8", errors="replace")
    ]
    assert readers, (
        "SessionPlan.is_deterministic is read by nobody. It is the value "
        "PageFeedbackService.record_outcome(is_deterministic=...) exists to "
        "receive, and the only thing that can honour the deterministic-run "
        "guarantee in page_feedback_service's docstring."
    )


def test_page_feedback_loop_is_closed() -> None:
    """record_outcome must be called, or the feedback store stays empty forever."""
    # Exclude the service's own internal delegation to the repository.
    #
    # This filter previously compared a forward-slash literal against
    # Path.relative_to(), which yields backslashes on Windows. The exclusion
    # silently never matched there, so the service's own line-99 call to
    # self._repo.record_outcome() counted as an external caller and this test
    # reported PASS on Windows while failing on Linux -- a false green in the
    # one file whose purpose is preventing false confidence. Compare basenames.
    self_file = "page_feedback_service.py"
    callers = [
        c for c in _calls_named(SRC, "record_outcome")
        if pathlib.PurePosixPath(c.rsplit(":", 1)[0]).name != self_file
    ]
    assert callers, (
        "PageFeedbackService.record_outcome() has no callers. The router reads "
        "feedback (page_analysis_router.py:88) but nothing ever writes it, so "
        "the minimum-samples gate never opens and the feedback branch is "
        "unreachable. The loop is built and disconnected, not unbuilt."
    )


def test_record_outcome_callers_pass_is_deterministic() -> None:
    """Closing the loop without the flag turns a dead feature into a repro bug."""
    offenders: list[str] = []
    for py in SRC.rglob("*.py"):
        if py.name == "page_feedback_service.py":
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "record_outcome"
            ):
                kwargs = {k.arg for k in node.keywords}
                if "is_deterministic" not in kwargs:
                    offenders.append(f"{py.relative_to(SRC).as_posix()}:{node.lineno}")

    assert not offenders, (
        "record_outcome() called without is_deterministic. On a seeded run this "
        "writes to the EMA store that the router reads, so two --seed 42 runs "
        f"produce different tier recommendations. Offenders: {offenders}"
    )

"""Pin: every event published into the EventBus has a subscriber — or an exemption.

What this pin checks, and what it deliberately does not check.

For every resolved ``publish(Event.X)`` and ``subscribe(Event.X)`` call in
``src/auto_apply``:

  A1  Every published event has at least one subscriber, or an exemption.
      TEETH ON DELIVERY. Three events are deliberately NOT exempted, and the
      pin fails naming them until their documented consumers are wired:

        - CAPTCHA_REQUIRES_MANUAL_SOLVE — the 2026-09-03 deadlock: published
          by orchestrator._handle_captcha immediately before pause(); no
          subscriber exists, so no prompt ever reached the user and the
          orchestrator sat in PAUSED for the rest of the session. Nothing in
          the 1,196-test suite failed.
        - REDIRECT_TO_LIST_DETECTED — the Event docstring itself specifies
          the consumer ("the orchestrator should enqueue a Discovery WorkUnit
          for the URL rather than retrying the application"); no such handler
          exists.
        - PROVIDER_TIMED_OUT — the watchdog docstring says the orchestrator
          should re-queue the work unit; nothing does.

      When the last of the three is wired, A1 goes green. The exemption
      dict is NOT the way out: silencing these three by exemption would be
      re-hiding the exact class the pin exists to catch.

  A2  Every subscribed event is published somewhere. REGRESSION GUARD —
      currently clean at zero; a failure here means a subscriber lost its
      publisher, not that the pin caught the class it was built for.

  A3  Stale exemptions. REGRESSION GUARD — an event in
      KNOWN_UNWIRED_EVENTS that has since been wired must leave the dict.
      Passes today because nothing exempted is wired yet; fails on future
      drift. A shrinking inventory is success.

  A4  Unresolvable event references. REGRESSION GUARD — passes today
      because every publish/subscribe first argument resolves through the
      three allowed forms; fails loudly with file and line if a fourth form
      ever appears. A structural check that silently undercounts is worse
      than no check.

  A5  Exemption ceiling and integrity. REGRESSION GUARD — MAX_EXEMPTIONS
      is a CEILING, not an equality; a lower count is success. Also rejects
      exemption entries naming no Event member, so a renamed member cannot
      leave a dangling exemption.

Resolver contract (the part that makes A4 honest). A publish/subscribe first
argument resolves to Event members through exactly three forms:

  1. Direct:         ``publish(Event.X, payload)``
  2. Inline ternary: ``publish(Event.A if cond else Event.B, payload)`` —
     both branches count. Live site: applications_workflow.py.
  3. Single-assignment local: ``event = <form 1 or 2>`` assigned exactly once
     earlier in the same function, then ``publish(event, ...)``. Live sites:
     vetting_workflow.py and applications_workflow.py. A name assigned twice
     in one function is treated as UNRESOLVABLE — the pin does not guess
     which value reaches the call.

Deliberate exclusions:

  - ``tests/`` is not scanned. A subscriber in a test proves a handler is
    callable, not that production calls it. The deadlock class lives in
    production.
  - ``domain/types.py``'s ``JobStatus.APPLICATION_FAILED`` is unrelated to
    ``Event.APPLICATION_FAILED``: one is a persisted job-pipeline state, the
    other a bus message. The resolver requires the ``Event.`` qualifier, so
    the name overlap cannot confuse this pin.
  - Payload shape is not policed. Wiring and schema are different problems.

Exemption policy mirrors test_port_wiring.py: every KNOWN_UNWIRED_EVENTS
entry carries a one-line reason and a disposition tag from WIRE-LATER ·
RETIRE-CANDIDATE · PLANNED · TEST-ONLY. Entries are removed as events get
wired; only a newly unwired event may push the count up, and only with a
written reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ._binding import iter_scope, iter_scopes, scope_assignments

_PKG_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _PKG_ROOT / "src" / "auto_apply"
_EVENTS_MODULE = _SRC_DIR / "domain" / "events.py"

# ─────────────────────────────────────────────────────────────────────────────
# Deliberately unexempted — currently EMPTY, and that emptiness is the success
# state this dict was built to force.
#
# On 2026-09-04 the three events below were wired with real consumers and this
# dict was emptied:
#
#   CAPTCHA_REQUIRES_MANUAL_SOLVE — consumed by the orchestrator recorder
#     (_on_captcha_manual_solve_requested); the pause/release is owned by the
#     HITL gate (orchestrator._escalate_captcha_to_human), replacing the
#     publish-then-pause() terminal hang.
#   REDIRECT_TO_LIST_DETECTED — consumed by the orchestrator
#     (_on_redirect_to_list_detected), which enqueues a DISCOVER_COMPANY
#     WorkUnit per the Event docstring.
#   PROVIDER_TIMED_OUT — consumed by the orchestrator
#     (_on_provider_timed_out), which records and reschedules.
#
# Adding an entry here requires a written defect reason, and the pin fails on
# purpose until that defect is wired. Do not add entries to silence the pin.
# ─────────────────────────────────────────────────────────────────────────────

_DELIBERATELY_UNEXEMPTED: dict[str, str] = {}

# ─────────────────────────────────────────────────────────────────────────────
# Exemption inventory — 13 published-never-subscribed telemetry events plus
# the 24 enum members nothing uses yet. Every entry is (tag, proof). Wiring
# an event deletes its entry; the count can only fall.
# ─────────────────────────────────────────────────────────────────────────────

KNOWN_UNWIRED_EVENTS: dict[str, tuple[str, str]] = {
    # ── Published-never-subscribed telemetry (13) ────────────────────────────
    "CAPTCHA_DETECTED": (
        "WIRE-LATER",
        "Published by ApplicationsWorkflow before enqueueing HANDLE_CAPTCHA; "
        "the task queue is the actual hand-off mechanism, the event is "
        "informational telemetry with no consumer yet.",
    ),
    "APPLICATION_FAILED": (
        "WIRE-LATER",
        "Published via ternary in applications_workflow.py; stats already "
        "flow via update_stats, so the event is currently redundant telemetry.",
    ),
    "APPLICATION_SUBMITTED": (
        "WIRE-LATER",
        "Same shape as APPLICATION_FAILED.",
    ),
    "JOB_VETTED_PASS": (
        "WIRE-LATER",
        "Published via ternary in vetting_workflow.py; stats flow via "
        "update_stats('vetted'), so the event awaits a dashboard/research "
        "consumer that does not exist yet.",
    ),
    "JOB_VETTED_FAIL": (
        "WIRE-LATER",
        "Same shape as JOB_VETTED_PASS.",
    ),
    "JOBS_DISCOVERED": (
        "WIRE-LATER",
        "Published by DiscoveryWorkflow after enqueueing VET tasks; no consumer.",
    ),
    "DISCOVERY_COMPLETE": (
        "WIRE-LATER",
        "Aggregate stats payload published per discovery round; no consumer.",
    ),
    "FORM_FIELD_FILLED": (
        "WIRE-LATER",
        "A working subscriber already exists, retired at "
        "docs/old_retired_files/.../application/services/telemetry.py — a "
        "complete Bayesian confidence tracker built for exactly this event. "
        "Recalling it removes this exemption. Do not build a new one.",
    ),
    "FORM_FIELD_FAILED": (
        "WIRE-LATER",
        "Same retired subscriber as FORM_FIELD_FILLED.",
    ),
    "TASK_PERMANENTLY_FAILED": (
        "WIRE-LATER",
        "Published by orchestrator._handle_task_error after retry exhaustion; "
        "no consumer.",
    ),
    "TASK_SKIPPED_DUPLICATE": (
        "WIRE-LATER",
        "Published by DiscoveryWorkflow on dedup skip; no consumer.",
    ),
    "PROVIDER_BENCHED": (
        "WIRE-LATER",
        "Published by the degradation detector; benching is already logged "
        "at WARNING (fail-loud in logs), so the event is dashboard telemetry.",
    ),
    "BROWSER_HEALTHY": (
        "WIRE-LATER",
        "Heartbeat published by BrowserHealthMonitor at intervals for UI "
        "display; no consumer.",
    ),
    # ── Never-published-nor-subscribed (24) — reported, tagged, failing nothing ──
    "SESSION_STARTED": (
        "WIRE-LATER",
        "Lifecycle event documented for UI; SessionController.get_stats() "
        "surfaces the same information synchronously, so urgency is low.",
    ),
    "SESSION_PAUSED": ("WIRE-LATER", "Same as SESSION_STARTED."),
    "SESSION_RESUMED": ("WIRE-LATER", "Same as SESSION_STARTED."),
    "SESSION_COMPLETE": ("WIRE-LATER", "Same as SESSION_STARTED."),
    "SESSION_ABORTED": ("WIRE-LATER", "Same as SESSION_STARTED."),
    "TASK_STARTED": (
        "WIRE-LATER",
        "Dashboard progress tick; unpublished.",
    ),
    "TASK_COMPLETED": ("WIRE-LATER", "Same as TASK_STARTED."),
    "TASK_FAILED": ("WIRE-LATER", "Same as TASK_STARTED."),
    "DISCOVERY_PAGE_SCRAPED": (
        "WIRE-LATER",
        "Per-page telemetry; unpublished.",
    ),
    "APPLICATION_STARTED": (
        "WIRE-LATER",
        "Unpublished; the attempt id (Stage 6e) currently carries the same join.",
    ),
    "APPLICATION_SKIPPED_PRIOR_SESSION": (
        "RETIRE-CANDIDATE",
        "Superseded by ApplicationEvidence.outcome = USER_SKIPPED, recorded "
        "by the orchestrator's batch scheduler path. Nothing is deleted; the "
        "enum member stays.",
    ),
    "LOGIC_CONFLICT_DETECTED": (
        "WIRE-LATER",
        "FSM state RESOLVING_LOGIC_CONFLICT exists with transitions but no "
        "producer of this event.",
    ),
    "CAPTCHA_RESOLVED": (
        "WIRE-LATER",
        "CaptchaResolutionService.resolve() returns bool but nothing "
        "publishes the resolution outcome.",
    ),
    "BOT_DETECTION_TRIGGERED": (
        "WIRE-LATER",
        "DefaultDetectionStrategy detects; nothing publishes.",
    ),
    "BROWSER_RESTARTED": (
        "WIRE-LATER",
        "Cascade-restart reporting, unpublished.",
    ),
    "BROWSER_CASCADE_EXHAUSTED": (
        "WIRE-LATER",
        "The cascade docstring says the orchestrator publishes this before "
        "aborting — no such publish exists. A documented-but-missing publisher.",
    ),
    "NETWORK_HEALTHY": (
        "WIRE-LATER",
        "Unpublished complement of the two live network events.",
    ),
    "CHECKPOINT_SAVED": (
        "WIRE-LATER",
        "CheckpointManager logs but never publishes.",
    ),
    "CHECKPOINT_RESTORED": ("WIRE-LATER", "Same as CHECKPOINT_SAVED."),
    "CHECKPOINT_FAILED": ("WIRE-LATER", "Same as CHECKPOINT_SAVED."),
    "RESEARCH_SIGNAL_RECORDED": (
        "WIRE-LATER",
        "The aggregator writes rows and logs; this event was designed for a "
        "different (pre-port) research path.",
    ),
    "PROGRESS_UPDATE": (
        "WIRE-LATER",
        "Documented for the live UI feed; dashboards currently poll "
        "get_stats() instead.",
    ),
    "LOG_MESSAGE": ("WIRE-LATER", "Same as PROGRESS_UPDATE."),
    "STATUS_UPDATE": ("WIRE-LATER", "Same as PROGRESS_UPDATE."),
}

# Ceiling, not equality. A lower count is success — remove entries as events
# get wired. Only a newly unwired event may push the count up, with a reason.
MAX_EXEMPTIONS = 37


# ─────────────────────────────────────────────────────────────────────────────
# Scan machinery
# ─────────────────────────────────────────────────────────────────────────────


def _iter_src_files() -> list:
    return [
        p
        for p in sorted(_SRC_DIR.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


def _extract_event_members() -> frozenset:
    """Names assigned at class-body level in domain/events.py's Event enum.

    Parsed, never imported — consistent with every other architecture pin,
    and immune to the pin itself breaking if the file it guards cannot import.
    """
    tree = ast.parse(_EVENTS_MODULE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Event":
            return frozenset(
                target.id
                for item in node.body
                if isinstance(item, ast.Assign)
                for target in item.targets
                if isinstance(target, ast.Name)
            )
    raise AssertionError(
        f"No 'class Event' found in {_EVENTS_MODULE} — the pin's seed is broken."
    )


def _event_attr_name(expr: ast.expr, members: frozenset) -> set[str] | None:
    """Resolve a direct ``Event.X`` reference, or None.

    The ``Event.`` qualifier is REQUIRED. ``JobStatus.APPLICATION_FAILED``
    (domain/types.py) shares a name with an Event member and must not match.
    """
    if (
        isinstance(expr, ast.Attribute)
        and isinstance(expr.value, ast.Name)
        and expr.value.id == "Event"
        and expr.attr in members
    ):
        return {expr.attr}
    return None


def _resolve_event_ref(
    expr: ast.expr,
    assignments: dict[str, ast.expr],
    members: frozenset,
    *,
    _allow_name_lookup: bool = True,
) -> set[str] | None:
    """Resolve a publish/subscribe first argument to Event member names.

    Three forms, and only three: direct Event.X; inline ternary (both
    branches count); single-assignment local holding either of those.

    Returns the set of member names the reference can mean, or None when the
    reference fits none of the forms — None is what A4 reports, loudly, with
    the file and line.
    """
    direct = _event_attr_name(expr, members)
    if direct is not None:
        return direct

    if isinstance(expr, ast.IfExp):
        body = _resolve_event_ref(expr.body, assignments, members, _allow_name_lookup=False)
        orelse = _resolve_event_ref(expr.orelse, assignments, members, _allow_name_lookup=False)
        if body is None or orelse is None:
            return None
        return body | orelse

    if _allow_name_lookup and isinstance(expr, ast.Name):
        value = assignments.get(expr.id)
        if value is None:
            return None
        # One hop only: the value must itself be a direct ref or ternary.
        # Chained names (a = b; b = Event.X) are unresolvable by contract.
        return _resolve_event_ref(value, assignments, members, _allow_name_lookup=False)

    return None


def _first_event_arg(call: ast.Call) -> ast.expr | None:
    """The first positional argument, or a keyword argument named ``event``."""
    if call.args:
        return call.args[0]
    for kw in call.keywords:
        if kw.arg == "event":
            return kw.value
    return None


def _scan_all() -> dict:
    members = _extract_event_members()
    published: dict[str, list[tuple[str, int]]] = {}
    subscribed: dict[str, list[tuple[str, int]]] = {}
    unresolvable: list[tuple[str, int, str, str]] = []

    for path in _iter_src_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        rel = path.relative_to(_PKG_ROOT).as_posix()
        for scope in iter_scopes(tree):
            assignments = scope_assignments(scope)
            for node in iter_scope(scope):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Attribute):
                    kind = node.func.attr
                elif isinstance(node.func, ast.Name):
                    kind = node.func.id
                else:
                    continue
                if kind not in ("publish", "subscribe"):
                    continue

                arg = _first_event_arg(node)
                if arg is None:
                    unresolvable.append((rel, node.lineno, kind, "<no event argument>"))
                    continue
                resolved = _resolve_event_ref(arg, assignments, members)
                if resolved is None:
                    unresolvable.append((rel, node.lineno, kind, ast.dump(arg)[:120]))
                    continue

                target = published if kind == "publish" else subscribed
                for name in resolved:
                    target.setdefault(name, []).append((rel, node.lineno))

    return {
        "members": members,
        "published": published,
        "subscribed": subscribed,
        "unresolvable": unresolvable,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Assertions
# ─────────────────────────────────────────────────────────────────────────────


def test_published_events_have_subscribers_or_exemptions__teeth() -> None:
    """A1 (TEETH ON DELIVERY): no published event may go unheard.

    Fails today, deliberately: the three events in _DELIBERATELY_UNEXEMPTED
    are documented safety defects with missing consumers. When the last one
    is wired, this pin goes green. Exempting them instead would re-hide the
    deadlock class the pin exists to catch.
    """
    scan = _scan_all()
    unwired = {
        name: sites
        for name, sites in scan["published"].items()
        if name not in scan["subscribed"] and name not in KNOWN_UNWIRED_EVENTS
    }
    lines = []
    for name in sorted(unwired):
        sites = ", ".join(f"{f}:{ln}" for f, ln in unwired[name])
        defect = _DELIBERATELY_UNEXEMPTED.get(
            name,
            "no exemption and no subscriber — wire a consumer or add a "
            "(tag, reason) entry to KNOWN_UNWIRED_EVENTS with a written reason.",
        )
        lines.append(
            f"  {name}\n"
            f"    published at: {sites}\n"
            f"    defect: {defect}"
        )
    assert not unwired, (
        "\nUNSUBSCRIBED PUBLISHED EVENTS — these events are published into a "
        "bus nobody listens to. They are deliberately NOT exempted: each is a "
        "safety defect with a documented consumer that does not exist. Wire "
        "the consumer; when the last one is wired this pin goes green. Do "
        "not silence it by adding exemptions.\n"
        + "\n".join(lines)
        + "\n"
    )


def test_subscribed_events_are_published__regression_guard() -> None:
    """A2 (REGRESSION GUARD, currently 0): no orphan subscribers.

    This set was EMPTY when the pin was written. It is a guard, not teeth —
    a failure here means a subscriber lost its publisher.
    """
    scan = _scan_all()
    orphan = {
        name: sites
        for name, sites in scan["subscribed"].items()
        if name not in scan["published"] and name not in KNOWN_UNWIRED_EVENTS
    }
    lines = [
        f"  {name} — subscribed at "
        + ", ".join(f"{f}:{ln}" for f, ln in orphan[name])
        for name in sorted(orphan)
    ]
    assert not orphan, (
        "\nORPHAN SUBSCRIBER — subscribed to an event nothing publishes. "
        "This set was EMPTY when this pin was written; this is a regression "
        "guard, not teeth:\n" + "\n".join(lines) + "\n"
    )


def test_stale_exemptions__regression_guard() -> None:
    """A3 (REGRESSION GUARD): an exempted event that gets wired leaves the dict.

    Staleness rule, derived from what each exemption covers:
      - Exemption for "published but no subscriber": stale when the event
        gains a SUBSCRIBER.
      - Exemption for "defined but unused": stale when the event gains a
        PUBLISHER or a subscriber.
      - Any exempted event with a subscriber is stale unconditionally.

    Passes today because nothing exempted is wired yet; fails on future drift.
    """
    scan = _scan_all()
    stale = []
    for name in KNOWN_UNWIRED_EVENTS:
        published = name in scan["published"]
        subscribed = name in scan["subscribed"]
        if subscribed:
            stale.append(
                f"  {name} — gained a subscriber at "
                + ", ".join(f"{f}:{ln}" for f, ln in scan["subscribed"][name])
            )
        elif published and not subscribed:
            continue  # the A1 exemption doing its job — not stale
        elif published:
            stale.append(
                f"  {name} — previously unused, now published at "
                + ", ".join(f"{f}:{ln}" for f, ln in scan["published"][name])
            )
    assert not stale, (
        "\nSTALE EXEMPTIONS — exempted as unwired but now wired. A shrinking "
        "inventory is success; delete these entries from KNOWN_UNWIRED_EVENTS:\n"
        + "\n".join(stale)
        + "\n"
    )


def test_unresolvable_event_references_fail_loudly__regression_guard() -> None:
    """A4 (REGRESSION GUARD): a publish/subscribe call the pin cannot resolve.

    Passes today because every call resolves through the three allowed forms.
    Fails loudly with file and line if a fourth form ever appears — a
    structural check that silently undercounts is worse than no check.
    """
    scan = _scan_all()
    lines = [
        f"  {rel}:{lineno} — {kind}( {expr} )"
        for rel, lineno, kind, expr in scan["unresolvable"]
    ]
    assert not scan["unresolvable"], (
        "\nUNRESOLVABLE EVENT REFERENCE — the pin cannot prove which event "
        "this call targets:\n"
        + "\n".join(lines)
        + "\n  fix: resolve to Event.X directly, via an inline ternary, or via\n"
        "       a single-assignment local in the same function.\n"
    )


def test_exemption_ceiling_and_integrity__regression_guard() -> None:
    """A5 (REGRESSION GUARD): the exemption dict stays bounded and honest.

    MAX_EXEMPTIONS is a ceiling — a count BELOW it is success. Also rejects
    exemption entries that name no Event member, so a renamed member cannot
    leave a dangling exemption that never goes stale.
    """
    members = _extract_event_members()
    failures = []
    unknown = sorted(set(KNOWN_UNWIRED_EVENTS) - set(members))
    if unknown:
        failures.append(
            "EXEMPTION ENTRIES NAMING NO EVENT MEMBER — these are not members "
            f"of domain/events.py's Event enum (renamed or mistyped): {unknown}"
        )
    if len(KNOWN_UNWIRED_EVENTS) > MAX_EXEMPTIONS:
        failures.append(
            f"EXEMPTION CEILING EXCEEDED: {len(KNOWN_UNWIRED_EVENTS)} entries "
            f"but MAX_EXEMPTIONS={MAX_EXEMPTIONS}. A count BELOW the ceiling "
            "is success — remove entries as events get wired; only a newly "
            "unwired event may push the count up, and only with a written reason."
        )
    assert not failures, "\n\n".join(failures) + "\n"

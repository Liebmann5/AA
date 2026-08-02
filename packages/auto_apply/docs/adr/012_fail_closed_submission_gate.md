

# ADR‑012: Fail‑Closed Submission Gate

**Status:** Accepted  
**Date:** 2026‑07‑26  
**Deciders:** Nick Liebmann  
**Technical Story:** Restoring `InteractionExecutor.click()` (Stage 1 of the foundational‑tool work) made every click in the Applications engine fire for the first time — including the submit click. Tracing the pre‑submit human‑in‑the‑loop check showed it was fail‑open in four distinct ways. A gate that only holds while clicking is broken is not a gate.

---

## Context

`ApplicationsWorkflow._submit_application` consulted the interrupt policy before
submitting and then ignored the answer in every non‑ideal case:

```python
try:
    ctx = type("ctx", (), {"job": job})()
    if self._interrupt_policy.should_pause(Checkpoint.BEFORE_FORM_SUBMIT, ctx):
        if self._approval_gate is not None:          # (1)
            choice = self._approval_gate(...)        # (3)
            if choice == "skip":                     # (4)
                return ...USER_SKIPPED
except Exception as exc:                             # (2)
    logger.debug(...)
```

1. **No approver wired.** A required pause with `_approval_gate is None` fell
   straight through to the submit click. This is a reachable production state:
   `SessionController._wire_approval_gate` binds the gate inside a `try/except`
   that logs `"HITL disabled"` and continues.
2. **Policy raised.** Swallowed at debug level, then submitted.
3. **Gate raised.** Same swallow, same result.
4. **Unrecognised answer.** Only the literal `"skip"` blocked. `None`, `""`, a
   dismissed dialog, or any unexpected UI value counted as consent.

The context object passed to the policy was also fabricated
(`type("ctx", (), {...})()`) rather than the frozen `ApplicationContext` the port
defines, so any policy reading `ctx.url` or `ctx.company` would raise — directly
into failure mode (2).

Note what was *not* broken: `human_review_checkpoints` does reach
`ProfileBasedInterruptPolicy` (composition root), and
`DEFAULT_CHECKPOINTS` already contains `BEFORE_FORM_SUBMIT`. The setting was
being read and its decision was being discarded at the point of use. The
separate red pin about that field's *read pattern* (`getattr` vs `.get`) is
unrelated to this decision and unaffected by it.

## Decision

Submission is **authorised explicitly or not at all**. `_authorize_submission`
returns `(authorized, outcome, detail)` and the caller returns evidence without
clicking whenever authorisation is absent. There is no `try/except` around the
gate that continues on error — a swallowed error is precisely how an unapproved
application gets sent.

Exactly two things authorise a submission:

1. **The user's policy asks for no pre‑submit pause.** Removing
   `BEFORE_FORM_SUBMIT` from `human_review_checkpoints` is a deliberate,
   informed choice to run autonomously, and it is honoured. The gate exists to
   resolve *ambiguity*, never to override a sovereign choice — principle 1 of
   `ENGINEERING_PHILOSOPHY.md` cuts both ways, and a tool that refuses to do
   what its user configured is not accommodating them.
2. **A wired approval gate returned the approval token** (`"submit"`, matching
   the options `SessionController.request_approval` already offers).

Everything else — no approver, policy raised, gate raised, unrecognised answer —
records `SUBMISSION_GATE_BLOCKED` and does not click. A deliberate human refusal
remains `USER_SKIPPED`, because a person saying no and a fault preventing the
question are different research signals and must not be conflated in the data.

`SUBMISSION_GATE_BLOCKED` is a new `ApplicationEvidence.outcome` value.
Before adding it, `outcome` consumers were audited for exhaustive handling:
there are no `match`/`case` dispatches on it anywhere, `SessionReportEntry.outcome`
is a plain `str`, the SQLite column is `outcome TEXT` with no `CHECK`
constraint, and every aggregation is an inclusion test against an explicit
tuple. The one aggregation that needed to learn the value is
`SessionReport.applications_failed`, which counted anything outside
`SUBMITTED / PROBABLY_SUBMITTED / USER_SKIPPED` as a failure: a gate refusal is
a *not attempted*, not a failure, so it joins that exclusion set.
`success_rate` (`submitted / completed`) is unaffected. The applied‑jobs cap
query counts only `SUBMITTED` and `PROBABLY_SUBMITTED`, so a gate‑blocked run
consumes no quota.

## Alternatives Considered

- **A new `dry_run` config flag.** Rejected: it adds a knob for a decision the
  existing checkpoint system already expresses, and two overlapping safety
  switches is worse than one that works. The shipped default
  (`BEFORE_FORM_SUBMIT` present, no gate wired in a bare install) already
  produces dry‑run behaviour.
- **Gate inside the existing `try/except`, logging louder.** Rejected: the
  swallow *is* the defect.
- **Treat an unwired approver as implicit consent for headless runs.**
  Rejected: `NeverInterruptPolicy` already exists for genuinely autonomous
  operation, and choosing it is explicit. Inferring consent from a wiring
  failure is exactly the class of accident this ADR prevents.

## Consequences

- A bare install with no HITL UI cannot auto‑submit. The safe path is the
  default path, not a configuration achievement.
- Users who configured autonomous submission are unaffected — pinned with the
  real `ProfileBasedInterruptPolicy` built from an opted‑out checkpoint list and
  no approval gate.
- Every checkpoint call site now passes a real `ApplicationContext`, so
  policies may read its fields without risking the old swallow.
- Nine pins hold the gate (`tests/workflows/test_submission_gate.py`), six of
  which failed against the previous code.

## Pre‑real‑site checklist

1. **Fail‑loud surfacing — DONE.** A blocked submission now emits one
   WARNING per session carrying the reason and the remedy, appears in the
   session summary as `submissions_blocked_by_gate`, and prints a remedy
   line in the CLI results. Fail‑closed is only safe if it is also
   fail‑loud: a default install blocking every submission correctly, while
   saying so only in debug logs, looks broken rather than safe — and
   invites the operator to "fix" it by disabling the check protecting them.
2. **Click‑target occlusion guard — DONE.** Ported into
   `PageActionService.click` as a three‑outcome probe with the
   predecessor's fatal flaw reversed: *undetermined proceeds*. Off‑viewport
   and probe failure no longer count as traps, and an occluded target is
   re‑checked after a scroll before the click is refused. Config:
   `occlusion_guard` (default true). The section below records why the
   original was disabled and is kept for that history.

## Open item — click‑target occlusion guard (pre‑real‑site)

`behavior.human_like_click` performed an occlusion/honeypot check via
`document.elementFromPoint` and raised on a suspected trap.
`PageActionService.click` — now the single click implementation — does **not**.
Stage 1 deliberately did not port that check across, because:

- it had never executed on any live path (`execute_plan` has zero callers and
  `interaction_port.click` did not exist), so no regression is being accepted;
  the guard is simply, and now visibly, **absent**; and
- its own source carries `#TODO: Revisit!!` and a note that it was "too
  aggressive and causing false positives" — importing a known false‑positive
  risk onto the submit path in the same stage that makes submit fire is the
  wrong trade.

This is recorded as an **explicit pre‑real‑site decision**: the Stage 7 live run
uses the mock forms in `tests/benchmarks/ats_forms/`, which will not exercise
occlusion at all, so nothing in the verification path will surface its absence.
Before AA submits against a real job site, the occlusion question needs its own
decision: port a tightened check into the tool's `click`, replace it with a
geometry test on the math subsystem's `DOMNode` data (where the deterministic
`HoneypotDetector` already lives), or accept its absence knowingly.

Honeypot *fields* remain protected on the live math path — `WebpageAnalyzer`
produces `structure.honeypots` and `ApplicationsWorkflow` skips those fields.
The gap is click‑target occlusion only.

"""Self-tuning under a significance rule (CT-ALG-019, 06 s9; CT-FR-024).

The unit of inference is the **site**, not the page: pages of one site are
correlated. For a candidate change θ0 → θ1, the caller replays stored
observations (the tools are pure) and scores both against gold labels per
site. This module decides; it never runs tools and never reads a clock.

* **Test.** One-sided exact sign test over the sites whose results differ
  (binomial, p0 = 0.5), α = 0.01 per cycle, Holm (1979) across parameters
  proposed in the same cycle.
* **Guards.** Non-inferiority on every non-targeted family: the lower 95%
  Wilson bound of the accuracy difference ≥ -0.01; time non-inferiority;
  a held-out site split (by site hash) never used to tune.
* **Application.** Next session only; each change moves a parameter at
  most 10% of its range; a cooldown of 5 cycles per parameter; the previous
  set stays the parent; automatic rollback if the next window regresses.
* **Safety parameters** (``ParamSpec.safety``) are never proposed.
* Insufficient evidence answers **no change**.

Sample size (the blueprint's figure, corrected): discordant sites needed for
power 0.8 against p1 = 0.8 is ``((z_{1-α}·0.5 + z_{1-β}·0.4) / 0.3)²``:
about 15 at α = 0.05, but the rule uses α = 0.01, which needs about 25
(``discordant_sites_needed``).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any

from pagecomp.params import ParameterSet, ParamSpec

_N = NormalDist()


def sign_test_p(wins: int, losses: int) -> float:
    """One-sided exact binomial P(X >= wins | n = wins + losses, p = 0.5)."""
    n = wins + losses
    if n == 0:
        return 1.0
    total = sum(math.comb(n, k) for k in range(wins, n + 1))
    return total / (2 ** n)


def holm(pvalues: Mapping[str, float], alpha: float) -> dict[str, bool]:
    """Holm step-down: which hypotheses are rejected at family-wise ``alpha``."""
    order = sorted(pvalues.items(), key=lambda kv: (kv[1], kv[0]))
    m = len(order)
    out = {k: False for k in pvalues}
    for i, (k, p) in enumerate(order):
        if p <= alpha / (m - i):
            out[k] = True
        else:
            break
    return out


def wilson_interval(successes: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    z = _N.inv_cdf(1 - (1 - conf) / 2)
    p = successes / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def diff_lower_bound(s1: int, n1: int, s0: int, n0: int, conf: float = 0.95) -> float:
    """Lower bound of p1 - p0 by Newcombe's hybrid score method (Wilson
    intervals per arm), a standard non-inferiority bound."""
    l1, u1 = wilson_interval(s1, n1, conf)
    l0, u0 = wilson_interval(s0, n0, conf)
    p1 = s1 / n1 if n1 else 0.0
    p0 = s0 / n0 if n0 else 0.0
    return (p1 - p0) - math.sqrt((p1 - l1) ** 2 + (u0 - p0) ** 2)


def discordant_sites_needed(alpha: float = 0.01, power: float = 0.8, p1: float = 0.8) -> int:
    za, zb = _N.inv_cdf(1 - alpha), _N.inv_cdf(power)
    n = ((za * 0.5 + zb * math.sqrt(p1 * (1 - p1))) / (p1 - 0.5)) ** 2
    return math.ceil(n)


def holdout(site_id: str, share: float = 0.2) -> bool:
    """Deterministic held-out split by site hash: never used to tune."""
    h = int(hashlib.sha256(site_id.encode()).hexdigest()[:8], 16)
    return (h % 10_000) / 10_000 < share


@dataclass(frozen=True)
class SiteOutcome:
    site: str
    correct_old: bool
    correct_new: bool


@dataclass(frozen=True)
class Proposal:
    tool: str
    param: str
    old: float
    new: float
    wins: int
    losses: int
    p_value: float
    accepted: bool
    reason: str


@dataclass
class Tuner:
    alpha: float = 0.01
    max_step: float = 0.10
    cooldown: int = 5
    non_inferiority: float = -0.01
    cycle: int = 0
    last_changed: dict[str, int] = field(default_factory=dict)
    history: list[ParameterSet] = field(default_factory=list)

    def propose(self, current: ParameterSet, specs: Mapping[str, Iterable[ParamSpec]],
                candidates: Mapping[tuple[str, str], tuple[float, Sequence[SiteOutcome]]],
                guards: Mapping[str, tuple[int, int, int, int]] | None = None,
                time_ok: bool = True) -> tuple[ParameterSet, list[Proposal]]:
        """Decide one cycle. ``candidates[(tool, param)] = (new value,
        per-site outcomes)``; ``guards[family] = (s_new, n_new, s_old, n_old)``
        for every non-targeted family. Returns the set for the **next**
        session (the current one when nothing passes) and the reasons.

        Missing evidence is never passing evidence: with ``guards`` left out
        nothing is accepted, and a family whose guard has no observations on
        either side fails non-inferiority. ``guards={}`` is the caller
        stating that no other family exists."""
        self.cycle += 1
        decl = {t: {p.name: p for p in ps} for t, ps in specs.items()}
        pvals: dict[str, float] = {}
        prelim: dict[str, Proposal] = {}
        for (tool, name), (new, outcomes) in sorted(candidates.items()):
            spec = decl.get(tool, {}).get(name)
            k = f"{tool}.{name}"
            old = float(current.for_tool(tool).get(name, spec.default if spec else 0.0))
            if spec is None:
                prelim[k] = Proposal(tool, name, old, new, 0, 0, 1.0, False, "undeclared parameter")
                continue
            if spec.safety:
                prelim[k] = Proposal(tool, name, old, new, 0, 0, 1.0, False, "safety parameter: never tuned")
                continue
            if self.cycle - self.last_changed.get(k, -10**9) <= self.cooldown:
                prelim[k] = Proposal(tool, name, old, new, 0, 0, 1.0, False, "cooldown")
                continue
            tuned = [o for o in outcomes if not holdout(o.site)]
            wins = sum(1 for o in tuned if o.correct_new and not o.correct_old)
            losses = sum(1 for o in tuned if o.correct_old and not o.correct_new)
            p = sign_test_p(wins, losses)
            step_ok, step_new = _bounded_step(spec, old, new, self.max_step)
            reason = "" if step_ok else "step clipped to 10% of range"
            if wins + losses < discordant_sites_needed(self.alpha):
                prelim[k] = Proposal(tool, name, old, step_new, wins, losses, p, False,
                                     f"insufficient evidence: {wins + losses} discordant sites, "
                                     f"{discordant_sites_needed(self.alpha)} needed")
                continue
            pvals[k] = p
            prelim[k] = Proposal(tool, name, old, step_new, wins, losses, p, False, reason)
        rejected = holm(pvals, self.alpha) if pvals else {}
        if guards is None:
            guard_fail = ["no guard evidence given"]
        else:
            guard_fail = [f if (n1 and n0) else f"{f} (no observations)"
                          for f, (s1, n1, s0, n0) in guards.items()
                          if not (n1 and n0) or diff_lower_bound(s1, n1, s0, n0) < self.non_inferiority]
        out: list[Proposal] = []
        changes: dict[str, dict[str, Any]] = {}
        for k, pr in prelim.items():
            if k in pvals:
                if not rejected.get(k):
                    pr = Proposal(pr.tool, pr.param, pr.old, pr.new, pr.wins, pr.losses, pr.p_value, False,
                                  "not significant after Holm")
                elif guard_fail:
                    pr = Proposal(pr.tool, pr.param, pr.old, pr.new, pr.wins, pr.losses, pr.p_value, False,
                                  "non-inferiority failed: " + ",".join(sorted(guard_fail)))
                elif not time_ok:
                    pr = Proposal(pr.tool, pr.param, pr.old, pr.new, pr.wins, pr.losses, pr.p_value, False,
                                  "time non-inferiority failed")
                else:
                    pr = Proposal(pr.tool, pr.param, pr.old, pr.new, pr.wins, pr.losses, pr.p_value, True,
                                  pr.reason or "accepted")
                    changes.setdefault(pr.tool, {})[pr.param] = pr.new
                    self.last_changed[k] = self.cycle
            out.append(pr)
        if not changes:
            return current, out
        self.history.append(current)
        new_set = current.with_overrides(specs, changes, reason=f"tuning cycle {self.cycle}")
        return new_set, out

    def rollback(self, regressed: bool, current: ParameterSet) -> ParameterSet:
        """If the next window regresses, return to the parent set."""
        if regressed and self.history:
            return self.history.pop()
        return current


def _bounded_step(spec: ParamSpec, old: float, new: float, max_step: float) -> tuple[bool, float]:
    if spec.lo is None or spec.hi is None:
        span = abs(old) if old else 1.0
    else:
        span = float(spec.hi) - float(spec.lo)
    limit = max_step * span
    delta = new - old
    if abs(delta) <= limit + 1e-12:
        return True, new
    clipped = old + math.copysign(limit, delta)
    if isinstance(spec.default, int) and not isinstance(spec.default, bool):
        clipped = float(round(clipped))
    return False, clipped

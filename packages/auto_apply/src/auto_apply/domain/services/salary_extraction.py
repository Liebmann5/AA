"""Salary extraction from posting text — one pure function, shared.

ST-01 through ST-03 decide "was pay disclosed?" and "is the range real?"
from DetectionContext.salary_min/salary_max. Nothing filled them, so ST-01
recorded a violation on every posting in a covered state — including
postings that showed their pay. This module is the reader.

One function, extract_salary(text), called from posting_observation()
(domain/services/posting_context.py), so vetting, the research aggregator
and replay all see the same salary for the same text. Pure: no I/O, no
clock, standard library only, linear in the input (detectors and
extractors eat arbitrary internet text).

WHAT A SALARY IS HERE
---------------------
* US dollars only. A figure needs "$" (or "USD"); "£80,000", "€90,000",
  "CA$95,000" and bare "90k - 110k" are NOT read as pay. Non-USD pay on a
  US posting is therefore "not found" — ST-01's evidence text says so.
* Periods: per hour (x HOURS_PER_YEAR), per week (x 52), biweekly / every
  two weeks (x 26), semi-monthly / twice a month (x 24), per month (x 12),
  per year. A figure paid per day, per shift or per pay period is not read
  at all: those have no single annual equivalent, and reading "$2,100
  biweekly" as $2,100 a year would be worse than not reading it. A figure with no period marker is read as annual only when it
  is at least $1,000; "$25" with no marker is not a salary.
* "k" means thousands: "$100k - $130k".
* "OTE" / "on-target" marks the figure kind="ote"; the numbers are still
  extracted and still count as disclosed pay.
* WHAT MAKES A FIGURE PAY: a single figure needs positive evidence — a
  pay label near it (salary, pay, pays, paid, wage, rate, compensation,
  base, earnings, remuneration, OTE/on-target), a range word bound to it
  ("up to", "starting at", "at least", "minimum", "maximum"...), or an
  hourly period bound to it ("$25/hr", "$25 per hour", "hourly $25").
  Currency plus a period alone is NOT enough: benefits carry periods too
  ("$270/month", "$5,250 per year"). "Earn" is deliberately NOT a cue —
  it is also the verb in "earn tips" and "earn a bonus"; "earn up to $X"
  is carried by "up to". A range keeps the currency rule: two figures
  clearly one range are pay without any further cue.
* Words for money that is not pay — stipend, tuition, reimbursement,
  allowance, benefit, credit, donation/donated, tips, raised, revenue,
  funding, bonus, equity, stock, signing/sign-on, relocation,
  scholarship, budget, referral, grant — exclude a figure when one is the
  label NEAREST to it, looking up to 45 characters on BOTH sides. For a
  range only the text before it is read, so "$130,000–$155,000 + equity"
  still counts.
* "between $X and $Y" is a range ("and" pairs only after "between", so
  "bonus $10,000 and salary $90,000" stays two figures); "Minimum $X ...
  maximum $Y" combines into one range; the currency marker may trail the
  figure ("25.00 USD per hour").
* "up to $X" discloses a ceiling only (salary_max); "starting at $X" a
  floor only (salary_min); a bare single figure is recorded as salary_min —
  the floor the employer named.
* A range is two figures joined by a dash (any of - – — ‑ −) or "to",
  possibly split across lines. Two figures NOT clearly one range are not a
  range: when a pairing is attempted and fails, both figures are dropped.
* Selection: ranges beat singles, salary-labelled figures beat bare ones,
  base pay beats OTE. If the best candidates still disagree on the numbers,
  the answer is "not found". Ambiguity never resolves to a guess.
* Guard rails: a candidate over $1,000,000/yr is not base pay (budgets,
  prices); a figure with no positive pay cue is not read at all, whatever
  its size ("$75,000", "$2,000/week"). Years, ZIPs, phone numbers,
  headcounts and "401(k)" carry no "$" and never match.

Known miss classes, chosen deliberately: "$"-less k-forms ("95k - 105k"),
figures over $1M/yr (a $600/hr consulting rate among them), malformed
ranges, and cue-less figures that probably are pay ("$2,000/week", "earn
$90,000 a year") — the price of requiring positive evidence. Every miss
makes ST-01 say "not found" — and ST-01's evidence text says exactly what
"not found" means.

The result carries the matched span (with its period words) and the kind,
so every stored figure can be audited against the text it came from; the
aggregator stores that span as salary_observations.source_text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["HOURS_PER_YEAR", "ExtractedSalary", "extract_salary"]

#: Full-time hours used to annualise hourly pay: 40 h/week x 52 weeks — the
#: BLS full-time convention. A stated assumption, not a fact about the job.
HOURS_PER_YEAR = 2080
_WEEKS_PER_YEAR = 52
_MONTHS_PER_YEAR = 12
_BIWEEKS_PER_YEAR = 26
_SEMIMONTHS_PER_YEAR = 24

_MIN_FIGURE_YEAR = 1_000      # a period-less figure below this is not a salary
_MAX_ANNUAL = 1_000_000       # above this is not base pay (budgets, prices)

_FIG = re.compile(
    r"(?<![A-Za-z])(?P<cur>\$|USD\b)?\s*"
    r"(?P<int>\d{1,3}(?:,\d{3})+|\d{1,15})"
    r"(?P<frac>\.\d{1,2})?(?P<k>[kK])?(?!\w)"
)
_GAP = re.compile(
    r"\s*(?:(?:per\s+|an?\s+|/)?(?:hour|hr|week|wk|month|mo|year|yr)\b)?\s*"
    r"(?:[-\u2013\u2014\u2011\u2212]|to)\s*",
    re.I,
)
# Pay periods with no annual reading: matched so that they are recognised
# (and the figure refused) instead of falling through to "year".
_ODD_PERIODS = (
    r"bi-?weekly|semi-?monthly|twice\s+(?:a|per)\s+month"
    r"|every\s+(?:two|2)\s+weeks|daily|per\s+pay\s+period"
)
_PERIOD_AFTER = re.compile(
    r"\s*(?:(?:per\s+|an?\s+|/)(hour|hr|week|wk|month|mo|year|yr|day|shift)\b"
    r"|(" + _ODD_PERIODS + r"|hourly|weekly|monthly|annual(?:ly)?|per\s+annum)\b)",
    re.I,
)
_PERIOD_BEFORE = re.compile(
    r"(" + _ODD_PERIODS + r"|hourly|weekly|monthly|annual(?:ly)?)", re.I
)
_LABEL = re.compile(
    r"on[-\s]target|sign[-\s]on"
    r"|salary|salaries|compensation|wage|earnings|remuneration"
    r"|\bpay\b|\bpays\b|\bpaid\b|\bbase\b|\bOTE\b|\brate\b"
    r"|bonus|equity|stock|signing|relocation|stipend|scholarship"
    r"|budget|referral|grant|tuition|reimbursement|allowance"
    r"|differential|subsidy"
    r"|\bbenefits?\b|\bcredit\b|donated|donation|\btips\b|raised"
    r"|revenue|funding",
    re.I,
)
_OTE = re.compile(r"\bOTE\b|on[-\s]target", re.I)
_MOD_MAX = re.compile(
    r"up\s+to|as\s+much\s+as|max(?:imum)?\b(?:\s+of)?|capped\s+at", re.I
)
_MOD_MIN = re.compile(
    r"starting\s+at|starts\s+at|from|at\s+least|min(?:imum)?\b(?:\s+of)?"
    r"|base\s+of|floor\s+of",
    re.I,
)
_AND_GAP = re.compile(r"\s*and\s*", re.I)
_BETWEEN = re.compile(r"\bbetween\b", re.I)
_TRAILING_USD = re.compile(r"\s*USD\b", re.I)

_CONTEXTS = frozenset({
    "salary", "salaries", "compensation", "wage", "earnings", "remuneration",
    "pay", "pays", "paid", "base", "ote", "on-target", "on target", "rate",
})
_EXCLUSIONS = frozenset({
    "bonus", "equity", "stock", "signing", "sign-on", "sign on", "relocation",
    "stipend", "scholarship", "budget", "referral", "grant", "tuition",
    "differential", "subsidy",
    "reimbursement", "allowance", "benefit", "benefits", "credit", "donated",
    "donation", "tips", "raised", "revenue", "funding",
})

_BEFORE_WINDOW = 45
_AFTER_WINDOW = 45


@dataclass(frozen=True)
class ExtractedSalary:
    """One pay figure or range read from posting text.

    salary_min / salary_max are ANNUAL USD equivalents (hourly x
    HOURS_PER_YEAR, weekly x 52, biweekly x 26, semi-monthly x 24,
    monthly x 12). A one-sided disclosure
    leaves the other side None: "up to $X" -> (None, X); "starting at $X"
    and bare single figures -> (X, None), the floor the employer named.
    period is the stated pay period ("year" also when inferred from
    magnitude); kind is "base" or "ote"; span is the exact text matched,
    whitespace-collapsed, including the period words — the audit trail.
    """

    salary_min: int | None
    salary_max: int | None
    period: str
    kind: str
    span: str

    @property
    def source_text(self) -> str:
        """The span as stored for audit; on-target earnings are tagged."""
        return self.span + (" [OTE]" if self.kind == "ote" else "")


@dataclass(frozen=True)
class _Figure:
    start: int
    end: int
    value: float
    has_currency: bool


@dataclass(frozen=True)
class _Candidate:
    start: int
    end: int
    is_range: bool
    kind: str
    has_context: bool
    annual_min: int | None
    annual_max: int | None
    period: str
    modifier: str  # "" | "min" | "max"


def _figure_value(match: re.Match[str]) -> float:
    value = float(match.group("int").replace(",", "") + (match.group("frac") or ""))
    return value * 1000.0 if match.group("k") else value


def _norm_period(word: str) -> str:
    w = re.sub(r"[\s-]", "", word.lower())
    if w in ("biweekly", "everytwoweeks", "every2weeks"):
        return "biweek"
    if w in ("semimonthly", "twiceamonth", "twicepermonth"):
        return "semimonth"
    if w in ("day", "daily", "shift", "perpayperiod"):
        return "unreadable"
    if w in ("hour", "hr", "hourly"):
        return "hour"
    if w in ("week", "wk", "weekly"):
        return "week"
    if w in ("month", "mo", "monthly"):
        return "month"
    return "year"  # year, yr, annual, annually, per annum


def _annualise(value: float, period: str | None) -> tuple[int, str] | None:
    """(annual USD, resolved period) or None when the figure cannot be read."""
    if period == "hour":
        resolved, annual = "hour", value * HOURS_PER_YEAR
    elif period == "week":
        resolved, annual = "week", value * _WEEKS_PER_YEAR
    elif period == "biweek":
        resolved, annual = "biweek", value * _BIWEEKS_PER_YEAR
    elif period == "semimonth":
        resolved, annual = "semimonth", value * _SEMIMONTHS_PER_YEAR
    elif period == "month":
        resolved, annual = "month", value * _MONTHS_PER_YEAR
    elif period == "unreadable":
        return None
    elif period == "year":
        resolved, annual = "year", value
    elif value >= _MIN_FIGURE_YEAR:
        resolved, annual = "year", value
    else:
        return None
    if not 0 < annual <= _MAX_ANNUAL:
        return None
    return int(round(annual)), resolved


def _trailing_period(text: str, end: int) -> tuple[str | None, int]:
    """The period words right after a figure, and where they end."""
    m = _PERIOD_AFTER.match(text, end)
    if m is None:
        return None, end
    return _norm_period(m.group(1) or m.group(2)), m.end()


def _before_period(before: str) -> str | None:
    m = _PERIOD_BEFORE.search(before)
    return _norm_period(m.group(1)) if m else None


def _nearest_label(before: str, after: str) -> str:
    """The label word closest to the figure, "" when there is none."""
    word = ""
    best = _BEFORE_WINDOW + _AFTER_WINDOW + 1
    for m in _LABEL.finditer(before):
        dist = len(before) - m.end()
        if dist <= best:
            word, best = m.group(0).lower(), dist
    for m in _LABEL.finditer(after):
        dist = m.start() + 1
        if dist < best:
            word, best = m.group(0).lower(), dist
    return word


def _single_candidate(text: str, fig: _Figure) -> _Candidate | None:
    stated, end = _trailing_period(text, fig.end)
    before = text[max(0, fig.start - _BEFORE_WINDOW):fig.start]
    if stated is None:
        stated = _before_period(before)
    resolved = _annualise(fig.value, stated)
    if resolved is None:
        return None
    annual, period = resolved
    label = _nearest_label(before, text[end:end + _AFTER_WINDOW])
    if label in _EXCLUSIONS:
        return None
    has_context = label in _CONTEXTS
    start = fig.start
    modifier = ""
    max_mods = list(_MOD_MAX.finditer(before))
    min_mods = list(_MOD_MIN.finditer(before))
    if max_mods and (not min_mods or max_mods[-1].start() > min_mods[-1].start()):
        modifier = "max"
        start = max(0, fig.start - _BEFORE_WINDOW) + max_mods[-1].start()
    elif min_mods:
        modifier = "min"
        start = max(0, fig.start - _BEFORE_WINDOW) + min_mods[-1].start()
    # A single figure needs positive evidence that it is pay; currency and
    # a period alone are not enough (benefits carry periods too).
    if not (has_context or modifier or stated == "hour"):
        return None
    annual_min, annual_max = (
        (None, annual) if modifier == "max" else (annual, None)
    )
    return _Candidate(
        start, end, False, "ote" if _OTE.search(before) else "base",
        has_context, annual_min, annual_max, period, modifier,
    )


def _range_candidate(text: str, first: _Figure, second: _Figure) -> _Candidate | None:
    if not (first.has_currency or second.has_currency):
        return None
    period, end = _trailing_period(text, second.end)
    before = text[max(0, first.start - _BEFORE_WINDOW):first.start]
    if period is None:
        first_period, _ = _trailing_period(text, first.end)
        period = first_period or _before_period(before)
    lo = _annualise(first.value, period)
    hi = _annualise(second.value, period)
    if lo is None or hi is None:
        return None
    low, resolved_period = lo
    high = hi[0]
    if low > high:
        return None
    label = _nearest_label(before, "")
    if label in _EXCLUSIONS:
        return None
    return _Candidate(
        first.start, end, True, "ote" if _OTE.search(before) else "base",
        label in _CONTEXTS, low, high, resolved_period, "",
    )


def extract_salary(text: str) -> ExtractedSalary | None:
    """The posting's disclosed pay, or None when none is clearly stated.

    Never raises for any str input; linear in len(text). See the module
    docstring for exactly what is and is not read as pay.
    """
    if not text:
        return None
    figures: list[_Figure] = []
    for m in _FIG.finditer(text):
        end = m.end()
        has_currency = m.group("cur") is not None
        if not has_currency:
            # "25.00 USD per hour": the currency marker may trail.
            usd = _TRAILING_USD.match(text, end)
            if usd is not None:
                has_currency = True
                end = usd.end()
        figures.append(_Figure(m.start(), end, _figure_value(m), has_currency))
    ranges: list[_Candidate] = []
    consumed: set[int] = set()
    index = 0
    while index + 1 < len(figures):
        gap = text[figures[index].end:figures[index + 1].start]
        paired = _GAP.fullmatch(gap) is not None
        if not paired and _AND_GAP.fullmatch(gap) is not None:
            # "between $X and $Y" — "and" pairs only after "between", so
            # "bonus $10,000 and salary $90,000" stays two figures.
            window = text[max(0, figures[index].start - 20):figures[index].start]
            paired = _BETWEEN.search(window) is not None
        if paired:
            # Paired or not, these two were meant as one range: a failed
            # pairing consumes both, so a malformed range reads as "not
            # found" rather than as two guesses.
            consumed.add(index)
            consumed.add(index + 1)
            candidate = _range_candidate(text, figures[index], figures[index + 1])
            if candidate is not None:
                ranges.append(candidate)
            index += 2
        else:
            index += 1
    singles: list[_Candidate] = []
    for i, fig in enumerate(figures):
        if i in consumed or not fig.has_currency:
            continue
        candidate = _single_candidate(text, fig)
        if candidate is not None:
            singles.append(candidate)
    candidates = ranges + singles
    if not candidates:
        return None

    def rank(c: _Candidate) -> int:
        return (20 if c.is_range else 10) + (1 if c.has_context else 0)

    best = max(rank(c) for c in candidates)
    top = [c for c in candidates if rank(c) == best]
    preferred = [c for c in top if c.kind == "base"] or top
    chosen: _Candidate | None = None
    min_side = next((c for c in preferred if c.modifier == "min"), None)
    max_side = next((c for c in preferred if c.modifier == "max"), None)
    if (
        min_side is not None
        and max_side is not None
        and min_side.annual_min is not None
        and max_side.annual_max is not None
        and min_side.annual_min <= max_side.annual_max
        and all(c in (min_side, max_side) for c in preferred)
    ):
        # "Minimum $X, maximum $Y": one range stated as two singles.
        chosen = _Candidate(
            min_side.start, max_side.end, True, "base", True,
            min_side.annual_min, max_side.annual_max, min_side.period, "",
        )
    if chosen is None:
        values = {(c.annual_min, c.annual_max) for c in preferred}
        if len(values) != 1:
            return None  # competing answers: not found, never a guess
        chosen = preferred[0]
    return ExtractedSalary(
        salary_min=chosen.annual_min,
        salary_max=chosen.annual_max,
        period=chosen.period,
        kind=chosen.kind,
        span=" ".join(text[chosen.start:chosen.end].split()),
    )

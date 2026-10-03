"""Labelled-example pins for domain/services/salary_extraction.py.

Method (item 4's): GROUND_TRUTH is the table the extractor was designed
against; HELD_OUT is a second table written against the design RULES,
which the finished extractor is then scored on, with precision and recall
pinned as floors so a later change cannot quietly make it worse. Honesty
note: both tables were authored in one pass, so HELD_OUT is a second
opinion, not the wall-clock-separated set item 4 had — the first live run
over real postings is the true held-out set.

These tests fail against the pre-change tree at COLLECTION: the module
does not exist there (ImportError) — that is the teeth for the file.
Expectations are annualised USD (hourly x 2,080, weekly x 52, monthly
x 12); (None, None) means the extractor must find nothing.
"""
from __future__ import annotations

import time
from datetime import date

import pytest

from auto_apply.domain.services.posting_context import posting_observation
from auto_apply.domain.services.salary_extraction import extract_salary

# fmt: off
GROUND_TRUTH: list[tuple[str, int | None, int | None]] = [
    # ── annual ranges, every dash and "to" ──────────────────────────────
    ("Salary: $90,000 - $110,000 per year", 90000, 110000),
    ("$90,000–$110,000", 90000, 110000),
    ("Pay range: $85,000 — $105,000 annually", 85000, 105000),
    ("$120,000 to $160,000", 120000, 160000),
    ("compensation of $50,000 - $60,000 a year", 50000, 60000),
    ("$100k - $130k", 100000, 130000),
    ("$100K-$130K", 100000, 130000),
    ("OTE $120,000 - $160,000", 120000, 160000),
    ("on-target earnings $150,000 to $180,000", 150000, 180000),
    ("Salary range: $90,000 – $250,000 per year, depending on experience.", 90000, 250000),
    ("$45,000 - $52,000.", 45000, 52000),
    ("$85,000 - $105,000 per year", 85000, 105000),
    ("base salary $70,000 – $80,000 plus benefits", 70000, 80000),
    ("The pay range for this role is $55,000 - $65,000.", 55000, 65000),
    ("$200,000 – $240,000 USD", 200000, 240000),
    ("USD 90,000 - 110,000 per year", 90000, 110000),
    ("$90,000 –\n$110,000 per year", 90000, 110000),
    ("from $90,000 to $110,000", 90000, 110000),
    ("Pay: $70,000 − $80,000 per year", 70000, 80000),
    ("Earn $100,000 - $120,000. Base salary plus commission.", 100000, 120000),
    ("compensation: $130,000–$155,000 + equity", 130000, 155000),
    ("Salary: $90,000 - $110,000. Bonus potential $20,000.", 90000, 110000),
    # ── hourly ──────────────────────────────────────────────────────────
    ("$38.00 - $46.00 per hour", 79040, 95680),
    ("$38/hr - $46/hr", 79040, 95680),
    ("$19 - $24 an hour depending on shift", 39520, 49920),
    ("$20.50 an hour", 42640, None),
    ("hourly pay of $25", 52000, None),
    ("$18.75/hour", 39000, None),
    ("Pay: $30 per hour", 62400, None),
    # ── weekly and monthly ──────────────────────────────────────────────
    ("$5,000 - $6,000 per month", 60000, 72000),
    ("monthly salary of $4,500", 54000, None),
    ("$2,000/week", None, None),  # a weekly period alone is not a pay cue
    ("$1,500 - $1,800 per week", 78000, 93600),
    # ── single figures, one-sided, OTE ──────────────────────────────────
    ("up to $90,000", None, 90000),
    ("starting at $50,000", 50000, None),
    ("at least $60,000 per year", 60000, None),
    ("$75,000", None, None),  # no pay cue: a bare figure is not read
    ("$75k", None, None),     # no pay cue: a bare figure is not read
    ("salary of $95,000", 95000, None),
    ("OTE $120,000", 120000, None),
    ("up to $35/hr", None, 72800),
    ("starting at $22 an hour", 45760, None),
    ("Base salary $90,000. OTE $120,000.", 90000, None),
    ("$60,000 base + $20,000 bonus potential", 60000, None),
    ("annual base salary of $88,000", 88000, None),
    # ── must NOT read as pay ────────────────────────────────────────────
    ("Competitive salary and great benefits.", None, None),
    ("Salary is commensurate with experience.", None, None),
    ("Pay TBD.", None, None),
    ("Market rate compensation.", None, None),
    ("401(k) with 4% match.", None, None),
    ("We have 1,000 employees worldwide.", None, None),
    ("Posted 2026. Apply by 2027.", None, None),
    ("Located in ZIP 90210.", None, None),
    ("Call 555-123-4567 to apply.", None, None),
    ("Sign-on bonus of $2,000!", None, None),
    ("Equity grant of $50,000 in stock.", None, None),
    ("£80,000 per year", None, None),
    ("€90,000 - €110,000", None, None),
    ("CA$95,000", None, None),
    ("90k - 110k", None, None),
    ("Salary: competitive. Bonus: $5,000.", None, None),
    ("Save $500 on your first order", None, None),
    ("Our budget is $2,000,000 for this project.", None, None),
    ("Referral bonus $1,500.", None, None),
    ("Pay commensurate with experience; DOE.", None, None),
    ("Salary negotiable.", None, None),
    # ── turn 2: measured false positives — benefits are not pay ─────────
    ("$1,500 annual learning stipend", None, None),
    ("Tuition reimbursement up to $5,250 per year", None, None),
    ("We donated $1,000,000 to charity last year.", None, None),
    ("Wellness reimbursement of $100 per month", None, None),
    ("Annual $2,000 professional development budget", None, None),
    ("Commuter benefit: $270/month", None, None),
    ("Earn up to $500 per week in tips", None, None),
    ("Tuition reimbursement $5,000 - $6,000 per year", None, None),
    # ── turn 2: measured misses — pay in other shapes ───────────────────
    ("This position pays between $45,000 and $52,000.", 45000, 52000),
    ("Pay rate: 25.00 USD per hour", 52000, None),
    ("Minimum $18/hr, maximum $24/hr", 37440, 49920),
    ("Minimum wage of $17 per hour", 35360, None),
    ("Salary: $90,000 per year. Annual bonus available.", 90000, None),
    # ── turn 2: measured correct, pinned so they cannot regress ─────────
    ("Relocation assistance up to $10,000", None, None),
    ("Phone stipend $50/month", None, None),
    ("Signing bonus $10,000 and salary $90,000 - $100,000", 90000, 100000),
    # ── pay periods that are not hour/week/month/year ───────────────────
    # Before: "biweekly" fell through to "year" (the figure read as a
    # $2,100 annual salary) and "Biweekly pay" matched the "weekly" inside
    # it (x 52, double the true figure).
    ("$2,100 - $2,400 biweekly", 54600, 62400),
    ("Biweekly pay: $2,100", 54600, None),
    ("Pay: $1,800 bi-weekly", 46800, None),
    ("Salary: $1,800 semi-monthly", 43200, None),
    ("Pay $4,000 twice a month", 96000, None),
    # No single annual equivalent: refused rather than guessed.
    ("Pay: $450 per day", None, None),
    ("Day rate pay: $1,200 daily", None, None),
    ("Pay $250 per shift", None, None),
    ("Pay: $3,000 per pay period", None, None),
    # Hourly add-ons and subsidies are not pay for the job.
    ("Shift differential of $2.00/hour for night shifts.", None, None),
    ("Childcare subsidy: $400 per month.", None, None),
    # ── the two size bounds, pinned row by row (HELD_OUT's floor alone
    # tolerates losing either) ───────────────────────────────────────────
    ("Rate: $600 per hour", None, None),  # $1.25M a year: over the cap
    ("Pay: $500", None, None),            # no period and under $1,000
]

HELD_OUT: list[tuple[str, int | None, int | None]] = [
    ("The salary for this position is $72,000 - $84,000 per year.", 72000, 84000),
    ("$66,000–$78,000 annually", 66000, 78000),
    ("Pay: $21.00 - $26.00 per hour", 43680, 54080),
    ("$19.50/hr", 40560, None),
    ("weekly pay of $1,200", 62400, None),
    ("$3,800 - $4,200 a month", 45600, 50400),
    ("OTE: $140,000 - $170,000", 140000, 170000),
    ("on-target earnings of $160,000", 160000, None),
    ("up to $120,000 per year", None, 120000),
    ("starting at $85,000", 85000, None),
    ("from $70,000 to $80,000 annually", 70000, 80000),
    ("$55k-$65k", 55000, 65000),
    ("salary $48,000", 48000, None),
    ("compensation: $95,000 - $115,000 + bonus", 95000, 115000),
    ("Base pay $82,000. OTE $110,000.", 82000, None),
    ("$88,000 –\n$96,000", 88000, 96000),
    ("Hourly: $27.50", 57200, None),
    ("$32 an hour", 66560, None),
    ("annual salary of $101,000", 101000, None),
    ("$2,400 per week", None, None),  # a weekly period alone is not a cue
    ("$6,500/month", None, None),     # a monthly period alone is not a cue
    ("Pay range: $41.00 – $49.00 an hour depending on experience.", 85280, 101920),
    ("Salary: $130,000 to $145,000.", 130000, 145000),
    # Deliberate miss: no "$" anywhere, so the extractor says "not found"
    # even though a human reads the salary. This is the recall cost of the
    # currency rule, pinned from both sides (see "80k - 95k per year").
    ("95k - 105k salary", 95000, 105000),
    # ── must NOT read as pay ────────────────────────────────────────────
    ("Competitive compensation package.", None, None),
    ("We offer 401(k) matching and 3 weeks PTO.", None, None),
    ("Over 5,000 applicants last year.", None, None),
    ("Call 800-555-0192 for details.", None, None),
    ("Signing bonus: $3,000.", None, None),
    ("$75,000 in equity over 4 years.", None, None),
    ("£65,000 per annum", None, None),
    ("80k - 95k per year", None, None),
    ("Founded in 2019, growing to 250 staff.", None, None),
    ("$600 per hour consulting rate", None, None),  # over the $1M/yr cap
    ("Salary commensurate with experience, DOE.", None, None),
    ("pays $48,000 a year", 48000, None),
    ("Between $55,000 and $65,000 depending on experience", 55000, 65000),
    ("Maximum $130,000 per year", None, 130000),
    ("Rate: $28.50 per hour", 59280, None),
    ("Health insurance stipend of $200/month", None, None),
]
# fmt: on

_PRECISION_FLOOR = 0.90
_RECALL_FLOOR = 0.90


@pytest.mark.parametrize(("text", "expected_min", "expected_max"), GROUND_TRUTH)
def test_ground_truth(text: str, expected_min: int | None, expected_max: int | None) -> None:
    """TEETH — every labelled pay string reads exactly as labelled."""
    result = extract_salary(text)
    if expected_min is None and expected_max is None:
        assert result is None, f"extracted {result!r} from {text!r}"
    else:
        assert result is not None, f"nothing extracted from {text!r}"
        assert (result.salary_min, result.salary_max) == (expected_min, expected_max)


def test_held_out_precision_and_recall_floors() -> None:
    """GUARD — the extractor's scored performance cannot quietly regress.

    precision = correct extractions / all extractions made; recall =
    correct extractions / rows that should yield one. A wrong-valued
    extraction costs both; a missed one costs recall only.
    """
    made = hits = should = 0
    misses: list[str] = []
    for text, expected_min, expected_max in HELD_OUT:
        expected = (expected_min, expected_max)
        has_expected = expected_min is not None or expected_max is not None
        result = extract_salary(text)
        got = None if result is None else (result.salary_min, result.salary_max)
        if has_expected:
            should += 1
        if got is not None:
            made += 1
            if has_expected and got == expected:
                hits += 1
            else:
                misses.append(f"wrong: {text!r} -> {got}, expected {expected}")
        elif has_expected:
            misses.append(f"missed: {text!r}, expected {expected}")
    precision = hits / made if made else 1.0
    recall = hits / should if should else 1.0
    assert precision >= _PRECISION_FLOOR, f"precision {precision:.3f}: {misses}"
    assert recall >= _RECALL_FLOOR, f"recall {recall:.3f}: {misses}"


@pytest.mark.parametrize(
    "text",
    [
        "", "$", "$-", "k", "$k", "$" + "9" * 5000, "\x00$\x00", "＄ 100",
        "per hour", "$90,000 – ", "–$90,000", "$1,2,3", "$0", "$0.00/hr",
        "USD", "USD k",
    ],
)
def test_extract_salary_never_raises(text: str) -> None:
    """GUARD — arbitrary internet text in; an answer or None out."""
    extract_salary(text)


def test_extraction_is_linear_on_hostile_input() -> None:
    """GUARD — thousands of dollars signs, commas, digits and repeated
    ranges extract in well under a second; no backtracking blow-up."""
    page = (
        ("$" * 20000)
        + ("9," * 20000)
        + ("$90,000 - $110,000 per year. " * 2000)
        + ("1" * 200000)
    )
    started = time.perf_counter()
    result = extract_salary(page)
    assert time.perf_counter() - started < 5.0
    # Two thousand identical ranges agree, so the answer is the range.
    assert result is not None
    assert (result.salary_min, result.salary_max) == (90000, 110000)


def test_posting_observation_fills_salary_from_description() -> None:
    """TEETH vs P1 — the shared builder now fills the salary fields, with
    the as-stated span carried for audit. Fails before: they were None."""
    obs = posting_observation(
        job_title="Registered Nurse",
        job_description="Pay: $38.00 - $46.00 per hour. Full-time.",
        company_name="Acme Health",
        location="Boulder, CO",
        platform="workday",
        url="https://example.test/jobs/7007",
        seen_on=date(2026, 9, 20),
    )
    assert obs.salary_min == 79040
    assert obs.salary_max == 95680
    assert obs.salary_source_text is not None
    assert "$38.00" in obs.salary_source_text


def test_posting_observation_leaves_salary_none_when_no_pay_found() -> None:
    """GUARD — no figure found stays visibly absent, never a guess."""
    obs = posting_observation(
        job_title="Data Analyst",
        job_description="Competitive pay and great benefits.",
        company_name="Acme",
        location="Sacramento, CA",
        platform="greenhouse",
        url="https://example.test/jobs/1001",
        seen_on=date(2026, 9, 14),
    )
    assert obs.salary_min is None
    assert obs.salary_max is None
    assert obs.salary_source_text is None

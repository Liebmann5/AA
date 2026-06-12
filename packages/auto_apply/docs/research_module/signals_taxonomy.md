# Signals Taxonomy

The Research Module records 21 standardised signal types across eight
categories. Each signal is a single, anonymised observation of a hiring
market pattern. Below is the complete catalogue.

---

## Categories & Signals

### Seniority
Signals that document mismatches between job titles, required experience, and
seniority levels.

| Signal | Description |
|--------|-------------|
| `TITLE_DESCRIPTION_MISMATCH` | A job posting’s title indicates a lower tier (e.g. “Software Engineer”) but the description contains explicit senior‑level requirements (e.g. “must lead a team”). |
| `TITLE_UNDISCLOSED_LEVEL` | The job title lacks any tier qualifier (e.g. “Engineer”), yet the description implies a specific level through required years of experience. |
| `ENTRY_LEVEL_EXPERIENCE_REQUIRED` | A position labelled “Entry Level”, “Junior”, or “New Grad” explicitly requires prior professional experience. |
| `MANAGER_HEAVY_POSTING` | A company’s job listings show a disproportionate ratio of manager/senior/lead roles versus individual contributor roles. |

### ATS Process
Signals that capture how Applicant Tracking Systems behave and how
transparent companies are about their use.

| Signal | Description |
|--------|-------------|
| `ATS_REJECTION_RAPID` | An application received a rejection response unusually quickly (e.g. within hours), suggesting automated filtering without human review. |
| `ATS_NO_RESPONSE` | An application received no response at all after a configurable number of days — commonly called “ghosting.” |
| `ATS_PRESENT_UNDISCLOSED` | An ATS was detected during the application process, but the job posting gave no indication that ATS software was in use. |
| `ATS_OPT_OUT_OFFERED` | The application process explicitly offered an option to bypass ATS evaluation (e.g. “click here to be reviewed by a human”). |

### Hidden Gating
Signals that reveal requirements not disclosed in the job posting but
enforced by the application form itself.

| Signal | Description |
|--------|-------------|
| `HIDDEN_REQUIREMENT_FORM` | A form question reveals a minimum requirement (e.g. “Do you have 5+ years of experience?”) that was not stated in the job description. |
| `HIDDEN_REQUIREMENT_DROPDOWN_GATE` | A dropdown field only offers options that imply a minimum threshold (e.g. “Select your experience: 3‑5 years, 5‑7 years…” with no “less than 3” option). |
| `HIDDEN_REQUIREMENT_NUMERIC_GATE` | A numeric text field rejects values below an undisclosed threshold (e.g. a salary expectation field that won’t accept numbers below a certain amount). |

### Form Design
Signals that document design flaws or logical contradictions in application
forms.

| Signal | Description |
|--------|-------------|
| `YIN_YANG_CONFLICT` | The application presents a binary choice that creates a conflict regardless of which option is chosen (e.g. “I am a US citizen / I require visa sponsorship” with no option for permanent residents). |
| `FORM_LOGIC_CONFLICT` | A form field presents options where no single answer correctly represents the candidate (e.g. “Select only one: Python, Java, or C++” when the candidate knows all three). |

### Compensation
Signals that document deceptive or unclear compensation practices.

| Signal | Description |
|--------|-------------|
| `UNPAID_DECEPTIVE_POSTING` | A job listing uses language implying paid employment (e.g. “competitive salary”) but reveals the position is unpaid or underpaid during the application. |

### Friction
Signals that capture unnecessary obstacles in the application process.

| Signal | Description |
|--------|-------------|
| `NO_DIRECT_CONTACT` | The application provides no way to contact a hiring manager or recruiter directly — only anonymous forms or generic inboxes. |
| `AUTH_WALL_MID_APPLICATION` | An account creation or login requirement appeared unexpectedly in the middle of the application, after the user had already started filling out fields. |
| `CAPTCHA_EXCESSIVE` | Multiple CAPTCHA challenges appeared during a single application session, making the process unusually difficult for a human user. |

### Early Career
Signals relevant to internships and entry‑level positions.

| Signal | Description |
|--------|-------------|
| `INTERNSHIP_CURRENT_STUDENT_ONLY` | An internship posting explicitly restricts applicants to currently enrolled students, excluding recent graduates. |
| `INTERNSHIP_UNPAID` | An internship position is unpaid or offers only academic credit. |

### Positive
Signals that document companies doing things right — equally important data
points for a balanced dataset.

| Signal | Description |
|--------|-------------|
| `INCLUSIVE_LANGUAGE_DETECTED` | The job posting uses explicit inclusive language (e.g. “we encourage candidates from all backgrounds to apply”). |
| `SALARY_RANGE_DISCLOSED` | The posting includes a specific salary range rather than vague terms like “competitive” or no information at all. |
| `TRANSPARENT_PROCESS_DESCRIBED` | The posting describes the full hiring process timeline and steps (e.g. “You will hear from us within one week”). |

---

## How Signals Are Recorded

- Each signal is a single row in `research_data/hiring_signals.csv`.
- Signals are generated by `ResearchCollector` subscribers listening to
  `EventBus` events (`APPLICATION_SUBMITTED`, `JOB_VETTED_FAIL`, etc.).
- No personal data is included — only categorical labels, aggregate counts,
  and platform‑type identifiers derived from URL domains (which are never
  stored).
- The `detail_code` field is sanitised to remove any residual URLs or email
  addresses before writing.

---

## Extending the Taxonomy

New signal types can be added by:
1. Adding a member to the `ResearchSignalType` enum in
   `application/services/research/collector.py`.
2. Adding a corresponding event handler in `ResearchCollector`.
3. Updating `_category_for()` to assign the signal to a category.
4. Adding an entry to this document.

The `_CSV_HEADERS` list is designed to accommodate new fields without
breaking existing data.

---

## Next Steps

- [Data Format](data_format.md) — the CSV schema and analysis examples.
- [Research Module Overview](index.md) — purpose, ethics, and privacy.
- [Understanding the Output](../user_guide/understanding_output.md) — where
  the research data file lives and how to use it.
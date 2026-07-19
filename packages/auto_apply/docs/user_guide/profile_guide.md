# Profile Format Reference

Your profile tells AutoApply who you are and what you're looking for.
It is stored as a JSON file in your data directory and validated against
AA's Pydantic v2 schema on every load — invalid profiles are rejected
with a clear error message before any session starts.

## File Location

| Mode | Default location |
|---|---|
| Standard | `~/.auto_apply/profiles/yourname_profile.json` |
| Portable (USB) | `<drive>:/data/profiles/yourname_profile.json` |
| Encrypted | Same location but with `.vault` extension |

To use a profile from a different location, set `AA_PROFILE_PATH` or use the
`--profile` CLI flag:

```bash
python -m auto_apply --profile /path/to/my-profile.json
python -m auto_apply --profile nick_engineer   # loads from storage dir by name
```

---

## Minimal Working Profile

This is the absolute minimum required to run AutoApply:

```json
{
  "profile_name": "Nick Liebmann",
  "personal_info": {
    "first_name": "Nick",
    "last_name": "Liebmann",
    "email": "nick@example.com"
  },
  "career_summary": "Software developer with 4 years of experience building Python automation tools.",
  "search_preferences": {
    "desired_job_titles": ["Software Engineer", "Python Developer"],
    "preferred_locations": ["Remote"]
  }
}
```

With this profile, AA can search for jobs, fill out basic name/email fields,
and use your career summary as a fallback for open-ended questions.

---

## Complete Profile Example

```json
{
  "profile_name": "Nick Liebmann — Engineering",
  "personal_info": {
    "first_name": "Nick",
    "last_name": "Liebmann",
    "email": "nick@example.com",
    "phone_number": "555-000-0000",
    "street_address": "123 Main St",
    "city": "Los Angeles",
    "state": "CA",
    "zip_code": "90001",
    "country": "United States",
    "resume_path": "resume.pdf"
  },
  "links": {
    "linkedin": "https://linkedin.com/in/nickliebmann",
    "github": "https://github.com/nickliebmann",
    "portfolio": "https://nickliebmann.dev"
  },
  "career_summary": "Full-stack Python developer with 4 years building open-source automation tools. Creator of AutoApply. Strong background in data engineering, SQLite, and browser automation.",
  "work_experience": [
    {
      "company": "Self-Employed / Open Source",
      "title": "Software Developer",
      "start_date": "2020-01",
      "end_date": "present",
      "description": "Built AutoApply, an autonomous job application platform used by researchers and job seekers. Technologies: Python, SQLite, Selenium, Playwright, Pydantic."
    }
  ],
  "education": [
    {
      "school": "University of Southern California",
      "degree": "Bachelor of Science",
      "discipline": "Computer Science",
      "start_date": "2016",
      "end_date": "2020",
      "gpa": null
    }
  ],
  "search_preferences": {
    "desired_job_titles": ["Software Engineer", "Python Developer", "Backend Engineer"],
    "preferred_locations": ["Remote", "Los Angeles, CA"],
    "skills": ["Python", "SQLite", "Selenium", "Playwright", "FastAPI", "Docker"],
    "employment_types": ["full-time"],
    "workplace_types": ["remote", "hybrid"],
    "salaryExpectations": 95000,
    "blocked_companies": [],
    "blocked_vocabulary": ["Staffing Agency", "W2 Only", "C2C"]
  },
  "app_config": {
    "preferred_browser": "chrome",
    "run_headless": false,
    "daily_application_limit": 50,
    "enable_behavior_humanization": true
  },
  "politeness_settings": {
    "respect_robots_txt": true,
    "default_delay": 2.0
  },
  "custom_answer_templates": [
    {
      "keywords": ["why this role", "why interested", "why us", "why this company"],
      "answer": "I'm drawn to this role because it aligns with my experience building production Python systems and my interest in automation at scale. I value engineering cultures that prioritize code quality and clear architecture.",
      "max_length": 400
    },
    {
      "keywords": ["salary", "compensation", "expected pay", "pay range"],
      "answer": "$95,000–$120,000 depending on the full compensation package.",
      "max_length": 100
    },
    {
      "keywords": ["authorized to work", "work authorization", "visa", "sponsorship"],
      "answer": "Yes",
      "max_length": 10
    }
  ]
}
```

---

## Field Reference

### `personal_info`

| Field | Required | Type | Notes |
|---|---|---|---|
| `first_name` | ✅ Yes | string | Used in almost every application form |
| `last_name` | ✅ Yes | string | Same |
| `email` | ✅ Yes | email | Primary contact for employers |
| `phone_number` | Recommended | string | Many forms require it |
| `street_address` | Optional | string | Full street address |
| `city` | Optional | string | Your city of residence |
| `state` | Optional | string | State/province abbreviation |
| `zip_code` | Optional | string | Postal code |
| `country` | Optional | string | Default: "United States" |
| `resume_path` | Recommended | path | Path to your resume (PDF, DOCX, TXT). Relative paths like `"resume.pdf"` resolve against the profiles directory for USB portability. |
| `cover_letter` | Optional | path or text | Path to a cover letter file, or the text of your cover letter. |

### `links`

| Field | Required | Type | Notes |
|---|---|---|---|
| `linkedin` | Optional | URL | Full LinkedIn profile URL |
| `github` | Optional | URL | GitHub profile URL |
| `portfolio` | Optional | URL | Personal website or portfolio |

### `work_experience`

Each entry describes one past or present job. AA uses the **description**
field to answer open-ended custom questions — the more detailed your
descriptions, the better AA can respond.

| Field | Required | Type | Notes |
|---|---|---|---|
| `company` | Yes | string | Employer name |
| `title` | Yes | string | Your job title |
| `start_date` | Yes | string | `"YYYY-MM"` or `"YYYY"` |
| `end_date` | Optional | string | `"YYYY-MM"`, `"present"`, or `null` |
| `description` | Recommended | string | What you did — used for AI answers |

### `education`

| Field | Required | Type | Notes |
|---|---|---|---|
| `school` | Yes | string | Institution name |
| `degree` | Yes | string | e.g., "B.S.", "M.A.", "Ph.D." |
| `discipline` | Yes | string | Field of study |
| `start_date` | Optional | string | `"YYYY"` |
| `end_date` | Optional | string | `"YYYY"` |
| `gpa` | Optional | string | GPA, if you want to include it |

### `career_summary`

**Required.** Minimum 50 characters. 3–5 sentences about your background,
skills, and what you are looking for. This is used:

- As the fallback answer when GPT4All is unavailable for custom questions
- In the GPT4All prompt context ("User background: ...")
- As a generic "about me" answer when no better match is found

A good career summary is the single most impactful field for improving AA's
form-filling quality.

### `search_preferences`

Controls what AA looks for and what it filters out.

| Field | Required | Type | Notes |
|---|---|---|---|
| `desired_job_titles` | ✅ Yes | list[string] | Titles to search for. Minimum 1. |
| `preferred_locations` | Optional | list[string] | e.g., `["Remote", "Los Angeles, CA"]` |
| `skills` | Recommended | list[string] | Your skills — matched against job requirements |
| `employment_types` | Optional | list[string] | `"full-time"`, `"part-time"`, `"contract"`, `"temporary"`, `"internship"` |
| `workplace_types` | Optional | list[string] | `"remote"`, `"hybrid"`, `"in-office"` |
| `salaryExpectations` | Optional | integer | Yearly USD. Used for filtering. |
| `blocked_companies` | Optional | list[string] | Company names to skip automatically |
| `blocked_vocabulary` | Optional | list[string] | Keywords that cause a job to be skipped |

### `custom_answer_templates`

Pre-write answers to common custom questions. AA checks these **before**
invoking GPT4All or falling back to your career summary.

The `keywords` list uses **fuzzy matching** — you don't need to match the
exact question text. `"why this role"` will match:

- "Why are you interested in this position?"
- "Tell us why you want to work here"
- "What draws you to this role?"

Each template has:

| Field | Type | Notes |
|---|---|---|
| `keywords` | list[string] | Phrases to match against the question |
| `answer` | string | Your pre-written answer (min 20 chars) |
| `max_length` | integer | Truncation limit. AA will not paste more than this many characters. Default: 500. |

### `app_config`

Controls AA's runtime behavior.

| Field | Type | Default | Notes |
|---|---|---|---|
| `preferred_browser` | string | `"any"` | `"chrome"`, `"firefox"`, `"edge"`, `"safari"`, `"any"` |
| `run_headless` | boolean | `false` | Hide the browser window |
| `daily_application_limit` | integer | 200 | Hard cap per session |
| `enable_behavior_humanization` | boolean | `true` | Add human-like timing |

### `politeness_settings`

| Field | Type | Default | Notes |
|---|---|---|---|
| `respect_robots_txt` | boolean | `true` | Obey website crawling rules |
| `default_delay` | float | 2.0 | Seconds between actions |

---

## Resume Path Portability

AA supports both absolute and relative resume paths:

```json
// Absolute — works on your machine, breaks on USB drive
"resume_path": "/home/nick/Documents/resume.pdf"

// Relative — portable! Resolves against the profiles directory
"resume_path": "resume.pdf"

// Relative with subfolder
"resume_path": "documents/resume.pdf"
```

For USB portable mode, **always use relative paths**. Place your resume
next to your profile JSON and use `"resume_path": "resume.pdf"`. AA
resolves it at runtime relative to the drive, so it works regardless
of which computer you plug into.

---

## Encrypting Your Profile

AA can encrypt your profile with AES-256. The plaintext JSON is replaced
with a `.vault` file that requires a password to open.

```bash
# Encrypt an existing profile
python -m auto_apply --encrypt-profile

# Or set a password in the environment to skip the prompt
export AA_VAULT_PASSWORD="your-secure-password"
```

If you lose your password, the profile **cannot** be recovered. There is
no backdoor. Store your password securely.

---

## Multiple Profiles

You can maintain multiple profiles for different job searches:

```
~/.auto_apply/profiles/
├── nick_engineer.json       # Software engineering
├── nick_data.json           # Data engineering
└── nick_management.json     # Engineering management
```

Switch between them at startup or with the `--profile` flag:

```bash
python -m auto_apply --profile nick_data
```

---

## Next Steps

- [Running a Job Hunt](running_a_job_hunt.md) — session modes and live monitoring
- [Configuration Reference](../getting_started/configuration.md) — environment variables and advanced settings
- [Profiles & Privacy](profiles_and_privacy.md) — encryption, data storage, and PII protection

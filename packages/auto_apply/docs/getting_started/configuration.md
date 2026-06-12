# Configuration

AutoApply is ready to run with zero configuration — the Setup Wizard creates
everything you need. This guide covers the details: where your profile lives,
what every field means, how to use environment variables for portable mode,
and how to lock down AA for shared machines.

---

## Configuration sources

AA reads settings from three places, in order of priority (highest first):

| Priority | Source | Purpose |
| -------- | ------ | ------- |
| 1 | **Environment variables** | Runtime overrides, portable‑mode paths, debugging |
| 2 | **Admin policy** (`aa_policy.json`) | Locks down features on shared/library computers |
| 3 | **User profile** (`<name>.json`) | Your personal info, search preferences, app behaviour |

The final value for any setting is the first non‑empty one found, checking
top to bottom. This means an admin can force a headless browser, a user can
override the default delay, and a portable‑mode user can redirect caches via
environment variables — all without editing code.

---

## User profile

Your profile is a JSON file stored in the AA data directory. It contains
everything AA needs to apply for jobs on your behalf.

### Profile location

| Platform | Default path |
| -------- | ------------ |
| Windows  | `%USERPROFILE%\.auto_apply\profiles\<name>.json` |
| macOS    | `~/.auto_apply/profiles/<name>.json` |
| Linux    | `~/.auto_apply/profiles/<name>.json` |
| **USB portable** | `<drive>:\AutoApply\data\profiles\<name>.json` |

To change the path, set the environment variable `AA_PROFILE_PATH` to an
absolute path before launching.

### First‑run wizard

The first time you launch AA, the Setup Wizard creates your profile
automatically. You can also create profiles manually by copying the
template from `resources/templates/default_profile.json` and editing it.

### Profile structure

A minimal profile looks like this:

```json
{
  "profile_name": "john-dev",
  "personal_info": {
    "first_name": "John",
    "last_name": "Doe",
    "email": "john@example.com",
    "phone_number": "555-1234",
    "street_address": "123 Main St",
    "city": "Portland",
    "state": "OR",
    "zip_code": "97201",
    "country": "United States",
    "resume_path": "/home/john/resume.pdf",
    "cover_letter": null
  },
  "links": {
    "linkedin": null,
    "github": null,
    "portfolio": null
  },
  "education": [],
  "work_experience": [],
  "career_summary": "Experienced software engineer with 5 years...",
  "search_preferences": {
    "desired_job_titles": ["Software Engineer", "Backend Developer"],
    "preferred_locations": ["Remote"],
    "skills": ["Python", "Docker", "SQL"]
  },
  "application_preferences": {},
  "app_config": {},
  "politeness_settings": {}
}
```

### Key profile fields

| Section | Field | Purpose |
| ------- | ----- | ------- |
| `personal_info` | `resume_path` | Absolute path to your resume (PDF, DOCX, or TXT) |
| `personal_info` | `cover_letter` | Path to a cover letter file, or a raw text string |
| `work_experience` | `description` | Used by the AI/NLP tier to answer open‑ended questions |
| `search_preferences` | `desired_job_titles` | Titles you want — AA searches and matches against these |
| `search_preferences` | `skills` | Your skills for matching against job requirements |
| `search_preferences` | `max_commute_miles` | Maximum one‑way commute (set to `null` for no limit) |
| `app_config` | `preferred_browser` | `"chrome"`, `"firefox"`, `"edge"`, `"any"` |
| `app_config` | `run_headless` | `true` to hide the browser window |
| `app_config` | `daily_application_limit` | Hard cap on applications per session |
| `politeness_settings` | `respect_robots_txt` | `true` to obey `robots.txt` (recommended) |
| `politeness_settings` | `default_delay` | Seconds between browser actions (min 0.5) |

The full profile schema is documented in the
[API Reference](../api_reference/index.md) (auto‑generated from Pydantic models).

### Encryption

AA can encrypt your profile with AES‑256 using a master password. To enable:

1. Launch AA with `--password` or set the `AA_MASTER_PASSWORD` environment
   variable.
2. AA will prompt for the password on startup (or read it from the variable).
3. All profile data is encrypted at rest.

If you lose your password, the profile cannot be recovered — there is no
backdoor. Store the password securely.

### External profiles (USB drives)

You can store your profile on a removable drive and load it on any machine:

1. Place your profile JSON on the drive (e.g. `E:\my_profile.json`).
2. Launch AA with `AA_PROFILE_PATH=E:\my_profile.json`.
3. AA reads the profile from the drive and stores session data locally (or on
   the same drive in portable mode).

This is ideal for users who want to keep their personal data entirely on a
USB stick, even when running AA on a shared computer.

---

## Environment variables

All environment variables are optional. They allow you to override paths,
enable portable mode, and tweak behaviour without editing code.

### General

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `AA_PROFILE_PATH` | `~/.auto_apply/profiles/<name>.json` | Path to a specific profile JSON |
| `AA_DB_PATH` | `~/.auto_apply/applications.db` | Path to the application history database |
| `AA_LOG_LEVEL` | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `AA_LOG_DIR` | `~/.auto_apply/logs/` | Directory for log files |
| `AA_MASTER_PASSWORD` | *(none)* | Master password for profile encryption (use with caution — visible in process lists) |

### Portable mode (cache redirection)

When running AA from a USB drive, you must ensure that all caches and
temporary files stay on the drive. Set these variables **before** launching
AA, or add them to a `launch.bat` script on the drive:

| Variable | What it controls |
| -------- | ---------------- |
| `HF_HOME` | Hugging Face model cache (SpaCy pipelines, future models) |
| `GPT4ALL_CACHE` | GPT4All model downloads |
| `PLAYWRIGHT_BROWSERS_PATH` | Playwright's bundled browser binaries |
| `SPACY_DATA` | SpaCy language model data |
| `TORCH_HOME` | PyTorch model cache |
| `USER_DATA_DIR` | Chromium user profile directory (Selenium) |
| `TEMP` / `TMP` | Temporary files (overrides system temp) |

**Example `launch.bat` for a portable USB setup:**

```batch
@echo off
set AA_PROFILE_PATH=%~dp0data\profiles\default.json
set AA_DB_PATH=%~dp0data\applications.db
set HF_HOME=%~dp0data\cache\huggingface
set GPT4ALL_CACHE=%~dp0data\cache\gpt4all
set PLAYWRIGHT_BROWSERS_PATH=%~dp0data\bin\pw-browsers
set SPACY_DATA=%~dp0data\cache\spacy
set TORCH_HOME=%~dp0data\cache\torch
set TEMP=%~dp0data\tmp
set TMP=%~dp0data\tmp

start "" "%~dp0AutoApply.exe" %*
```

With these variables set, AA writes **nothing** outside the USB drive's
folder structure. See [PyInstaller Portable Build](../deployment/pyinstaller_portable.md)
for the complete portable packaging guide.

### Debugging & development

| Variable | Effect |
| -------- | ------ |
| `AA_DEBUG=1` | Equivalent to `--debug` CLI flag — enables verbose logging |
| `CONTAINER=1` | Forces container mode (needed for Podman / Kubernetes where auto‑detection fails) |

---

## Admin policy

IT administrators can deploy a JSON file that locks down AA's behaviour on
shared computers. The file `aa_policy.json` is placed in AA's application
directory (or on the USB drive root) and set to read‑only via OS permissions.

A policy can restrict:

- Allowed browsers
- Maximum applications per session
- Whether the browser must run headless
- Minimum action delay
- Whether research data collection is permitted

The full syntax and deployment instructions are in the
[Admin Policy Guide](../user_guide/admin_policy.md) and
[Enterprise Deployment Guide](../deployment/enterprise_admin_policy.md).

---

## Configuration verification

Run AA with the `--check-config` flag to validate your setup without starting
a session:

```bash
python -m auto_apply --check-config
```

Output:

```
✅ Profile loaded: john-dev
✅ Database accessible: ~/.auto_apply/applications.db
✅ At least one browser available: chrome
✅ Admin policy: none
⚠️  Playwright browsers not installed — Selenium will be used
⚠️  SpaCy model not installed — NLP tier disabled
```

This tells you exactly what is working and what is optional.

---

## Next steps

- [Running a Job Hunt](../user_guide/running_a_job_hunt.md) — session modes, GUI vs CLI
- [Profiles & Privacy](../user_guide/profiles_and_privacy.md) — encryption, data storage, PII protection
- [FAQ](../faq.md) — common errors and their fixes
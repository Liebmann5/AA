# AutoApply — Portable Edition

## What This Is

This USB drive contains a complete, self-contained copy of **AutoApply** —
an autonomous agent for discovering, vetting, and applying for jobs. You
can plug this drive into any Windows, macOS, or Linux computer and run AA
without installing anything and without leaving any trace on the host
machine.

---

## How to Use

### Windows
Double-click **`launch_portable.bat`**

### Linux / macOS
Open a terminal in this folder and run:
```bash
chmod +x launch_portable.sh
./launch_portable.sh
```

---

## Your Profile

Your profile is stored at:

```
data/profiles/default.json
```

Edit it with any text editor to add your name, email, job preferences,
and any blocked companies or keywords.

Your resume should be placed at:

```
data/profiles/resume.pdf
```

Then set `"resume_path": "resume.pdf"` in your profile. This relative
path works on any computer regardless of the drive letter.

---

## What's Where

| Path | Purpose |
|------|---------|
| `data/profiles/` | Your user profile(s) and resume |
| `data/aa_data.db` | SQLite database: jobs, applications, work queue |
| `data/logs/` | Session logs |
| `data/checkpoints/` | Crash recovery snapshots |
| `data/screenshots/` | Screenshots captured on failures |
| `data/reports/` | Session JSON reports |
| `data/research/` | Anonymized research signals (opt-in only) |
| `data/cache/` | Browser profile, AI model cache |
| `data/tmp/` | Temporary files (wiped after each session) |

---

## Privacy Guarantee

1. **ALL data stays on this drive.** Nothing is written to the host
   computer's hard drive, user folder, or registry.
2. When you remove the drive, **zero traces remain** on the host machine.
3. The optional research module collects only anonymized, aggregate data.
   Company names and job URLs are never stored.

---

## Need Help?

- Full documentation: https://github.com/Liebmann5/AA
- Report a bug: https://github.com/Liebmann5/AA/issues
- Architecture deep-dive: `AA_ARCHITECTURE_BIBLE.md` (on this drive)

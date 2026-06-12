# Profiles & Privacy

Your profile is the only personal information AA ever touches. This guide
explains how to create profiles, keep them safe with encryption, store them
on external drives, and understand exactly what AA does with your data.

---

## 1. Creating your first profile

### Setup Wizard (automatic)

The very first time you launch AutoApply, the **Setup Wizard** opens
automatically. It asks for the bare minimum:

- A name for your profile (e.g. "John‑Dev")
- Your resume file (PDF or DOCX)
- An email address

Everything else — work history, skills, salary preferences — can be added
later. Once you click **Create Profile & Continue**, AA saves your profile
in its data directory and you never have to fill it in again.

### Manual creation

If you prefer to create a profile by hand, copy the template file from
`resources/templates/default_profile.json` to your AA data folder (usually
`~/.auto_apply/profiles/`) and edit it with any text editor. The file is
plain JSON and every field is documented inside the template.

!!! tip
    If you want to test different job‑hunt strategies, you can create multiple
    profiles — one for "Python Developer", another for "Data Engineer", etc.
    AA's profile selector lets you switch between them on startup.

---

## 2. Understanding your profile

Your profile is a JSON file organised into sections. Here is what each
section contains and how AA uses it.

### `personal_info`

Basic identity and contact information. This is what AA types into form
fields like "First Name", "Last Name", "Email", and "Phone Number".

- `resume_path` – The absolute path to your resume file. AA uploads this
  whenever a form asks for a CV.
- `cover_letter` – Either a path to a cover letter file or the text of your
  cover letter. AA uses the text version when a form has a "Cover Letter"
  text field rather than a file upload.

### `work_experience`

A list of your previous jobs. Each entry has a `company`, `title`, `start_date`,
`end_date`, and `description`. The **description** is particularly important —
when a form asks an open‑ended question like "Describe a challenging project",
AA searches your work descriptions for the most relevant paragraph and uses it
as your answer. The more detailed your descriptions, the better AA can respond.

### `search_preferences`

Controls *what* AA looks for:

- `desired_job_titles` – The titles you want (e.g. "Software Engineer").
- `preferred_locations` – Cities, states, or "Remote".
- `skills` – Your technical skills for matching against job requirements.
- `max_commute_miles` – If you only want jobs within a certain distance.
  Set to `null` to accept any location.
- `blocked_companies` / `blocked_vocabulary` – Companies or keywords you want
  AA to skip automatically.

### `app_config`

Controls *how* AA behaves:

- `preferred_browser` – Which browser to use ("chrome", "firefox", "edge", or
  "any").
- `run_headless` – If `true`, the browser window is hidden. Useful for
  background operation.
- `daily_application_limit` – Hard cap on how many applications AA will send
  in one session.
- `human_review_checkpoints` – List of moments where AA pauses and asks you
  to approve or skip. Default: `["BEFORE_FORM_SUBMIT", "ON_SUSPICIOUS_REDIRECT"]`.

### `politeness_settings`

- `respect_robots_txt` – If `true`, AA obeys website rules about what pages
  bots may visit. We recommend keeping this on.
- `default_delay` – How many seconds AA waits between actions (minimum 0.5).
  Higher values make AA look more like a human.

The complete profile schema is generated from AA's source code and available
in the [API Reference](../api_reference/index.md).

---

## 3. Keeping your data safe: Encryption

AA can encrypt your profile with **AES‑256**, the same standard used by banks
and governments. Encryption is optional but strongly recommended — especially
if you store your profile on a shared computer or a USB drive.

### What encryption does

- Your profile file is replaced with an encrypted blob. Without the password,
  the file is unreadable.
- Encryption is applied when you **save** the profile. AA decrypts it into
  memory only while the session is running.
- The password is never stored anywhere. If you lose it, the profile **cannot**
  be recovered. There is no backdoor.

### Setting up encryption

1. Launch AA with the `--password` flag, or set the `AA_MASTER_PASSWORD`
   environment variable. AA will prompt you for the password.
2. AA derives an encryption key from your password using PBKDF2 (480,000
   iterations) — this makes brute‑force attacks extremely slow.
3. The next time you open AA, you must provide the same password to unlock
   your profile.

### Changing or removing encryption

- To change your password, load the profile with the old password, then
  re‑save it with a new one.
- To remove encryption, load the profile with the password and save it while
  no password is set. AA will write a plain‑text JSON again.

---

## 4. Storing profiles on external drives

You can keep your profile on a USB stick and load it whenever you plug the
drive into any computer. This is perfect for:

- Using AA on library or shared computers without leaving personal data behind.
- Switching between your home computer and a laptop.
- Keeping your profile physically separate from your application history.

### Loading a profile from a USB drive

There are three ways:

1. **Launch argument** – `python -m auto_apply --profile E:\my_profile.json`
2. **Environment variable** – Set `AA_PROFILE_PATH=E:\my_profile.json` before
   launching.
3. **Auto‑detection** – In portable mode, AA scans the drive for any
   `profile.json` file in its data folder and offers to load it.

When you load an external profile, AA still stores session data (application
history, logs, screenshots) in its normal data directory *on the computer you
are using*. If you want session data to also stay on the USB drive, run AA in
full portable mode (see below).

### Keeping everything on the USB drive (Portable Mode)

If you downloaded the **USB portable package**, everything — profile, database,
logs, caches — lives on the flash drive. When you unplug, nothing remains on
the host computer.

To achieve this with a manual install, set the cache redirection environment
variables described in the [Configuration Guide](../getting_started/configuration.md#portable-mode-cache-redirection)
before launching AA. This ensures that even temporary files never touch the
host.

---

## 5. Where your data lives

| Data | Default location |
| ---- | ---------------- |
| Profiles | `~/.auto_apply/profiles/` (or USB drive in portable mode) |
| Application history | `~/.auto_apply/applications.db` |
| Session logs | `~/.auto_apply/logs/app.log` |
| Failure screenshots | `~/.auto_apply/screenshots/` |
| Checkpoints | `~/.auto_apply/checkpoints/` |
| Research signals (opt‑in) | `~/.auto_apply/research_data/hiring_signals.csv` |

All of these paths can be overridden with environment variables. See the
[Configuration Reference](../getting_started/configuration.md) for details.

---

## 6. Privacy: What AA shares and what it doesn't

### AA never sends your data anywhere

AutoApply runs entirely on your machine. It does **not** phone home. It does
**not** use cloud services. It does **not** have analytics. When you apply for
a job, AA behaves exactly like you would if you were typing into a browser —
it sends only the information that the form requires.

### The research module (opt‑in only)

If you explicitly enable **Research Collection** in your profile (`enable_research_collection: true`),
AA records anonymised observations about the hiring market. This data:

- Contains **no personal information** — no names, emails, job URLs, or company
  names.
- Is stored locally as a CSV file.
- Is never uploaded unless you manually export and choose to share it.

You can read exactly what is collected and why in the
[Research Module documentation](../research_module/index.md).

### Admin policy and privacy

If AA is deployed on a shared computer, an administrator may have set an
**Admin Policy** that disables research collection or restricts which browsers
can be used. This policy is enforced automatically. You can see whether an
admin policy is active by running AA with the `--check-config` flag.

---

## 7. Best practices for sensitive information

- **Encrypt your profile.** If your profile contains your home address, phone
  number, or any other PII, enable encryption. The small inconvenience of
  typing a password on startup is worth the security.
- **Keep your profile on a USB drive** if you use shared computers. Never
  store a plain‑text profile on a machine you don't control.
- **Review applications before submitting.** The default human‑review
  checkpoints exist for a reason — they let you catch any field that was
  filled incorrectly before it is sent.
- **Use a dedicated email address** for job applications. AA fills out forms
  with whatever email you provide. Using a separate inbox keeps your job hunt
  organised and protects your primary email from potential spam.

---

## Next steps

- [Configuration Reference](../getting_started/configuration.md) – every
  environment variable and profile field in detail.
- [Admin Policy](admin_policy.md) – how IT admins can lock down AA.
- [FAQ](../faq.md) – answers to common privacy and security questions.
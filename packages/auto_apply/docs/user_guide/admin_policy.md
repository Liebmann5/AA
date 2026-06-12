# Admin Policy

An **Admin Policy** lets a system administrator lock down AutoApply's
behaviour across all users on a shared computer — a library, a school lab, a
corporate fleet. Once deployed, users cannot override the locked settings.

AA's policy system is designed to be **zero‑configuration for the end user**.
The administrator drops a single JSON file onto the machine, sets its
permissions to read‑only, and AA enforces it automatically on every launch.

---

## How it works

The policy file is called `aa_policy.json`. AA looks for it in its
**application directory** — the folder containing `AutoApply.exe` (portable
build) or the installed package root. If the file exists, AA reads it at
startup and applies every constraint it finds.

The policy is the **top tier** of AA's three‑tier configuration hierarchy:

```
AdminPolicy   (top — overrides everything below)
    ↓
UserSettings  (the user's profile)
    ↓
RuntimeDefaults (built‑in fallbacks)
```

If a field is set in the admin policy, the user's preference is ignored for
that field. If a field is absent (or `null`), the user's setting (or the
default) wins. This lets administrators lock only what they need and leave
everything else flexible.

!!! important
    The policy file is **not cryptographically signed**. It relies on OS
    file permissions for protection — the same model used by Chrome and
    Firefox enterprise policies. On a properly configured machine, standard
    users cannot modify the file because it is read‑only.

---

## 1. Creating the policy file

AA includes a template generator to help you create a policy from scratch:

```bash
python -m auto_apply --create-policy
```

This writes `aa_policy.json` to the current directory with every available
field documented. You can also create the file manually — it's plain JSON.

### Where to place the file

| Installation type | Policy location |
| ----------------- | --------------- |
| Portable (USB)    | Next to `AutoApply.exe` |
| pip install       | The folder where `auto_apply` is installed (typically `site-packages/auto_apply/`) |
| From source       | The repository root |

AA also checks the directory containing the profile file, but the primary
location is the application directory. To be safe, place the policy in both
locations if you are unsure.

---

## 2. Policy fields

All fields are optional. Only include the fields you want to lock — everything
else will use the user's preference.

```json
{
  "_comment": "AA Admin Policy — set fields you want to lock. null = user controlled.",
  
  "allowed_browsers": ["firefox", "chrome"],
  "blocked_tools": ["undetected_chromedriver"],
  "max_applications_per_session": 50,
  "force_headless": true,
  "force_humanization": true,
  "force_respect_robots_txt": true,
  "min_action_delay_seconds": 2.0,
  "disable_research_collection": true,
  "config_overrides": {
    "log_retention_days": 7
  }
}
```

### `allowed_browsers`

A list of browser names that users are permitted to use. If your organisation
only supports Firefox and Chrome, set:

```json
"allowed_browsers": ["firefox", "chrome"]
```

Users who prefer Edge or Safari will be silently redirected to the first
allowed browser that is installed. If no allowed browser is installed, AA
will not start and will display a clear error message.

If you omit this field (or set it to `null`), all browsers are allowed.

### `blocked_tools`

A list of tool names that are prohibited. For example, to prevent the use of
`undetected-chromedriver`:

```json
"blocked_tools": ["undetected_chromedriver"]
```

AA checks this list against its detected capabilities at startup. Blocked
tools are removed from the available list before any browser selection
happens.

### `max_applications_per_session`

A hard cap on the number of job applications AA will submit in one session.
This protects your network from excessive traffic and prevents users from
running AA unattended for days.

```json
"max_applications_per_session": 50
```

If the user has a lower limit in their profile, the lower value is used.
The admin cap is a ceiling, not a floor.

### `force_headless`

If `true`, the browser window is always hidden, regardless of the user's
preference. This is essential on shared computers where visible browser
windows would disrupt other users.

```json
"force_headless": true
```

### `force_humanization`

If `true`, human‑behaviour simulation (random delays, mouse movements) is
always enabled. This prevents users from running AA at aggressive speeds that
could trigger bot detection and get your institution's IP address flagged.

```json
"force_humanization": true
```

### `force_respect_robots_txt`

If `true`, AA always obeys `robots.txt` rules, even if the user has disabled
this in their profile. This protects your organisation from violating website
terms of service and potential legal liability.

```json
"force_respect_robots_txt": true
```

### `min_action_delay_seconds`

A minimum delay (in seconds) between browser actions. This sets a floor on
how fast AA can operate — users can set a longer delay, but never a shorter
one.

```json
"min_action_delay_seconds": 2.0
```

### `disable_research_collection`

If `true`, the research data collection feature is permanently disabled on
this device, regardless of any user's opt‑in preference. This is for
institutions that have strict data‑collection policies.

```json
"disable_research_collection": true
```

### `config_overrides`

A catch‑all for overriding any key in AA's internal runtime configuration.
This is an escape hatch for constraints not covered by the explicit fields
above. Use sparingly — most needs are covered by the named fields.

```json
"config_overrides": {
  "log_retention_days": 7,
  "checkpoint_interval_actions": 10
}
```

---

## 3. Protecting the policy file

AA trusts the policy file only if the operating system prevents unauthorised
users from modifying it. After creating `aa_policy.json`, you must set its
permissions to **read‑only for standard users**.

=== "Windows"

    1. Right‑click `aa_policy.json` → **Properties**.
    2. Go to the **Security** tab → **Advanced**.
    3. Disable inheritance and convert inherited permissions to explicit.
    4. Remove all entries for standard users, or set them to **Read & execute**
       and **Read** only.
    5. Ensure the Administrators group retains **Full control**.

    Alternatively, from an elevated command prompt:
    ```cmd
    icacls aa_policy.json /inheritance:r /grant:r "Administrators:(F)" /grant:r "SYSTEM:(F)" /grant:r "Users:(R)"
    ```

=== "macOS"

    ```bash
    chmod 644 aa_policy.json
    sudo chown root:admin aa_policy.json
    ```

    This makes the file readable by everyone but writable only by root.

=== "Linux"

    ```bash
    chmod 644 aa_policy.json
    sudo chown root:root aa_policy.json
    ```

    On systems with SELinux or AppArmor, ensure the policy file has the
    correct security context for the application to read it.

---

## 4. Verifying the policy

Run AA with the `--check-config` flag to confirm the policy is loaded:

```bash
python -m auto_apply --check-config
```

If a policy is active, you will see:

```
✅ Admin policy loaded: aa_policy.json
   Active constraints: force_headless, allowed_browsers=[firefox], max_apps=50
```

If the file is present but malformed, AA logs a warning and ignores it
(users run unrestricted — fail‑safe). Check the log file
(`~/.auto_apply/logs/app.log`) for details.

---

## 5. Deployment scenarios

### Library or computer lab

- Place `aa_policy.json` in the AA installation directory.
- Set permissions as described above so students can't modify it.
- Use `force_headless: true` so browser windows don't pop up.
- Use `allowed_browsers` to restrict which browsers are used.
- Set `disable_research_collection: true` to prevent any data collection.

### Enterprise fleet

- Deploy `aa_policy.json` via Group Policy (Windows), MDM profile (macOS),
  or configuration management tool (Linux).
- Combine with a custom PyInstaller build that bundles the policy file inside
  the executable directory.
- Use `max_applications_per_session` to prevent network abuse.
- Use `force_respect_robots_txt: true` to ensure compliance with website
  terms of service.

### USB portable drives

- Place `aa_policy.json` in the root of the portable directory (next to
  `AutoApply.exe`).
- AA automatically detects and enforces it when running in portable mode.
- The policy travels with the drive — it's enforced on any computer the
  drive is plugged into.

---

## 6. How the policy interacts with user settings

- If a policy field is set to a value, that value **replaces** the user's
  setting entirely. The user's preference is logged and ignored.
- If a policy field is absent or `null`, the user's preference (or the
  runtime default) is used.
- The `config_overrides` field merges with the effective configuration
  dict — it can override any key, but the named fields (like
  `force_headless`) take precedence over `config_overrides` if both
  specify the same thing.

The policy is applied once at session startup. Changing the file mid‑session
has no effect — the user must restart AA.

---

## 7. Example: Locking down a library computer

Here is a complete policy for a public library machine:

```json
{
  "allowed_browsers": ["firefox"],
  "max_applications_per_session": 25,
  "force_headless": true,
  "force_humanization": true,
  "force_respect_robots_txt": true,
  "min_action_delay_seconds": 3.0,
  "disable_research_collection": true,
  "config_overrides": {
    "log_retention_days": 3,
    "enable_company_batching": false
  }
}
```

This policy:

- Only allows Firefox (removes Chrome/Edge).
- Caps applications at 25 per session.
- Forces headless operation (no visible windows).
- Enforces human‑like timing (minimum 3 seconds between actions).
- Requires `robots.txt` compliance.
- Disables research data collection.
- Keeps logs for only 3 days.
- Disables company batching (one application at a time — less network load).

---

## Next steps

- [Configuration Reference](../getting_started/configuration.md) – the full
  list of configurable fields.
- [Enterprise Deployment](../deployment/enterprise_admin_policy.md) – mass
  deployment strategies and tools.
- [FAQ](../faq.md) – answers to common admin policy questions.
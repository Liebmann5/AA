# Enterprise Admin Policy

The **Admin Policy** is the mechanism by which system administrators lock
down AutoApply’s behaviour across an entire fleet — a university computer
lab, a corporate desktop pool, or a library network. Once deployed, users
cannot override the locked settings. The policy file is a single JSON
document, protected by OS file permissions, and read once at session startup.

This guide covers everything you need to deploy an admin policy at scale:
creating the file, protecting it, pushing it to hundreds of machines, and
verifying it works.

---

## How the Policy Works

AA reads configuration from three tiers, in this order (higher overrides
lower):

```
AdminPolicy   (top — locked by the device owner)
    ↓
UserSettings  (the user’s profile JSON)
    ↓
RuntimeDefaults (built‑in fallbacks)
```

- If a policy field is set to a non‑null value, that value **replaces** the
  user’s preference for that field.
- If a policy field is absent or `null`, the user’s preference (or the
  runtime default) is used.
- The policy is loaded **once per session** and is immutable after startup.
- The policy file is not cryptographically signed. It relies on **OS file
  permissions** for protection — the same model used by Chrome and Firefox
  enterprise policies.

---

## 1. Creating the Policy File

AA ships with a template generator. On any machine with AA installed, run:

```bash
python -m auto_apply --create-policy
```

This writes `aa_policy.json` to the current directory with every available
field documented. You can also create the file by hand — it is plain JSON.

### Where to Place the Policy

AA searches for `aa_policy.json` in the **application directory** — the
folder that contains `AutoApply.exe` (portable builds) or the installed
package root (pip installs). If you are unsure, place the file in both
locations:

| Installation type | Primary policy location |
| ----------------- | ----------------------- |
| Portable (USB)    | Next to `AutoApply.exe` |
| pip install       | The `site-packages/auto_apply/` folder |
| From source       | The repository root |

AA also checks the profile’s directory, but the application directory is
authoritative.

---

## 2. Policy Field Reference

All fields are optional. Only include the fields you want to lock.

```json
{
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
- **Type:** `list[str] | null`
- A whitelist of browser names permitted on this device. If set, any browser
  not in this list is silently skipped by the Browser Cascade.
- Example: `["firefox"]` — only Firefox may be used; Chrome, Edge, and
  Safari are blocked regardless of whether they are installed.
- If `null` or absent, all detected browsers are allowed.

### `blocked_tools`
- **Type:** `list[str] | null`
- A blacklist of tool names that must not be used. Currently supported:
  `"undetected_chromedriver"`.
- Blocked tools are removed from the available capabilities list before any
  browser selection occurs.

### `max_applications_per_session`
- **Type:** `int | null`
- A hard cap on the number of job applications AA will submit in one session.
  This protects your network from excessive traffic and prevents users from
  running AA unattended for days.
- If the user has a lower limit in their profile, the lower value is used.
  The admin cap is a ceiling, not a floor.

### `force_headless`
- **Type:** `bool | null`
- If `true`, the browser window is always hidden, regardless of the user’s
  preference. Essential on shared computers where visible browser windows
  would disrupt other users.

### `force_humanization`
- **Type:** `bool | null`
- If `true`, human‑behaviour simulation (random delays, mouse movements,
  typing cadence) is always enabled. Prevents users from running AA at
  aggressive speeds that could trigger bot detection and get your
  institution’s IP address flagged.

### `force_respect_robots_txt`
- **Type:** `bool | null`
- If `true`, AA always obeys `robots.txt` rules, even if the user has
  disabled this in their profile. This protects your organisation from
  violating website terms of service and potential legal liability.

### `min_action_delay_seconds`
- **Type:** `float | null`
- A minimum delay (in seconds) between browser actions. Users can set a
  longer delay in their profile, but never a shorter one. A value of `2.0`
  means AA will wait at least two seconds between clicks, keystrokes, and
  page loads.

### `disable_research_collection`
- **Type:** `bool | null`
- If `true`, the research data collection feature is permanently disabled on
  this device, regardless of any user’s opt‑in preference. This is for
  institutions that have strict data‑collection policies.

### `config_overrides`
- **Type:** `dict | null`
- A catch‑all for overriding any key in AA’s internal runtime configuration.
  This is an escape hatch for constraints not covered by the explicit fields
  above. Use sparingly — most needs are covered by the named fields.
- Example: `"log_retention_days": 3` — delete session logs older than three
  days.

---

## 3. Protecting the Policy File

AA trusts the policy file only if the operating system prevents unauthorised
users from modifying it. After creating `aa_policy.json`, you must set its
permissions to **read‑only for standard users**.

=== "Windows"

    1.  Right‑click `aa_policy.json` → **Properties**.
    2.  Go to the **Security** tab → **Advanced**.
    3.  Disable inheritance and convert inherited permissions to explicit.
    4.  Remove all entries for standard users, or set them to **Read &
        execute** and **Read** only.
    5.  Ensure the Administrators group retains **Full control**.

    From an elevated command prompt, you can also use `icacls`:
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

After setting permissions, verify with `ls -l` (macOS/Linux) or the
Windows Security tab that standard users cannot write to the file.

---

## 4. Mass Deployment

### 4.1 Windows — Group Policy

Group Policy is the recommended method for domain‑joined Windows machines.

1.  Create a **Group Policy Object** (GPO) for AutoApply.
2.  Navigate to **Computer Configuration** → **Preferences** → **Files**.
3.  Create a new **File** preference item:
    - **Action:** Update
    - **Source file:** `\\server\share\aa_policy.json`
    - **Destination file:** `C:\Program Files\AutoApply\aa_policy.json`
      (or the path where AA is installed)
4.  Under the **Common** tab, check **“Run in logged‑on user’s security
    context”** and **“Item‑level targeting”** if you need to filter by OU
    or group.
5.  After the file is deployed, use a **Startup Script** or **Scheduled
    Task** to set the file’s ACL with `icacls` (see above).

Users will receive the policy at the next Group Policy refresh.

### 4.2 Windows — Intune / MDM

For cloud‑managed Windows devices, deploy the policy as a **custom
configuration profile**:

1.  In Microsoft Intune, go to **Devices** → **Configuration profiles** →
    **Create profile**.
2.  Choose **Windows 10 and later** → **Templates** → **Custom**.
3.  Add an **OMA‑URI setting** that deploys a file to the AA installation
    directory. Use the `./Device/Vendor/MSFT/EnterpriseDesktopAppManagement`
    CSP or a PowerShell script deployment.
4.  The script should copy `aa_policy.json` from a secure blob storage to
    the AA directory and set its ACL.

### 4.3 macOS — MDM (Jamf, Kandji, etc.)

Deploy the policy file via your MDM’s file deployment mechanism:

1.  Upload `aa_policy.json` to your MDM as a managed file.
2.  Target the deployment to the directory where AA is installed (e.g.
    `/Applications/AutoApply/aa_policy.json`).
3.  Include a post‑install script that runs `chmod 644` and
    `chown root:admin` on the file.

### 4.4 Linux — Configuration Management

Use Ansible, Puppet, Chef, or Salt to deploy the policy:

**Ansible example:**
```yaml
- name: Deploy AA admin policy
  copy:
    src: files/aa_policy.json
    dest: /opt/auto_apply/aa_policy.json
    owner: root
    group: root
    mode: '0644'
```

For immutable infrastructure, bake the policy file into your golden image
(see [Imaging](#45-imaging)).

### 4.5 Imaging

If you deploy AA as part of a golden image (e.g. for a computer lab that
is re‑imaged every semester), place `aa_policy.json` in the AA directory
before capturing the image. Ensure the file’s permissions are set correctly
in the image — they will be preserved when the image is deployed.

After imaging, verify that the policy is active by running:
```bash
AutoApply.exe --check-config
```

---

## 5. USB Portable Deployments

If users run AA from a USB drive, the policy file **travels with the drive**:

1.  Place `aa_policy.json` in the root of the portable directory, next to
    `AutoApply.exe`.
2.  AA automatically detects and enforces it when running in portable mode.
3.  The policy is enforced on **any computer** the drive is plugged into —
    the user cannot bypass it by switching machines.

For IT‑provided USB drives, set the policy file’s attributes to
**read‑only** on the drive. On FAT32/exFAT, this is a flag that is easily
removed, but it serves as a basic deterrent. For stricter enforcement,
consider formatting the drive with NTFS and setting ACLs as described above.

---

## 6. Verifying the Policy

Run AA with the `--check-config` flag to confirm the policy is loaded and
active:

```bash
python -m auto_apply --check-config
```

Output:

```
✅ Admin policy loaded: aa_policy.json
   Active constraints: force_headless, allowed_browsers=[firefox], max_apps=50
```

If the policy file is present but malformed, AA logs a warning and ignores
it (users run unrestricted — fail‑safe). Check the log file at
`data/logs/app.log` for details.

---

## 7. Handling Policy Updates

To update a policy:

1.  Replace the `aa_policy.json` file with the new version.
2.  Ensure the new file retains the correct read‑only permissions.
3.  Restart AA on the affected machines.

Policy changes take effect at the next session startup. Users who are
mid‑session are not affected until they restart AA.

---

## 8. Troubleshooting

| Problem | Solution |
| ------- | -------- |
| Policy file exists but AA says “No admin policy loaded” | Check that the file is valid JSON. Run `python -m json.tool aa_policy.json` to validate. Also check file permissions — if AA cannot read the file, it silently ignores it. |
| Users can still override a locked setting | Verify that the policy field is not `null` in the JSON. A `null` value means “no constraint.” Also verify that the policy is in the correct directory — AA only checks the application directory and profile directory. |
| `--check-config` shows “Admin policy: none” despite the file being present | AA may be running from a different directory than where the policy is located. Use `--policy-path` to explicitly specify the policy file location, or move the file to AA's application directory. |
| Malformed policy causes AA to crash | This should not happen. AA wraps policy loading in a `try/except` and falls back to unrestricted mode on any error. If a crash occurs, please report it as a bug. |
| Policy is not enforced on USB drives when plugged into a different machine | The policy file must be in the same directory as `AutoApply.exe` on the USB drive. Double‑check the drive layout. Also ensure the file is not hidden or blocked by antivirus software on the host machine. |

---

## Next Steps

- [PyInstaller Portable Build](pyinstaller_portable.md) — build a custom
  portable package with the policy pre‑baked.
- [Admin Policy (User Guide)](../user_guide/admin_policy.md) — simpler
  guide for single‑machine setups.
- [Configuration Reference](../getting_started/configuration.md) — all
  environment variables and profile fields.
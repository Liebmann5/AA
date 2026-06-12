# Docker

Run AutoApply in a container — ideal for headless servers, VPS instances,
scheduled cron jobs, or any environment where you don't want to install
browser dependencies directly on the host.

The Docker image bundles AA with Chromium, the Selenium driver, and all
required system libraries. It detects the container environment automatically
and applies the necessary Chrome flags — no manual configuration required.

---

## Quick Start

```bash
# Build the image
docker build -t auto-apply:latest .

# Run once (headless, no GUI)
docker run --rm \
  -v "$HOME/.auto_apply:/data" \
  -e AA_PROFILE_PATH=/data/profile.json \
  auto-apply:latest
```

On the first run, AA will create a default profile template in the mounted
volume. Edit `profile.json` to add your details, then run the container again
to start a job hunt.

---

## Dockerfile

The image is based on `python:3.11-slim` and includes Chromium and its
dependencies. Playwright is not bundled by default — if you want Playwright
support, use the `[browser]` extra in a custom image.

```dockerfile
FROM python:3.11-slim

# Install Chromium and its dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libgdk-pixbuf2.0-0 \
    libnspr4 \
    libnss3 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/auto_apply /app
RUN pip install --no-cache-dir -e .

# Data directory for profile, DB, audit logs, screenshots
VOLUME ["/data"]

ENTRYPOINT ["python", "-m", "auto_apply", "--cli"]
```

> **Note:** If you use a Debian‑based base image that ships `chromium` instead
> of `google-chrome`, set `browser_name = "chromium"` in your profile JSON.
> AA's `SeleniumProvider` treats `chromium` identically to `chrome`.

---

## docker-compose.yml

For persistent setups, use Docker Compose to manage the data volume and
environment variables:

```yaml
services:
  auto-apply:
    image: auto-apply:latest
    build: .
    volumes:
      - aa_data:/data
    environment:
      AA_PROFILE_PATH: /data/profile.json
      AA_DB_PATH: /data/applications.db
      AA_LOG_LEVEL: INFO
    restart: "no"

volumes:
  aa_data:
```

---

## Volume Mounts

AA stores all persistent data inside `/data` in the container. Map this to
a host directory or a named volume to preserve your profile and application
history across container restarts.

| Host path (example) | Container path | Purpose |
| ------------------- | -------------- | ------- |
| `~/.auto_apply/profile.json` | `/data/profile.json` | User profile (required) |
| `~/.auto_apply/applications.db` | `/data/applications.db` | Application history (SQLite) |
| `~/.auto_apply/logs/` | `/data/logs/` | Session audit logs |
| `~/.auto_apply/screenshots/` | `/data/screenshots/` | Failure screenshots |
| `~/.auto_apply/checkpoints/` | `/data/checkpoints/` | Crash‑recovery snapshots |
| `~/.auto_apply/research_data/` | `/data/research_data/` | Anonymised research signals (opt‑in) |

!!! tip
    If you want AA to use a different profile, set `AA_PROFILE_PATH` to the
    absolute path inside the container — for example,
    `/data/profiles/john-dev.json`.

---

## Environment Variables

All environment variables are optional unless noted.

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `AA_PROFILE_PATH` | `/data/profile.json` | Absolute path to profile JSON (required on first run) |
| `AA_DB_PATH` | `/data/applications.db` | SQLite database path |
| `AA_LOG_LEVEL` | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `CONTAINER` | *(auto‑detected)* | Set to `1` to force container mode if auto‑detection fails (Podman, Kubernetes) |

---

## Headless Mode

The Docker image always runs headless — there is no display server. AA
detects the container environment and applies the necessary Chrome flags
automatically:

- `--no-sandbox`
- `--disable-setuid-sandbox`
- `--disable-dev-shm-usage`
- `--no-zygote`
- `--headless=new`

You do not need to set `run_headless` in your profile — it is forced on in
containers regardless of user preference. If your admin policy also sets
`force_headless: true`, the two constraints are consistent and no conflict
occurs.

---

## How Container Detection Works

`SeleniumProvider._is_in_container()` (and `PlaywrightProvider._is_in_container()`) check three signals in order:

1.  **`/.dockerenv`** — Docker injects this empty file into every container.
    This is the most reliable single‑file signal.
2.  **`/proc/1/cgroup`** — under cgroup v1, the hierarchy path for PID 1
    contains `"docker"`, `"containerd"`, `"kubepods"`, or `"lxc"` when the
    process is containerised. This covers Kubernetes pods and LXC containers
    where `/.dockerenv` is absent.
3.  **`CONTAINER` env var** — explicit opt‑in for Podman and any environment
    where the file‑system signals are unavailable. Set to `1`, `true`, or
    `docker`.

No configuration is required for standard Docker; the detection is fully
automatic.

---

## Viewport Locking (Headless)

When running headless, AA forces a `1920 × 1080` viewport. Headless Chrome
reports a `0 × 0` viewport by default — a strong bot signal on most ATS
platforms. Locking it to a standard desktop resolution makes the session
indistinguishable from a normal headed run.

For Selenium, the flag `--window-size=1920,1080` is added to Chrome options.
For Playwright, the browser context is created with
`viewport={"width": 1920, "height": 1080}`.

---

## Troubleshooting

### Chrome crashes immediately on startup

**Symptom:** `DevToolsActivePort file doesn't exist` or `session not created`.

**Cause:** The sandbox is enabled but the container's seccomp/namespace
configuration does not allow it.

**Fix:** Ensure `CONTAINER=1` is set (or that `/.dockerenv` exists) so the
`--no-sandbox` and `--disable-setuid-sandbox` flags are applied. If you are
using Podman, you must set `CONTAINER=1` explicitly.

### "Out of shared memory" / `SIGBUS`

**Symptom:** Chrome renderer crashes with `SIGBUS` shortly after launch.

**Cause:** `/dev/shm` in the container is too small (default 64 MB).

**Fix:** Either pass `--shm-size=256m` to `docker run`, or rely on the
`--disable-dev-shm-usage` flag (already set) which writes shared memory to
`/tmp` instead.

### Blank screenshots / invisible elements

**Symptom:** Screenshots are blank or elements are not rendered.

**Cause:** GPU acceleration is unavailable in headless containers.

**Fix:** `--disable-gpu` is always added to Playwright launch args. If the
issue persists, set `run_headless = true` in the profile to activate the full
headless flag set.

### Auto‑detection not triggering (Podman / Kubernetes)

**Symptom:** Container Chrome flags are not applied even though you are
inside a container.

**Cause:** Podman does not inject `/.dockerenv`, and cgroup v2 hierarchies
do not contain the `"docker"` token.

**Fix:** Set the `CONTAINER` environment variable explicitly:

```bash
docker run -e CONTAINER=1 ...
# or in docker-compose.yml
environment:
  CONTAINER: "1"
```

---

## Next Steps

- [PyInstaller Portable Build](pyinstaller_portable.md) — build a standalone
  `.exe` for USB deployment.
- [Enterprise Admin Policy](enterprise_admin_policy.md) — lock down AA in
  institutional environments.
- [Configuration Reference](../getting_started/configuration.md) — all
  environment variables and profile fields.
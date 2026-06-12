# PyInstaller Portable Build

The portable build is the ultimate expression of AA’s “worst‑case first”
philosophy. It produces a single folder that can be copied to a USB flash
drive and run on any Windows computer **without installing Python,
dependencies, or a browser**. The user plugs in the drive, double‑clicks
`AutoApply.exe`, and AA runs entirely from the USB stick — leaving nothing
on the host machine.

This guide walks you through building that portable package from source.

---

## What the Portable Build Includes

When you finish this guide, your USB drive will contain:

- `AutoApply.exe` — the application launcher.
- Python 3.12 and all core AA dependencies (no system Python needed).
- A portable Chromium browser (no installation, no admin rights).
- A portable Firefox browser (optional, smaller alternative).
- All AA resources (ATS descriptors, locale files, profile templates).
- Cache directories redirected to the drive (AI models, browser profiles).
- An optional `aa_policy.json` for admin enforcement.

The total size is approximately **200–300 MB** depending on which browsers
you bundle. Nothing is written to the host computer’s registry, user
profile, or temporary folders.

---

## Prerequisites

You need these installed **on your build machine only** (not on the target
USB machine):

- **Python 3.10+** (the same version AA targets)
- **AA source code** (cloned from the repository)
- **PyInstaller** (`pip install pyinstaller`)
- **Portable browser binaries** (see [Step 2](#2-bundle-portable-browsers))

---

## 1. Create the PyInstaller Spec File

PyInstaller reads a `.spec` file that tells it exactly what to include.
Save the following as `AutoApply.spec` in the repository root.

```python
# AutoApply.spec
# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

# Paths relative to the repo root (AA/)
_here = Path(__file__).parent.absolute()
_package_dir = _here / "packages" / "auto_apply" / "src" / "auto_apply"
_resources_dir = _package_dir / "resources"
_bin_dir = _here / "portable_browsers"   # see Step 2

a = Analysis(
    [str(_package_dir / "__main__.py")],
    pathex=[str(_package_dir.parent)],
    binaries=[],
    datas=[
        # ATS platform descriptors
        (str(_resources_dir / "ats"), "auto_apply/resources/ats"),
        # Locale files
        (str(_resources_dir / "locales"), "auto_apply/resources/locales"),
        # Config files
        (str(_resources_dir / "config"), "auto_apply/resources/config"),
        # Profile templates
        (str(_resources_dir / "templates"), "auto_apply/resources/templates"),
        # Evasion detection keywords
        (
            str(_package_dir / "adapters" / "secondary" / "evasion" / "detection_config.json"),
            "auto_apply/adapters/secondary/evasion",
        ),
        # Rule‑based reasoning definitions
        (
            str(_package_dir / "adapters" / "secondary" / "reasoning" / "rules"),
            "auto_apply/adapters/secondary/reasoning/rules",
        ),
        # Portable browser binaries (if you are bundling them)
        (str(_bin_dir), "bin"),
    ],
    hiddenimports=[
        "pydantic",
        "pydantic_settings",
        "selenium",
        "bs4",
        "yaml",
        "clingo",
        "cryptography",
        "psutil",
        "requests",
        "urllib3",
        "certifi",
        "pydantic_core",
        "pydantic.deprecated",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",          # remove if you only need CLI
        "matplotlib",
        "numpy",
        "pandas",
        "PIL",
        "cv2",
    ],
)

# Block the most common data‑leakage imports
a.binaries = [
    (name, path, typ)
    for name, path, typ in a.binaries
    if not name.startswith("api-ms-win-")   # system DLLs — loaded from host
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="AutoApply",
    icon=None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,           # show console for CLI output
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

!!! note
    The `console=True` setting keeps a terminal window open so you can see
    AA’s live CLI dashboard. If you are building a GUI‑only version, set
    `console=False` — but then you lose the ability to see log output unless
    you redirect it to a file.

---

## 2. Bundle Portable Browsers

AA needs a browser to fill out forms. On a USB drive, we cannot rely on the
host machine having Chrome or Firefox installed — so we bundle portable
versions directly on the drive.

### Option A: Chromium Portable (Recommended)

1. Download the latest **ungoogled‑chromium** portable ZIP from
   [chromium.woolyss.com](https://chromium.woolyss.com/) or the official
   [Chromium Portable](https://github.com/Hibbiki/chromium-win32/releases)
   project.
2. Extract the folder to a directory on your build machine, e.g.:
   `C:\portable_browsers\chromium\`
3. Ensure the folder contains `chrome.exe` (the main executable).

AA will automatically detect the portable browser if it is in the expected
location on the USB drive (see [USB Layout](#3-usb-layout)).

### Option B: Firefox Portable

1. Download **Firefox Portable** from
   [portableapps.com](https://portableapps.com/apps/internet/firefox_portable).
2. Extract to `C:\portable_browsers\firefox\`.

You can bundle both browsers — AA’s Browser Cascade will prefer Chromium
and fall back to Firefox if needed.

### Telling AA Where the Browsers Live

In the portable launch script (see [Step 4](#4-the-portable-launch-script)),
we set the `AA_BROWSER_BINARY_PATH` environment variable to point to the
portable browser on the USB drive. The `SeleniumProvider` and
`PlaywrightProvider` read this variable and use it as the executable path.

---

## 3. USB Layout

After building, arrange the portable folder on the USB drive like this:

```
E:\                              (your USB drive root)
├── AutoApply.exe                (the compiled application)
├── data\                        (AA's runtime data — grows over time)
│   ├── profiles\                (user profiles)
│   ├── logs\                    (session logs)
│   ├── checkpoints\             (crash recovery)
│   ├── screenshots\             (failure captures)
│   ├── research_data\           (opt‑in research signals)
│   ├── applications.db          (SQLite job history)
│   ├── cache\                   (all third‑party caches)
│   │   ├── huggingface\
│   │   ├── gpt4all\
│   │   ├── spacy\
│   │   └── torch\
│   └── tmp\                     (temp files — cleared on exit)
├── bin\                         (portable browser binaries)
│   ├── chromium\
│   │   └── chrome.exe
│   └── firefox\
│       └── firefox.exe
├── aa_policy.json               (optional admin policy)
└── launch_portable.bat          (the launch script)
```

`AutoApply.exe` and `data/` are created by the build. `bin/` and
`launch_portable.bat` you create manually (see below).

---

## 4. The Portable Launch Script

The launch script sets all the environment variables that keep AA’s data
confined to the USB drive. Save this as `launch_portable.bat` on the USB
drive, next to `AutoApply.exe`.

```batch
@echo off
setlocal

REM Get the drive letter and path where this script lives
set "PORTABLE_ROOT=%~dp0"

REM ---- Redirect all data to the USB drive ----
set "AA_PROFILE_PATH=%PORTABLE_ROOT%data\profiles\default.json"
set "AA_DB_PATH=%PORTABLE_ROOT%data\applications.db"
set "AA_LOG_DIR=%PORTABLE_ROOT%data\logs"

REM ---- Cache directories (prevent writes to %APPDATA%, %LOCALAPPDATA%, etc.) ----
set "HF_HOME=%PORTABLE_ROOT%data\cache\huggingface"
set "GPT4ALL_CACHE=%PORTABLE_ROOT%data\cache\gpt4all"
set "SPACY_DATA=%PORTABLE_ROOT%data\cache\spacy"
set "TORCH_HOME=%PORTABLE_ROOT%data\cache\torch"
set "USER_DATA_DIR=%PORTABLE_ROOT%data\cache\chromium_profile"

REM ---- Playwright browsers (if bundled) ----
set "PLAYWRIGHT_BROWSERS_PATH=%PORTABLE_ROOT%bin\pw-browsers"

REM ---- Temporary files ----
set "TEMP=%PORTABLE_ROOT%data\tmp"
set "TMP=%PORTABLE_ROOT%data\tmp"

REM ---- Portable browser binary ----
set "AA_BROWSER_BINARY_PATH=%PORTABLE_ROOT%bin\chromium\chrome.exe"

REM ---- Create directories if they don't exist ----
mkdir "%PORTABLE_ROOT%data\profiles" 2>nul
mkdir "%PORTABLE_ROOT%data\logs" 2>nul
mkdir "%PORTABLE_ROOT%data\checkpoints" 2>nul
mkdir "%PORTABLE_ROOT%data\screenshots" 2>nul
mkdir "%PORTABLE_ROOT%data\cache" 2>nul
mkdir "%PORTABLE_ROOT%data\tmp" 2>nul

REM ---- Launch ----
echo Starting AutoApply (portable mode)...
echo Data directory: %PORTABLE_ROOT%data
echo.
start "" /wait "%PORTABLE_ROOT%AutoApply.exe" %*

REM ---- Cleanup temp files on exit ----
rmdir /s /q "%PORTABLE_ROOT%data\tmp" 2>nul
mkdir "%PORTABLE_ROOT%data\tmp" 2>nul

echo.
echo AutoApply closed. All data saved to the USB drive.
pause
```

!!! important
    The `start "" /wait` command waits for `AutoApply.exe` to exit before
    running the cleanup. This ensures that any temporary files used during
    the session are removed, leaving the USB drive in a clean state.

---

## 5. Cache Redirection in `main.py`

The environment variables in the launch script are the primary mechanism
for redirecting caches. For an extra layer of safety, AA also sets these
variables **programmatically** in `main.py` before any third‑party library
is imported. This guards against a user launching `AutoApply.exe` directly
without the batch script.

Add this function to `main.py`, called at the very top before any other
imports:

```python
def _redirect_caches_to_app_root() -> None:
    """Force all third‑party libraries to store data on the portable drive."""
    from auto_apply.domain.config import APP_ROOT, IS_FROZEN

    if not IS_FROZEN:
        return  # Dev mode — use normal cache locations

    cache_dir = APP_ROOT / "data" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("HF_HOME", str(cache_dir / "huggingface"))
    os.environ.setdefault("GPT4ALL_CACHE", str(cache_dir / "gpt4all"))
    os.environ.setdefault("SPACY_DATA", str(cache_dir / "spacy"))
    os.environ.setdefault("TORCH_HOME", str(cache_dir / "torch"))
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                          str(APP_ROOT / "data" / "bin" / "pw-browsers"))
    os.environ.setdefault("USER_DATA_DIR",
                          str(cache_dir / "chromium_profile"))
    os.environ.setdefault("TEMP", str(APP_ROOT / "data" / "tmp"))
    os.environ.setdefault("TMP", str(APP_ROOT / "data" / "tmp"))
```

The `os.environ.setdefault` calls ensure that the launch script’s
environment variables take precedence — the programmatic redirects are a
fallback, not an override.

---

## 6. Building the .exe

With the spec file and portable browsers prepared, build the executable:

```bash
pyinstaller AutoApply.spec
```

This creates a `dist/AutoApply/` folder containing `AutoApply.exe` and all
supporting files. **Copy the entire `dist/AutoApply/` folder** — not just
the `.exe` — to the root of your USB drive.

The first time you run `AutoApply.exe`, AA will create the `data/` directory
structure automatically. On subsequent runs, it will use the existing
profiles and databases.

---

## 7. Running from USB

1. Plug the USB drive into any Windows computer.
2. Double‑click `launch_portable.bat` (or `AutoApply.exe` directly).
3. AA starts. If this is the first run, the Setup Wizard appears — create
   your profile.
4. On subsequent runs, AA loads your profile and you can start a session
   immediately.
5. When you close AA, all data is saved to the USB drive. Unplug the drive —
   nothing remains on the host computer.

---

## 8. Verifying Zero Traces

AA includes a built‑in verification mode that scans the host machine for any
files accidentally written outside the USB drive. Run it like this:

```bash
AutoApply.exe --verify-portable
```

On exit, AA prints a report:

```
✅ No files written to %TEMP%
✅ No files written to %LOCALAPPDATA%
✅ No files written to %APPDATA%
✅ No registry keys created
✅ Portable integrity verified
```

If any file is found outside the drive, AA logs its path and a warning. This
mode is designed for IT administrators and security‑conscious users who need
to prove that AA leaves the host machine completely untouched.

---

## 9. Customising the Build

### Removing optional extras

If you want a smaller portable package (e.g. for a USB drive with limited
space), you can strip out optional dependencies by editing the `excludes`
list in the `.spec` file and removing the corresponding `hiddenimports`. For
example, to remove the NLP tier:

```python
excludes=[
    "spacy",
    "en_core_web_sm",
    "en_core_web_md",
    "en_core_web_lg",
    ...
]
```

The core AA (Selenium + BS4 + form filling) will still work perfectly.

### Bundling an admin policy

Place `aa_policy.json` in the USB root, next to `AutoApply.exe`. AA
automatically detects and enforces it. No code changes needed. This is how
IT admins can distribute pre‑configured, locked‑down portable builds.

### Adding a custom profile

If you want the portable build to come with a pre‑filled profile (e.g. for
a kiosk or a specific user), place the profile JSON in `data/profiles/` on
the USB drive and set `AA_PROFILE_PATH` to point to it in the launch script.

---

## 10. Troubleshooting

| Problem | Solution |
| ------- | -------- |
| `AutoApply.exe` won't start (missing DLL) | The target machine may lack the Visual C++ Redistributable. Install [vc_redist.x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe) on the target machine, or bundle the DLLs with the build. |
| Portable browser not found | Check that `AA_BROWSER_BINARY_PATH` points to the correct `chrome.exe` or `firefox.exe`. The path must be absolute on the USB drive (the launch script handles this automatically). |
| AA still writes to `%APPDATA%` | Ensure `_redirect_caches_to_app_root()` is called before any other imports in `main.py`. Some libraries cache aggressively and must be intercepted before they touch the filesystem. |
| Build is too large (>500 MB) | Remove optional browsers (Firefox, Playwright), exclude `spacy`, and use `upx=True` (already enabled) to compress the executable. |
| `--verify-portable` reports a file leak | Check that the environment variables in the launch script are all set correctly. If a specific library is leaking, add its cache path to the `setdefault` block in `_redirect_caches_to_app_root()`. |

---

## Next Steps

- [Enterprise Admin Policy](enterprise_admin_policy.md) — mass deployment
  strategies and policy enforcement.
- [Docker](docker.md) — containerised deployment alternative.
- [Configuration Reference](../getting_started/configuration.md) — all
  environment variables and profile fields.
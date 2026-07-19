# AutoApply — Installation Guide

## System Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| Python | 3.10 | 3.11 or 3.12 |
| RAM | 512 MB | 2 GB |
| Disk space | 200 MB | 1 GB |
| OS | Windows 10, Ubuntu 20.04, macOS 12 | Same |
| Browser | Chrome 115+ OR Firefox 100+ | Chrome latest |

AA is designed to work on the weakest machine first — a library computer
with 2 GB RAM, no admin rights, and no GPU. Every richer feature (SpaCy,
GPT4All, Playwright) is opt-in and degrades gracefully when absent.

---

## Method 1: Install from PyPI (Recommended)

```bash
# Core install (~30 MB, works with your system browser)
pip install auto_apply

# Verify
python -m auto_apply --version
```

To add smarter NLP (SpaCy):
```bash
pip install "auto_apply[nlp]"
python -m spacy download en_core_web_lg   # 685 MB, best accuracy
# OR for smaller size:
python -m spacy download en_core_web_sm   # 12 MB, still better than nothing
```

To add local AI for custom questions (GPT4All):
```bash
pip install "auto_apply[ai]"
# The default model (~4.7 GB) downloads automatically on first use
```

Everything at once:
```bash
pip install "auto_apply[all]"
python -m spacy download en_core_web_lg
```

---

## Method 2: Install from Source (Developers and Power Users)

```bash
# 1. Clone the repository
git clone https://github.com/Liebmann5/AA
cd AA

# 2. Install uv (fast Python package manager)
pip install uv

# 3. Install AutoApply and all development dependencies
uv sync

# 4. Verify installation
cd packages/auto_apply
python -m auto_apply --version

# 5. First run (will prompt to create a profile)
python -m auto_apply --cli
```

With uv you can also add optional extras:
```bash
uv sync --extra nlp       # + SpaCy
uv sync --extra ai        # + GPT4All
uv sync --extra browser   # + Playwright
uv sync --extra all       # everything
```

---

## Method 3: No Admin Rights (Library / Public Computer)

If you cannot install Python globally, use a user-level installation:

```bash
# Install Python to your user directory (no admin required)
# Windows: Download Python from python.org and check "Add to PATH"
# Linux/macOS: Python is usually pre-installed

# Install uv without admin rights
pip install --user uv

# Add user binary path to your PATH (Linux/macOS)
export PATH="$HOME/.local/bin:$PATH"

# Install AutoApply to user directory
cd AA
uv sync

# Run
cd packages/auto_apply
python -m auto_apply --cli
```

---

## Method 4: USB Drive (Zero Traces on Host)

If you cannot install anything on the computer you are using, download the
pre-built portable package:

1. Download `AutoApply-portable.zip` from the
   [latest release](https://github.com/Liebmann5/AA/releases).
2. Extract it to the root of a USB flash drive.
3. **Windows:** Double-click `launch_portable.bat`
4. **Linux/macOS:** Open a terminal and run `bash launch_portable.sh`

**What's inside:**
- Python interpreter and all core dependencies
- Portable Chromium and Firefox binaries (no installation needed)
- All profiles, databases, logs, and caches stay on the USB drive
- Zero files written to the host computer

See the full guide: `docs/deployment/pyinstaller_portable.md`

---

## Verify Your Installation

Run this to confirm everything is working:

```bash
python -m auto_apply --check-config
```

Expected output:
```
AutoApply v0.2.0-beta

 Platform          : linux (6.5.0)
 Python version    : 3.11.5
 CPU cores         : 4
 RAM (MB)          : 8192
 Free disk (MB)    : 51200
 Low-resource mode : False
 Browsers detected : ['chrome', 'firefox']
 Tools available   : ['playwright', 'psutil']
 Admin policy      : none
```

---

## Optional Components

These are not required for basic operation:

| Component | What it adds | Install command |
|---|---|---|
| SpaCy | Better job vetting, semantic field matching | `pip install "auto_apply[nlp]"` |
| GPT4All | AI-generated custom question answers | `pip install "auto_apply[ai]"` |
| pyarrow | Parquet export for research data | `pip install "auto_apply[research]"` |
| Playwright | Alternative browser automation | `pip install "auto_apply[browser]"` |

---

## Playwright Browsers (Optional)

If you installed the `[browser]` extra, download browser binaries once:

```bash
python -m playwright install firefox    # ~80 MB, smallest option
# OR for all browsers:
python -m playwright install            # ~300 MB
```

AA's Browser Cascade prefers Playwright's bundled browsers for better stealth
but falls back to Selenium with your system browser automatically if Playwright
is unavailable.

---

## Troubleshooting

### "Chrome not found" or "ChromeDriver version mismatch"

```bash
# Check Chrome version:
google-chrome --version   # Linux
# or: chrome.exe --version  (Windows)

# Download matching ChromeDriver from:
# https://googlechromelabs.github.io/chrome-for-testing/
# Place chromedriver in your PATH or set AA_CHROMEDRIVER_PATH

# Alternatively, AA will try Firefox next automatically.
```

### "No profile found"

AutoApply will guide you through creating a profile on first launch.
Or create `~/.auto_apply/profiles/myprofile.json` manually.
See `docs/user_guide/profile_guide.md` for the full format reference.

### "Cannot reach internet" warning

Check your network connection. On library computers, you may need to open a
browser first to agree to the captive portal / acceptable use policy.

### "CAPTCHA detected"

Normal — many job boards have bot protection. AutoApply will pause and ask
you to solve the CAPTCHA, then continue automatically.

### AA is slow or freezes

On low-memory machines, disable AI: do not install the `[ai]` extra, or set
`ai_enabled: false` in your profile. AA will use template answers instead.

### "No supported browser is installed"

AA could not find Chrome, Firefox, Edge, or Safari. Install any of these
browsers, or use the USB portable package which bundles its own browser.

---

## Next Steps

- [Quick Start](docs/getting_started/quick_start.md) — your first job hunt in 5 minutes
- [Configuration](docs/getting_started/configuration.md) — full profile and settings guide
- [Profile Format Reference](docs/user_guide/profiles_and_privacy.md) — every profile field explained
- [FAQ](docs/faq.md) — answers to common questions
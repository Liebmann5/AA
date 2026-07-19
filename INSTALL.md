# AutoApply — Installation Guide

## System Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| Python | 3.10 | 3.11+ |
| RAM | 512 MB | 2 GB |
| Disk space | 200 MB | 1 GB |
| OS | Windows 10, Ubuntu 20.04, macOS 12 | Same |
| Browser | Chrome 115+ OR Firefox 100+ | Chrome latest |

---

## Method 1: Install from Source (Developers and Power Users)

```bash
# 1. Clone the repository
git clone https://github.com/Liebmann5/AA
cd AA

# 2. Install uv (fast Python package manager)
pip install uv

# 3. Install AutoApply and all dependencies
uv sync

# 4. Verify installation
cd packages/auto_apply
python -m auto_apply --check-config

# 5. First run (will prompt to create a profile)
python -m auto_apply --cli
```

---

## Method 2: pip Install (End Users)

```bash
# Core install (~30 MB, works with your system browser)
pip install auto_apply

# Optional upgrades:
pip install "auto_apply[nlp]"       # SpaCy for smarter vetting
pip install "auto_apply[browser]"    # Playwright for enhanced stealth
pip install "auto_apply[ai]"         # GPT4All local LLM

# First run
python -m auto_apply --cli
```

---

## Method 3: No Admin Rights (Library / Public Computer)

If you cannot install Python globally, use a user-level installation:

```bash
# Install Python to your user directory (no admin required)
# Windows: Download Python from python.org, check "Add to PATH"
# Linux/macOS: Python is usually pre-installed

# Install uv without admin rights
pip install --user uv

# Add user binary path to your PATH (Linux/macOS)
export PATH="$HOME/.local/bin:$PATH"

# Install AutoApply to user directory
uv sync

# Run
python -m auto_apply --cli
```

---

## Method 4: USB Drive (Zero Traces on Host)

See the full guide in `docs/deployment/pyinstaller_portable.md`.

**Quick setup:**
1. Download the latest portable release from the Releases page
2. Extract to your USB drive
3. **Windows:** Double-click `launch_portable.bat`
4. **Linux/macOS:** Run `bash launch_portable.sh`

---

## Verify Your Installation

Run this to confirm everything is working:

```bash
python -m auto_apply --check-config
```

Expected output:
```
AutoApply — Environment Configuration Check

 Platform          : linux (6.5.0)
 Python version    : 3.11.5
 CPU cores         : 4
 RAM (MB)          : 8192
 Free disk (MB)    : 51200
 Low-resource mode : False
 Browsers detected : ['chrome', 'firefox']
 Tools available   : ['playwright', 'spacy']
 Admin policy      : none
```

---

## Research-Grade Verification

If you plan to use AA for academic research, verify that deterministic
execution works correctly:

```bash
# Run a short deterministic session (does not require a browser)
python -m auto_apply --seed 42 --check-config

# Run the property-based test suite (requires hypothesis)
uv run pytest tests/property_based/ -v --hypothesis-seed=0

# Run the mock ATS benchmark to verify form-filling correctness
uv run pytest tests/benchmarks/ats_forms/ -v

# Run the architectural integrity tests
uv run pytest tests/test_architecture.py -v
```

All four should pass before collecting research data.  See
`packages/auto_apply/docs/REPRODUCIBILITY.md` for the complete
reproducibility guide, including deterministic execution requirements,
research signal schemas, and cryptographic provenance verification.

---

## Optional Components

These are not required for basic operation:

| Component | What it adds | Install command |
|---|---|---|
| SpaCy | Better job vetting, semantic field matching | `uv sync --extra nlp` then `python -m spacy download en_core_web_lg` |
| GPT4All | AI-generated custom question answers | `uv sync --extra ai` |
| pyarrow | Parquet export for research data | `uv sync --extra research` |
| Playwright | Alternative browser automation | `uv sync --extra browser` then `python -m playwright install firefox` |

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
```

### "No profile found"

AutoApply will guide you through creating a profile on first launch.
Or create `~/.auto_apply/profiles/myprofile.json` manually.
See `docs/user_guide/profiles_and_privacy.md` for the full format reference.

### "Cannot reach internet" warning

Check your network connection. On library computers, you may need to open a
browser first to agree to the captive portal / acceptable use policy.

### "CAPTCHA detected"

Normal — many job boards have bot protection. AutoApply will pause and ask
you to solve the CAPTCHA, then continue automatically.

### AA is slow / freezes on low-memory machines

Disable AI features: remove `gpt4all` from extras or set `ai_enabled: false`
in your profile. AA's core engine works on 512 MB RAM.

### Exporting research data

```bash
python -m auto_apply --export-research              # CSV (default)
python -m auto_apply --export-research --export-format json
python -m auto_apply --export-research --export-format parquet
```

---

## Next Steps

- [Quick Start](packages/auto_apply/docs/getting_started/quick_start.md)
- [Configuration Guide](packages/auto_apply/docs/getting_started/configuration.md)
- [User Guide](packages/auto_apply/docs/user_guide/index.md)
- [Reproducibility Guide](packages/auto_apply/docs/REPRODUCIBILITY.md)
- [Architecture Bible](AA_ARCHITECTURE_BIBLE.md)

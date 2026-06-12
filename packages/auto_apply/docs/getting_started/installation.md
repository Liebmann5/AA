# Installation

AutoApply is designed to work on **any computer with Python 3.10+**, from a
high‑end desktop to a library PC with 2 GB RAM and no admin rights. Choose
the install method that matches your hardware and ambition.

---

## Prerequisites

- **Python 3.10 or newer** – [Download from python.org](https://www.python.org/downloads/).
- **pip** – usually bundled with Python.
- *(Optional)* **uv** – a faster Python package manager, used by developers.
  [Install uv](https://docs.astral.sh/uv/getting-started/installation/).

---

## 1. Core Install (Recommended for most users)

This installs the minimum needed to run AutoApply. It uses **Selenium** to
drive your existing browser (Chrome, Firefox, Edge, or Safari) and falls back
to static HTML parsing when no browser is available.

```bash
pip install auto_apply
```

**What you get:** job discovery, filtering, form‑filling, research module,
profile encryption, GUI and CLI. Download size ≈ 30 MB.

**What you can add later:**
- `pip install "auto_apply[nlp]"` – smarter text matching (SpaCy)
- `pip install "auto_apply[ai]"` – local LLM for open‑ended questions (GPT4All)

---

## 2. NLP Install (Adds SpaCy)

SpaCy improves job‑title matching, skill extraction, and form‑field
classification. It makes AA noticeably smarter at the cost of one extra
model download.

```bash
pip install "auto_apply[nlp]"
python -m spacy download en_core_web_lg   # best quality, ≈ 700 MB
# OR for smaller size:
python -m spacy download en_core_web_sm   # smaller, ≈ 50 MB, still better than nothing
```

If you skip this step, AA falls back to a built‑in text matcher that works
correctly, just with less nuance.

---

## 3. AI Install (Adds GPT4All)

This gives AA the ability to **answer open‑ended questions** on application
forms ("Tell us about a project you're proud of"). It requires substantial
disk space and RAM.

```bash
pip install "auto_apply[ai]"
```

The first time AA needs GPT4All, it will automatically download the default
model (~4.7 GB) to your cache directory. This happens only once. If your
machine doesn't have enough RAM, AA will skip the model and use SpaCy (or
the fallback) instead — it will never crash because GPT4All is missing.

> ⚠️ **Minimum RAM:** GPT4All needs ≈ 6 GB free RAM. AA's resource manager
> will block it automatically on low‑spec machines.

---

## 4. Full Install (Everything at once)

```bash
pip install "auto_apply[full]"
python -m spacy download en_core_web_lg
```

This includes the core, NLP, AI, and experimental offline CAPTCHA solving.

---

## 5. Developer Install (with uv)

If you plan to contribute code, use `uv` for reproducible, fast environments.

```bash
git clone https://github.com/Liebmann5/AA.git
cd AA
uv sync
```

This creates a virtual environment, installs all core and dev dependencies
(pytest, ruff, black), and locks everything with `uv.lock`. From here you
can run AA with:

```bash
uv run python -m auto_apply
```

See the [Developer Guide](../developer_guide/project_setup.md) for details.

---

## 6. USB Portable Install (No Python Required)

For library computers, borrowed machines, or anyone who cannot install
software, download the pre‑built portable package:

1. Download `AutoApply-portable.zip` from the
   [latest release](https://github.com/Liebmann5/AA/releases).
2. Extract it to the root of a USB flash drive.
3. Run `AutoApply.exe` directly from the drive.

**What's inside the portable package:**
- Python interpreter and all dependencies (core + NLP + AI, optional)
- Portable Chromium and Firefox binaries (no installation needed)
- All profiles, databases, logs, and caches stay on the USB drive
- Zero files written to the host computer

> 💡 The portable build respects any `aa_policy.json` file placed next to
> `AutoApply.exe` — useful for IT admins.

---

## 7. Build Your Own Portable Package (PyInstaller)

If you want to create a custom portable build (e.g., with only the core
dependencies, or with a specific browser), use the included PyInstaller spec.

```bash
pip install pyinstaller
pyinstaller --onedir --add-data "src/auto_apply/resources:resources" ^
    --add-data "path/to/portable/chromium:bin/chromium" ^
    --name AutoApply src/auto_apply/main.py
```

Full instructions and a ready‑to‑use `.spec` file are in
**[PyInstaller Portable Build](../deployment/pyinstaller_portable.md)**.

---

## 8. Post‑Install: Playwright Browsers (Optional)

If you installed Playwright (part of the `[browser]` or `[full]` extra),
you need to download the browser binaries once:

```bash
python -m playwright install firefox    # ≈ 80 MB, smallest option
# OR for all browsers:
python -m playwright install
```

The next time you launch AA, the Browser Cascade will detect Playwright and
prefer it over Selenium for better evasion. If the binaries are missing, AA
falls back to Selenium automatically — no crash, no error.

---

## 9. Verification

Run this one‑liner to confirm everything is working:

```bash
python -m auto_apply --cli --max-results 1
```

If you see a session summary without errors, AA is ready.

---

## Troubleshooting

| Problem | Solution |
| ------- | -------- |
| `ModuleNotFoundError: No module named 'pip'` | Your system Python is broken. Run `python -m ensurepip --upgrade` or use the portable `.exe`. |
| `This version of ChromeDriver only supports Chrome version X` | Update Chrome, or pin `selenium` to match your Chrome version. AA's Browser Cascade will try Firefox next automatically. |
| `Playwright: Executable doesn't exist` | Run `python -m playwright install firefox` or skip Playwright — Selenium will work fine. |
| `No module named 'spacy'` | You installed the core version. Run `pip install "auto_apply[nlp]"` then `python -m spacy download en_core_web_sm`. |
| AA is slow / freezes | On low‑memory machines, disable AI: remove `gpt4all` from extras or set `ai_enabled: false` in your profile. |

For more issues, see the [FAQ](../faq.md).

---

## Next Steps

- [Quick Start](quick_start.md) — run your first job hunt in 5 minutes
- [Configuration](configuration.md) — create and customise your profile
- [Profiles & Privacy](../user_guide/profiles_and_privacy.md) — encrypt your data, store it externally
# auto_apply.spec
# PyInstaller build specification for AutoApply portable executable.
#
# Build command (from the AA/ project root):
#   pip install pyinstaller
#   pyinstaller auto_apply.spec
#
# Output:
#   dist/AutoApply/          ← copy this entire folder to your USB drive
#   dist/AutoApply/AutoApply (Linux/macOS) or AutoApply.exe (Windows)
#
# Notes:
# - Use --onedir (this spec) NOT --onefile for USB drives.
#   --onefile extracts to the HOST machine's %TEMP% on each launch,
#   leaving traces. --onedir runs directly from the drive.
#
# - SpaCy, GPT4All, and Playwright are NOT bundled by default (they are
#   large and optional). The launcher script installs or locates them.
#   Add them to datas[] below if you want a fully self-contained build.

import sys
from pathlib import Path

block_cipher = None

# Package root
SRC = Path("packages/auto_apply/src/auto_apply")

# Collect all YAML/JSON resource files inside the package
datas = [
    (str(SRC / "resources"), "auto_apply/resources"),
    (str(SRC / "domain" / "config.py"), "auto_apply/domain"),
]

# Hidden imports that PyInstaller's static analysis misses
hidden_imports = [
    "auto_apply.domain.config",
    "auto_apply.domain.models.work_unit",
    "auto_apply.domain.models.session_plan",
    "auto_apply.domain.models.profile",
    "auto_apply.domain.models.job",
    "auto_apply.domain.models.application_evidence",
    "auto_apply.domain.models.capability_profile",
    "auto_apply.domain.ports.research_port",
    "auto_apply.adapters.secondary.browser.selenium_provider",
    "auto_apply.adapters.secondary.research.signal_aggregator",
    "auto_apply.infrastructure.composition_root",
    "pydantic",
    "pydantic_settings",
    "bs4",
    "selenium",
    "sqlite3",
    "tkinter",
    "tkinter.ttk",
    "charset_normalizer",
    "certifi",
]

# Optional: add spacy if you want it bundled
# (large — ~200MB; most users prefer to install separately)
# try:
#     import spacy
#     hidden_imports.append("spacy")
# except ImportError:
#     pass

a = Analysis(
    scripts=["packages/auto_apply/src/auto_apply/main.py"],
    pathex=["packages/auto_apply/src"],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",   # plotting library, not needed
        "numpy",        # only needed if spacy/torch are bundled
        "PIL",          # image processing, not needed
        "IPython",      # notebook, not needed
        "jupyter",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoApply",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX compression can trigger antivirus false positives
    console=True,        # Show console — users can see logs
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="resources/aa_icon.ico",   # Uncomment if you have an icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AutoApply",
)

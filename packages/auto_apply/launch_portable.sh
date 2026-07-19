#!/usr/bin/env bash
# launch_portable.sh — AutoApply portable launcher for Linux and macOS
#
# USAGE:
#   1. Copy this script to the root of your USB drive
#   2. Run: chmod +x launch_portable.sh
#   3. Run: ./launch_portable.sh
#
# All AutoApply data will be written to ./data/ on this drive.
# Nothing is written to the host machine (no ~/.auto_apply, no /tmp).

set -euo pipefail

# Resolve the directory containing this script (= USB drive root)
PORTABLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "AutoApply Portable Mode"
echo "Data directory: ${PORTABLE_ROOT}/data"
echo ""

# ── Redirect ALL data to the USB drive ──────────────────────────────────────
export AA_DATA_DIR="${PORTABLE_ROOT}/data"

# ── Browser profile on the drive ────────────────────────────────────────────
export USER_DATA_DIR="${PORTABLE_ROOT}/data/cache/chromium_profile"

# ── Temporary files on the drive ────────────────────────────────────────────
export TMPDIR="${PORTABLE_ROOT}/data/tmp"
export TEMP="${PORTABLE_ROOT}/data/tmp"

# ── AI / ML cache dirs (prevent writes to host ~/.cache) ────────────────────
export HF_HOME="${PORTABLE_ROOT}/data/cache/huggingface"
export TORCH_HOME="${PORTABLE_ROOT}/data/cache/torch"
export GPT4ALL_CACHE="${PORTABLE_ROOT}/data/cache/gpt4all"
# SpaCy models: set to a path on the drive
export SPACY_DATA="${PORTABLE_ROOT}/data/cache/spacy"
# Playwright browsers (if bundled)
export PLAYWRIGHT_BROWSERS_PATH="${PORTABLE_ROOT}/bin/pw-browsers"

# ── Portable browser binary (optional — falls back to system Chrome) ─────────
CHROME_CANDIDATES=(
    "${PORTABLE_ROOT}/bin/chromium/chrome"           # Linux Chromium portable
    "${PORTABLE_ROOT}/bin/chrome/chrome"             # Linux Chrome portable
    "${PORTABLE_ROOT}/bin/chrome/Google Chrome.app/Contents/MacOS/Google Chrome"  # macOS
    "/usr/bin/google-chrome"                         # System Chrome (fallback)
    "/usr/bin/chromium-browser"                      # System Chromium (fallback)
    "/usr/bin/chromium"                              # Arch Linux (fallback)
)

for CANDIDATE in "${CHROME_CANDIDATES[@]}"; do
    if [[ -f "${CANDIDATE}" ]]; then
        export AA_BROWSER_BINARY_PATH="${CANDIDATE}"
        echo "Using browser: ${CANDIDATE}"
        break
    fi
done

# ── Portable ChromeDriver (optional) ────────────────────────────────────────
CHROMEDRIVER_CANDIDATES=(
    "${PORTABLE_ROOT}/bin/chromedriver"
    "${PORTABLE_ROOT}/bin/chromium/chromedriver"
)
for CANDIDATE in "${CHROMEDRIVER_CANDIDATES[@]}"; do
    if [[ -f "${CANDIDATE}" ]]; then
        export AA_CHROMEDRIVER_PATH="${CANDIDATE}"
        echo "Using ChromeDriver: ${CANDIDATE}"
        break
    fi
done

# ── Create data directories ──────────────────────────────────────────────────
mkdir -p \
    "${AA_DATA_DIR}/profiles" \
    "${AA_DATA_DIR}/logs" \
    "${AA_DATA_DIR}/checkpoints" \
    "${AA_DATA_DIR}/screenshots" \
    "${AA_DATA_DIR}/reports" \
    "${AA_DATA_DIR}/research" \
    "${AA_DATA_DIR}/cache/chromium_profile" \
    "${AA_DATA_DIR}/cache/gpt4all" \
    "${AA_DATA_DIR}/cache/spacy" \
    "${AA_DATA_DIR}/tmp"

# ── Determine how to launch ──────────────────────────────────────────────────
if [[ -f "${PORTABLE_ROOT}/AutoApply" ]]; then
    # Frozen binary (PyInstaller --onedir)
    echo ""
    echo "Starting AutoApply (frozen binary)..."
    "${PORTABLE_ROOT}/AutoApply" "$@"

elif [[ -f "${PORTABLE_ROOT}/AA/packages/auto_apply/src/auto_apply/main.py" ]]; then
    # Source mode
    echo ""
    echo "Starting AutoApply (source mode)..."
    cd "${PORTABLE_ROOT}/AA"
    python -m auto_apply "$@"

else
    echo ""
    echo "ERROR: Could not find AutoApply executable or source."
    echo "Expected one of:"
    echo "  ${PORTABLE_ROOT}/AutoApply            (frozen binary)"
    echo "  ${PORTABLE_ROOT}/AA/packages/...      (source mode)"
    exit 1
fi

# ── Cleanup temp files after session ────────────────────────────────────────
echo ""
echo "Session complete. Cleaning up temporary files..."
rm -rf "${AA_DATA_DIR}/tmp"
mkdir -p "${AA_DATA_DIR}/tmp"
echo "Temp files removed. All session data saved to the USB drive."

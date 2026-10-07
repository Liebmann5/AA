#!/bin/sh
# install.sh — AutoApply bootstrap for macOS and Linux.
#
# One command, no prerequisites beyond what the OS ships (curl, tar, a sha256
# tool). No git, no compiler (wheels only — macOS never needs the Command
# Line Tools for this path), no admin rights, nothing system-wide.
#
# What it does, in order:
#   1. creates the AA root (default ~/.auto_apply; --root or AA_INSTALL_ROOT)
#   2. downloads the pinned uv binary, verifies its SHA-256 against
#      install_pins.txt, extracts it into <root>/uv
#   3. points UV_PYTHON_INSTALL_DIR / UV_CACHE_DIR into the root
#   4. fetches the AA source archive (release asset, or --archive for
#      offline/USB) and extracts it into <root>/app
#   5. hands over to AA's own --install (all further logic lives in Python)
#
# Everything it downloads is shown with sizes and confirmed first. The uv and
# Python executables are checksum-verified; the source archive is verified
# against the release's SHA256SUMS.txt when available — that detects
# corruption, not compromise, and this script says so rather than implying
# otherwise. Read this script and install_pins.txt before piping it; that is
# the trust model, stated plainly.
#
# Offline / USB: install.sh --root /media/usb/AutoApply --archive AA-src.tar.gz --offline
# One prepared copy per OS: uv binaries and Python builds are per-platform.
set -eu

ROOT="${AA_INSTALL_ROOT:-$HOME/.auto_apply}"
YES=0
OFFLINE=0
ALLOW_UNVERIFIED_SOURCE=0
ARCHIVE=""
EXTRAS=""
SHORTCUT=0
PINS_REF="main"   # release process pins this to the tag being released

usage() {
    echo "usage: install.sh [--root DIR] [--yes] [--offline] [--archive FILE_OR_URL] [--extra NAME]... [--shortcut]"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --root) ROOT="$2"; shift 2 ;;
        --yes|-y) YES=1; shift ;;
        --offline) OFFLINE=1; shift ;;
        --archive) ARCHIVE="$2"; shift 2 ;;
        --extra) EXTRAS="$EXTRAS $2"; shift 2 ;;
        --shortcut) SHORTCUT=1; shift ;;
        --allow-unverified-source) ALLOW_UNVERIFIED_SOURCE=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

die() { echo "install: $*" >&2; exit 1; }

# ── pins ────────────────────────────────────────────────────────────────────
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || echo ".")
PINS_FILE="$SCRIPT_DIR/install_pins.txt"

fetch() {
    # fetch URL DEST
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --retry 3 -o "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$2" "$1"
    else
        die "neither curl nor wget found — one of them is required (both ship with macOS and virtually all Linux)"
    fi
}

if [ ! -f "$PINS_FILE" ]; then
    [ "$OFFLINE" = 1 ] && die "offline mode but install_pins.txt not found next to the script"
    PINS_FILE="$ROOT/.install_pins.txt"
    mkdir -p "$ROOT"
    echo "Fetching install pins (one file, all versions and checksums)..."
    fetch "https://raw.githubusercontent.com/Liebmann5/AA/${PINS_REF}/packages/auto_apply/install_pins.txt" "$PINS_FILE"
fi

pin() { grep "^$1=" "$PINS_FILE" | cut -d= -f2-; }

UV_VERSION=$(pin UV_VERSION)
PYTHON_VERSION=$(pin PYTHON_VERSION)
AA_RELEASE_REPO=$(pin AA_RELEASE_REPO)
AA_ARCHIVE_ASSET=$(pin AA_ARCHIVE_ASSET)
AA_SUMS_ASSET=$(pin AA_SUMS_ASSET)
SIZE_UV_MB=$(pin SIZE_UV_MB)
SIZE_PYTHON_MB=$(pin SIZE_PYTHON_MB)
SIZE_ARCHIVE_MB=$(pin SIZE_ARCHIVE_MB)
SIZE_DEPS_CORE_MB=$(pin SIZE_DEPS_CORE_MB)
[ -n "$UV_VERSION" ] && [ -n "$PYTHON_VERSION" ] || die "install_pins.txt is missing UV_VERSION or PYTHON_VERSION"

# ── platform detection ──────────────────────────────────────────────────────
OS=$(uname -s)
ARCH=$(uname -m)
case "$OS" in
    Darwin)
        case "$ARCH" in
            arm64) TARGET="aarch64-apple-darwin" ;;
            x86_64) TARGET="x86_64-apple-darwin" ;;
            *) die "unsupported Mac architecture: $ARCH" ;;
        esac ;;
    Linux)
        case "$ARCH" in
            x86_64) TARGET="x86_64-unknown-linux-gnu" ;;
            aarch64) TARGET="aarch64-unknown-linux-gnu" ;;
            *) die "unsupported Linux architecture: $ARCH" ;;
        esac ;;
    *) die "unsupported operating system: $OS (on Windows, use install.ps1)" ;;
esac
CHECKSUM_KEY="UV_SHA256_$(printf '%s' "$TARGET" | tr 'a-z-' 'A-Z_')"
EXPECTED=$(pin "$CHECKSUM_KEY")

# ── the plan, then consent ─────────────────────────────────────────────────
cat <<EOF

AutoApply will be installed into: $ROOT
Nothing is installed system-wide; no administrator rights are used.

Downloads needed:
  uv $UV_VERSION (the installer/runtime)        ~${SIZE_UV_MB} MB
  Python $PYTHON_VERSION (via uv, into the root)   ~${SIZE_PYTHON_MB} MB
  AutoApply source archive                      ~${SIZE_ARCHIVE_MB} MB
  Core dependencies (resolved by uv)            ~${SIZE_DEPS_CORE_MB} MB
Your browser is detected later, never installed.

EOF
if [ "$OFFLINE" = 1 ]; then
    echo "Offline mode: no downloads — the root must be pre-populated."
fi
if [ "$YES" != 1 ]; then
    printf "Proceed? [y/N] "
    if ! read -r answer < /dev/tty 2>/dev/null; then
        die "no terminal to ask for confirmation — re-run with --yes"
    fi
    case "$answer" in
        y|Y|yes|YES) ;;
        *) echo "Nothing was downloaded."; exit 0 ;;
    esac
fi

mkdir -p "$ROOT/uv" "$ROOT/tmp" "$ROOT/app"

# ── uv, checksum-verified ──────────────────────────────────────────────────
UV_BIN="$ROOT/uv/uv"
if [ -x "$UV_BIN" ] && "$UV_BIN" --version 2>/dev/null | grep -q "$UV_VERSION"; then
    echo "uv $UV_VERSION already present — skipping."
else
    [ "$OFFLINE" = 1 ] && die "offline mode but no usable uv at $UV_BIN — pre-populate the root or re-run online"
    case "$EXPECTED" in
        REPLACE_*|"")
            die "uv's SHA-256 is not pinned in install_pins.txt ($CHECKSUM_KEY) — the release process fills this from the published uv release. Refusing to run an unverifiable binary." ;;
    esac
    ARCHIVE_FILE="$ROOT/tmp/uv-${TARGET}.tar.gz"
    echo "Downloading uv $UV_VERSION..."
    fetch "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${TARGET}.tar.gz" "$ARCHIVE_FILE"
    if command -v sha256sum >/dev/null 2>&1; then
        ACTUAL=$(sha256sum "$ARCHIVE_FILE" | awk '{print $1}')
    elif command -v shasum >/dev/null 2>&1; then
        ACTUAL=$(shasum -a 256 "$ARCHIVE_FILE" | awk '{print $1}')
    else
        ACTUAL=$(openssl dgst -sha256 -r "$ARCHIVE_FILE" | awk '{print $1}')
    fi
    if [ "$ACTUAL" != "$EXPECTED" ]; then
        rm -f "$ARCHIVE_FILE"
        die "checksum mismatch for uv $UV_VERSION (expected $EXPECTED, got $ACTUAL). The download was deleted; nothing was installed. This is the safety property working — do not bypass it."
    fi
    tar -xzf "$ARCHIVE_FILE" -C "$ROOT/uv"
    if [ ! -f "$UV_BIN" ]; then
        for d in "$ROOT"/uv/*/; do
            if [ -f "${d}uv" ]; then mv "${d}"* "$ROOT/uv/"; rmdir "$d" 2>/dev/null || true; break; fi
        done
    fi
    chmod +x "$UV_BIN" 2>/dev/null || true
    rm -f "$ARCHIVE_FILE"
fi

if ! "$UV_BIN" --version >/dev/null 2>&1; then
    die "cannot execute $UV_BIN — is this filesystem mounted noexec (common on USB drives)? Try --root on a normal filesystem."
fi

export UV_PYTHON_INSTALL_DIR="$ROOT/python"
export UV_CACHE_DIR="$ROOT/uv-cache"
export UV_NO_MODIFY_PATH=1
export UV_UNMANAGED_INSTALL="$ROOT/uv"

# ── the source archive ─────────────────────────────────────────────────────
if [ -f "$ROOT/app/pyproject.toml" ]; then
    echo "AA source already present — skipping."
elif [ -n "$ARCHIVE" ]; then
    case "$ARCHIVE" in
        http://*|https://*)
            [ "$OFFLINE" = 1 ] && die "--offline with a URL archive makes no sense"
            echo "Downloading source archive from $ARCHIVE..."
            fetch "$ARCHIVE" "$ROOT/tmp/aa-src.tar.gz" ;;
        *)
            cp "$ARCHIVE" "$ROOT/tmp/aa-src.tar.gz" ;;
    esac
    tar -xzf "$ROOT/tmp/aa-src.tar.gz" -C "$ROOT/app" --strip-components=1
    rm -f "$ROOT/tmp/aa-src.tar.gz"
else
    [ "$OFFLINE" = 1 ] && die "offline mode but no source at $ROOT/app — pass --archive AA-src.tar.gz"
    ASSET_URL="https://github.com/${AA_RELEASE_REPO}/releases/latest/download/${AA_ARCHIVE_ASSET}"
    echo "Downloading AutoApply source (release asset)..."
    if ! fetch "$ASSET_URL" "$ROOT/tmp/aa-src.tar.gz"; then
        die "no source archive at $ASSET_URL (is there a release yet?). Use --archive AA-src.tar.gz for a local copy."
    fi
    # Verify against the release's checksum file. Ruled (D16): an
    # unverified source archive is NOT acceptable by default — this
    # installer refuses an unverified uv, and the source is no different.
    if fetch "https://github.com/${AA_RELEASE_REPO}/releases/latest/download/${AA_SUMS_ASSET}" "$ROOT/tmp/${AA_SUMS_ASSET}" 2>/dev/null; then
        SUM=$(grep " ${AA_ARCHIVE_ASSET}\$" "$ROOT/tmp/${AA_SUMS_ASSET}" | awk '{print $1}')
        if [ -n "$SUM" ]; then
            if command -v sha256sum >/dev/null 2>&1; then GOT=$(sha256sum "$ROOT/tmp/aa-src.tar.gz" | awk '{print $1}'); else GOT=$(shasum -a 256 "$ROOT/tmp/aa-src.tar.gz" | awk '{print $1}'); fi
            [ "$GOT" = "$SUM" ] || { rm -f "$ROOT/tmp/aa-src.tar.gz"; die "source archive checksum mismatch — deleted, nothing installed."; }
            echo "Source archive checksum verified."
        fi
    elif [ "$ALLOW_UNVERIFIED_SOURCE" = 1 ]; then
        echo "WARNING: no ${AA_SUMS_ASSET} in the release — the archive is authenticated by HTTPS only (uv and Python ARE checksum-verified)."
    else
        rm -f "$ROOT/tmp/aa-src.tar.gz"
        die "the release offers no ${AA_SUMS_ASSET} — refusing an unverifiable source archive. Re-run with --allow-unverified-source to accept HTTPS-only verification, or use --archive AA-src.tar.gz for a local copy."
    fi
    tar -xzf "$ROOT/tmp/aa-src.tar.gz" -C "$ROOT/app" --strip-components=1
    rm -f "$ROOT/tmp/aa-src.tar.gz" "$ROOT/tmp/SHA256SUMS.txt"
fi

# ── hand over to AA's own installer (all further logic lives in Python) ────
export AA_MANAGED_ROOT="$ROOT"
export AA_DATA_DIR="$ROOT/data"

set -- --root "$ROOT" --yes
[ "$OFFLINE" = 1 ] && set -- "$@" --offline
[ "$SHORTCUT" = 1 ] && set -- "$@" --shortcut
for extra in $EXTRAS; do
    set -- "$@" --extra "$extra"
done
UV_RUN_ARGS=""
[ "$OFFLINE" = 1 ] && UV_RUN_ARGS="--offline"

# The bootstrap asked for consent above and it covers this whole flow, so
# --yes is passed on deliberately (see the plan printed before the download).
# Arguments are built with set -- (D14, measured): a root containing spaces
# — /Users/Jane Doe/.auto_apply — split into two arguments before.
# shellcheck disable=SC2086
"$UV_BIN" run $UV_RUN_ARGS --project "$ROOT/app" --package auto_apply \
    python -m auto_apply --install "$@"

cat <<EOF

AutoApply is installed.
Start it with: $ROOT/bin/auto-apply        (GUI)
               $ROOT/bin/auto-apply --cli  (terminal)
Add $ROOT/bin to your PATH if you like — nothing requires it.
To remove everything: $ROOT/bin/auto-apply --uninstall
EOF

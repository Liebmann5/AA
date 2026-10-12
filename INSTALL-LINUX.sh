#!/bin/sh
# INSTALL-LINUX.sh - install AutoApply on Linux (run: sh INSTALL-LINUX.sh).
# It only starts packages/auto_apply/install.sh for you; all the work and every
# question happen there. Nothing system-wide, no administrator rights.
# Kept pure ASCII with LF line endings.
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)
INSTALLER="$HERE/packages/auto_apply/install.sh"

finish() {
    echo
    printf "Press Enter to close this window. "
    read -r _ </dev/tty 2>/dev/null || true
    exit "$1"
}

if [ ! -f "$INSTALLER" ]; then
    echo
    echo "The AutoApply files are not next to this installer."
    echo "Unzip the download first, open the unzipped folder, and run"
    echo "INSTALL-LINUX.sh from there."
    finish 1
fi

echo
echo "=============================================================="
echo " AutoApply installer"
echo "=============================================================="
echo " The installer shows what it downloads and where it goes, then"
echo " asks before doing anything. Type y and press Enter to go on."
echo

if ! sh "$INSTALLER" --shortcut; then
    echo
    echo "=============================================================="
    echo " The installation stopped. The message above says why."
    echo " Running this installer again is safe: it resumes and repairs."
    echo " If it keeps failing, copy or photograph this window and open"
    echo " an issue at https://github.com/Liebmann5/AA/issues"
    echo "=============================================================="
    finish 1
fi

ROOT="${AA_INSTALL_ROOT:-$HOME/.auto_apply}"
if [ ! -x "$ROOT/bin/auto-apply" ]; then
    echo
    echo "Nothing was installed."
    finish 0
fi

echo
echo "=============================================================="
echo " Done. To start AutoApply any time later:"
echo "   open AutoApply from your applications menu,"
echo " or paste this into Terminal:"
echo "   \"$ROOT/bin/auto-apply\""
echo " To remove AutoApply completely, paste this into Terminal:"
echo "   \"$ROOT/bin/auto-apply\" --uninstall"
echo "=============================================================="
echo
printf "Start AutoApply now? [Y/n] "
answer=""
read -r answer </dev/tty 2>/dev/null || true
case "$answer" in
    n|N|no|NO|No) ;;
    *) "$ROOT/bin/auto-apply" ;;
esac
finish 0

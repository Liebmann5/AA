#!/bin/bash
# RETIRED FROM: packages/auto_apply/run.sh
set -e

echo "--- AutoApply Setup and Launcher for Linux/macOS ---"

# --- Section 1: Define paths ---
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
PROJECT_DIR="$SCRIPT_DIR"
VENV_DIR="$PROJECT_DIR/.venv"

# --- Section 2: Parse Arguments ---
COMMAND="run"
DEV_SETUP_ONLY=false
PASS_THROUGH_ARGS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        --dev) DEV_SETUP_ONLY=true; shift ;;
        run|test|docs|clean|wipe) COMMAND=$1; shift ;;
        *) PASS_THROUGH_ARGS+=("$1"); shift ;;
    esac
done

# --- Section 3: Handle 'clean' and 'wipe' commands ---
if [[ "$COMMAND" == "clean" || "$COMMAND" == "wipe" ]]; then
    if [[ "$COMMAND" == "wipe" ]]; then
        echo "[*] Wiping all project artifacts and caches..."
    else
        echo "[*] Cleaning project build artifacts..."
    fi
    
    rm -rf "$VENV_DIR" "$PROJECT_DIR/src/auto_apply.egg-info"
    
    if [[ "$COMMAND" == "wipe" ]]; then
        echo "[*] Searching for and removing __pycache__ and .pytest_cache directories..."
        # Use find to locate and delete all specified directories
        find "$PROJECT_DIR" -type d \( -name "__pycache__" -o -name ".pytest_cache" \) -exec rm -rf {} +
    fi
    
    echo "[+] $COMMAND complete."
    exit 0
fi

# --- Section 4: Find Global Python & Setup Venv ---
PYTHON_CMD=$(command -v python3 || command -v python || command -v py)
if [ -z "$PYTHON_CMD" ]; then echo "[!] Error: Python 3 not found."; exit 1; fi
if [[ "$COMMAND" != "run" ]]; then echo "[+] Found Global Python: $PYTHON_CMD"; fi

if [ ! -d "$VENV_DIR" ]; then
    echo "[*] Creating virtual environment..."
    "$PYTHON_CMD" -m venv "$VENV_DIR" --prompt "smells_like_updog"
    NEEDS_INSTALL=true
fi

# --- Section 5: Activate Venv and Install Dependencies ---
source "$VENV_DIR/bin/activate"
if [[ "$COMMAND" != "run" ]]; then echo "[+] Virtual environment activated."; fi

INSTALL_EXTRAS=""
if [[ "$DEV_SETUP_ONLY" == true || "$COMMAND" == "test" || "$COMMAND" == "docs" ]]; then
    NEEDS_INSTALL=true
    INSTALL_EXTRAS="[dev,docs]"
fi

if [[ "$NEEDS_INSTALL" == true ]]; then
    echo "[*] Installing/Verifying dependencies..."
    python -m pip install -e "${PROJECT_DIR}${INSTALL_EXTRAS}"
    if [[ "$DEV_SETUP_ONLY" == true ]]; then
        echo "[+] Developer environment is ready."
        exit 0
    fi
fi

# --- Section 6: Execute Command ---
case $COMMAND in
    run)
        echo "[*] Launching AutoApply..."
        echo "---------------------------------"
        python -m auto_apply "${PASS_THROUGH_ARGS[@]}"
        ;;
    test)
        echo "[*] Running tests with pytest..."
        python -m pytest "$PROJECT_DIR/tests" "${PASS_THROUGH_ARGS[@]}"
        ;;
    docs)
        echo "[*] Serving documentation at http://127.0.0.1:8000"
        cd "$PROJECT_DIR"
        python -m mkdocs serve
        ;;
esac

echo "---------------------------------"
echo "[*] Command '$COMMAND' has finished."
deactivate
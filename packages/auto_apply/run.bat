@echo off
setlocal enabledelayedexpansion

echo --- AutoApply Setup and Launcher for Windows ---

REM --- ============================================================================
REM --- CRITICAL PRE-FLIGHT CHECK ---
REM --- ============================================================================
IF DEFINED VIRTUAL_ENV (
    echo [!!!] CRITICAL ERROR: This script cannot be run from within an already active virtual environment.
    echo [!!!] The previous session may not have shut down correctly.
    echo.
    echo [ ACTION REQUIRED ] Please run the following command first to exit the environment:
    echo.
    echo     deactivate
    echo.
    echo Then, run this script again.
    exit /b 1
)

REM --- Section 1: Define paths ---
set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "ACTIVATE_SCRIPT=%VENV_DIR%\Scripts\Activate.bat"

REM --- ============================================================================
REM --- ROBUST ARGUMENT PARSER ---
REM --- ============================================================================
set "COMMAND=run"
set "DEV_SETUP_ONLY=false"
set "PASS_THROUGH_ARGS="

REM Stage 1: Identify the main command from the first argument.
REM This loop robustly finds the main command and --dev flag, regardless of order.
:arg_parse_loop
if "%~1"=="" goto :end_arg_parse_loop
if /i "%~1"=="run" ( set "COMMAND=run" & shift )
if /i "%~1"=="test" ( set "COMMAND=test" & shift )
if /i "%~1"=="docs" ( set "COMMAND=docs" & shift )
if /i "%~1"=="clean" ( set "COMMAND=clean" & shift )
if /i "%~1"=="wipe" ( set "COMMAND=wipe" & shift )
if /i "%~1"=="--dev" ( set "DEV_SETUP_ONLY=true" & shift )

@REM REM Stage 2: Treat ALL remaining arguments as pass-through arguments.
@REM :pass_loop
@REM if "%~1"=="" goto :end_pass_loop
@REM set "PASS_THROUGH_ARGS=!PASS_THROUGH_ARGS! %~1"
@REM shift
@REM goto :pass_loop
@REM :end_pass_loop
REM If it's not a main command, it's a pass-through argument.
set "PASS_THROUGH_ARGS=!PASS_THROUGH_ARGS! %~1"
shift
goto :arg_parse_loop

:found_command
shift

REM All remaining arguments are pass-through.
:pass_loop
if "%~1"=="" goto :end_pass_loop
set "PASS_THROUGH_ARGS=!PASS_THROUGH_ARGS! %~1"
shift
goto :pass_loop
:end_pass_loop

:end_arg_parse_loop

REM --- Section 3: Handle 'clean' and 'wipe' commands ---
if "%COMMAND%"=="clean" (
    echo [*] Cleaning project build artifacts...
    if exist "%VENV_DIR%" ( echo [-] Removing virtual environment... & rmdir /s /q "%VENV_DIR%" )
    if errorlevel 1 ( echo [!] Warning: Could not fully remove .venv. It may be in use. Please close other terminals. )
    if exist "%PROJECT_DIR%\src\auto_apply.egg-info" ( echo [-] Removing egg-info... & rmdir /s /q "%PROJECT_DIR%\src\auto_apply.egg-info" )
    echo [+] Clean complete.
    exit /b 0
)
if "%COMMAND%"=="wipe" (
    echo [*] Wiping all project artifacts and caches...
    if exist "%VENV_DIR%" ( echo [-] Removing virtual environment... & rmdir /s /q "%VENV_DIR%" )
    if errorlevel 1 ( echo [!] Warning: Could not fully remove .venv. It may be in use. Please close other terminals. )
    if exist "%PROJECT_DIR%\src\auto_apply.egg-info" ( echo [-] Removing egg-info... & rmdir /s /q "%PROJECT_DIR%\src\auto_apply.egg-info" )
    if exist "%PROJECT_DIR%\.pytest_cache" ( echo [-] Removing pytest cache... & rmdir /s /q "%PROJECT_DIR%\.pytest_cache" )
    for /r "%PROJECT_DIR%" /d %%F in (__pycache__) do ( if exist "%%F" ( rmdir /s /q "%%F" ) )
    echo [+] Wipe complete.
    exit /b 0
)

REM --- Section 4: Self-Healing Venv Setup ---
set "PYTHON_CMD="
for %%C in (py python3 python) do ( if not defined PYTHON_CMD ( %%C --version >nul 2>nul && set "PYTHON_CMD=%%C" ) )
if not defined PYTHON_CMD ( echo [!] Error: Python 3 not found. & exit /b 1 )

if not exist "%ACTIVATE_SCRIPT%" (
    echo [!] Virtual environment is missing or corrupted. Rebuilding...
    if exist "%VENV_DIR%" (
        echo [-] Removing corrupted venv directory...
        rmdir /s /q "%VENV_DIR%"
        if errorlevel 1 (
            echo [!!!] CRITICAL ERROR: Failed to remove corrupted .venv directory. It is likely in use.
            echo [!!!] Please close all terminals, manually delete the '.venv' folder, and run this script again.
            exit /b 1
        )
    )
    echo [*] Creating new virtual environment...
    %PYTHON_CMD% -m venv "%VENV_DIR%" --prompt "smells_like_updog"
    set "NEEDS_INSTALL=true"
)
@REM call "%ACTIVATE_SCRIPT%"
@REM set "INSTALL_EXTRAS="
@REM if "%DEV_SETUP_ONLY%"=="true" ( set "NEEDS_INSTALL=true" & set "INSTALL_EXTRAS=[dev,docs]" )
@REM if "%COMMAND%"=="test" ( set "NEEDS_INSTALL=true" & set "INSTALL_EXTRAS=[dev,docs]" )
@REM if "%COMMAND%"=="docs" ( set "NEEDS_INSTALL=true" & set "INSTALL_EXTRAS=[dev,docs]" )
@REM if "%NEEDS_INSTALL%"=="true" (
@REM     echo [*] Installing dependencies...
@REM     python -m pip install -e "%PROJECT_DIR%%INSTALL_EXTRAS%"
@REM     if errorlevel 1 ( echo [!] Failed to install dependencies. & exit /b 1 )
@REM     if "%DEV_SETUP_ONLY%"=="true" (
@REM         echo [+] Developer environment is ready.
@REM         exit /b 0
@REM     )
@REM )

@REM REM --- Section 5: Activate Venv and Install Dependencies ---
@REM call "%ACTIVATE_SCRIPT%"

@REM set "INSTALL_EXTRAS="
@REM if "%DEV_SETUP_ONLY%"=="true" ( set "NEEDS_INSTALL=true" & set "INSTALL_EXTRAS=[dev,docs]" )
@REM if "%COMMAND%"=="test" ( set "NEEDS_INSTALL=true" & set "INSTALL_EXTRAS=[dev,docs]" )
@REM if "%COMMAND%"=="docs" ( set "NEEDS_INSTALL=true" & set "INSTALL_EXTRAS=[dev,docs]" )

@REM if defined NEEDS_INSTALL (
@REM     echo [*] Installing dependencies...
@REM     python -m pip install -e "%PROJECT_DIR%%INSTALL_EXTRAS%"
@REM     if errorlevel 1 ( echo [!] Failed to install dependencies. & exit /b 1 )
@REM     if "%DEV_SETUP_ONLY%"=="true" (
@REM         echo [+] Developer environment is ready.
@REM         exit /b 0
@REM     )
@REM )
REM --- Section 5: Activate Venv and Install Dependencies ---
call "%ACTIVATE_SCRIPT%"

REM --- THE DEFINITIVE FIX IS HERE ---
REM This logic is now granular and installs only what is needed.
set "INSTALL_EXTRAS="
if "%COMMAND%"=="test" (
    echo [*] Test command requires [dev] dependencies.
    set "NEEDS_INSTALL=true"
    set "INSTALL_EXTRAS=[dev]"
)
if "%COMMAND%"=="docs" (
    echo [*] Docs command requires [docs] dependencies.
    set "NEEDS_INSTALL=true"
    set "INSTALL_EXTRAS=[docs]"
)
if "%DEV_SETUP_ONLY%"=="true" (
    echo [*] Full developer setup requires [dev,docs] dependencies.
    set "NEEDS_INSTALL=true"
    set "INSTALL_EXTRAS=[dev,docs]"
)

if defined NEEDS_INSTALL (
    echo [*] Installing dependencies for: %PROJECT_DIR%%INSTALL_EXTRAS%
    python -m pip install -e "%PROJECT_DIR%%INSTALL_EXTRAS%"
    if errorlevel 1 ( echo [!] Failed to install dependencies. & exit /b 1 )
    if "%DEV_SETUP_ONLY%"=="true" (
        echo [+] Developer environment is ready.
        exit /b 0
    )
)

REM --- LAST MINUTE CHECKS ---
REM Checks if Playwright has any browsers installed & if no then can download some
echo [*] Checking Playwright browser availability...
python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start();
print(p.chromium.executable_path)" 2>NUL
if errorlevel 1 (
    echo.
    echo [!] Playwright browsers are not installed.
    echo     AA works best with Playwright for advanced evasion.
    echo.
    echo     Available browsers:
    echo       [1] Chromium (~300 MB)
    echo       [2] Firefox  (~80 MB)
    echo       [3] Webkit   (~50 MB)
    echo       [4] All three
    echo       [Enter] Skip (AA will use Selenium instead)
    echo.
    set /p CHOICE="Which would you like to install? "
    if "%CHOICE%"=="1" python -m playwright install chromium
    if "%CHOICE%"=="2" python -m playwright install firefox
    if "%CHOICE%"=="3" python -m playwright install webkit
    if "%CHOICE%"=="4" python -m playwright install
)

REM Checks if NLP/AI extras are installed & if no then can download some
echo [*] Checking if NLP/AI extras are installed...

if errorlevel 1 (
    echo.
    echo [!] Playwright browsers are not installed.
    echo     AA works best with Playwright for advanced evasion.
    echo.
    echo     Available browsers:
    echo       [1] AI          (~300 MB)
    echo       [2] NLP         (~80 MB)
    echo       [3] CORE_WEB_LG (~400 MB)
    echo       [4] All three
    echo       [Enter] Skip (AA will use Selenium instead)
    echo.
    set /p CHOICE="Which would you like to install? "
    if "%CHOICE%"=="1" pip install "auto_apply[ai]"
    if "%CHOICE%"=="2" pip install "auto_apply[nlp]"
    if "%CHOICE%"=="3" python -m spacy download en_core_web_lg
    if "%CHOICE%"=="4" pip install "auto_apply[full]" && python -m spacy download en_core_web_lg
) 

REM --- Section 6: Execute Command ---
if "%COMMAND%"=="run" (
    echo [*] Launching AutoApply...
    echo ---------------------------------
    python -m auto_apply %PASS_THROUGH_ARGS%
) else if "%COMMAND%"=="test" (
    echo [*] Running tests with pytest...
    python -m pytest "%PROJECT_DIR%/tests" %PASS_THROUGH_ARGS%
) else if "%COMMAND%"=="docs" (
    echo [*] Serving documentation at http://127.0.0.1:8000
    cd /d "%PROJECT_DIR%"
    python -m mkdocs serve
)

echo ---------------------------------
echo [*] Command '%COMMAND%' has finished.
deactivate
endlocal
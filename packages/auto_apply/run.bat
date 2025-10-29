@echo off
setlocal enabledelayedexpansion

echo --- AutoApply Setup and Launcher for Windows ---

REM --- Section 1: Define paths ---
set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "VENV_DIR=%PROJECT_DIR%\.venv"

REM --- Section 2: Parse Arguments ---
set "COMMAND=run"
set "DEV_SETUP_ONLY=false"
set "PASS_THROUGH_ARGS="
:arg_loop
if "%~1"=="" goto :end_arg_loop
if /i "%~1"=="--dev" ( set "DEV_SETUP_ONLY=true" ) else if /i "%~1"=="run" ( set "COMMAND=run" ) else if /i "%~1"=="test" ( set "COMMAND=test" ) else if /i "%~1"=="docs" ( set "COMMAND=docs" ) else if /i "%~1"=="clean" ( set "COMMAND=clean" ) else if /i "%~1"=="wipe" ( set "COMMAND=wipe" ) else ( set "PASS_THROUGH_ARGS=!PASS_THROUGH_ARGS! %~1" )
shift
goto :arg_loop
:end_arg_loop

REM --- Section 3: Handle 'clean' and 'wipe' commands ---
if "%COMMAND%"=="clean" (
    echo [*] Cleaning project build artifacts...
    if exist "%VENV_DIR%" ( echo [-] Removing virtual environment... & rmdir /s /q "%VENV_DIR%" )
    if exist "%PROJECT_DIR%\src\auto_apply.egg-info" ( echo [-] Removing egg-info... & rmdir /s /q "%PROJECT_DIR%\src\auto_apply.egg-info" )
    echo [+] Clean complete.
    exit /b 0
)

if "%COMMAND%"=="wipe" (
    echo [*] Wiping all project artifacts and caches...
    if exist "%VENV_DIR%" ( echo [-] Removing virtual environment... & rmdir /s /q "%VENV_DIR%" )
    if exist "%PROJECT_DIR%\src\auto_apply.egg-info" ( echo [-] Removing egg-info... & rmdir /s /q "%PROJECT_DIR%\src\auto_apply.egg-info" )
    if exist "%PROJECT_DIR%\.pytest_cache" ( echo [-] Removing pytest cache... & rmdir /s /q "%PROJECT_DIR%\.pytest_cache" )
    
    echo [*] Searching for and removing __pycache__ directories...
    for /r "%PROJECT_DIR%" /d %%F in (__pycache__) do (
        if exist "%%F" (
            echo [-] Removing cache: %%F
            rmdir /s /q "%%F"
        )
    )
    echo [+] Wipe complete.
    exit /b 0
)


REM --- Section 4: Find Global Python & Setup Venv ---
set "PYTHON_CMD="
for %%C in (py python3 python) do ( if not defined PYTHON_CMD ( %%C --version >nul 2>nul && set "PYTHON_CMD=%%C" ) )
if not defined PYTHON_CMD ( echo [!] Error: Python 3 not found. & exit /b 1 )
if not "%COMMAND%"=="run" ( echo [+] Found Global Python: %PYTHON_CMD% )

if not exist "%VENV_DIR%\" (
    echo [*] Creating virtual environment...
    %PYTHON_CMD% -m venv "%VENV_DIR%" --prompt "smells_like_updog"
    set "NEEDS_INSTALL=true"
)

REM --- Section 5: Activate Venv and Install Dependencies ---
call "%VENV_DIR%\Scripts\activate.bat"
if not "%COMMAND%"=="run" ( echo [+] Virtual environment activated. )

set "INSTALL_EXTRAS="
if "%DEV_SETUP_ONLY%"=="true" ( set "NEEDS_INSTALL=true" & set "INSTALL_EXTRAS=[dev,docs]" )
if "%COMMAND%"=="test" ( set "NEEDS_INSTALL=true" & set "INSTALL_EXTRAS=[dev,docs]" )
if "%COMMAND%"=="docs" ( set "NEEDS_INSTALL=true" & set "INSTALL_EXTRAS=[dev,docs]" )

if "%NEEDS_INSTALL%"=="true" (
    echo [*] Installing/Verifying dependencies...
    python -m pip install -e "%PROJECT_DIR%%INSTALL_EXTRAS%"
    if errorlevel 1 ( echo [!] Failed to install dependencies. & exit /b 1 )
    if "%DEV_SETUP_ONLY%"=="true" (
        echo [+] Developer environment is ready.
        exit /b 0
    )
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
@echo off
rem INSTALL-WINDOWS.bat - double-click to install AutoApply on Windows.
rem Pure ASCII, CRLF line endings: cmd.exe misreads anything else.
rem It only starts packages\auto_apply\install.ps1 for you; all the work and
rem every question happen there. Nothing system-wide, no admin rights.
setlocal
title AutoApply installer
set "AA_HERE=%~dp0"
set "AA_PS1=%~dp0packages\auto_apply\install.ps1"

if exist "%AA_PS1%" goto have_files
echo.
echo  The AutoApply files are not next to this installer.
echo.
echo  This usually means it was opened from inside the ZIP file.
echo  Close this window, right-click the ZIP you downloaded, choose
echo  "Extract All...", open the extracted folder and double-click
echo  INSTALL-WINDOWS.bat there.
echo.
pause
exit /b 1

:have_files
where powershell.exe >nul 2>nul
if not errorlevel 1 goto have_ps
echo.
echo  Windows PowerShell was not found on this computer, and the installer
echo  needs it. It is part of every Windows 10 and 11 installation.
echo.
pause
exit /b 1

:have_ps
echo.
echo  ==============================================================
echo   AutoApply installer
echo  ==============================================================
echo   The installer will show what it downloads and where it goes,
echo   then ask before doing anything. Type y and press Enter to go on.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%AA_PS1%" -Shortcut
if errorlevel 1 goto failed

set "AA_ROOT=%USERPROFILE%\.auto_apply"
set "AA_SHOW=%%USERPROFILE%%\.auto_apply"
if defined AA_INSTALL_ROOT set "AA_ROOT=%AA_INSTALL_ROOT%"
if defined AA_INSTALL_ROOT set "AA_SHOW=%AA_INSTALL_ROOT%"
if not exist "%AA_ROOT%\bin\auto-apply.bat" goto done_not_installed

echo.
echo  ==============================================================
echo   Done. To start AutoApply any time later:
echo     press the Windows key + R, paste the line below, press Enter
echo     %AA_SHOW%\bin\auto-apply.bat
echo.
echo   To remove AutoApply completely, use the same box with:
echo     %AA_SHOW%\bin\auto-apply.bat --uninstall
echo  ==============================================================
echo.
set "AA_START="
set /p "AA_START=Start AutoApply now? [Y/n] "
if /i "%AA_START%"=="n" goto end
if /i "%AA_START%"=="no" goto end
call "%AA_ROOT%\bin\auto-apply.bat"
goto end

:done_not_installed
echo.
echo  Nothing was installed.
goto end

:failed
echo.
echo  ==============================================================
echo   The installation stopped. The red text above says why.
echo   Running this installer again is safe: it resumes and repairs.
echo   If it keeps failing, take a screenshot of this window and open
echo   an issue at https://github.com/Liebmann5/AA/issues
echo  ==============================================================

:end
echo.
pause
endlocal

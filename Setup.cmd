@echo off
rem Atlas setup: creates .venv next to this file, installs the two dependencies (offline from wheels\
rem when possible, otherwise from the internet), runs the offline tests and creates the Atlas shortcut.
rem Safe to run again at any time; a .venv copied from another computer is rebuilt.
setlocal
cd /d "%~dp0"

echo [1/4] Looking for Python 3.11 or newer ...
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=python"
if not defined PY (
    echo     Python 3.11+ was not found. Install it from https://www.python.org/downloads/
    echo     and tick "Add python.exe to PATH", then run Setup.cmd again.
    goto fail
)
%PY% -c "import sys; print('    found Python', sys.version.split()[0])"

rem Some dependency files have very long names; a deep folder exceeds the 260-character Windows path limit.
%PY% -c "import os, sys; sys.exit(len(os.getcwd()) > 100)" || (
    echo     This folder's path is too long for Windows. Move Atlas to a shorter path, such as C:\Atlas,
    echo     then run Setup.cmd again.
    goto fail
)

echo [2/4] Creating .venv ...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>nul || (
        echo     existing .venv belongs to another computer; rebuilding it
        rmdir /s /q ".venv"
    )
)
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv || goto fail
)

echo [3/4] Installing dependencies ...
set "INSTALLED="
if exist "wheels\" ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --no-index --find-links wheels -r requirements.txt >nul 2>nul && set "INSTALLED=1"
if not defined INSTALLED (
    echo     downloading from the internet
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto fail
)

echo [4/4] Running offline tests ...
".venv\Scripts\python.exe" -m unittest discover -s tests -t . >"%TEMP%\atlas_setup_tests.txt" 2>&1
if errorlevel 1 (
    type "%TEMP%\atlas_setup_tests.txt"
    goto fail
)
echo     tests passed

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d = (Get-Location).Path; $s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Atlas.lnk'));" ^
  "$s.TargetPath = Join-Path $d '.venv\Scripts\pythonw.exe'; $s.Arguments = '-m oradoc.webapp'; $s.WorkingDirectory = $d;" ^
  "$s.IconLocation = \"$env:SystemRoot\System32\imageres.dll,170\"; $s.Description = 'Atlas'; $s.Save()" >nul 2>nul

echo.
echo Setup complete. Start Atlas with Atlas.lnk (or Atlas.cmd).
if not defined ATLAS_NOPAUSE pause
exit /b 0

:fail
echo.
echo Setup FAILED.
if not defined ATLAS_NOPAUSE pause
exit /b 1

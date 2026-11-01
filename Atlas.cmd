@echo off
rem Starts Atlas (local documentation app) without a console window and opens it in the browser.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Atlas is not set up on this computer yet. Run Setup.cmd first.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m oradoc.webapp

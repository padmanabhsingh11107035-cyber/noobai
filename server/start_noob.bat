@echo off
title NOOB Server (console mode) - keep this window open
rem Runs the NOOB server in a visible window (useful to see errors). Normally use "NOOB App.bat".
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" noob_server.py
) else (
    python noob_server.py
)
echo.
echo NOOB server stopped. Read the message above if there was an error.
pause

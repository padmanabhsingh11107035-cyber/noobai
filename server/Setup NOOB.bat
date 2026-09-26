@echo off
title Setup NOOB
rem One-time setup: installs everything NOOB needs INSIDE this folder (nothing goes to other drives).
cd /d "%~dp0"
echo.
echo  Setting up NOOB... this downloads about 300 MB and can take 5-15 minutes.
echo.
where python >nul 2>nul
if errorlevel 1 (
    echo  Python is not installed. Install Python 3.12 or newer from python.org
    echo  and tick "Add Python to PATH", then run this again.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" python -m venv .venv
".venv\Scripts\python.exe" -m pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo  Setup failed. Check the internet connection and run "Setup NOOB.bat" again.
    pause
    exit /b 1
)
echo.
echo  Done! Now double-click "NOOB App.bat" to open NOOB.
echo.
pause

@echo off
rem Opens the NOOB App (starts the NOOB server in the background if needed).
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" noob_launcher.py
    exit /b
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw noob_launcher.py
) else (
    python noob_launcher.py
)

@echo off
title Setup online access for NOOB AI
rem Optional: gives NOOB AI a secure web address (free Cloudflare Tunnel). Needs a domain on your Cloudflare account.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" noob_tunnel.py setup
) else (
    python noob_tunnel.py setup
)
echo.
pause

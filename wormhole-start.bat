@echo off
title ShadowBroker - Wormhole Local Agent

echo ===================================================
echo     W O R M H O L E   --   LOCAL AGENT
echo ===================================================
echo.

:: Check for Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] ERROR: Python is not installed or not in PATH.
    echo [!] Install Python 3.10-3.12 from https://python.org
    echo [!] IMPORTANT: Check "Add to PATH" during install.
    echo.
    pause
    exit /b 1
)

cd backend
if not exist "venv\" (
    echo [*] Creating Python virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [!] ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

call venv\Scripts\activate.bat
echo [*] Installing Python dependencies (first run only)...
pip install -q -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [!] ERROR: pip install failed. See errors above.
    echo.
    pause
    exit /b 1
)

echo.
echo [*] Starting Wormhole Local Agent on 127.0.0.1:8787
echo [*] Press Ctrl+C to stop
echo.

set MESH_ONLY=true
set MESH_RNS_ENABLED=true
python wormhole_server.py

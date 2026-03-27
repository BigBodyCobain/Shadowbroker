@echo off
title ShadowBroker - Global Threat Intercept

echo ===================================================
echo     S H A D O W B R O K E R   --   STARTUP
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

:: Check Python version (warn if 3.13+)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [*] Found Python %PYVER%
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    if %%b GEQ 13 (
        echo [!] WARNING: Python %PYVER% detected. Some packages may fail to build.
        echo [!] Recommended: Python 3.10, 3.11, or 3.12.
        echo.
    )
)

:: Check for Node.js
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] ERROR: Node.js/npm is not installed or not in PATH.
    echo [!] Install Node.js 18+ from https://nodejs.org
    echo.
    pause
    exit /b 1
)

for /f "tokens=1 delims= " %%v in ('node --version 2^>^&1') do echo [*] Found Node.js %%v

:: ── AGGRESSIVE ZOMBIE CLEANUP ──────────────────────────────────────
:: Kill ANY process holding ports 8000 or 3000 (LISTENING, TIME_WAIT,
:: ESTABLISHED — all states). Also kill orphaned uvicorn/ais_proxy
:: processes that might be lingering from a previous crashed session.
echo.
echo [*] Clearing zombie processes...

:: Kill by port — catches processes in ANY state, not just LISTENING
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 "') do (
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000 "') do (
    taskkill /F /PID %%a >nul 2>&1
)

:: Note: wmic zombie-kill removed — hangs on Win11. Port-based kill above
:: already catches any process holding 8000/3000.

:: Brief pause to let OS release the ports
timeout /t 1 /nobreak >nul

:: Verify ports are actually free
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo [!] WARNING: Port 8000 is still occupied! Waiting 3s for OS cleanup...
    timeout /t 3 /nobreak >nul
)
netstat -ano | findstr ":3000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo [!] WARNING: Port 3000 is still occupied! Waiting 3s for OS cleanup...
    timeout /t 3 /nobreak >nul
)

echo [*] Ports clear.
:: ────────────────────────────────────────────────────────────────────

echo.
echo [*] Setting up backend...
cd backend

:: Check if UV is available (preferred, much faster installs)
where uv >nul 2>&1
if %errorlevel% neq 0 goto :use_pip

echo [*] Using UV for Python dependency management.
if not exist "venv\" (
    echo [*] Creating Python virtual environment...
    uv venv
    if %errorlevel% neq 0 (
        echo [!] ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)
call venv\Scripts\activate.bat
echo [*] Installing Python dependencies via UV (fast)...
cd ..
uv sync --frozen --no-dev
if %errorlevel% neq 0 goto :dep_fail
cd backend
goto :deps_ok

:use_pip
echo [*] UV not found, using pip (install UV for faster installs: https://docs.astral.sh/uv/)
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
echo [*] Installing Python dependencies (this may take a minute)...
pip install -q -r requirements.txt
if %errorlevel% neq 0 goto :dep_fail
goto :deps_ok

:dep_fail
echo.
echo [!] ERROR: Python dependency install failed. See errors above.
echo [!] If you see Rust/cargo errors, your Python version may be too new.
echo [!] Recommended: Python 3.10, 3.11, or 3.12.
echo.
pause
exit /b 1

:deps_ok
echo [*] Backend dependencies OK.
if not exist "node_modules\ws" (
    echo [*] Installing backend Node.js dependencies...
    call npm ci --omit=dev --silent
)
echo [*] Backend Node.js dependencies OK.
cd ..

echo.
echo [*] Setting up frontend...
cd frontend
if not exist "node_modules\" (
    echo [*] Installing frontend dependencies...
    call npm install
    if %errorlevel% neq 0 (
        echo [!] ERROR: npm install failed. See errors above.
        pause
        exit /b 1
    )
)
echo [*] Frontend dependencies OK.

echo.
echo ===================================================
echo   Starting services...
echo   Dashboard: http://localhost:3000
echo   Keep this window open! Initial load takes ~10s.
echo   This is the hardened web/local runtime, not the final native shell.
echo   Security work must not come at the cost of unusable map responsiveness.
echo ===================================================
echo   (Press Ctrl+C to stop)
echo.

call npm run dev

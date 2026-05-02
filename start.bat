@echo off
title ShadowBroker - Global Threat Intercept

echo ===================================================
echo     S H A D O W B R O K E R   --   STARTUP
echo ===================================================
echo.

:: Remember where we started (project root)
set "ROOT=%~dp0"
:: Strip trailing backslash
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

:: Check for stale docker-compose.yml from pre-migration clones
findstr /R /C:"build:" "%ROOT%\docker-compose.yml" >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo ================================================================
    echo   [!] WARNING: Your docker-compose.yml is outdated.
    echo.
    echo   It contains 'build:' directives, which means Docker will
    echo   compile from local source instead of pulling pre-built images.
    echo   You will NOT receive updates this way.
    echo.
    echo   If you use Docker, re-clone the repository:
    echo     git clone https://github.com/BigBodyCobain/Shadowbroker.git
    echo     cd Shadowbroker
    echo     docker compose pull
    echo     docker compose up -d
    echo ================================================================
    echo.
)

:: Check for Python and pin the exact interpreter we will use later.
set "PYTHON_EXE="
for /f "usebackq delims=" %%p in (`python -c "import sys; print(sys.executable)" 2^>nul`) do if not defined PYTHON_EXE set "PYTHON_EXE=%%p"
if not defined PYTHON_EXE (
    for /f "usebackq delims=" %%p in (`py -3.11 -c "import sys; print(sys.executable)" 2^>nul`) do if not defined PYTHON_EXE set "PYTHON_EXE=%%p"
)
if not defined PYTHON_EXE (
    for /f "usebackq delims=" %%p in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do if not defined PYTHON_EXE set "PYTHON_EXE=%%p"
)
if not defined PYTHON_EXE (
    echo [!] ERROR: Python is not installed or not in PATH.
    echo [!] Install Python 3.10-3.12 from https://python.org
    echo [!] IMPORTANT: Check "Add to PATH" during install.
    echo.
    pause
    exit /b 1
)
set "BACKEND_BASE_PYTHON=%PYTHON_EXE%"

:: Check Python version (warn if 3.13+)
for /f "tokens=2 delims= " %%v in ('"%PYTHON_EXE%" --version 2^>^&1') do set PYVER=%%v
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
echo.
echo [*] Clearing zombie processes...

:: Kill by port — catches processes in ANY state, not just LISTENING
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 "') do (
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000 "') do (
    taskkill /F /PID %%a >nul 2>&1
)

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
cd /d "%ROOT%\backend"
set "VENV_MARKER=.venv-dir"
set "PINNED_VENV_DIR="
if exist "%VENV_MARKER%" set /p PINNED_VENV_DIR=<"%VENV_MARKER%"

:: Check if UV is available (preferred, much faster installs)
where uv >nul 2>&1
if %errorlevel% neq 0 goto :use_pip

echo [*] Using UV for Python dependency management.
set "PRIMARY_VENV_DIR=venv"
if defined PINNED_VENV_DIR set "PRIMARY_VENV_DIR=%PINNED_VENV_DIR%"
set "REPAIR_VENV_DIR=venv-repair-%RANDOM%%RANDOM%"
set "VENV_DIR=%PRIMARY_VENV_DIR%"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
if exist "%VENV_PY%" (
    "%VENV_PY%" -V >nul 2>&1
    if errorlevel 1 (
        echo [*] Existing backend Python venv is stale. Rebuilding it...
        rmdir /s /q "%PRIMARY_VENV_DIR%" >nul 2>&1
        if exist "%PRIMARY_VENV_DIR%\" (
            set "VENV_DIR=%REPAIR_VENV_DIR%"
            echo [*] Primary venv could not be replaced cleanly. Falling back to %REPAIR_VENV_DIR%...
        )
    )
)
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
if /I not "%VENV_DIR%"=="%PRIMARY_VENV_DIR%" if exist "%VENV_PY%" (
    "%VENV_PY%" -V >nul 2>&1
    if errorlevel 1 rmdir /s /q "%VENV_DIR%" >nul 2>&1
)
set "BACKEND_VENV_DIR=%VENV_DIR%"
if not exist "%VENV_DIR%\" (
    echo [*] Creating Python virtual environment...
    if exist "%VENV_DIR%\" rmdir /s /q "%VENV_DIR%" >nul 2>&1
    uv venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [!] ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)
"%VENV_PY%" -V >nul 2>&1
if errorlevel 1 (
    echo [!] ERROR: Backend virtual environment could not start Python after repair.
    pause
    exit /b 1
)
echo [*] Installing Python dependencies via UV (fast)...
cd /d "%ROOT%"
set "UV_PROJECT_ENVIRONMENT=%ROOT%\backend\%VENV_DIR%"
uv sync --frozen --no-dev
set "UV_PROJECT_ENVIRONMENT="
if %errorlevel% neq 0 goto :dep_fail
cd /d "%ROOT%\backend"
goto :deps_ok

:use_pip
echo [*] UV not found, using pip (install UV for faster installs: https://docs.astral.sh/uv/)
set "PRIMARY_VENV_DIR=venv"
if defined PINNED_VENV_DIR set "PRIMARY_VENV_DIR=%PINNED_VENV_DIR%"
set "REPAIR_VENV_DIR=venv-repair-%RANDOM%%RANDOM%"
set "VENV_DIR=%PRIMARY_VENV_DIR%"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
if exist "%VENV_PY%" (
    "%VENV_PY%" -V >nul 2>&1
    if errorlevel 1 (
        echo [*] Existing backend Python venv is stale. Rebuilding it...
        rmdir /s /q "%PRIMARY_VENV_DIR%" >nul 2>&1
        if exist "%PRIMARY_VENV_DIR%\" (
            set "VENV_DIR=%REPAIR_VENV_DIR%"
            echo [*] Primary venv could not be replaced cleanly. Falling back to %REPAIR_VENV_DIR%...
        )
    )
)
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
if /I not "%VENV_DIR%"=="%PRIMARY_VENV_DIR%" if exist "%VENV_PY%" (
    "%VENV_PY%" -V >nul 2>&1
    if errorlevel 1 rmdir /s /q "%VENV_DIR%" >nul 2>&1
)
set "BACKEND_VENV_DIR=%VENV_DIR%"
if not exist "%VENV_DIR%\" (
    echo [*] Creating Python virtual environment...
    if /I not "%VENV_DIR%"=="%PRIMARY_VENV_DIR%" if exist "%VENV_DIR%\" rmdir /s /q "%VENV_DIR%" >nul 2>&1
    "%PYTHON_EXE%" -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [!] ERROR: Failed to create virtual environment with %PYTHON_EXE%.
        pause
        exit /b 1
    )
)
"%VENV_PY%" -V >nul 2>&1
if errorlevel 1 (
    echo [!] ERROR: Backend virtual environment could not start Python after repair.
    pause
    exit /b 1
)
echo [*] Installing Python dependencies (this may take a minute)...
"%VENV_PY%" -m pip install -q .
if %errorlevel% neq 0 goto :dep_fail
goto :deps_ok

:dep_fail
echo.
echo [!] ERROR: Python dependency install failed. See errors above.
echo [!] If you see Rust/cargo errors, your Python version may be too new.
echo [!] Recommended: Python 3.10, 3.11, or 3.12.
echo.
cd /d "%ROOT%"
pause
exit /b 1

:deps_ok
> "%VENV_MARKER%" echo %VENV_DIR%
echo [*] Backend dependencies OK.
if not exist "node_modules\ws" (
    echo [*] Installing backend Node.js dependencies...
    call npm ci --omit=dev --silent
)
echo [*] Backend Node.js dependencies OK.
cd /d "%ROOT%"

echo.
echo [*] Setting up frontend...
cd /d "%ROOT%\frontend"
set "FRONTEND_DEPS_OK=1"
if not exist "node_modules\" set "FRONTEND_DEPS_OK=0"
if "%FRONTEND_DEPS_OK%"=="1" node -e "require.resolve('next/dist/bin/next',{paths:['.']});require.resolve('lucide-react',{paths:['.']});require.resolve('maplibre-gl',{paths:['.']});require.resolve('@swc/helpers/_/_interop_require_default',{paths:['.']})" >nul 2>&1
if "%FRONTEND_DEPS_OK%"=="1" if errorlevel 1 set "FRONTEND_DEPS_OK=0"
if "%FRONTEND_DEPS_OK%"=="0" (
    echo [*] Frontend install is missing required packages. Repairing with npm ci...
    call npm ci
    if errorlevel 1 (
        echo [!] ERROR: frontend dependency install failed. See errors above.
        cd /d "%ROOT%"
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

echo.
echo ===================================================
echo   ShadowBroker has stopped. Check errors above.
echo ===================================================
pause

@echo off
title ShadowBroker - Mesh Node
color 0B

echo ===================================================
echo     S H A D O W B R O K E R   --   MESH NODE
echo ===================================================
echo.
echo   Lightweight node — syncs the Infonet chain only.
echo   No map, no frontend, no data feeds.
echo   Private hashchain relay: gate messages + offline DM spool.
echo   Close this window to stop the node.
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

:: Check Python version
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [*] Found Python %PYVER%

:: Kill anything on port 8000
echo [*] Clearing port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

cd backend

:: Setup venv
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
echo [*] Installing Python dependencies...
pip install -q -r requirements.txt
if %errorlevel% neq 0 goto :dep_fail
goto :deps_ok

:dep_fail
echo.
echo [!] ERROR: Python dependency install failed.
pause
exit /b 1

:deps_ok
echo [*] Dependencies OK.

:: Install ws package for ais_proxy (needed even in mesh-only mode to avoid import errors)
if not exist "node_modules\ws" (
    echo [*] Installing backend Node.js dependencies...
    where npm >nul 2>&1
    if %errorlevel% equ 0 (
        call npm ci --omit=dev --silent 2>nul
    )
)

:: Auto-enable the node on startup
echo [*] Auto-enabling node participation...
if not exist "data\" mkdir data
echo {"enabled":true,"updated_at":0} > data\node.json

set MESH_ONLY=true
set SHADOWBROKER_MESH_NODE_RUNTIME=true
set MESH_NODE_MODE=participant
set MESH_INFONET_ALLOW_CLEARNET_SYNC=false
set MESH_ARTI_ENABLED=true
set MESH_DM_HASHCHAIN_SPOOL_LIMIT=2
set MESH_DM_HASHCHAIN_SPOOL_TTL_S=3600
if "%MESH_INFONET_FLEET_JOIN%"=="" set MESH_INFONET_FLEET_JOIN=true
if "%MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY%"=="" set MESH_BOOTSTRAP_SIGNER_PUBLIC_KEY=ul1d0kj/ODPIp0OhHzX8eLAVXzJ3CVvzW1vn2IC6q3I=
if "%MESH_SYNC_TIMEOUT_S%"=="" set MESH_SYNC_TIMEOUT_S=45
if "%MESH_RELAY_PUSH_TIMEOUT_S%"=="" set MESH_RELAY_PUSH_TIMEOUT_S=45
if "%MESH_SYNC_MAX_PEERS_PER_CYCLE%"=="" set MESH_SYNC_MAX_PEERS_PER_CYCLE=5
if "%MESH_SWARM_MANIFEST_PULL_INTERVAL_S%"=="" set MESH_SWARM_MANIFEST_PULL_INTERVAL_S=300

echo.
echo ===================================================
echo   Mesh node starting on port 8000
echo   Mode: MESH_ONLY (no data feeds)
if "%MESH_BOOTSTRAP_SEED_PEERS%"=="" (
  echo   Bootstrap: sb-testnet fleet defaults
) else (
  echo   Bootstrap: %MESH_BOOTSTRAP_SEED_PEERS%
)
echo   Swarm: announce + signed manifest pull (fleet join)
echo   Press Ctrl+C to stop
echo ===================================================
echo.

python -m uvicorn main:app --host 0.0.0.0 --port 8000

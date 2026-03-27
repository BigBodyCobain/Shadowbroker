@echo off
setlocal
echo ==========================================
echo  SHADOWBROKER - Kill Wormhole Process
echo ==========================================
echo.

REM 1. Try graceful API shutdown via the backend
echo [*] Attempting graceful shutdown via API...
curl -s -X POST http://127.0.0.1:8000/api/wormhole/leave >nul 2>&1
if %errorlevel%==0 (
    echo [+] API leave request sent.
) else (
    echo [-] Backend not reachable, skipping API call.
)

REM 2. Kill any process listening on port 8787 (Wormhole server)
echo [*] Checking port 8787 for Wormhole process...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8787 " ^| findstr "LISTENING"') do (
    echo [*] Found PID %%a on port 8787, killing...
    taskkill /F /PID %%a >nul 2>&1
    if %errorlevel%==0 (
        echo [+] Killed PID %%a
    ) else (
        echo [-] Could not kill PID %%a
    )
)

REM 3. Kill any python process running wormhole_server.py
echo [*] Searching for wormhole_server.py processes...
for /f "tokens=2" %%a in ('wmic process where "commandline like '%%wormhole_server.py%%'" get processid /value 2^>nul ^| findstr "="') do (
    set PID=%%a
    set PID=!PID:ProcessId=!
    set PID=!PID:~1!
    if defined PID (
        echo [*] Killing wormhole_server.py PID !PID!
        taskkill /F /PID !PID! >nul 2>&1
    )
)

echo.
echo [+] Wormhole cleanup complete.
echo     If processes persist, check Task Manager for python.exe on port 8787.
pause

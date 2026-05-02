@echo off
:: ============================================================
::  WORMHOLE KILLER — Windows
::  Finds and terminates any orphaned wormhole_server.py processes
:: ============================================================

echo.
echo  ========================================
echo   SHADOWBROKER WORMHOLE CLEANUP (Windows)
echo  ========================================
echo.

set FOUND=0

:: Find all python processes running wormhole_server.py
for /f "tokens=2" %%P in ('wmic process where "commandline like '%%wormhole_server.py%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    echo  [KILL] Terminating wormhole process PID: %%P
    taskkill /PID %%P /F >nul 2>&1
    set FOUND=1
)

:: Also check port 8787 (default Wormhole port) for anything lingering
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":8787 " ^| findstr "LISTENING"') do (
    echo  [KILL] Terminating process on port 8787, PID: %%P
    taskkill /PID %%P /F >nul 2>&1
    set FOUND=1
)

if %FOUND%==0 (
    echo  [OK] No orphaned wormhole processes found.
) else (
    echo.
    echo  [DONE] All wormhole processes terminated.
)

echo.
pause

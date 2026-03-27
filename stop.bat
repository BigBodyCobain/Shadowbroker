@echo off
echo ===================================================
echo   S H A D O W B R O K E R   --   SHUTDOWN
echo ===================================================
echo.
echo [*] Killing all ShadowBroker processes...

:: Kill by port
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 "') do (
    echo     Killing PID %%a (port 8000)
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000 "') do (
    echo     Killing PID %%a (port 3000)
    taskkill /F /PID %%a >nul 2>&1
)

:: Kill orphaned uvicorn and ais_proxy
for /f "tokens=2" %%a in ('wmic process where "CommandLine like '%%uvicorn%%main:app%%'" get ProcessId 2^>nul ^| findstr /r "[0-9]"') do (
    echo     Killing uvicorn PID %%a
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=2" %%a in ('wmic process where "CommandLine like '%%ais_proxy%%'" get ProcessId 2^>nul ^| findstr /r "[0-9]"') do (
    echo     Killing ais_proxy PID %%a
    taskkill /F /PID %%a >nul 2>&1
)

timeout /t 1 /nobreak >nul

:: Verify
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo [!] Port 8000 still occupied — force killing...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
        taskkill /F /PID %%a >nul 2>&1
    )
)
netstat -ano | findstr ":3000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo [!] Port 3000 still occupied — force killing...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000 " ^| findstr "LISTENING"') do (
        taskkill /F /PID %%a >nul 2>&1
    )
)

echo.
echo [*] All processes stopped. Ports 8000/3000 should be free.
echo.
pause

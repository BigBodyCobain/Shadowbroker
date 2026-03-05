@echo off
title ShadowBroker - Global Threat Intercept

echo ===================================================
echo     S H A D O W B R O K E R   --   STARTUP
echo ===================================================
echo.
echo Installing backend dependencies if needed...
cd backend
if not exist "venv\" (
    echo Creating Python virtual environment...
    python -m venv venv
)
call venv\Scripts\activate.bat
pip install -r requirements.txt >nul 2>&1
cd ..

echo.
echo Installing frontend dependencies if needed...
cd frontend
if not exist "node_modules\" (
    echo Running npm install...
    call npm install
)

echo.
echo Starting both services...
echo (Press Ctrl+C to stop the dashboard)
echo.

:: Start the dev server which runs both NEXT and API via concurrently
call npm run dev

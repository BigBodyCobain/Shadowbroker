@echo off
REM Compatibility wrapper: canonical script is kill_wormhole.bat
echo [deprecated] killwormhole.bat is deprecated; use kill_wormhole.bat 1>&2
call "%~dp0kill_wormhole.bat" %*
exit /b %ERRORLEVEL%

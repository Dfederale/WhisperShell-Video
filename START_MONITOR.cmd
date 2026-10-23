@echo off
setlocal
cd /d "%~dp0"
if exist "runtime\python\python.exe" (
  "runtime\python\python.exe" "%~dp0monitor.py" %*
  goto :result
)
where py >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0monitor.py" %*
  goto :result
)
where python >nul 2>&1
if not errorlevel 1 (
  python "%~dp0monitor.py" %*
  goto :result
)
echo Python 3.10 or newer is required to launch Monitor.
set "MONITOR_EXIT=1"
goto :end
:result
set "MONITOR_EXIT=%errorlevel%"
:end
if not "%MONITOR_EXIT%"=="0" pause
exit /b %MONITOR_EXIT%

@echo off
setlocal
cd /d "%~dp0"
if exist "runtime\python\python.exe" (
  "runtime\python\python.exe" "%~dp0WhisperShell.py" %*
  goto :done
)
where py >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0WhisperShell.py" %*
  goto :done
)
where python >nul 2>&1
if not errorlevel 1 (
  python "%~dp0WhisperShell.py" %*
  goto :done
)
echo Python 3.10+ was not found. No runtime is bundled in this foundation package.
set "EXIT_CODE=1"
goto :end
:done
set "EXIT_CODE=%errorlevel%"
:end
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%

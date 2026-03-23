@echo off
setlocal EnableExtensions

set "REPO_ROOT=%~dp0"

pushd "%REPO_ROOT%"

echo [INFO] Launching local Windows startup flow...
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%scripts\start-windows.ps1"
if errorlevel 1 (
  goto :fail
)

popd
endlocal
exit /b 0

:fail
echo.
pause
popd
endlocal
exit /b 1

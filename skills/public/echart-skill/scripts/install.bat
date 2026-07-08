@echo off
REM =============================================================================
REM echart-skill Installer (Windows)
REM =============================================================================
REM Installs echart-skill Python dependencies. Online PyPI installation is the
REM default; local wheels are only for separately distributed offline archives.
REM
REM Usage:
REM   scripts\install.bat                 full install (core + optional)
REM   scripts\install.bat --core-only     core dependencies only
REM   scripts\install.bat --offline       force separately supplied wheels\
REM =============================================================================

setlocal enabledelayedexpansion

REM --- resolve script/root directories (handle spaces in paths) ---------------
set "SCRIPT_DIR=%~dp0"
REM Remove trailing backslash for safety
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
pushd "%SCRIPT_DIR%\.."
set "ROOT_DIR=%CD%"
popd
set "WHEELS_DIR=%ROOT_DIR%\wheels"
set "CORE_REQ=%ROOT_DIR%\requirements-core.txt"
set "FULL_REQ=%ROOT_DIR%\requirements.txt"

set CORE_ONLY=0
set FORCE_OFFLINE=0

:parse_args
if "%~1"=="" goto :check_python
if "%~1"=="--core-only" (
    set CORE_ONLY=1
    shift
    goto :parse_args
)
if "%~1"=="--offline" (
    set FORCE_OFFLINE=1
    shift
    goto :parse_args
)
if "%~1"=="--help" goto :show_help
if "%~1"=="-h" goto :show_help
echo [ERROR] Unknown option: %~1
exit /b 1

:show_help
echo Usage: scripts\install.bat [--core-only] [--offline]
echo.
echo Options:
echo   --core-only   Install only core dependencies (duckdb, pandas, ...)
echo   --offline     Force offline mode (requires wheels\ directory)
exit /b 0

:check_python
echo.
echo ================================================================
echo           echart-skill  Dependency Installer  (Windows^)
echo ================================================================
echo.

REM --- find Python (try py launcher first, then python, python3) --------------
set "PYTHON="

REM Helper: test if a candidate is Python 3.10+
for %%c in (py python python3) do (
    where %%c >nul 2>&1
    if !errorlevel!==0 (
        %%c -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
        if !errorlevel!==0 (
            set "PYTHON=%%c"
            goto :found_python
        )
    )
)

REM Also try common install locations
for %%d in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%PROGRAMFILES%\Python312\python.exe"
    "%PROGRAMFILES%\Python311\python.exe"
    "%PROGRAMFILES%\Python310\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
) do (
    if exist %%d (
        %%d -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
        if !errorlevel!==0 (
            set "PYTHON=%%~d"
            goto :found_python
        )
    )
)

:found_python
if "%PYTHON%"=="" (
    echo [ERROR] Python 3.10+ is required but was not found.
    echo.
    echo   Install it from https://www.python.org/downloads/
    echo   Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM Get Python version string for display
for /f "tokens=*" %%v in ('"%PYTHON%" --version 2^>^&1') do set "PY_VER=%%v"
echo [INFO] Using %PY_VER% ^(%PYTHON%^)

REM --- detect install mode ---------------------------------------------------
set OFFLINE_MODE=0

if %FORCE_OFFLINE%==1 (
    set OFFLINE_MODE=1
) else (
    if exist "%WHEELS_DIR%\*.whl" (
        set OFFLINE_MODE=1
    )
)

if !OFFLINE_MODE!==1 (
    echo [ OK ] Offline mode - installing from pre-downloaded wheels
) else (
    echo [INFO] Online mode - installing from PyPI
    echo [WARN] Offline wheels are not bundled in the skill package.
)

set "REQ_FILE=%FULL_REQ%"
if %CORE_ONLY%==1 (
    set "REQ_FILE=%CORE_REQ%"
    echo [INFO] Installing CORE dependencies only
) else (
    echo [INFO] Installing FULL dependencies (core + optional)
)

REM --- install ---------------------------------------------------------------
echo.
echo [INFO] Installing dependencies ...
echo.

if !OFFLINE_MODE!==1 (
    "%PYTHON%" -m pip install --no-index --find-links="%WHEELS_DIR%" -r "%REQ_FILE%"
    if !errorlevel! neq 0 (
        echo.
        echo [ERROR] Offline install failed.
        echo   Make sure the wheels\ directory contains the required .whl files.
        echo   Try online mode: scripts\install.bat
        echo   Or re-download wheels: scripts\download_wheels.sh
        pause
        exit /b 1
    )
) else (
    "%PYTHON%" -m pip install -r "%REQ_FILE%"
    if !errorlevel! neq 0 (
        echo.
        echo [ERROR] pip install failed. Check your network connection.
        pause
        exit /b 1
    )
)

echo [ OK ] Dependencies installed successfully.

REM --- summary ---------------------------------------------------------------
echo.
echo ------------------------------------------------------------
echo   echart-skill installation complete ^^
echo ------------------------------------------------------------
echo.

REM Show key package versions
"%PYTHON%" -c "import importlib.metadata as m; [print(f'  {p:15s} {m.version(p)}') for p in ['duckdb','pandas','openpyxl','pydantic','structlog']]" 2>nul

echo.
echo   Run your agent and type /help to get started!
echo.
exit /b 0

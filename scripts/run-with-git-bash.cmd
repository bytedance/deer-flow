@echo off
setlocal

set "bash_exe="

for /f "delims=" %%I in ('where git 2^>NUL') do (
    if exist "%%~dpI..\bin\bash.exe" (
        set "bash_exe=%%~dpI..\bin\bash.exe"
        goto :found_bash
    )
)

echo Could not locate Git for Windows Bash ("..\bin\bash.exe" relative to git on PATH). Ensure Git for Windows is installed and that git and bash.exe are available on PATH.
exit /b 1

:found_bash
echo Detected Windows - using Git Bash...
"%bash_exe%" %*
set "cmd_rc=%ERRORLEVEL%"
exit /b %cmd_rc%

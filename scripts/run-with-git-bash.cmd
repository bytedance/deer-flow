@echo off
setlocal

set "bash_exe="

for /f "delims=" %%I in ('where git 2^>NUL') do (
    if exist "%%~dpI..\bin\bash.exe" (
        set "bash_exe=%%~dpI..\bin\bash.exe"
        goto :found_bash
    )
)

echo Git Bash not found next to git.exe. Please install Git for Windows or make bash.exe available through git.exe.
exit /b 1

:found_bash
echo Detected Windows - using Git Bash...
"%bash_exe%" %*
set "cmd_rc=%ERRORLEVEL%"
exit /b %cmd_rc%

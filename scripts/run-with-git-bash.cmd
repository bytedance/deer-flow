@echo off
setlocal EnableDelayedExpansion

for /f "delims=" %%I in ('where git 2^>NUL') do (
    if exist "%%~dpI..\bin\bash.exe" (
        echo Detected Windows - using Git Bash...
        "%%~dpI..\bin\bash.exe" %*
        set "cmd_rc=!ERRORLEVEL!"
        exit /b !cmd_rc!
    )
)

echo Git Bash not found next to git.exe. Please install Git for Windows or make bash.exe available through git.exe.
exit /b 1

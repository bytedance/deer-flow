@echo off
SETLOCAL ENABLEEXTENSIONS

REM Check if argument is dev mode
SET MODE=%1
IF "%MODE%"=="--dev" GOTO DEV
IF "%MODE%"=="-d" GOTO DEV
IF "%MODE%"=="dev" GOTO DEV
IF "%MODE%"=="development" GOTO DEV

:PROD
echo Starting DeerFlow in [PRODUCTION] mode...
start uv run server.py
cd web
start pnpm start
REM Wait for user to close
GOTO END

:DEV
echo Starting DeerFlow in [DEVELOPMENT] mode...
start uv run server.py --reload
cd web
start pnpm dev
REM Wait for user to close
pause

:END
ENDLOCAL

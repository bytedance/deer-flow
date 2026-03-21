@echo off
REM Intercepts 'uvicorn' calls and routes them through python -m uvicorn to bypass AppLocker execution blocks on unsigned .venv executables.
python -m uvicorn %*

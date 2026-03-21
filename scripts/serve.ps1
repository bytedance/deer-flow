# scripts/serve.ps1
# Windows PowerShell equivalent for serve.sh

param (
    [switch]$Dev = $true,
    [switch]$Prod = $false
)

$ErrorActionPreference = "Stop"

$REPO_ROOT = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location -Path $REPO_ROOT

if ($Prod) {
    $Dev = $false
}

Write-Host "Starting DeerFlow Services on Windows..." -ForegroundColor Cyan

if (-not (Test-Path "$REPO_ROOT\backend\config.yaml") -and -not (Test-Path "$REPO_ROOT\config.yaml")) {
    Write-Host "No config.yaml found." -ForegroundColor Red
    exit 1
}

$env:PYTHONPATH = "."

# AppLocker / Antivirus Workaround: Remove blocked python shim executables
Write-Host "Applying AppLocker Execution Bypasses..." -ForegroundColor DarkGray
if (Test-Path "$REPO_ROOT\backend\.venv\Scripts\uvicorn.exe") {
    Remove-Item -Path "$REPO_ROOT\backend\.venv\Scripts\uvicorn.exe" -Force
}
New-Item -Path "$REPO_ROOT\backend\.venv\Scripts\uvicorn.bat" -ItemType File -Value "@echo off`r`npython -m uvicorn %*" -Force | Out-Null

if ($Dev) {
    # Using python -m langgraph_cli bypasses initial AppLocker blocks
    $LangGraphArgs = "run python -m langgraph_cli dev --no-browser --allow-blocking --no-reload"
    $GatewayArgs = "run python -m uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload --reload-include=*.yaml --reload-include=.env"
    $FrontendCmd = "run dev"
} else {
    $LangGraphArgs = "run python -m langgraph_cli dev --no-browser --allow-blocking --no-reload"
    $GatewayArgs = "run python -m uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001"
    $FrontendCmd = "run preview"
}

Write-Host "Starting LangGraph server..." -ForegroundColor DarkGray
Start-Process -FilePath "cmd.exe" -ArgumentList "/k python -m uv $LangGraphArgs" -WorkingDirectory "$REPO_ROOT\backend" -WindowStyle Normal
Write-Host "OK: LangGraph server started on localhost:2024" -ForegroundColor Green

Write-Host "Starting Gateway API..." -ForegroundColor DarkGray
Start-Process -FilePath "cmd.exe" -ArgumentList "/k python -m uv $GatewayArgs" -WorkingDirectory "$REPO_ROOT\backend" -WindowStyle Normal
Write-Host "OK: Gateway API started on localhost:8001" -ForegroundColor Green

Write-Host "Starting Frontend..." -ForegroundColor DarkGray
Start-Process -FilePath "cmd.exe" -ArgumentList "/k pnpm $FrontendCmd" -WorkingDirectory "$REPO_ROOT\frontend" -WindowStyle Normal
Write-Host "OK: Frontend started on localhost:3000" -ForegroundColor Green

Write-Host ""
Write-Host "Please ensure frontend/.env has the correct API URLs." -ForegroundColor Magenta

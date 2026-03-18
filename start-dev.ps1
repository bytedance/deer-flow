$ErrorActionPreference = "Stop"
$RootPath = Get-Location

Write-Host "🦌 Starting DeerFlow Local Development (Option B)" -ForegroundColor Green
Write-Host "Opening 4 separate terminal windows..." -ForegroundColor Yellow
Write-Host "----------------------------------------------------"

# 1. Nginx Reverse Proxy (2026)
$nginxCmd = "`$host.UI.RawUI.WindowTitle = 'DeerFlow - Nginx (2026)'; cd '$RootPath'; Write-Host 'Starting Nginx...' -ForegroundColor Cyan; nginx -c '$RootPath\docker\nginx\nginx.local.conf' -p '$RootPath'"
Start-Process powershell -ArgumentList "-NoExit -Command `"$nginxCmd`""
Write-Host "✅ Nginx starting..."

# 2. LangGraph Agent Server (2024)
$langGraphCmd = "`$host.UI.RawUI.WindowTitle = 'DeerFlow - LangGraph (2024)'; cd '$RootPath\backend'; Write-Host 'Starting LangGraph...' -ForegroundColor Cyan; uv run langgraph dev --no-browser --allow-blocking --no-reload"
Start-Process powershell -ArgumentList "-NoExit -Command `"$langGraphCmd`""
Write-Host "✅ LangGraph Server starting..."

# 3. Gateway API (8001)
$gatewayCmd = "`$host.UI.RawUI.WindowTitle = 'DeerFlow - Gateway (8001)'; cd '$RootPath\backend'; Write-Host 'Starting Gateway API...' -ForegroundColor Cyan; `$env:PYTHONPATH = '.'; uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload"
Start-Process powershell -ArgumentList "-NoExit -Command `"$gatewayCmd`""
Write-Host "✅ Gateway API starting..."

# 4. Frontend (3000)
$frontendCmd = "`$host.UI.RawUI.WindowTitle = 'DeerFlow - Frontend (3000)'; cd '$RootPath\frontend'; Write-Host 'Starting Frontend...' -ForegroundColor Cyan; pnpm dev"
Start-Process powershell -ArgumentList "-NoExit -Command `"$frontendCmd`""
Write-Host "✅ Frontend starting..."

Write-Host "----------------------------------------------------"
Write-Host "All 4 services should now be running in separate windows." -ForegroundColor Green
Write-Host "The windows are cleanly titled so you can easily Alt-Tab between them." -ForegroundColor Yellow
Write-Host ""
Write-Host "👉 App URL: http://localhost:2026" -ForegroundColor Cyan
Write-Host ""
Write-Host "To stop everything later, just close the 4 popup terminal windows."

# ============================================================
# DeerFlow - Launcher
# Arranca Docker Desktop, LM Studio, los contenedores y abre
# el navegador en http://localhost:2026
# ============================================================

$PROJECT_ROOT  = "D:\Escritorio\Cursor\DeerFlow 2.0\deer-flow"
$DOCKER_DIR    = "$PROJECT_ROOT\docker"
$COMPOSE_FILE  = "$DOCKER_DIR\docker-compose-dev.yaml"
$COMPOSE_PROJ  = "deer-flow-dev"
$DOCKER_EXE    = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$LMSTUDIO_EXE  = "C:\Program Files\LM Studio\LM Studio.exe"
$APP_URL       = "http://localhost:2026"

function Write-Step($msg) {
    Write-Host ""
    Write-Host ">> $msg" -ForegroundColor Cyan
}

function Write-OK($msg) {
    Write-Host "   [OK] $msg" -ForegroundColor Green
}

function Write-Info($msg) {
    Write-Host "   $msg" -ForegroundColor Gray
}

# ── 1. Docker Desktop ─────────────────────────────────────
Write-Step "Verificando Docker Desktop..."

$dockerRunning = docker info 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Info "Docker Desktop no está activo. Iniciando..."
    Start-Process $DOCKER_EXE
    Write-Info "Esperando a que el daemon de Docker esté listo (hasta 60s)..."
    $timeout = 60
    $elapsed = 0
    do {
        Start-Sleep -Seconds 3
        $elapsed += 3
        docker info 2>$null | Out-Null
    } while ($LASTEXITCODE -ne 0 -and $elapsed -lt $timeout)

    if ($LASTEXITCODE -ne 0) {
        Write-Host "   [ERROR] Docker no respondio en $timeout segundos." -ForegroundColor Red
        Read-Host "Presiona Enter para salir"
        exit 1
    }
}
Write-OK "Docker Desktop listo."

# ── 2. Contenedores DeerFlow ──────────────────────────────
Write-Step "Verificando contenedores DeerFlow..."

$running = docker ps --filter "name=deer-flow-nginx" --format "{{.Names}}" 2>$null
if ($running -match "deer-flow-nginx") {
    Write-OK "Contenedores ya en ejecucion."
} else {
    Write-Info "Iniciando contenedores (docker compose up)..."
    Push-Location $DOCKER_DIR
    docker compose -p $COMPOSE_PROJ -f $COMPOSE_FILE up --build -d --remove-orphans frontend gateway langgraph nginx
    Pop-Location
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   [ERROR] Fallo al iniciar los contenedores." -ForegroundColor Red
        Read-Host "Presiona Enter para salir"
        exit 1
    }
    Write-OK "Contenedores iniciados."
}

# ── 3. LM Studio ──────────────────────────────────────────
Write-Step "Verificando LM Studio..."

$lmProc = Get-Process "LM Studio" -ErrorAction SilentlyContinue
if ($lmProc) {
    Write-OK "LM Studio ya esta en ejecucion."
} else {
    Write-Info "Abriendo LM Studio..."
    Start-Process $LMSTUDIO_EXE
    Write-OK "LM Studio iniciado."
}

# ── 4. Esperar puerto 2026 ────────────────────────────────
Write-Step "Esperando que DeerFlow responda en $APP_URL ..."

$timeout = 60
$elapsed = 0
$ready   = $false
do {
    try {
        $r = Invoke-WebRequest -Uri $APP_URL -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        $ready = $true
    } catch {
        Start-Sleep -Seconds 2
        $elapsed += 2
    }
} while (-not $ready -and $elapsed -lt $timeout)

if (-not $ready) {
    Write-Host "   [AVISO] La app no respondio en $timeout s - abriendo el navegador de todos modos." -ForegroundColor Yellow
}
Write-OK "DeerFlow listo."

# ── 5. Abrir navegador ────────────────────────────────────
Write-Step "Abriendo $APP_URL en el navegador..."
Start-Process $APP_URL
Write-OK "Listo. DeerFlow abierto en el navegador."
Write-Host ""

$ErrorActionPreference = 'Stop'

function Resolve-RepoRoot {
  $scriptDir = $PSScriptRoot
  if (-not $scriptDir) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
  }
  $root = Resolve-Path -LiteralPath (Join-Path $scriptDir '..')
  return $root.Path
}

function Write-Info {
  param([Parameter(Mandatory = $true)][string]$Message)
  Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Warn {
  param([Parameter(Mandatory = $true)][string]$Message)
  Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Err {
  param([Parameter(Mandatory = $true)][string]$Message)
  Write-Host "[ERR ] $Message" -ForegroundColor Red
}

function Test-CommandExists {
  param([Parameter(Mandatory = $true)][string]$Name)
  return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-GitAvailable {
  if (-not (Test-CommandExists 'git')) { return $false }
  try {
    & git --version | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Get-GitProbeValueOrThrow {
  param(
    [Parameter(Mandatory = $true)][string[]]$GitArgs,
    [Parameter(Mandatory = $true)][string]$Label,
    [switch]$AllowEmpty
  )

  $result = & git @GitArgs 2>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Err "Unable to determine git metadata for auto-update: $Label."
    Write-Host ''
    Write-Host 'Next steps:'
    Write-Host '  1) cd to repo root'
    Write-Host '  2) git status'
    Write-Host '  3) Verify your remote and branch setup'
    throw (New-StartupAbortException "Auto-update aborted because git metadata could not be determined: $Label.")
  }

  if (-not $result) {
    if ($AllowEmpty) {
      return $null
    }

    Write-Err "Git metadata for auto-update was empty: $Label."
    Write-Host ''
    Write-Host 'Next steps:'
    Write-Host '  1) cd to repo root'
    Write-Host '  2) git status'
    Write-Host '  3) Verify your remote and branch setup'
    throw (New-StartupAbortException "Auto-update aborted because git metadata was empty: $Label.")
  }

  return ($result | Select-Object -First 1).Trim()
}

function Get-RemoteOriginUrl {
  return Get-GitProbeValueOrThrow -GitArgs @('config', '--get', 'remote.origin.url') -Label 'origin URL'
}

function Is-OfficialOriginUrl {
  param([AllowNull()][string]$Url)
  if ($null -eq $Url) { return $false }
  $u = $Url.Trim()
  if ([string]::IsNullOrWhiteSpace($u)) { return $false }

  $normalized = $u.TrimEnd('/')
  if ($normalized.EndsWith('.git')) {
    $normalized = $normalized.Substring(0, $normalized.Length - 4)
  }

  $official = @(
    'https://github.com/bytedance/deer-flow',
    'git@github.com:bytedance/deer-flow',
    'ssh://git@github.com/bytedance/deer-flow'
  )

  return $official -contains $normalized
}

function Get-CurrentBranch {
  return Get-GitProbeValueOrThrow -GitArgs @('rev-parse', '--abbrev-ref', 'HEAD') -Label 'current branch'
}

function Get-UpstreamRef {
  return Get-GitProbeValueOrThrow -GitArgs @('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}') -Label 'upstream branch'
}

function Test-PortFree {
  param([Parameter(Mandatory = $true)][int]$Port)

  try {
    $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    foreach ($listener in $listeners) {
      if ($listener.Port -eq $Port) {
        return $false
      }
    }
    return $true
  } catch {
    return $false
  }
}

function Get-PortOccupantInfo {
  param([Parameter(Mandatory = $true)][int]$Port)

  try {
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
    if (-not $connection) {
      return $null
    }

    $process = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
    return [pscustomobject]@{
      Port = $Port
      ProcessId = $connection.OwningProcess
      ProcessName = $(if ($process) { $process.ProcessName } else { 'unknown' })
    }
  } catch {
    return $null
  }
}

function Wait-PortTcp {
  param(
    [Parameter(Mandatory = $true)][int]$Port,
    [int]$TimeoutSec = 120,
    [int]$PollMs = 500
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    $client = $null
    $waitHandle = $null
    try {
      $client = New-Object System.Net.Sockets.TcpClient
      $iar = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
      $waitHandle = $iar.AsyncWaitHandle
      if ($waitHandle.WaitOne(500, $false)) {
        $client.EndConnect($iar)
        return $true
      }
    } catch {
    } finally {
      if ($waitHandle) {
        try { $waitHandle.Close() } catch { }
      }
      if ($client) {
        try { $client.Close() } catch { }
      }
    }
    Start-Sleep -Milliseconds $PollMs
  }
  return $false
}

function Wait-HttpOk {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [int]$TimeoutSec = 120,
    [int]$PollMs = 500
  )

  $invokeWebRequestParams = @{
    Uri = $Url
    Method = 'GET'
    TimeoutSec = 5
  }
  $invokeWebRequestCommand = Get-Command 'Invoke-WebRequest' -ErrorAction SilentlyContinue
  if ($invokeWebRequestCommand -and $invokeWebRequestCommand.Parameters.ContainsKey('UseBasicParsing')) {
    $invokeWebRequestParams.UseBasicParsing = $true
  }

  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $resp = Invoke-WebRequest @invokeWebRequestParams
      if ($resp.StatusCode -eq 200) {
        return $true
      }
    } catch {
    }
    Start-Sleep -Milliseconds $PollMs
  }
  return $false
}

function Ensure-FileFromExample {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$ExamplePath,
    [switch]$AllowEmptyJson
  )

  if (Test-Path -LiteralPath $Path) { return }

  $parent = Split-Path -Parent $Path
  if ($parent -and -not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
  }

  if (Test-Path -LiteralPath $ExamplePath) {
    Copy-Item -LiteralPath $ExamplePath -Destination $Path -Force
    return
  }

  if ($AllowEmptyJson) {
    Set-Content -LiteralPath $Path -Value '{}' -Encoding ASCII
    return
  }

  throw "Missing template file: $ExamplePath"
}

function Get-MissingConfigEnvironmentVariables {
  param([Parameter(Mandatory = $true)][string]$ConfigPath)

  if (-not (Test-Path -LiteralPath $ConfigPath)) {
    return @()
  }

  $content = Get-Content -LiteralPath $ConfigPath -Raw
  $matches = [System.Text.RegularExpressions.Regex]::Matches($content, '\$([A-Z_][A-Z0-9_]*)')
  if ($matches.Count -eq 0) {
    return @()
  }

  $names = @()
  foreach ($match in $matches) {
    $name = $match.Groups[1].Value
    if ($names -notcontains $name) {
      $names += $name
    }
  }

  $missing = @()
  foreach ($name in $names) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
      $missing += $name
    }
  }

  return $missing
}

function Test-BackendDepsPresent {
  param([Parameter(Mandatory = $true)][string]$RepoRoot)
  return Test-Path -LiteralPath (Join-Path $RepoRoot 'backend\.venv')
}

function Test-FrontendDepsPresent {
  param([Parameter(Mandatory = $true)][string]$RepoRoot)
  return Test-Path -LiteralPath (Join-Path $RepoRoot 'frontend\node_modules')
}

function Write-MissingCommandGuidance {
  param([Parameter(Mandatory = $true)][string[]]$Missing)

  if ($Missing.Count -eq 0) {
    return
  }

  Write-Host 'Install the missing tools, then run this script again.'

  foreach ($cmd in $Missing) {
    switch ($cmd) {
      'node' {
        Write-Host 'Install Node.js 22+ from https://nodejs.org/'
      }
      'pnpm' {
        Write-Host 'npm install -g pnpm'
      }
      'uv' {
        Write-Host 'Install uv from https://docs.astral.sh/uv/getting-started/installation/'
      }
    }
  }
}

function New-StartupAbortException {
  param([Parameter(Mandatory = $true)][string]$Message)

  $exception = New-Object System.Exception($Message)
  $exception.Data['DeerFlowAlreadyReported'] = $true
  return $exception
}

function Invoke-ConservativeAutoUpdate {
  param([Parameter(Mandatory = $true)][string]$RepoRoot)

  $gitDir = Join-Path $RepoRoot '.git'
  if (-not (Test-Path -LiteralPath $gitDir)) {
    Write-Warn "No .git found (file or directory); skipping auto-update."
    return
  }

  if (-not (Test-GitAvailable)) {
    Write-Warn "git is not available; skipping auto-update."
    return
  }

  Push-Location -LiteralPath $RepoRoot
  try {
    $origin = Get-RemoteOriginUrl
    if (-not (Is-OfficialOriginUrl $origin)) {
      Write-Warn "Repo origin is not an official DeerFlow URL; skipping auto-update. (origin: $origin)"
      return
    }

    $branch = Get-CurrentBranch
    $upstream = Get-UpstreamRef
    if ($branch -ne 'main' -or $upstream -ne 'origin/main') {
      Write-Warn "Not on official main tracking origin/main; skipping auto-update. (branch: $branch, upstream: $upstream)"
      return
    }

    Write-Info 'Checking for upstream updates (origin/main)...'
    & git fetch origin main | Out-Null
    if ($LASTEXITCODE -ne 0) {
      Write-Err 'git fetch failed. Stopping startup to avoid running stale code.'
      Write-Host ''
      Write-Host 'Next steps:'
      Write-Host '  1) cd to repo root'
      Write-Host '  2) git fetch origin main'
      Write-Host '  3) If that fails, verify network access and your "origin" remote'
      throw (New-StartupAbortException 'Auto-update aborted due to git fetch failure.')
    }

    $counts = (& git rev-list --left-right --count HEAD...origin/main 2>$null)
    if (-not $counts) {
      Write-Warn 'Unable to determine ahead/behind; skipping auto-update.'
      return
    }

    $parts = ($counts | Select-Object -First 1).Trim().Split(@(' ', "`t"), [System.StringSplitOptions]::RemoveEmptyEntries)
    if ($parts.Count -lt 2) {
      Write-Warn 'Unexpected ahead/behind output; skipping auto-update.'
      return
    }

    $ahead = [int]$parts[0]
    $behind = [int]$parts[1]

    if ($ahead -gt 0) {
      Write-Warn "Local branch is ahead/diverged from origin/main (ahead: $ahead, behind: $behind); skipping auto-update."
      return
    }

    if ($behind -le 0) {
      Write-Info 'Already up to date.'
      return
    }

    Write-Err 'Official main is newer than the current checkout.'
    Write-Host ''
    Write-Host 'Next steps:'
    Write-Host '  1) git stash or commit your local work if needed'
    Write-Host '  2) git pull --ff-only origin main'
    Write-Host '  3) Re-run start-windows.bat'
    throw (New-StartupAbortException 'Startup aborted because the current branch is behind origin/main.')
  } finally {
    Pop-Location
  }
}

function Start-ServiceWindow {
  param(
    [Parameter(Mandatory = $true)][string]$Title,
    [Parameter(Mandatory = $true)][string]$WorkingDir,
    [Parameter(Mandatory = $true)][string]$Command
  )

  $escapedTitle = $Title.Replace("'", "''")
  $escapedDir = $WorkingDir.Replace("'", "''")

  $inner = @(
    "`$ErrorActionPreference = 'Stop'",
    "`$host.UI.RawUI.WindowTitle = '$escapedTitle'",
    "Set-Location -LiteralPath '$escapedDir'",
    'try {',
    $Command,
    "if (`$LASTEXITCODE -ne 0) { Write-Host ''; Write-Host '[ERR ] Process exited with a non-zero code.' -ForegroundColor Red; try { Read-Host 'Press Enter to close this window' | Out-Null } catch { } }",
    '} catch {',
    "Write-Host ''; Write-Host ('[ERR ] ' + `$_.Exception.Message) -ForegroundColor Red; try { Read-Host 'Press Enter to close this window' | Out-Null } catch { }",
    '}'
  ) -join '; '

  $args = @(
    '-NoProfile',
    '-ExecutionPolicy',
    'Bypass',
    '-NoExit',
    '-Command',
    "& { $inner }"
  )
  Start-Process -FilePath 'powershell' -ArgumentList $args | Out-Null
}

function Invoke-DeerFlowWindowsStart {
  $repoRoot = Resolve-RepoRoot
  Push-Location -LiteralPath $repoRoot
  try {
    Write-Info "Repo root: $repoRoot"

    Invoke-ConservativeAutoUpdate -RepoRoot $repoRoot

    Write-Info 'Bootstrapping config files (copy examples if missing)...'
    Ensure-FileFromExample -Path (Join-Path $repoRoot 'config.yaml') -ExamplePath (Join-Path $repoRoot 'config.example.yaml')
    Ensure-FileFromExample -Path (Join-Path $repoRoot '.env') -ExamplePath (Join-Path $repoRoot '.env.example')
    Ensure-FileFromExample -Path (Join-Path $repoRoot 'frontend\.env') -ExamplePath (Join-Path $repoRoot 'frontend\.env.example')
    Ensure-FileFromExample -Path (Join-Path $repoRoot 'extensions_config.json') -ExamplePath (Join-Path $repoRoot 'extensions_config.example.json') -AllowEmptyJson

    $missingConfigEnv = Get-MissingConfigEnvironmentVariables -ConfigPath (Join-Path $repoRoot 'config.yaml')
    if ($missingConfigEnv.Count -gt 0) {
      Write-Err "Missing environment variables referenced by config.yaml: $($missingConfigEnv -join ', ')"
      Write-Err 'Set the missing environment variables and run start-windows.bat again.'
      throw (New-StartupAbortException 'Startup aborted because config.yaml references missing environment variables.')
    }

    Write-Info 'Checking required commands...'
    $missing = @()
    foreach ($cmd in @('node', 'pnpm', 'uv')) {
      if (-not (Test-CommandExists $cmd)) {
        $missing += $cmd
      }
    }
    if ($missing.Count -gt 0) {
      Write-Err "Missing required commands: $($missing -join ', ')"
      Write-MissingCommandGuidance -Missing $missing
      throw (New-StartupAbortException 'Startup aborted because required commands are missing.')
    }

    if (-not (Test-BackendDepsPresent -RepoRoot $repoRoot)) {
      Write-Err 'Backend dependencies not found: backend/.venv is missing.'
      Write-Host 'cd backend'
      Write-Host 'uv sync'
      throw (New-StartupAbortException 'Startup aborted because backend dependencies are missing.')
    }

    if (-not (Test-FrontendDepsPresent -RepoRoot $repoRoot)) {
      Write-Err 'Frontend dependencies not found: frontend/node_modules is missing.'
      Write-Host 'cd frontend'
      Write-Host 'pnpm install'
      throw (New-StartupAbortException 'Startup aborted because frontend dependencies are missing.')
    }

    Write-Info 'Checking ports are free (no auto-kill)...'
    $ports = @(2024, 8001, 2026)
    $busy = @()
    foreach ($p in $ports) {
      if (-not (Test-PortFree -Port $p)) {
        $busy += $p
      }
    }
    if ($busy.Count -gt 0) {
      Write-Err "Port(s) already in use: $($busy -join ', ')"
      foreach ($busyPort in $busy) {
        $occupant = Get-PortOccupantInfo -Port $busyPort
        if ($occupant) {
          Write-Err "Port $($occupant.Port) is owned by PID $($occupant.ProcessId) ($($occupant.ProcessName))"
        }
      }
      Write-Err 'Stop the conflicting service(s) and try again.'
      throw (New-StartupAbortException 'Startup aborted because required ports are busy.')
    }

    Write-Info 'Starting services in separate PowerShell windows...'
    $backendDir = Join-Path $repoRoot 'backend'
    $frontendDir = Join-Path $repoRoot 'frontend'

    Start-ServiceWindow -Title 'DeerFlow LangGraph' -WorkingDir $backendDir -Command 'uv run langgraph dev --no-browser --allow-blocking --host 0.0.0.0 --port 2024'
    Start-ServiceWindow -Title 'DeerFlow Gateway' -WorkingDir $backendDir -Command '$env:PYTHONPATH=''.''; uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload'
    Start-ServiceWindow -Title 'DeerFlow Frontend' -WorkingDir $frontendDir -Command 'pnpm run dev -- --port 2026'

    Write-Info 'Waiting for readiness...'
    if (-not (Wait-PortTcp -Port 2024 -TimeoutSec 180)) {
      Write-Err 'LangGraph port 2024 did not become ready in time.'
      throw (New-StartupAbortException 'Startup aborted because LangGraph did not become ready in time.')
    }
    if (-not (Wait-HttpOk -Url 'http://localhost:8001/health' -TimeoutSec 180)) {
      Write-Err 'Gateway health check did not return 200 in time: http://localhost:8001/health'
      throw (New-StartupAbortException 'Startup aborted because the Gateway health check did not become ready in time.')
    }
    if (-not (Wait-PortTcp -Port 2026 -TimeoutSec 300)) {
      Write-Err 'Frontend port 2026 did not become ready in time.'
      throw (New-StartupAbortException 'Startup aborted because the Frontend did not become ready in time.')
    }

    Write-Info 'Opening browser: http://localhost:2026'
    Start-Process 'http://localhost:2026' | Out-Null
    Write-Info 'Done.'
  } finally {
    Pop-Location
  }
}

function Invoke-StartupScriptEntry {
  try {
    Invoke-DeerFlowWindowsStart
    return 0
  } catch {
    if (-not $_.Exception.Data['DeerFlowAlreadyReported']) {
      Write-Err $_.Exception.Message
    }
    return 1
  }
}

if ($MyInvocation.InvocationName -ne '.') {
  exit (Invoke-StartupScriptEntry)
}

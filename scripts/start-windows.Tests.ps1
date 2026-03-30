$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $here 'start-windows.ps1'

function Set-HostCapture {
  $script:HostMessages = @()
  function global:Write-Host {
    [CmdletBinding()]
    param(
      [Parameter(Position = 0, ValueFromRemainingArguments = $true)][object[]]$Object,
      [object]$ForegroundColor,
      [object]$BackgroundColor,
      [object]$Separator,
      [switch]$NoNewline
    )

    if ($null -eq $Separator) {
      $Separator = ' '
    }

    $script:HostMessages += (($Object | ForEach-Object { [string]$_ }) -join ([string]$Separator))
  }
}

function Remove-TestOverrides {
  foreach ($name in @(
    'Write-Host',
    'git',
    'Invoke-WebRequest',
    'Start-Process',
    'Resolve-RepoRoot',
    'Invoke-ConservativeAutoUpdate',
    'Ensure-FileFromExample',
    'Get-MissingConfigEnvironmentVariables',
    'Test-CommandExists',
    'Test-BackendDepsPresent',
    'Test-FrontendDepsPresent',
    'Get-PortOccupantInfo',
    'Test-PortFree',
    'Wait-PortTcp',
    'Wait-HttpOk',
    'Start-ServiceWindow'
  )) {
    if (Test-Path -LiteralPath ("function:" + $name)) {
      Remove-Item -LiteralPath ("function:" + $name) -Force
    }
  }

  $script:HostMessages = @()
  $script:GitCalls = @()
  $script:InvokeWebRequestCalls = @()
  $script:StartProcessCalls = @()
  $script:ServiceWindowCalls = @()
  $global:LASTEXITCODE = 0
}

function Set-GitScenario {
  param(
    [string]$Counts = '0 1',
    [string]$StatusOutput = '',
    [string]$OriginUrl = 'https://github.com/bytedance/deer-flow.git',
    [string]$Branch = 'main',
    [string]$Upstream = 'origin/main',
    [int]$OriginExitCode = 0,
    [int]$BranchExitCode = 0,
    [int]$UpstreamExitCode = 0,
    [int]$FetchExitCode = 0
  )

  $script:GitCalls = @()
  $script:GitScenario = @{
    Counts = $Counts
    StatusOutput = $StatusOutput
    OriginUrl = $OriginUrl
    Branch = $Branch
    Upstream = $Upstream
    OriginExitCode = $OriginExitCode
    BranchExitCode = $BranchExitCode
    UpstreamExitCode = $UpstreamExitCode
    FetchExitCode = $FetchExitCode
  }

  function global:git {
    param([Parameter(ValueFromRemainingArguments = $true)][object[]]$GitArgs)

    $command = ($GitArgs | ForEach-Object { [string]$_ }) -join ' '
    $script:GitCalls += $command

    switch -Wildcard ($command) {
      '--version' {
        $global:LASTEXITCODE = 0
        'git version 2.43.0'
        return
      }
      'config --get remote.origin.url' {
        $global:LASTEXITCODE = $script:GitScenario.OriginExitCode
        if ($global:LASTEXITCODE -eq 0) { $script:GitScenario.OriginUrl }
        return
      }
      'rev-parse --abbrev-ref HEAD' {
        $global:LASTEXITCODE = $script:GitScenario.BranchExitCode
        if ($global:LASTEXITCODE -eq 0) { $script:GitScenario.Branch }
        return
      }
      'rev-parse --abbrev-ref --symbolic-full-name @{u}' {
        $global:LASTEXITCODE = $script:GitScenario.UpstreamExitCode
        if ($global:LASTEXITCODE -eq 0) { $script:GitScenario.Upstream }
        return
      }
      'fetch origin main' {
        $global:LASTEXITCODE = $script:GitScenario.FetchExitCode
        if ($global:LASTEXITCODE -eq 0) { 'ok' }
        return
      }
      'rev-list --left-right --count HEAD...origin/main' {
        $global:LASTEXITCODE = 0
        $script:GitScenario.Counts
        return
      }
      default {
        throw "Unexpected git command in test: $command"
      }
    }
  }
}

Describe 'scripts/start-windows.ps1' {
  It 'exists' {
    (Test-Path -LiteralPath $scriptPath) | Should Be $true
  }

  if (Test-Path -LiteralPath $scriptPath) {
    . $scriptPath

    BeforeEach {
      Remove-TestOverrides
      . $scriptPath
    }

    AfterEach {
      Remove-TestOverrides
    }

    It 'resolves repo root from script location' {
      $root = Resolve-RepoRoot
      (Test-Path -LiteralPath (Join-Path $root 'backend')) | Should Be $true
      (Test-Path -LiteralPath (Join-Path $root 'frontend')) | Should Be $true
    }

    It 'Is-OfficialOriginUrl accepts only official DeerFlow origin URL forms' {
      Is-OfficialOriginUrl 'https://github.com/bytedance/deer-flow.git' | Should Be $true
      Is-OfficialOriginUrl 'https://github.com/bytedance/deer-flow' | Should Be $true
      Is-OfficialOriginUrl 'https://github.com/bytedance/deer-flow/' | Should Be $true
      Is-OfficialOriginUrl 'git@github.com:bytedance/deer-flow.git' | Should Be $true
      Is-OfficialOriginUrl 'git@github.com:bytedance/deer-flow' | Should Be $true
      Is-OfficialOriginUrl 'ssh://git@github.com/bytedance/deer-flow.git' | Should Be $true
      Is-OfficialOriginUrl 'ssh://git@github.com/bytedance/deer-flow' | Should Be $true
    }

    It 'Is-OfficialOriginUrl rejects non-official origins' {
      Is-OfficialOriginUrl 'https://github.com/bytedance/deer-flow2' | Should Be $false
      Is-OfficialOriginUrl 'https://github.com/someone/deer-flow.git' | Should Be $false
      Is-OfficialOriginUrl 'git@github.com:someone/deer-flow' | Should Be $false
      Is-OfficialOriginUrl '' | Should Be $false
      Is-OfficialOriginUrl $null | Should Be $false
    }

    It 'Ensure-FileFromExample copies the example file when target missing' {
      $dir = Join-Path $TestDrive 'cfg'
      New-Item -ItemType Directory -Path $dir | Out-Null

      $example = Join-Path $dir 'config.example'
      $target = Join-Path $dir 'config'
      Set-Content -LiteralPath $example -Value 'hello' -Encoding ASCII

      Ensure-FileFromExample -Path $target -ExamplePath $example

      (Test-Path -LiteralPath $target) | Should Be $true
      (Get-Content -LiteralPath $target -Raw).Trim() | Should Be 'hello'
    }

    It 'Get-MissingConfigEnvironmentVariables ignores commented example placeholders' {
      $repoRoot = Join-Path $TestDrive 'repo-commented-env'
      New-Item -ItemType Directory -Path $repoRoot | Out-Null

      $configPath = Join-Path $repoRoot 'config.yaml'
      Set-Content -LiteralPath $configPath -Encoding ASCII -Value @'
models:
  - name: glm-4-flash
    api_key: direct-inline-key
    base_url: https://open.bigmodel.cn/api/paas/v4
    model: glm-4-flash

# Example values below should not be treated as required:
# api_key: $OPENAI_API_KEY
# api_key: $ANTHROPIC_API_KEY
tools:
  - name: web_search
    use: deerflow.community.tavily.tools:web_search_tool
    # api_key: $TAVILY_API_KEY
'@

      $missing = Get-MissingConfigEnvironmentVariables -ConfigPath $configPath

      @($missing).Count | Should Be 0
    }

    It 'Get-MissingConfigEnvironmentVariables only reports active YAML values that still reference host env vars' {
      $repoRoot = Join-Path $TestDrive 'repo-active-env'
      New-Item -ItemType Directory -Path $repoRoot | Out-Null

      $configPath = Join-Path $repoRoot 'config.yaml'
      Set-Content -LiteralPath $configPath -Encoding ASCII -Value @'
models:
  - name: active-env-model
    api_key: $ACTIVE_MODEL_KEY
    base_url: https://example.com/v1
    model: demo-model
tools:
  - name: web_search
    use: deerflow.community.tavily.tools:web_search_tool
    api_key: $ACTIVE_TOOL_KEY
'@

      [Environment]::SetEnvironmentVariable('ACTIVE_MODEL_KEY', $null)
      [Environment]::SetEnvironmentVariable('ACTIVE_TOOL_KEY', 'present-value')

      try {
        $missing = Get-MissingConfigEnvironmentVariables -ConfigPath $configPath

        @($missing).Count | Should Be 1
        $missing[0] | Should Be 'ACTIVE_MODEL_KEY'
      } finally {
        [Environment]::SetEnvironmentVariable('ACTIVE_TOOL_KEY', $null)
      }
    }

    It 'Test-PortFree returns false when a TCP listener is already bound' {
      $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
      $listener.Start()
      try {
        $port = $listener.LocalEndpoint.Port
        (Test-PortFree -Port $port) | Should Be $false
      } finally {
        $listener.Stop()
      }
    }

    It 'Wait-PortTcp returns true when a local listener appears during the polling window' {
      $bootstrap = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
      $bootstrap.Start()
      $port = $bootstrap.LocalEndpoint.Port
      $bootstrap.Stop()

      $job = Start-Job -ScriptBlock {
        param($Port)
        Start-Sleep -Milliseconds 300
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        try {
          Start-Sleep -Seconds 2
        } finally {
          $listener.Stop()
        }
      } -ArgumentList $port

      try {
        (Wait-PortTcp -Port $port -TimeoutSec 2 -PollMs 100) | Should Be $true
      } finally {
        Receive-Job $job -Wait | Out-Null
        Remove-Job $job -Force
      }
    }

    It 'Wait-HttpOk returns true for HTTP 200 and includes UseBasicParsing when supported' {
      $script:InvokeWebRequestCalls = @()
      function global:Invoke-WebRequest {
        param(
          [string]$Uri,
          [string]$Method,
          [int]$TimeoutSec,
          [switch]$UseBasicParsing
        )

        $script:InvokeWebRequestCalls += [pscustomobject]@{
          Uri = $Uri
          Method = $Method
          TimeoutSec = $TimeoutSec
          UseBasicParsing = $UseBasicParsing.IsPresent
        }
        [pscustomobject]@{ StatusCode = 200 }
      }

      (Wait-HttpOk -Url 'http://localhost:8001/health' -TimeoutSec 1 -PollMs 10) | Should Be $true
      $script:InvokeWebRequestCalls.Count | Should Be 1
      $script:InvokeWebRequestCalls[0].Method | Should Be 'GET'
      $script:InvokeWebRequestCalls[0].Uri | Should Be 'http://localhost:8001/health'
      $script:InvokeWebRequestCalls[0].TimeoutSec | Should Be 5
      $script:InvokeWebRequestCalls[0].UseBasicParsing | Should Be $true
    }

    It 'Write-MissingCommandGuidance prints actionable remediation per missing tool' {
      Set-HostCapture

      Write-MissingCommandGuidance -Missing @('node', 'pnpm', 'uv')

      ($script:HostMessages -join "`n") | Should Match 'Install the missing tools, then run this script again\.'
      ($script:HostMessages -join "`n") | Should Match 'Install Node\.js 22\+ from https://nodejs\.org/'
      ($script:HostMessages -join "`n") | Should Match 'npm install -g pnpm'
      ($script:HostMessages -join "`n") | Should Match 'Install uv from https://docs\.astral\.sh/uv/getting-started/installation/'
    }

    It 'Invoke-ConservativeAutoUpdate stops when git fetch fails' {
      Set-HostCapture
      Set-GitScenario -FetchExitCode 1
      $repoRoot = Join-Path $TestDrive 'repo-fetch-fail'
      New-Item -ItemType Directory -Path $repoRoot | Out-Null
      Set-Content -LiteralPath (Join-Path $repoRoot '.git') -Value 'gitdir: fake' -Encoding ASCII

      { Invoke-ConservativeAutoUpdate -RepoRoot $repoRoot } | Should Throw

      ($script:HostMessages -join "`n") | Should Match 'git fetch failed'
      ($script:HostMessages -join "`n") | Should Match 'Next steps'
    }

    It 'Invoke-ConservativeAutoUpdate warns and skips for non-main or wrong upstream without fetch or pull' {
      Set-HostCapture
      Set-GitScenario -Branch 'feature/test' -Upstream 'origin/feature/test'
      $repoRoot = Join-Path $TestDrive 'repo-non-main'
      New-Item -ItemType Directory -Path $repoRoot | Out-Null
      Set-Content -LiteralPath (Join-Path $repoRoot '.git') -Value 'gitdir: fake' -Encoding ASCII

      Invoke-ConservativeAutoUpdate -RepoRoot $repoRoot

      ($script:HostMessages -join "`n") | Should Match 'Not on official main tracking origin/main; skipping auto-update'
      ($script:GitCalls -contains 'fetch origin main') | Should Be $false
    }

    It 'Invoke-DeerFlowWindowsStart throws for busy ports after printing the busy list' {
      Set-HostCapture
      $repoRoot = Join-Path $TestDrive 'repo-busy-port'
      New-Item -ItemType Directory -Path $repoRoot | Out-Null

      function Resolve-RepoRoot { $repoRoot }
      function Invoke-ConservativeAutoUpdate { param([string]$RepoRoot) }
      function Ensure-FileFromExample { param([string]$Path, [string]$ExamplePath, [switch]$AllowEmptyJson) }
      function Test-CommandExists { param([string]$Name) $true }
      function Test-BackendDepsPresent { param([string]$RepoRoot) $true }
      function Test-FrontendDepsPresent { param([string]$RepoRoot) $true }
      function Get-PortOccupantInfo {
        param([int]$Port)
        if ($Port -eq 8001) {
          return [pscustomobject]@{
            Port = 8001
            ProcessId = 4242
            ProcessName = 'node'
          }
        }
        return $null
      }
      function Test-PortFree {
        param([int]$Port)
        return $Port -ne 8001
      }

      { Invoke-DeerFlowWindowsStart } | Should Throw

      ($script:HostMessages -join "`n") | Should Match 'Port\(s\) already in use: 8001'
      ($script:HostMessages -join "`n") | Should Match 'Port 8001 is owned by PID 4242 \(node\)'
    }

    It 'Invoke-DeerFlowWindowsStart throws early when config.yaml references missing environment variables' {
      Set-HostCapture
      $repoRoot = Join-Path $TestDrive 'repo-missing-config-env'
      New-Item -ItemType Directory -Path $repoRoot | Out-Null

      function Resolve-RepoRoot { $repoRoot }
      function Invoke-ConservativeAutoUpdate { param([string]$RepoRoot) }
      function Ensure-FileFromExample { param([string]$Path, [string]$ExamplePath, [switch]$AllowEmptyJson) }
      function Test-CommandExists { param([string]$Name) $true }
      function Test-BackendDepsPresent { param([string]$RepoRoot) $true }
      function Test-FrontendDepsPresent { param([string]$RepoRoot) $true }
      function Get-MissingConfigEnvironmentVariables {
        param([string]$ConfigPath)
        return @('ZHIPU_API_KEY', 'OPENAI_API_KEY')
      }

      { Invoke-DeerFlowWindowsStart } | Should Throw

      ($script:HostMessages -join "`n") | Should Match 'Missing environment variables referenced by config\.yaml: ZHIPU_API_KEY, OPENAI_API_KEY'
      ($script:HostMessages -join "`n") | Should Match 'Set the missing environment variables and run start-windows\.bat again\.'
    }

    It 'Invoke-DeerFlowWindowsStart schedules the exact service windows and browser target' {
      $repoRoot = Join-Path $TestDrive 'repo-start'
      New-Item -ItemType Directory -Path $repoRoot | Out-Null
      New-Item -ItemType Directory -Path (Join-Path $repoRoot 'backend') | Out-Null
      New-Item -ItemType Directory -Path (Join-Path $repoRoot 'frontend') | Out-Null

      $script:ServiceWindowCalls = @()
      $script:StartProcessCalls = @()

      function Resolve-RepoRoot { $repoRoot }
      function Invoke-ConservativeAutoUpdate { param([string]$RepoRoot) }
      function Ensure-FileFromExample {
        param([string]$Path, [string]$ExamplePath, [switch]$AllowEmptyJson)
      }
      function Test-CommandExists { param([string]$Name) $true }
      function Test-BackendDepsPresent { param([string]$RepoRoot) $true }
      function Test-FrontendDepsPresent { param([string]$RepoRoot) $true }
      function Test-PortFree { param([int]$Port) $true }
      function Wait-PortTcp { param([int]$Port, [int]$TimeoutSec, [int]$PollMs) $true }
      function Wait-HttpOk { param([string]$Url, [int]$TimeoutSec, [int]$PollMs) $true }
      function Start-ServiceWindow {
        param([string]$Title, [string]$WorkingDir, [string]$Command)
        $script:ServiceWindowCalls += [pscustomobject]@{
          Title = $Title
          WorkingDir = $WorkingDir
          Command = $Command
        }
      }
      function Start-Process {
        param(
          [Parameter(Position = 0)][object]$FilePath,
          [object[]]$ArgumentList
        )

        $script:StartProcessCalls += [pscustomobject]@{
          FilePath = $FilePath
          ArgumentList = $ArgumentList
        }
      }

      Invoke-DeerFlowWindowsStart

      $script:ServiceWindowCalls.Count | Should Be 3
      $script:ServiceWindowCalls[0].Title | Should Be 'DeerFlow LangGraph'
      $script:ServiceWindowCalls[0].Command | Should Be 'uv run langgraph dev --no-browser --allow-blocking --host 0.0.0.0 --port 2024'
      $script:ServiceWindowCalls[1].Title | Should Be 'DeerFlow Gateway'
      $script:ServiceWindowCalls[1].Command | Should Be '$env:PYTHONPATH=''.''; uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload'
      $script:ServiceWindowCalls[2].Title | Should Be 'DeerFlow Frontend'
      $script:ServiceWindowCalls[2].Command | Should Be 'pnpm run dev -- --port 2026'
      $script:StartProcessCalls.Count | Should Be 1
      $script:StartProcessCalls[0].FilePath | Should Be 'http://localhost:2026'
    }
  }
}

# minimax-docx Environment Setup & Initialization Script (Windows PowerShell)
# Supports: Windows 10/11, Windows Server 2019+
# License: MIT
#Requires -Version 5.1

param(
    [switch]$Minimal,
    [switch]$SkipVerify,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$DotnetDir = Join-Path $ScriptDir "dotnet"
$LogFile = Join-Path $ProjectDir ".setup.log"

# --- Output Helpers ---
function Log   { Write-Host "[OK]    $args" -ForegroundColor Green }
function Warn  { Write-Host "[WARN]  $args" -ForegroundColor Yellow }
function Fail  { Write-Host "[FAIL]  $args" -ForegroundColor Red }
function Info  { Write-Host "[INFO]  $args" -ForegroundColor Cyan }
function Step  { Write-Host "`n=== $args ===" -ForegroundColor Blue }

if ($Help) {
    Write-Host @"
Usage: setup.ps1 [options]
  -Minimal       Only install critical dependencies (skip pandoc, soffice, fonts)
  -SkipVerify    Skip the verification test at the end
  -Help          Show this help
"@
    exit 0
}

Write-Host "============================================"
Write-Host "  minimax-docx Setup & Initialization (Windows)"
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "============================================"

"" | Set-Content $LogFile

# --- Detect Package Manager ---
$HasWinget = $null -ne (Get-Command winget -ErrorAction SilentlyContinue)
$HasChoco  = $null -ne (Get-Command choco -ErrorAction SilentlyContinue)
$HasScoop  = $null -ne (Get-Command scoop -ErrorAction SilentlyContinue)

if ($HasWinget)     { Info "Package manager: winget" }
elseif ($HasChoco)  { Info "Package manager: chocolatey" }
elseif ($HasScoop)  { Info "Package manager: scoop" }
else                { Warn "No package manager found (winget/choco/scoop). Manual install may be needed." }

# --- .NET SDK ---
Step "Checking .NET SDK"

$dotnetCmd = Get-Command dotnet -ErrorAction SilentlyContinue
if ($dotnetCmd) {
    $dotnetVer = & dotnet --version 2>$null
    $majorVer = [int]($dotnetVer -split '\.')[0]
    if ($majorVer -ge 8) {
        Log "dotnet $dotnetVer already installed (>= 8.0 OK)"
    } else {
        Warn "dotnet $dotnetVer found but < 8.0, upgrading..."
        $dotnetCmd = $null
    }
}

if (-not $dotnetCmd -or $majorVer -lt 8) {
    Info "Installing .NET SDK..."
    if ($HasWinget) {
        winget install Microsoft.DotNet.SDK.8 --accept-source-agreements --accept-package-agreements 2>>$LogFile
    } elseif ($HasChoco) {
        choco install dotnet-sdk -y 2>>$LogFile
    } elseif ($HasScoop) {
        scoop install dotnet-sdk 2>>$LogFile
    } else {
        Fail "Cannot auto-install .NET SDK. Download from: https://dotnet.microsoft.com/download"
        Fail "After installing, restart PowerShell and re-run this script."
        exit 1
    }

    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

    if (Get-Command dotnet -ErrorAction SilentlyContinue) {
        Log "dotnet $(dotnet --version) installed"
    } else {
        Fail "dotnet installation failed. Restart PowerShell and retry, or install manually."
        exit 1
    }
}

# --- Pandoc (Optional) ---
if (-not $Minimal) {
    Step "Checking pandoc (optional: content preview)"

    if (Get-Command pandoc -ErrorAction SilentlyContinue) {
        $pandocVer = (pandoc --version | Select-Object -First 1) -replace '.*?(\d+\.\d+(\.\d+)?)', '$1'
        Log "pandoc $pandocVer already installed"
    } else {
        Info "Installing pandoc..."
        if ($HasWinget)    { winget install JohnMacFarlane.Pandoc --accept-source-agreements 2>>$LogFile }
        elseif ($HasChoco) { choco install pandoc -y 2>>$LogFile }
        elseif ($HasScoop) { scoop install pandoc 2>>$LogFile }
        else               { Warn "Install pandoc manually: https://pandoc.org/installing.html" }

        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

        if (Get-Command pandoc -ErrorAction SilentlyContinue) {
            Log "pandoc installed"
        } else {
            Warn "pandoc not found after install (optional, will degrade gracefully)"
        }
    }
}

# --- LibreOffice (Optional) ---
if (-not $Minimal) {
    Step "Checking LibreOffice/soffice (optional: .doc conversion)"

    $sofficeFound = $false

    # Check common Windows install paths
    $sofficePaths = @(
        "C:\Program Files\LibreOffice\program\soffice.exe",
        "C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "${env:LOCALAPPDATA}\Programs\LibreOffice\program\soffice.exe"
    )

    if (Get-Command soffice -ErrorAction SilentlyContinue) {
        Log "soffice found in PATH"
        $sofficeFound = $true
    } else {
        foreach ($p in $sofficePaths) {
            if (Test-Path $p) {
                Log "soffice found at: $p"
                Info "Tip: Add to PATH: `$env:Path += ';$(Split-Path $p)'"
                $sofficeFound = $true
                break
            }
        }
    }

    if (-not $sofficeFound) {
        Info "Installing LibreOffice (this may take a while)..."
        if ($HasWinget)    { winget install TheDocumentFoundation.LibreOffice --accept-source-agreements 2>>$LogFile }
        elseif ($HasChoco) { choco install libreoffice-fresh -y 2>>$LogFile }
        else               { Warn "Install LibreOffice manually: https://www.libreoffice.org/download/" }
    }
}

# --- NuGet Configuration ---
Step "Checking NuGet configuration"

$nugetSources = & dotnet nuget list source 2>$null
if ($nugetSources -match "nuget.org") {
    Log "nuget.org source is configured"
} else {
    Warn "nuget.org not in sources. Adding..."
    & dotnet nuget add source "https://api.nuget.org/v3/index.json" --name "nuget.org" 2>>$LogFile
}

# --- Encoding Check ---
Step "Checking console encoding"

$currentEncoding = [Console]::OutputEncoding.EncodingName
if ($currentEncoding -match "UTF-8|Unicode") {
    Log "Console encoding: $currentEncoding (UTF-8 compatible)"
} else {
    Warn "Console encoding: $currentEncoding (may cause issues with CJK text)"
    Info "To fix: [Console]::OutputEncoding = [System.Text.Encoding]::UTF8"
    Info "Or set system-wide: Settings > Time & Language > Language > Administrative > Change system locale > Beta: UTF-8"
    # Apply for this session
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    Log "Set UTF-8 encoding for this session"
}

# --- Font Check ---
if (-not $Minimal) {
    Step "Checking fonts"

    $fonts = [System.Drawing.FontFamily]::Families 2>$null
    if ($fonts) {
        $fontNames = $fonts | ForEach-Object { $_.Name }
        $hasCalibri = $fontNames -contains "Calibri"
        $hasTimes = $fontNames -contains "Times New Roman"
        $hasCJK = ($fontNames | Where-Object { $_ -match "SimSun|Microsoft YaHei|MS Mincho|Malgun Gothic" }).Count -gt 0

        if ($hasCalibri)   { Log "Western fonts: Calibri found" }       else { Warn "Calibri not found (install Microsoft Office or fonts)" }
        if ($hasTimes)     { Log "Western fonts: Times New Roman found" } else { Warn "Times New Roman not found" }
        if ($hasCJK)       { Log "CJK fonts: available" }               else { Warn "CJK fonts not found (install language packs for Chinese/Japanese/Korean)" }
    } else {
        Info "Cannot enumerate fonts (System.Drawing not loaded). Skipping font check."
    }
}

# --- Build Project ---
Step "Building minimax-docx .NET project"

if (-not (Test-Path $DotnetDir)) {
    Fail "Dotnet project directory not found: $DotnetDir"
    exit 1
}

Push-Location $DotnetDir

Info "Restoring NuGet packages..."
$restoreResult = & dotnet restore --verbosity quiet 2>&1
if ($LASTEXITCODE -ne 0) {
    Fail "NuGet restore failed:"
    $restoreResult | ForEach-Object { Fail "  $_" }
    Fail "Common causes:"
    Fail "  - No internet (NuGet needs to download packages)"
    Fail "  - Corporate proxy/firewall blocking nuget.org"
    Fail "  - Insufficient disk space"
    Fail "Try: dotnet restore --verbosity detailed"
    Pop-Location
    exit 1
}
Log "NuGet packages restored"

Info "Building project..."
$buildResult = & dotnet build --verbosity quiet --no-restore 2>&1
if ($LASTEXITCODE -ne 0) {
    Fail "Build failed:"
    $buildResult | ForEach-Object { Fail "  $_" }
    Pop-Location
    exit 1
}
Log "Project built successfully"

Pop-Location

# --- Verification ---
if (-not $SkipVerify) {
    Step "Verification Test"

    $testOutput = Join-Path $env:TEMP "minimax-docx-setup-test-$PID.docx"

    Info "Creating a test document..."
    Push-Location $DotnetDir
    $testResult = & dotnet run --project MiniMaxAIDocx.Cli -- create --type report --output $testOutput --title "Setup Test" 2>&1
    $testExitCode = $LASTEXITCODE
    Pop-Location

    if ($testExitCode -eq 0 -and (Test-Path $testOutput)) {
        Log "Test document created: $testOutput"

        if (Get-Command pandoc -ErrorAction SilentlyContinue) {
            $preview = & pandoc -f docx -t plain $testOutput 2>$null | Select-Object -First 3
            if ($preview) { Log "Preview working: `"$($preview -join ' ')`"" }
        }

        Remove-Item $testOutput -Force
        Log "Test passed - minimax-docx is ready to use!"
    } else {
        Fail "Test document creation failed. Output:"
        $testResult | ForEach-Object { Fail "  $_" }
    }
}

# --- Summary ---
Step "Setup Complete"

Write-Host ""
Write-Host "  Environment: Windows $([System.Environment]::OSVersion.Version)"
Write-Host "  .NET SDK:    $(dotnet --version 2>$null)"
$pandocInfo = if (Get-Command pandoc -ErrorAction SilentlyContinue) { pandoc --version | Select-Object -First 1 } else { "not installed (optional)" }
Write-Host "  pandoc:      $pandocInfo"
Write-Host "  Project:     $DotnetDir"
Write-Host ""
Write-Host "  Usage:"
Write-Host "    dotnet run --project $DotnetDir\MiniMaxAIDocx.Cli -- create --type report --output my_report.docx"
Write-Host ""
Write-Host "  Log file: $LogFile"

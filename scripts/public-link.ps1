# ============================================================================
#  HUMINT Shield - publish the training pages on a free public URL
# ============================================================================
#  Usage:
#     powershell -ExecutionPolicy Bypass -File scripts\public-link.ps1
#     powershell -ExecutionPolicy Bypass -File scripts\public-link.ps1 -NoRestart
#
#  What it does, with no manual steps:
#     1. stops any previous tunnel started by this script
#     2. opens a Cloudflare quick tunnel (free, no account) to the backend
#     3. reads the random https://<name>.trycloudflare.com address
#     4. writes it into backend\.env (BASE_URL + CORS_ORIGINS)
#     5. restarts the backend so the new address takes effect
#     6. verifies the public URL end to end and prints it
#
#  The address is random and changes on every run; re-run this script after a
#  reboot (or use Windows Task Scheduler) to publish the training pages again.
# ============================================================================

param(
    [switch]$NoRestart,
    [string]$Cloudflared = '',
    [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'

$root    = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$envFile = Join-Path $backend '.env'
$logFile = Join-Path $root '.tunnel.log'

function Write-Step([string]$Message) {
    Write-Host "[public-link] $Message" -ForegroundColor Cyan
}

function Resolve-Cloudflared([string]$Explicit) {
    if ($Explicit -and (Test-Path $Explicit)) { return $Explicit }
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        (Join-Path $env:TEMP 'opencode\cloudflared.exe'),
        (Join-Path $env:TEMP 'cloudflared.exe'),
        (Join-Path $env:LOCALAPPDATA 'cloudflared\cloudflared.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    throw 'cloudflared.exe was not found. Pass -Cloudflared <path>.'
}

function Stop-OldTunnel() {
    Get-Process cloudflared -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Step "stopping previous tunnel (pid $($_.Id))"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
}

function Get-PublicUrl([string]$File, [int]$Timeout) {
    $deadline = (Get-Date).AddSeconds($Timeout)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $File) {
            $match = Select-String -Path $File -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue |
                     Select-Object -First 1
            if ($match) { return $match.Matches[0].Value }
        }
        Start-Sleep -Milliseconds 700
    }
    return $null
}

function Set-EnvValue([string]$Path, [string]$Key, [string]$Value) {
    $lines = Get-Content $Path -Encoding UTF8
    $found = $false
    $updated = foreach ($line in $lines) {
        if ($line -match "^\s*$([regex]::Escape($Key))\s*=") {
            $found = $true
            "$Key=$Value"
        } else {
            $line
        }
    }
    if (-not $found) { $updated = @($updated) + "$Key=$Value" }
    Set-Content -Path $Path -Value $updated -Encoding UTF8
}

function Get-EnvValue([string]$Path, [string]$Key) {
    $match = Select-String -Path $Path -Pattern "^\s*$([regex]::Escape($Key))\s*=\s*(.*)$" -ErrorAction SilentlyContinue |
             Select-Object -First 1
    if ($match) { return $match.Matches[0].Groups[1].Value.Trim() }
    return ''
}

function Restart-Backend() {
    $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        Write-Step "stopping backend (pid $($listener.OwningProcess))"
        Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    Write-Step 'starting backend ...'
    # The output must go to files: a detached child that inherits this script's
    # stdout would keep the caller's pipe open and make the script look stuck.
    Start-Process -FilePath 'py' `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000' `
        -WorkingDirectory $backend `
        -RedirectStandardOutput (Join-Path $root '.backend.out.log') `
        -RedirectStandardError (Join-Path $root '.backend.err.log') `
        -WindowStyle Hidden
}

function Wait-Healthy([string]$Url, [int]$Timeout = 40) {
    $deadline = (Get-Date).AddSeconds($Timeout)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Milliseconds 800
    }
    return $false
}

# ---------------------------------------------------------------------------
Write-Host ''
Write-Host '=== publishing the training pages ===' -ForegroundColor White

if (-not (Test-Path $envFile)) {
    throw "backend\.env not found at $envFile"
}

$exe = Resolve-Cloudflared $Cloudflared
Write-Step "cloudflared: $exe"

Stop-OldTunnel
if (Test-Path $logFile) { Remove-Item $logFile -Force }

Write-Step 'opening a free quick tunnel ...'
Start-Process -FilePath $exe `
    -ArgumentList 'tunnel', '--url', 'http://localhost:8000', '--no-autoupdate' `
    -RedirectStandardError $logFile `
    -RedirectStandardOutput (Join-Path $root '.tunnel.out.log') `
    -WindowStyle Hidden

$publicUrl = Get-PublicUrl $logFile $TimeoutSeconds
if (-not $publicUrl) {
    throw "could not read the public URL within $TimeoutSeconds seconds - see $logFile"
}
Write-Step "public address: $publicUrl"

# ------------------------------------------------------------------ .env
$origins = Get-EnvValue $envFile 'CORS_ORIGINS'
if (-not $origins) {
    $origins = 'http://127.0.0.1:5173,http://localhost:5173'
}
$kept = $origins.Split(',') |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and ($_ -notmatch 'trycloudflare\.com$') }
$newOrigins = (@($kept) + $publicUrl) -join ','

Set-EnvValue $envFile 'BASE_URL' $publicUrl
Set-EnvValue $envFile 'CORS_ORIGINS' $newOrigins
Write-Step 'updated backend\.env (BASE_URL, CORS_ORIGINS)'

if ($NoRestart) {
    Write-Step '-NoRestart set: restart the backend yourself to apply it.'
} else {
    Restart-Backend
}

# ------------------------------------------------------------ verification
Write-Step 'verifying ...'
$localOk  = Wait-Healthy 'http://127.0.0.1:8000/healthz' 40
# A quick tunnel needs a few seconds to become routable from the internet.
$publicOk = Wait-Healthy "$publicUrl/healthz" 90

Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host '  PUBLIC TRAINING LINK' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host ("  Base URL        : {0}   [{1}]" -f $publicUrl, $(if ($publicOk) { 'UP' } else { 'DOWN' }))
Write-Host ("  Backend local   : http://127.0.0.1:8000/healthz   [{0}]" -f $(if ($localOk) { 'UP' } else { 'DOWN' }))
Write-Host  '  Recipient view  : <the link inside the email>'
Write-Host  '  Dashboard (UI)  : http://127.0.0.1:5173'
Write-Host '============================================================' -ForegroundColor Green
Write-Host ''

if (-not ($localOk -and $publicOk)) {
    Write-Host 'One of the health checks failed.' -ForegroundColor Red
    exit 1
}

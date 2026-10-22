# ============================================================================
#  HUMINT Shield - start the local development stack
# ============================================================================
#  Usage:
#     powershell -ExecutionPolicy Bypass -File scripts\start-dev.ps1
#     powershell -ExecutionPolicy Bypass -File scripts\start-dev.ps1 -Tunnel
#
#  - Starts the FastAPI backend on http://127.0.0.1:8000  (reads backend\.env)
#  - Starts the Vite dev server on http://127.0.0.1:5173
#  - With -Tunnel, also opens a public Cloudflare quick tunnel for the backend
#  - Skips any service that is already listening on its port
# ============================================================================

param(
    [switch]$Tunnel,
    [string]$Cloudflared = ''
)

$ErrorActionPreference = 'Stop'
$root     = Split-Path -Parent $PSScriptRoot
$backend  = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

function Test-Port([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-Healthy([string]$Url, [int]$TimeoutSeconds = 40) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Milliseconds 800
    }
    return $false
}

Write-Host ''
Write-Host '=== HUMINT Shield : starting dev stack ===' -ForegroundColor Cyan

# ---------------------------------------------------------------- backend
if (Test-Port 8000) {
    Write-Host '[backend ] already listening on :8000 - skipped' -ForegroundColor Yellow
} else {
    Write-Host '[backend ] starting uvicorn ...' -ForegroundColor Green
    Start-Process -FilePath 'py' `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000' `
        -WorkingDirectory $backend
}

# --------------------------------------------------------------- frontend
$nodeDir = 'C:\Program Files\nodejs'
if ((Test-Path $nodeDir) -and ($env:Path -notlike "*$nodeDir*")) {
    $env:Path = "$nodeDir;$env:Path"
}

if (Test-Port 5173) {
    Write-Host '[frontend] already listening on :5173 - skipped' -ForegroundColor Yellow
} else {
    Write-Host '[frontend] starting Vite ...' -ForegroundColor Green
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/c', 'npm.cmd run dev' `
        -WorkingDirectory $frontend
}

# ----------------------------------------------------------------- tunnel
if ($Tunnel) {
    if (-not $Cloudflared) {
        $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
        if ($cmd) {
            $Cloudflared = $cmd.Source
        } else {
            $fallback = Join-Path $env:TEMP 'opencode\cloudflared.exe'
            if (Test-Path $fallback) { $Cloudflared = $fallback }
        }
    }
    if (-not $Cloudflared -or -not (Test-Path $Cloudflared)) {
        Write-Host '[tunnel  ] cloudflared not found - skipped (pass -Cloudflared <path>)' -ForegroundColor Red
    } else {
        Write-Host '[tunnel  ] opening public quick tunnel ...' -ForegroundColor Green
        Start-Process -FilePath $Cloudflared `
            -ArgumentList 'tunnel', '--url', 'http://localhost:8000', '--no-autoupdate' `
            -WorkingDirectory $root
        Write-Host '[tunnel  ] read the https://<random>.trycloudflare.com address from the new window' -ForegroundColor Yellow
        Write-Host '[tunnel  ] then put it in backend\.env as BASE_URL and restart the backend' -ForegroundColor Yellow
    }
}

# ------------------------------------------------------------ readiness
Write-Host ''
Write-Host '=== waiting for services ===' -ForegroundColor Cyan
$apiOk  = Wait-Healthy 'http://127.0.0.1:8000/healthz'
$webOk  = Test-Port 5173

# ------------------------------------------------------------------ links
Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host '  ACCESS LINKS' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ("  Dashboard (UI) : http://127.0.0.1:5173          [{0}]" -f $(if ($webOk) { 'UP' } else { 'DOWN' }))
Write-Host ("  API docs       : http://127.0.0.1:8000/docs     [{0}]" -f $(if ($apiOk) { 'UP' } else { 'DOWN' }))
Write-Host  '  API health     : http://127.0.0.1:8000/healthz'
Write-Host  '  Login          : admin / ChangeMe123!'
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ''

if (-not $apiOk) {
    Write-Host 'Backend did not become healthy - check its window for errors.' -ForegroundColor Red
    exit 1
}

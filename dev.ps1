# Start backend (FastAPI) + frontend (Vite) for local development.
# Usage: .\dev.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$procs = @()

function Stop-Children {
    foreach ($p in $procs) {
        if ($null -ne $p -and -not $p.HasExited) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            # Kill any child processes (uvicorn / node) spawned under the shell
            Get-CimInstance Win32_Process |
                Where-Object { $_.ParentProcessId -eq $p.Id } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        }
    }
}

try {
    Write-Host "Starting backend  -> http://127.0.0.1:8765" -ForegroundColor Cyan
    $backend = Start-Process -PassThru -NoNewWindow `
        -WorkingDirectory $Root `
        -FilePath "uv" `
        -ArgumentList @("run", "python", "backend/run.py")
    $procs += $backend

    Write-Host "Starting frontend -> http://127.0.0.1:5173 (proxies /api,/media)" -ForegroundColor Cyan
    $frontend = Start-Process -PassThru -NoNewWindow `
        -WorkingDirectory (Join-Path $Root "frontend") `
        -FilePath "pnpm" `
        -ArgumentList @("dev")
    $procs += $frontend

    Write-Host ""
    Write-Host "Both running. Press Ctrl+C to stop." -ForegroundColor Green
    Write-Host ""

    Wait-Process -Id ($procs | ForEach-Object { $_.Id })
}
finally {
    Write-Host "`nStopping..." -ForegroundColor Yellow
    Stop-Children
}

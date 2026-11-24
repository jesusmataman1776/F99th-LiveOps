# F99th LiveOps manual launcher. Does not change Windows startup or Tailscale Funnel.
$ErrorActionPreference = 'Stop'
$dashboard = 'C:\F99th\Dashboard'
$app = Join-Path $dashboard 'app.py'
$port = 8765

if (-not (Test-Path -LiteralPath $app -PathType Leaf)) {
    Write-Host "ERROR: Cannot find $app" -ForegroundColor Red
    Write-Host 'Check that this is the F99th3 server and the dashboard path is correct.'
    Read-Host 'Press Enter to close'
    exit 1
}

# Check the port before starting a second dashboard instance.
$listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if ($listener) {
    $pids = (($listener | Select-Object -ExpandProperty OwningProcess -Unique) -join ', ')
    Write-Host "Port $port is already listening (process ID: $pids)." -ForegroundColor Yellow
    Write-Host 'The dashboard may already be running. No second process was started.'
    Write-Host "Open http://127.0.0.1:$port to verify the map."
    Read-Host 'Press Enter to close'
    exit 0
}

# Prefer the dashboard's own environment, then Python installed on the machine.
$candidates = @(
    (Join-Path $dashboard '.venv\Scripts\python.exe')
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe')
)
$pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($pyLauncher) {
    $candidates += & $pyLauncher.Source -3 -c 'import sys; print(sys.executable)'
}
$candidates += (Get-Command python.exe -ErrorAction SilentlyContinue).Source
$python = $null
foreach ($candidate in $candidates) {
    if ($candidate -and $candidate -notmatch 'WindowsApps' -and (Test-Path -LiteralPath $candidate)) {
        & $candidate -c 'import sys; sys.exit(sys.version_info < (3, 10))'
        if ($LASTEXITCODE -eq 0) {
            $python = $candidate
            break
        }
    }
}
if (-not $python) {

    Write-Host 'ERROR: A working Python interpreter was not found.' -ForegroundColor Red
    Write-Host 'Install Python or modify $python in this launcher to its full executable path.'
    Read-Host 'Press Enter to close'
    exit 1
}

Write-Host "Starting F99th LiveOps on http://127.0.0.1:$port" -ForegroundColor Cyan
Write-Host "Python: $python"
Write-Host "Application: $app"
Write-Host 'Leave this window open while the dashboard runs. Press Ctrl+C to stop it.'
Write-Host 'Existing Tailscale Funnel settings are unchanged.'
Write-Host ''

Set-Location -LiteralPath $dashboard
& $python -u $app --port $port
$exitCode = $LASTEXITCODE
Write-Host "LiveOps exited (code $exitCode)." -ForegroundColor Yellow
Read-Host 'Press Enter to close'
exit $exitCode

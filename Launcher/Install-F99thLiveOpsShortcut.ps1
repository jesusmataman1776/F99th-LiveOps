# One-time installer for a MANUAL F99th LiveOps Desktop shortcut.
# Does not register a scheduled task or modify automatic Windows startup.
$ErrorActionPreference = 'Stop'
$targetDir = 'C:\F99th\Dashboard\Launcher'
$sourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$dashboard = 'C:\F99th\Dashboard\app.py'
if (-not (Test-Path -LiteralPath $dashboard -PathType Leaf)) {
    Write-Host "ERROR: Missing $dashboard" -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
if ([IO.Path]::GetFullPath($sourceDir) -ne [IO.Path]::GetFullPath($targetDir)) {
    Copy-Item -LiteralPath (Join-Path $sourceDir 'Start-F99thLiveOps.ps1') -Destination $targetDir -Force
    Copy-Item -LiteralPath (Join-Path $sourceDir 'F99th-LiveOps.ico') -Destination $targetDir -Force
}

$desktop = [Environment]::GetFolderPath('Desktop')
$linkPath = Join-Path $desktop 'F99th LiveOps Map.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($linkPath)
$link.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$link.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "C:\F99th\Dashboard\Launcher\Start-F99thLiveOps.ps1"'
$link.WorkingDirectory = 'C:\F99th\Dashboard'
$link.IconLocation = 'C:\F99th\Dashboard\Launcher\F99th-LiveOps.ico,0'
$link.Description = 'Start the F99th Live Operations world-map dashboard (manual launcher)'
$link.Save()
Write-Host "Desktop shortcut created: $linkPath" -ForegroundColor Green
Write-Host 'Double-click F99th LiveOps Map to start the map.'
Read-Host 'Press Enter to close'

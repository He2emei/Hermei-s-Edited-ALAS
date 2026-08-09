[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$StartupScript = Join-Path $PSScriptRoot 'start-alas-at-logon.ps1'
if (-not (Test-Path -LiteralPath $StartupScript -PathType Leaf)) {
    throw "Startup script not found: $StartupScript"
}

$StartupDirectory = [Environment]::GetFolderPath('Startup')
$ShortcutPath = Join-Path $StartupDirectory 'AzurLaneAutoScript.lnk'
$PowerShellExecutable = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Arguments = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $StartupScript

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $PowerShellExecutable
$shortcut.Arguments = $Arguments
$shortcut.WorkingDirectory = Split-Path -Parent $PSScriptRoot
$shortcut.Description = 'Start MuMu instances 0 and 1, then ALAS schedulers alas and alas2'
$shortcut.Save()

Write-Host "Installed current-user logon startup shortcut: $ShortcutPath"
